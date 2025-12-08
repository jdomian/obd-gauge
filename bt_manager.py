"""
Bluetooth Management for OBD-Gauge

Handles scanning, pairing, and connecting to OBD2 adapters like OBDLink MX+.

Supports two connection modes:
1. rfcomm device files (legacy) - uses shell commands, can be fragile
2. Direct Bluetooth sockets (preferred) - uses PyBluez, more reliable
"""

import subprocess
import re
import time
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

# Import OBDSocket for socket-based connections
try:
    from obd_socket import OBDSocket, ConnectionState, OBDData
    HAS_OBD_SOCKET = True
except ImportError:
    HAS_OBD_SOCKET = False
    OBDSocket = None
    ConnectionState = None
    OBDData = None


@dataclass
class BTDevice:
    """Represents a discovered Bluetooth device."""
    mac: str
    name: str
    paired: bool = False
    trusted: bool = False
    connected: bool = False


@dataclass
class BTStatus:
    """Current Bluetooth OBD connection status."""
    paired: bool
    connected: bool
    device_name: str
    device_mac: str
    rfcomm_device: Optional[str]  # e.g., "/dev/rfcomm0"


def _run(cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a shell command with timeout."""
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )


def _run_bluetoothctl(commands: list[str], timeout: int = 10) -> str:
    """Run commands through bluetoothctl."""
    cmd_str = "\n".join(commands + ["exit"])
    try:
        result = subprocess.run(
            ["bluetoothctl"],
            input=cmd_str,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return ""


def get_paired_devices() -> list[BTDevice]:
    """Get list of paired Bluetooth devices."""
    devices = []
    result = _run("bluetoothctl devices Paired")

    for line in result.stdout.strip().split("\n"):
        if line.startswith("Device "):
            parts = line.split(" ", 2)
            if len(parts) >= 3:
                mac = parts[1]
                name = parts[2]
                devices.append(BTDevice(mac=mac, name=name, paired=True))

    return devices


def get_bt_status(config_mac: str = None) -> BTStatus:
    """
    Get current Bluetooth OBD connection status.

    Args:
        config_mac: Expected device MAC from config (to check if paired)
    """
    # Default status
    status = BTStatus(
        paired=False,
        connected=False,
        device_name="Not paired",
        device_mac="",
        rfcomm_device=None
    )

    # Check paired devices
    paired_devices = get_paired_devices()

    # If we have a config MAC, check if it's paired
    if config_mac:
        for dev in paired_devices:
            if dev.mac.upper() == config_mac.upper():
                status.paired = True
                status.device_name = dev.name
                status.device_mac = dev.mac
                break
    elif paired_devices:
        # Just use first paired device if no config
        status.paired = True
        status.device_name = paired_devices[0].name
        status.device_mac = paired_devices[0].mac

    # Check rfcomm connection
    rfcomm_result = _run("rfcomm show", timeout=5)
    if status.device_mac and status.device_mac.upper() in rfcomm_result.stdout.upper():
        status.connected = True
        # Extract rfcomm device number
        match = re.search(r"rfcomm(\d+)", rfcomm_result.stdout)
        if match:
            status.rfcomm_device = f"/dev/rfcomm{match.group(1)}"

    return status


def scan_devices(timeout: int = 10) -> list[BTDevice]:
    """
    Scan for nearby Bluetooth devices.

    Args:
        timeout: How long to scan in seconds

    Returns:
        List of discovered devices
    """
    devices = []

    print(f"Scanning for Bluetooth devices ({timeout}s)...")

    # Start scan
    _run(f"bluetoothctl --timeout {timeout} scan on", timeout=timeout + 5)

    # Get discovered devices
    result = _run("bluetoothctl devices")

    for line in result.stdout.strip().split("\n"):
        if line.startswith("Device "):
            parts = line.split(" ", 2)
            if len(parts) >= 3:
                mac = parts[1]
                name = parts[2]
                # Check if already paired
                paired = any(d.mac == mac for d in get_paired_devices())
                devices.append(BTDevice(mac=mac, name=name, paired=paired))

    # Filter to likely OBD devices (optional - can remove to show all)
    obd_keywords = ["OBD", "ELM", "OBDII", "MX", "Link", "Vgate", "Veepeak"]
    obd_devices = [d for d in devices if any(k.lower() in d.name.lower() for k in obd_keywords)]

    # Return OBD devices first, then others
    return obd_devices + [d for d in devices if d not in obd_devices]


def pair_device(mac: str) -> bool:
    """
    Pair with a Bluetooth device.

    Args:
        mac: Device MAC address

    Returns:
        True if pairing successful
    """
    print(f"Pairing with {mac}...")

    try:
        # Pair
        result = _run_bluetoothctl([f"pair {mac}"], timeout=30)
        if "Failed" in result:
            print(f"Pairing failed: {result}")
            return False

        # Trust (auto-reconnect)
        _run_bluetoothctl([f"trust {mac}"])

        print(f"Paired and trusted {mac}")
        return True

    except Exception as e:
        print(f"Pairing error: {e}")
        return False


def unpair_device(mac: str) -> bool:
    """Remove pairing with a device."""
    try:
        _run_bluetoothctl([f"remove {mac}"])
        print(f"Unpaired {mac}")
        return True
    except Exception as e:
        print(f"Unpair error: {e}")
        return False


def connect_obd(mac: str, rfcomm_num: int = 0) -> Optional[str]:
    """
    Connect to OBD device and create rfcomm serial port.

    Args:
        mac: Device MAC address
        rfcomm_num: rfcomm device number (default 0 = /dev/rfcomm0)

    Returns:
        Path to rfcomm device (e.g., "/dev/rfcomm0") or None if failed
    """
    rfcomm_device = f"/dev/rfcomm{rfcomm_num}"

    print(f"Connecting to {mac} on {rfcomm_device}...")

    try:
        # Release any existing binding
        _run(f"sudo rfcomm release {rfcomm_num}", timeout=5)
        time.sleep(0.5)

        # Bind rfcomm to device (SPP channel 1 is standard for OBD)
        result = _run(f"sudo rfcomm bind {rfcomm_num} {mac} 1", timeout=10)

        if result.returncode != 0:
            print(f"rfcomm bind failed: {result.stderr}")
            return None

        # Verify the device exists
        time.sleep(1)
        if subprocess.run(["test", "-e", rfcomm_device]).returncode == 0:
            print(f"Connected: {rfcomm_device}")
            return rfcomm_device
        else:
            print(f"Device {rfcomm_device} not created")
            return None

    except Exception as e:
        print(f"Connection error: {e}")
        return None


def disconnect_obd(rfcomm_num: int = 0) -> bool:
    """
    Disconnect rfcomm serial port.

    Args:
        rfcomm_num: rfcomm device number to release
    """
    try:
        _run(f"sudo rfcomm release {rfcomm_num}", timeout=5)
        print(f"Disconnected rfcomm{rfcomm_num}")
        return True
    except Exception as e:
        print(f"Disconnect error: {e}")
        return False


def is_bluetooth_enabled() -> bool:
    """Check if Bluetooth adapter is powered on."""
    result = _run("bluetoothctl show")
    return "Powered: yes" in result.stdout


def enable_bluetooth() -> bool:
    """Enable Bluetooth adapter."""
    try:
        _run_bluetoothctl(["power on"])
        _run_bluetoothctl(["agent on"])
        _run_bluetoothctl(["default-agent"])
        return True
    except Exception:
        return False


# =============================================================================
# Socket-based OBD Connection (Preferred Method)
# =============================================================================

def connect_obd_socket(mac: str, channel: int = 1) -> Optional['OBDSocket']:
    """
    Connect to OBD adapter using direct Bluetooth socket.

    This is the preferred method - more reliable than rfcomm device files.

    Args:
        mac: Device MAC address (e.g., "AA:BB:CC:DD:EE:FF")
        channel: RFCOMM channel (usually 1 for OBD adapters)

    Returns:
        Connected OBDSocket instance or None if failed
    """
    if not HAS_OBD_SOCKET:
        print("Error: obd_socket module not available")
        return None

    try:
        obd = OBDSocket(mac, channel)
        if obd.connect():
            return obd
        else:
            return None
    except Exception as e:
        print(f"Socket connection error: {e}")
        return None


def create_obd_connection(mac: str, channel: int = 1,
                          state_callback=None,
                          data_callback=None) -> Optional['OBDSocket']:
    """
    Create OBDSocket with callbacks for UI integration.

    Args:
        mac: Device MAC address
        channel: RFCOMM channel
        state_callback: Called on state changes - callback(state, message)
        data_callback: Called with new data - callback(OBDData)

    Returns:
        OBDSocket instance (not yet connected) or None
    """
    if not HAS_OBD_SOCKET:
        print("Error: obd_socket module not available")
        return None

    try:
        obd = OBDSocket(mac, channel)
        if state_callback:
            obd.set_state_callback(state_callback)
        if data_callback:
            obd.set_data_callback(data_callback)
        return obd
    except Exception as e:
        print(f"Error creating OBDSocket: {e}")
        return None


def has_socket_support() -> bool:
    """Check if socket-based OBD connection is available."""
    return HAS_OBD_SOCKET


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python bluetooth.py [status|scan|pair MAC|connect MAC|disconnect]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        status = get_bt_status()
        print(f"Paired: {status.paired}")
        print(f"Connected: {status.connected}")
        print(f"Device: {status.device_name} ({status.device_mac})")
        print(f"rfcomm: {status.rfcomm_device}")

    elif cmd == "scan":
        devices = scan_devices(timeout=10)
        print(f"\nFound {len(devices)} devices:")
        for d in devices:
            paired_str = " [PAIRED]" if d.paired else ""
            print(f"  {d.mac} - {d.name}{paired_str}")

    elif cmd == "pair":
        if len(sys.argv) < 3:
            print("Usage: python bluetooth.py pair <MAC>")
            sys.exit(1)
        pair_device(sys.argv[2])

    elif cmd == "connect":
        if len(sys.argv) < 3:
            print("Usage: python bluetooth.py connect <MAC>")
            sys.exit(1)
        connect_obd(sys.argv[2])

    elif cmd == "disconnect":
        disconnect_obd()

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
