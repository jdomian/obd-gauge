#!/usr/bin/env python3
"""
OBD-II ELM327 Simulator

Emulates an OBDLink MX+ adapter using real RS7 scan data.
Supports dynamic values controlled by virtual accelerator pedal.

Usage:
    # Stdio mode (for Bluetooth pipe via rfcomm watch)
    python3 simulator.py --stdio

    # Interactive mode (for testing)
    python3 simulator.py

    # TCP socket mode (for network testing)
    python3 simulator.py --tcp --port 35000
"""

import sys
import os
import json
import time
import argparse
import threading
import socket
import select
from pathlib import Path

# Shared state file for accelerator pedal input
STATE_FILE = "/tmp/obd_sim_state.json"

# Default state (idle)
DEFAULT_STATE = {
    "throttle": 0.0,      # 0-100%
    "rpm": 660,           # Engine RPM
    "map_kpa": 38,        # Manifold Absolute Pressure
    "coolant_c": 75,      # Coolant temp Celsius
    "speed_kph": 0,       # Vehicle speed
    "intake_temp_c": 25,  # Intake air temp
    "voltage": 14.3,      # Battery voltage
    "baro_kpa": 99,       # Barometric pressure (St. Louis elevation)
}

class OBDSimulator:
    """ELM327 protocol simulator with RS7 data."""

    # ELM327 identification
    ELM_VERSION = "ELM327 v1.4b"
    DEVICE_DESC = "OBDLink MX+ (Sim)"

    def __init__(self, scan_data_path=None):
        """Initialize simulator with optional scan data."""
        self.echo = True  # Echo commands back
        self.linefeed = True
        self.spaces = True
        self.headers = False
        self.protocol = "6"  # ISO 15765-4 CAN 11/500

        # Load scan data if available
        self.scan_data = None
        self.supported_pids = set()
        if scan_data_path and os.path.exists(scan_data_path):
            self._load_scan_data(scan_data_path)
        else:
            # Default supported PIDs for RS7
            self.supported_pids = {
                "01", "03", "04", "05", "06", "07", "08", "09",
                "0B", "0C", "0D", "0E", "11", "12", "13", "15",
                "19", "1C", "1F", "20", "21", "2E", "2F", "30",
                "31", "33", "34", "38", "3C", "3D", "40", "41",
                "42", "43", "44", "45", "46", "47", "49", "4A",
                "4C", "51", "56", "58", "60", "67", "6D", "70",
                "75", "76", "77"
            }

        # Initialize state
        self._init_state_file()

    def _load_scan_data(self, path):
        """Load real scan data from JSON file."""
        try:
            with open(path) as f:
                self.scan_data = json.load(f)

            # Extract supported PIDs
            if "supported_pids" in self.scan_data:
                for mode, pids in self.scan_data["supported_pids"].items():
                    if mode == "01":
                        self.supported_pids.update(pids)

            print(f"Loaded scan data: {len(self.supported_pids)} PIDs supported", file=sys.stderr)
        except Exception as e:
            print(f"Failed to load scan data: {e}", file=sys.stderr)

    def _init_state_file(self):
        """Initialize shared state file."""
        if not os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'w') as f:
                json.dump(DEFAULT_STATE, f)

    def _get_state(self):
        """Read current state from file."""
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            return DEFAULT_STATE.copy()

    def _format_response(self, data):
        """Format response with optional spaces."""
        if self.spaces:
            return " ".join(data[i:i+2] for i in range(0, len(data), 2))
        return data

    def _pid_bitmap(self, start_pid):
        """Generate PID support bitmap for 0100, 0120, 0140, 0160."""
        # Which PIDs are supported in this range
        bitmap = 0
        base = int(start_pid, 16)

        for i in range(32):
            pid = f"{base + i + 1:02X}"
            if pid in self.supported_pids:
                bitmap |= (1 << (31 - i))

        # Return as 4 bytes hex
        return f"{bitmap:08X}"

    def process_command(self, cmd):
        """Process an ELM327/OBD command and return response."""
        cmd = cmd.strip().upper()

        if not cmd:
            return ""

        # AT commands
        if cmd.startswith("AT"):
            return self._handle_at_command(cmd[2:])

        # ST commands (STN chip specific)
        if cmd.startswith("ST"):
            return self._handle_st_command(cmd[2:])

        # OBD Mode 01 (current data)
        if cmd.startswith("01"):
            return self._handle_mode01(cmd[2:])

        # OBD Mode 09 (vehicle info)
        if cmd.startswith("09"):
            return self._handle_mode09(cmd[2:])

        # Unknown command
        return "?"

    def _handle_at_command(self, cmd):
        """Handle AT commands."""
        if cmd == "Z":  # Reset
            self.echo = True
            self.linefeed = True
            self.spaces = True
            self.headers = False
            return self.ELM_VERSION

        if cmd == "I":  # Identify
            return self.ELM_VERSION

        if cmd == "E0":  # Echo off
            self.echo = False
            return "OK"

        if cmd == "E1":  # Echo on
            self.echo = True
            return "OK"

        if cmd == "L0":  # Linefeeds off
            self.linefeed = False
            return "OK"

        if cmd == "L1":  # Linefeeds on
            self.linefeed = True
            return "OK"

        if cmd == "S0":  # Spaces off
            self.spaces = False
            return "OK"

        if cmd == "S1":  # Spaces on
            self.spaces = True
            return "OK"

        if cmd == "H0":  # Headers off
            self.headers = False
            return "OK"

        if cmd == "H1":  # Headers on
            self.headers = True
            return "OK"

        if cmd.startswith("SP"):  # Set protocol
            self.protocol = cmd[2:] if len(cmd) > 2 else "0"
            return "OK"

        if cmd == "DP":  # Describe protocol
            return "AUTO, ISO 15765-4 (CAN 11/500)"

        if cmd == "DPN":  # Describe protocol number
            return f"A{self.protocol}"

        if cmd == "RV":  # Read voltage
            state = self._get_state()
            return f"{state['voltage']:.1f}V"

        if cmd == "@1":  # Device description
            return "OBD Solutions LLC"

        if cmd == "WS":  # Warm start
            return self.ELM_VERSION

        # Unknown AT command - just return OK
        return "OK"

    def _handle_st_command(self, cmd):
        """Handle ST commands (STN chip specific)."""
        if cmd == "I":  # STN version
            return "STN2255 v5.10.3"

        if cmd == "SN":  # Serial number
            return "225530429398"

        if cmd == "MFR":  # Manufacturer
            return "OBD Solutions LLC"

        return "OK"

    def _handle_mode01(self, pid):
        """Handle Mode 01 (current data) requests."""
        state = self._get_state()

        # PID support bitmaps
        if pid == "00":
            bitmap = self._pid_bitmap("00")
            return self._format_response(f"4100{bitmap}")

        if pid == "20":
            bitmap = self._pid_bitmap("20")
            return self._format_response(f"4120{bitmap}")

        if pid == "40":
            bitmap = self._pid_bitmap("40")
            return self._format_response(f"4140{bitmap}")

        if pid == "60":
            bitmap = self._pid_bitmap("60")
            return self._format_response(f"4160{bitmap}")

        # Dynamic PIDs based on state

        # 0105 - Coolant temperature (A - 40 = C)
        if pid == "05":
            temp = int(state["coolant_c"] + 40)
            return self._format_response(f"4105{temp:02X}")

        # 010B - Intake manifold pressure (MAP) kPa
        if pid == "0B":
            kpa = int(state["map_kpa"])
            return self._format_response(f"410B{kpa:02X}")

        # 010C - Engine RPM ((A*256+B)/4)
        if pid == "0C":
            rpm_raw = int(state["rpm"] * 4)
            a = (rpm_raw >> 8) & 0xFF
            b = rpm_raw & 0xFF
            return self._format_response(f"410C{a:02X}{b:02X}")

        # 010D - Vehicle speed km/h
        if pid == "0D":
            speed = int(state["speed_kph"])
            return self._format_response(f"410D{speed:02X}")

        # 010F - Intake air temperature (A - 40 = C)
        if pid == "0F":
            temp = int(state["intake_temp_c"] + 40)
            return self._format_response(f"410F{temp:02X}")

        # 0111 - Throttle position (A * 100 / 255 = %)
        if pid == "11":
            tps = int(state["throttle"] * 255 / 100)
            return self._format_response(f"4111{tps:02X}")

        # 0133 - Barometric pressure kPa
        if pid == "33":
            baro = int(state["baro_kpa"])
            return self._format_response(f"4133{baro:02X}")

        # 0104 - Engine load (simulated from throttle)
        if pid == "04":
            load = int(state["throttle"] * 0.8 * 255 / 100)  # 80% of throttle
            return self._format_response(f"4104{load:02X}")

        # 0142 - Control module voltage ((A*256+B)/1000)
        if pid == "42":
            v_raw = int(state["voltage"] * 1000)
            a = (v_raw >> 8) & 0xFF
            b = v_raw & 0xFF
            return self._format_response(f"4142{a:02X}{b:02X}")

        # 0146 - Ambient air temp (A - 40)
        if pid == "46":
            temp = int(state["intake_temp_c"] + 40 - 10)  # Ambient ~10C cooler
            return self._format_response(f"4146{temp:02X}")

        # Check if PID is in supported list but we don't have specific handling
        if pid in self.supported_pids:
            # Return a generic response
            return self._format_response(f"41{pid}00")

        return "NO DATA"

    def _handle_mode09(self, pid):
        """Handle Mode 09 (vehicle info) requests."""
        # 0902 - VIN
        if pid == "02":
            # RS7 VIN from scan data
            vin = "WUAW2AFC1GN900322"
            # Multi-line response format
            return f"014\r0: 49 02 01 {' '.join(f'{ord(c):02X}' for c in vin[:6])}\r1: {' '.join(f'{ord(c):02X}' for c in vin[6:13])}\r2: {' '.join(f'{ord(c):02X}' for c in vin[13:])}"

        # 090A - ECU name
        if pid == "0A":
            return "ECM-EngineControl"

        return "NO DATA"

    def format_output(self, response):
        """Format output with optional echo and prompt."""
        output = ""
        if response:
            output = response
        if self.linefeed:
            output += "\r\n"
        else:
            output += "\r"
        output += ">"
        return output


def run_interactive(sim):
    """Run simulator in interactive mode."""
    print(f"OBD Simulator - {sim.ELM_VERSION}", file=sys.stderr)
    print("Type commands (ATZ, 010C, etc.) or 'quit' to exit", file=sys.stderr)
    print(f"State file: {STATE_FILE}", file=sys.stderr)
    print(">", end="", flush=True)

    while True:
        try:
            line = input()
            if line.lower() in ("quit", "exit", "q"):
                break

            response = sim.process_command(line)
            print(sim.format_output(response), end="", flush=True)

        except EOFError:
            break
        except KeyboardInterrupt:
            break

    print("\nGoodbye!", file=sys.stderr)


def run_stdio(sim):
    """Run simulator in stdio mode (for Bluetooth pipe)."""
    print(f"OBD Simulator starting in stdio mode...", file=sys.stderr)
    print(f"State file: {STATE_FILE}", file=sys.stderr)

    # Send initial prompt
    sys.stdout.write(">")
    sys.stdout.flush()

    buffer = ""

    while True:
        try:
            # Read one character at a time
            char = sys.stdin.read(1)
            if not char:
                break

            # Build up command until CR
            if char == '\r' or char == '\n':
                if buffer:
                    response = sim.process_command(buffer)
                    output = sim.format_output(response)
                    sys.stdout.write(output)
                    sys.stdout.flush()
                    buffer = ""
            else:
                buffer += char
                # Echo if enabled
                if sim.echo:
                    sys.stdout.write(char)
                    sys.stdout.flush()

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            break


def run_tcp_server(sim, port):
    """Run simulator as TCP server."""
    print(f"OBD Simulator starting on TCP port {port}...", file=sys.stderr)
    print(f"State file: {STATE_FILE}", file=sys.stderr)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port))
    server.listen(1)

    print(f"Listening on 0.0.0.0:{port}", file=sys.stderr)

    while True:
        try:
            client, addr = server.accept()
            print(f"Client connected: {addr}", file=sys.stderr)

            # Send prompt
            client.send(b">")

            buffer = ""
            while True:
                try:
                    data = client.recv(1024)
                    if not data:
                        break

                    buffer += data.decode('utf-8', errors='ignore')

                    # Process complete commands
                    while '\r' in buffer or '\n' in buffer:
                        idx = min(
                            buffer.find('\r') if '\r' in buffer else len(buffer),
                            buffer.find('\n') if '\n' in buffer else len(buffer)
                        )
                        cmd = buffer[:idx]
                        buffer = buffer[idx+1:]

                        if cmd:
                            response = sim.process_command(cmd)
                            output = sim.format_output(response)
                            client.send(output.encode())

                except Exception as e:
                    print(f"Client error: {e}", file=sys.stderr)
                    break

            print(f"Client disconnected: {addr}", file=sys.stderr)
            client.close()

        except KeyboardInterrupt:
            break

    server.close()


def main():
    parser = argparse.ArgumentParser(description="OBD-II ELM327 Simulator")
    parser.add_argument("--stdio", action="store_true", help="Run in stdio mode (for Bluetooth)")
    parser.add_argument("--tcp", action="store_true", help="Run as TCP server")
    parser.add_argument("--port", type=int, default=35000, help="TCP port (default: 35000)")
    parser.add_argument("--data", type=str, help="Path to scan data JSON file")
    args = parser.parse_args()

    # Find scan data file
    scan_data_path = args.data
    if not scan_data_path:
        # Look for scan data in common locations
        possible_paths = [
            "/home/claude/obd-gauge/docs/data/obd_scan_20251207_180326.json",
            "./docs/data/obd_scan_20251207_180326.json",
            "../docs/data/obd_scan_20251207_180326.json",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                scan_data_path = path
                break

    sim = OBDSimulator(scan_data_path)

    if args.stdio:
        run_stdio(sim)
    elif args.tcp:
        run_tcp_server(sim, args.port)
    else:
        run_interactive(sim)


if __name__ == "__main__":
    main()
