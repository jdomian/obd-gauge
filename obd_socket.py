#!/usr/bin/env python3
"""
OBD-II Socket Communication Module

Supports both Bluetooth (PyBluez RFCOMM) and TCP socket connections
for ELM327-compatible OBD adapters and simulators.

Supports:
- ELM327 AT commands for initialization
- OBD-II PID queries and response parsing
- Threaded polling for continuous data updates
- Connection status callbacks for UI integration
- TCP mode for simulator testing (when Bluetooth is unavailable)
"""

import socket
try:
    import bluetooth
    HAS_BLUETOOTH = True
except ImportError:
    HAS_BLUETOOTH = False

import threading
import time
import re
import logging
from typing import Optional, Callable, Dict, List, Any, Union
from dataclasses import dataclass
from enum import Enum

# Configure logging - also write to file for debugging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Add file handler for debugging
_fh = logging.FileHandler('/tmp/obd-gauge.log')
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(_fh)


class ConnectionState(Enum):
    """OBD connection states"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    INITIALIZING = "initializing"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class OBDData:
    """Container for OBD sensor data"""
    boost_psi: float = 0.0
    map_kpa: float = 101.0  # Atmospheric pressure
    coolant_temp_c: float = 0.0
    coolant_temp_f: float = 32.0
    rpm: int = 0
    speed_kph: int = 0
    speed_mph: int = 0
    intake_temp_c: float = 0.0
    throttle_pos: float = 0.0
    timestamp: float = 0.0


class OBDSocket:
    """
    OBD socket communication supporting both Bluetooth and TCP.

    Uses PyBluez BluetoothSocket for RFCOMM connection to ELM327-compatible
    OBD adapters, or TCP sockets for simulator/network connections.
    Handles protocol initialization, PID queries, and response parsing.
    """

    # ELM327 initialization commands
    INIT_COMMANDS = [
        ("ATZ", 2.0),      # Reset - needs longer timeout
        ("ATE0", 0.5),     # Echo off
        ("ATL0", 0.5),     # Linefeeds off
        ("ATS0", 0.5),     # Spaces off (compact responses)
        ("ATH0", 0.5),     # Headers off
        ("ATSP6", 1.0),    # Force CAN 500 protocol (RS7)
    ]

    # STN2255 extended commands (OBDLink MX+ specific)
    # DISABLED: These flow control commands break communication with Audi RS7 ECU
    # The ECU returns "NO DATA" after STFCP/STFAC/FC SD commands are sent
    # Keeping standard ELM327 mode which works reliably
    STN_COMMANDS = [
        # ("STFCP", 0.3),           # Fast CAN polling mode - BREAKS AUDI
        # ("STFAC", 0.3),           # Fast CAN auto-format - BREAKS AUDI
        # ("AT FC SD 30 00 00", 0.3),  # Flow Control - BREAKS AUDI
    ]

    # OBD-II PID definitions (Mode 01)
    # Format: PID -> (bytes, name, parse_function)
    PIDS = {
        "010B": (1, "MAP", lambda x: x[0]),  # Manifold Absolute Pressure (kPa)
        "0105": (1, "ECT", lambda x: x[0] - 40),  # Engine Coolant Temp (C)
        "010C": (2, "RPM", lambda x: ((x[0] * 256) + x[1]) // 4),  # Engine RPM
        "010D": (1, "VSS", lambda x: x[0]),  # Vehicle Speed (km/h)
        "010F": (1, "IAT", lambda x: x[0] - 40),  # Intake Air Temp (C)
        "0111": (1, "TPS", lambda x: x[0] * 100 // 255),  # Throttle Position (%)
        "0149": (1, "APP_D", lambda x: x[0] * 100 // 255),  # Accelerator Pedal Position D (%)
        "014A": (1, "APP_E", lambda x: x[0] * 100 // 255),  # Accelerator Pedal Position E (%)
    }

    # Atmospheric pressure baseline for boost calculation
    ATMOSPHERIC_KPA = 101.325

    def __init__(self, address: str, channel_or_port: int = 1, use_tcp: bool = False):
        """
        Initialize OBD socket connection.

        Args:
            address: Bluetooth MAC address (e.g., "AA:BB:CC:DD:EE:FF") or TCP host (e.g., "10.0.0.174")
            channel_or_port: RFCOMM channel (Bluetooth) or TCP port (default 1 for BT, 35000 for TCP)
            use_tcp: If True, use TCP socket instead of Bluetooth
        """
        self.address = address
        self.use_tcp = use_tcp

        if use_tcp:
            self.tcp_host = address
            self.tcp_port = channel_or_port if channel_or_port != 1 else 35000  # Default TCP port
        else:
            self.mac_address = address
            self.channel = channel_or_port

        self.socket: Optional[Union[socket.socket, 'bluetooth.BluetoothSocket']] = None
        self.state = ConnectionState.DISCONNECTED
        self.state_callback: Optional[Callable[[ConnectionState, str], None]] = None
        self.data_callback: Optional[Callable[[OBDData], None]] = None

        self._polling_thread: Optional[threading.Thread] = None
        self._stop_polling = threading.Event()
        self._lock = threading.Lock()

        self.data = OBDData()
        self.elm_version = ""
        self.protocol = ""

    def set_state_callback(self, callback: Callable[[ConnectionState, str], None]):
        """Set callback for connection state changes. callback(state, message)"""
        self.state_callback = callback

    def set_data_callback(self, callback: Callable[[OBDData], None]):
        """Set callback for new OBD data. callback(OBDData)"""
        self.data_callback = callback

    def _set_state(self, state: ConnectionState, message: str = ""):
        """Update state and notify callback"""
        self.state = state
        logger.info(f"OBD State: {state.value} - {message}")
        if self.state_callback:
            try:
                self.state_callback(state, message)
            except Exception as e:
                logger.error(f"State callback error: {e}")

    def connect(self) -> bool:
        """
        Establish socket connection to OBD adapter (Bluetooth or TCP).

        Returns:
            True if connection successful, False otherwise
        """
        if self.state == ConnectionState.CONNECTED:
            logger.warning("Already connected")
            return True

        if self.use_tcp:
            return self._connect_tcp()
        else:
            return self._connect_bluetooth()

    def _connect_tcp(self) -> bool:
        """Connect via TCP socket (for simulator/network)"""
        self._set_state(ConnectionState.CONNECTING, f"Connecting to {self.tcp_host}:{self.tcp_port}")

        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10.0)

            logger.info(f"TCP connecting to {self.tcp_host}:{self.tcp_port}")
            self.socket.connect((self.tcp_host, self.tcp_port))

            # Set shorter timeout for commands
            self.socket.settimeout(0.5)

            # Read initial prompt
            try:
                initial = self.socket.recv(64)
                logger.debug(f"TCP initial response: {initial}")
            except:
                pass

            logger.info("TCP connected, initializing ELM327...")
            return self._initialize()

        except socket.error as e:
            error_msg = f"TCP error: {e}"
            logger.error(error_msg)
            self._set_state(ConnectionState.ERROR, error_msg)
            self.disconnect()
            return False
        except Exception as e:
            error_msg = f"Connection error: {e}"
            logger.error(error_msg)
            self._set_state(ConnectionState.ERROR, error_msg)
            self.disconnect()
            return False

    def _connect_bluetooth(self) -> bool:
        """Connect via Bluetooth RFCOMM socket using native Python socket"""
        self._set_state(ConnectionState.CONNECTING, f"Connecting to {self.mac_address}")

        try:
            # Use native Python socket instead of PyBluez (fixes Error 77)
            # AF_BLUETOOTH = 31, BTPROTO_RFCOMM = 3
            self.socket = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            self.socket.settimeout(10.0)  # 10 second connection timeout

            logger.info(f"Connecting to {self.mac_address} channel {self.channel}")
            self.socket.connect((self.mac_address, self.channel))

            # Set shorter timeout for commands
            self.socket.settimeout(0.5)

            logger.info("Socket connected, initializing ELM327...")
            return self._initialize()

        except OSError as e:
            error_msg = f"Bluetooth error: {e}"
            logger.error(error_msg)
            self._set_state(ConnectionState.ERROR, error_msg)
            self.disconnect()
            return False
        except Exception as e:
            error_msg = f"Connection error: {e}"
            logger.error(error_msg)
            self._set_state(ConnectionState.ERROR, error_msg)
            self.disconnect()
            return False

    def _initialize(self) -> bool:
        """
        Send ELM327 initialization commands.

        Returns:
            True if initialization successful
        """
        self._set_state(ConnectionState.INITIALIZING, "Initializing ELM327")

        try:
            # Clear any pending data
            self._flush_input()

            for cmd, timeout in self.INIT_COMMANDS:
                response = self._send_command(cmd, timeout)
                if response is None:
                    logger.warning(f"No response to {cmd}")
                    continue

                logger.debug(f"{cmd} -> {response}")

                # Capture ELM version from ATZ response
                if cmd == "ATZ" and "ELM327" in response:
                    self.elm_version = response.strip()

            # Try STN2255 extended commands (OBDLink MX+ specific)
            # These may fail on regular ELM327 adapters - that's OK
            self._is_stn2255 = False
            for cmd, timeout in self.STN_COMMANDS:
                response = self._send_command(cmd, timeout)
                if response and "?" not in response and "ERROR" not in response.upper():
                    logger.info(f"STN2255 cmd OK: {cmd} -> {response}")
                    self._is_stn2255 = True
                else:
                    logger.debug(f"STN2255 cmd not supported: {cmd}")

            if self._is_stn2255:
                logger.info("STN2255 adapter detected - fast polling enabled")

            # Verify communication with a simple PID query
            # Try to read supported PIDs
            response = self._send_command("0100", timeout=2.0)
            if response and "41" in response:
                self.protocol = "Auto-detected"
                self._set_state(ConnectionState.CONNECTED,
                               f"Connected - {self.elm_version}")
                return True
            else:
                # Some simulators might not support 0100, try a basic PID
                response = self._send_command("010C", timeout=2.0)
                if response:
                    self._set_state(ConnectionState.CONNECTED,
                                   f"Connected - {self.elm_version}")
                    return True

            self._set_state(ConnectionState.ERROR, "Failed to verify OBD connection")
            return False

        except Exception as e:
            error_msg = f"Initialization error: {e}"
            logger.error(error_msg)
            self._set_state(ConnectionState.ERROR, error_msg)
            return False

    def _flush_input(self):
        """Clear any pending data in the socket buffer"""
        if not self.socket:
            return
        try:
            self.socket.settimeout(0.1)
            while True:
                try:
                    data = self.socket.recv(1024)
                    if not data:
                        break
                except:
                    break
            self.socket.settimeout(0.5)
        except:
            pass

    def _send_command(self, cmd: str, timeout: float = 0.5) -> Optional[str]:
        """
        Send command to ELM327 and read response.

        Args:
            cmd: AT command or OBD PID to send
            timeout: Response timeout in seconds

        Returns:
            Response string or None on error
        """
        if not self.socket:
            return None

        try:
            with self._lock:
                # Send command with carriage return
                self.socket.send((cmd + "\r").encode())

                # Read response until prompt (>)
                self.socket.settimeout(timeout)
                response = ""
                start_time = time.time()

                while time.time() - start_time < timeout:
                    try:
                        chunk = self.socket.recv(1024).decode('utf-8', errors='ignore')
                        response += chunk
                        if ">" in response:
                            break
                    except (socket.timeout, socket.error):
                        break
                    except Exception:
                        break

                # Clean up response
                response = response.replace(">", "").replace("\r", " ").strip()

                # Remove echo if present
                if response.upper().startswith(cmd.upper()):
                    response = response[len(cmd):].strip()

                return response if response else None

        except Exception as e:
            logger.error(f"Command error ({cmd}): {e}")
            return None

    def query_pid(self, pid: str, fast: bool = False) -> Optional[Any]:
        """
        Query a single OBD-II PID and return parsed value.

        Args:
            pid: PID code (e.g., "010B" for MAP sensor)

        Returns:
            Parsed value or None on error
        """
        if self.state != ConnectionState.CONNECTED:
            return None

        response = self._send_command(pid, timeout=0.3 if fast else 0.5)
        if not response:
            return None

        # Debug throttle/accelerator PIDs
        if pid in ("0111", "0149", "014A") and hasattr(self, '_dbg_count') and self._dbg_count % 60 == 0:
            logger.info(f"[OBD] Raw {pid} response: '{response}'")

        return self._parse_pid_response(pid, response)

    def _parse_pid_response(self, pid: str, response: str) -> Optional[Any]:
        """
        Parse OBD-II PID response into value.

        Args:
            pid: Original PID code
            response: Raw response string

        Returns:
            Parsed value or None
        """
        try:
            # Remove "NO DATA", "SEARCHING...", etc.
            if "NO DATA" in response.upper() or "SEARCHING" in response.upper():
                return None

            # Response format: "41 0B XX" for PID 010B
            # Remove spaces and find hex bytes
            clean = response.replace(" ", "").upper()

            # Find the response pattern (41XX...)
            # Mode 01 response is 41, followed by PID, followed by data
            expected_prefix = "41" + pid[2:4].upper()  # e.g., "410B" for "010B"

            if expected_prefix not in clean:
                logger.debug(f"Expected {expected_prefix} not in {clean}")
                return None

            # Extract data bytes after the prefix
            idx = clean.index(expected_prefix) + len(expected_prefix)
            hex_data = clean[idx:]

            # Get PID definition
            if pid not in self.PIDS:
                logger.warning(f"Unknown PID: {pid}")
                return None

            num_bytes, name, parse_func = self.PIDS[pid]

            # Extract required number of bytes
            if len(hex_data) < num_bytes * 2:
                logger.debug(f"Insufficient data for {pid}: {hex_data}")
                return None

            # Convert hex string to bytes
            data_bytes = [int(hex_data[i:i+2], 16) for i in range(0, num_bytes * 2, 2)]

            # Apply parse function
            return parse_func(data_bytes)

        except Exception as e:
            logger.error(f"Parse error for {pid}: {e}")
            return None

    def query_all(self) -> OBDData:
        """
        Query all supported PIDs and update data object.

        Returns:
            Updated OBDData object
        """
        # Query MAP (boost)
        map_kpa = self.query_pid("010B")
        if map_kpa is not None:
            self.data.map_kpa = map_kpa
            # Convert to boost PSI (pressure relative to atmosphere)
            self.data.boost_psi = (map_kpa - self.ATMOSPHERIC_KPA) * 0.145038

        # Query coolant temp
        coolant_c = self.query_pid("0105")
        if coolant_c is not None:
            self.data.coolant_temp_c = coolant_c
            self.data.coolant_temp_f = coolant_c * 9/5 + 32

        # Query RPM
        rpm = self.query_pid("010C")
        if rpm is not None:
            self.data.rpm = rpm

        # Query vehicle speed
        speed_kph = self.query_pid("010D")
        if speed_kph is not None:
            self.data.speed_kph = speed_kph
            self.data.speed_mph = int(speed_kph * 0.621371)

        # Query intake air temp
        iat_c = self.query_pid("010F")
        if iat_c is not None:
            self.data.intake_temp_c = iat_c

        # Query throttle position
        throttle = self.query_pid("0111")
        if throttle is not None:
            self.data.throttle_pos = throttle

        self.data.timestamp = time.time()
        return self.data


    def set_active_pid(self, pid: str):
        """Set which PID to poll in fast mode (for future use)."""
        self._active_pid = pid
        logger.info(f"Active PID set to: {pid}")

    def query_fast(self) -> OBDData:
        """Query only the active PID for maximum speed.

        Only polls whichever gauge is currently visible on screen.
        Call set_active_pid() when user swipes to different gauge.
        """
        # Get active PID (default to throttle)
        pid = getattr(self, '_active_pid', '0111')

        result = self.query_pid(pid, fast=True)
        if result is not None:
            if pid == '0111':  # Throttle
                self.data.throttle_pos = result
            elif pid == '010B':  # MAP/Boost
                self.data.map_kpa = result
                self.data.boost_psi = (result - 101.325) * 0.145038
            elif pid == '0105':  # Coolant temp
                self.data.coolant_temp_c = result
                self.data.coolant_temp_f = result * 9/5 + 32
            elif pid == '010C':  # RPM
                self.data.rpm = result
            elif pid == '010F':  # Intake air temp
                self.data.intake_temp_c = result

        self.data.timestamp = time.time()
        return self.data
    def start_polling(self, rate_hz: float = 10.0):
        """
        Start background thread to continuously poll OBD data.

        Args:
            rate_hz: Polling rate in Hz (default 10 = 100ms between queries)
        """
        if self._polling_thread and self._polling_thread.is_alive():
            logger.warning("Polling already running")
            return

        if self.state != ConnectionState.CONNECTED:
            logger.error("Cannot start polling - not connected")
            return

        self._stop_polling.clear()
        self._polling_thread = threading.Thread(
            target=self._polling_loop,
            args=(rate_hz,),
            daemon=True
        )
        self._polling_thread.start()
        logger.info(f"Started OBD polling at {rate_hz} Hz")
        # Direct file write for debugging
        with open('/tmp/obd-debug.txt', 'a') as f:
            f.write(f"start_polling called at {rate_hz} Hz\n")

    def _polling_loop(self, rate_hz: float):
        """Background polling loop"""
        interval = 1.0 / rate_hz
        error_count = 0
        max_errors = 5
        logger.info(f"[OBD] Entering polling loop at {rate_hz} Hz")

        while not self._stop_polling.is_set():
            start = time.time()

            try:
                # Fast polling: query essential PIDs every cycle, full query rarely
                self._poll_count = getattr(self, "_poll_count", 0) + 1
                if self._poll_count % 100 == 0:
                    data = self.query_all()  # Full query for coolant, speed, IAT (every ~10 sec)
                else:
                    data = self.query_fast()  # Fast query for boost, RPM, throttle
                error_count = 0  # Reset on success

                if self.data_callback:
                    self.data_callback(data)

            except Exception as e:
                error_count += 1
                logger.error(f"Polling error ({error_count}/{max_errors}): {e}")

                if error_count >= max_errors:
                    logger.error("Too many polling errors, stopping")
                    self._set_state(ConnectionState.ERROR, "Connection lost")
                    break

            # Sleep for remaining interval
            elapsed = time.time() - start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                self._stop_polling.wait(sleep_time)

    def stop_polling(self):
        """Stop background polling thread"""
        if self._polling_thread:
            self._stop_polling.set()
            self._polling_thread.join(timeout=2.0)
            self._polling_thread = None
            logger.info("Stopped OBD polling")

    def disconnect(self):
        """Close connection and cleanup"""
        self.stop_polling()

        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

        self._set_state(ConnectionState.DISCONNECTED, "Disconnected")

    def is_connected(self) -> bool:
        """Check if currently connected"""
        return self.state == ConnectionState.CONNECTED

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
        return False


# Convenience functions for boost calculation
def map_to_boost_psi(map_kpa: float, atmospheric_kpa: float = 101.325) -> float:
    """
    Convert MAP sensor reading to boost pressure in PSI.

    Args:
        map_kpa: Manifold Absolute Pressure in kPa
        atmospheric_kpa: Atmospheric pressure baseline (default sea level)

    Returns:
        Boost pressure in PSI (negative = vacuum, positive = boost)
    """
    return (map_kpa - atmospheric_kpa) * 0.145038


def celsius_to_fahrenheit(temp_c: float) -> float:
    """Convert Celsius to Fahrenheit"""
    return temp_c * 9/5 + 32


# Test function
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python obd_socket.py <MAC_ADDRESS or HOST:PORT>")
        print("")
        print("Bluetooth mode:")
        print("  python obd_socket.py AA:BB:CC:DD:EE:FF")
        print("")
        print("TCP mode (for simulator):")
        print("  python obd_socket.py 10.0.0.174:35000")
        print("  python obd_socket.py tcp:10.0.0.174:35000")
        sys.exit(1)

    target = sys.argv[1]

    # Determine if TCP or Bluetooth
    use_tcp = False
    if target.startswith("tcp:"):
        use_tcp = True
        target = target[4:]  # Remove "tcp:" prefix

    if ":" in target and not target.count(":") == 5:  # Not a MAC address
        # TCP mode: host:port
        use_tcp = True
        parts = target.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 35000
        address = host
        channel_or_port = port
    else:
        # Bluetooth mode
        address = target
        channel_or_port = 1

    def on_state_change(state, msg):
        print(f"[STATE] {state.value}: {msg}")

    def on_data(data):
        print(f"[DATA] Boost: {data.boost_psi:.1f} PSI, "
              f"Coolant: {data.coolant_temp_f:.0f}F, "
              f"RPM: {data.rpm}, "
              f"Speed: {data.speed_mph} mph")

    mode = "TCP" if use_tcp else "Bluetooth"
    print(f"Mode: {mode}")
    print(f"Target: {address}:{channel_or_port}")

    obd = OBDSocket(address, channel_or_port, use_tcp=use_tcp)
    obd.set_state_callback(on_state_change)
    obd.set_data_callback(on_data)

    print(f"Connecting...")
    if obd.connect():
        print("Connected! Starting polling...")
        obd.start_polling(rate_hz=2)  # 2 Hz for testing

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")

    obd.disconnect()
    print("Done")

