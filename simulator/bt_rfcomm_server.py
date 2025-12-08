#!/usr/bin/env python3
"""
Bluetooth RFCOMM Server for OBD Simulator

Uses Python's built-in Bluetooth socket support to create a proper
SPP server that the obd-gauge can connect to.

This is more reliable than rfcomm watch + sdptool on newer BlueZ.
"""

import socket
import sys
import os
import subprocess

# Add parent directory for simulator import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from simulator import OBDSimulator

RFCOMM_CHANNEL = 1
SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"

def register_spp_service():
    """Register SPP service via sdptool."""
    try:
        subprocess.run(
            ["sudo", "sdptool", "add", "--channel=1", "SP"],
            capture_output=True,
            check=False
        )
        print("SPP service registered", file=sys.stderr)
    except Exception as e:
        print(f"Could not register SPP: {e}", file=sys.stderr)

def make_discoverable():
    """Make Bluetooth adapter discoverable."""
    try:
        # Enable discoverable and pairable mode
        subprocess.run(
            ["sudo", "hciconfig", "hci0", "piscan"],
            capture_output=True,
            check=False
        )
        subprocess.run(
            ["bluetoothctl", "discoverable", "on"],
            capture_output=True,
            check=False
        )
        subprocess.run(
            ["bluetoothctl", "pairable", "on"],
            capture_output=True,
            check=False
        )
        print("Bluetooth discoverable", file=sys.stderr)
    except Exception as e:
        print(f"Could not set discoverable: {e}", file=sys.stderr)

def handle_client(client_socket, addr, sim):
    """Handle a connected client."""
    print(f"Client connected: {addr}", file=sys.stderr)

    # Send initial prompt
    client_socket.send(b">")

    buffer = ""

    try:
        while True:
            data = client_socket.recv(1024)
            if not data:
                break

            buffer += data.decode('utf-8', errors='ignore')

            # Process complete commands (terminated by CR or LF)
            while '\r' in buffer or '\n' in buffer:
                # Find first terminator
                idx = len(buffer)
                if '\r' in buffer:
                    idx = min(idx, buffer.find('\r'))
                if '\n' in buffer:
                    idx = min(idx, buffer.find('\n'))

                cmd = buffer[:idx]
                buffer = buffer[idx+1:].lstrip('\r\n')

                if cmd:
                    response = sim.process_command(cmd)
                    output = sim.format_output(response)
                    client_socket.send(output.encode())

    except Exception as e:
        print(f"Client error: {e}", file=sys.stderr)
    finally:
        print(f"Client disconnected: {addr}", file=sys.stderr)
        client_socket.close()

def main():
    # Find scan data
    scan_data_path = "/home/claude/obd-gauge/docs/data/obd_scan_20251207_180326.json"
    if not os.path.exists(scan_data_path):
        scan_data_path = None

    # Create simulator
    sim = OBDSimulator(scan_data_path)

    print("=" * 50, file=sys.stderr)
    print("OBD Simulator - Bluetooth RFCOMM Server", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    # Setup Bluetooth
    make_discoverable()
    register_spp_service()

    # Create RFCOMM socket
    server_socket = socket.socket(
        socket.AF_BLUETOOTH,
        socket.SOCK_STREAM,
        socket.BTPROTO_RFCOMM
    )

    # Get local Bluetooth address
    local_addr = ""
    try:
        result = subprocess.run(
            ["hciconfig", "hci0"],
            capture_output=True,
            text=True
        )
        for line in result.stdout.split('\n'):
            if 'BD Address' in line:
                local_addr = line.split()[2]
                break
    except:
        pass

    if not local_addr:
        print("ERROR: Could not get Bluetooth address", file=sys.stderr)
        sys.exit(1)

    # Bind to our Bluetooth address on channel 1
    server_socket.bind((local_addr, RFCOMM_CHANNEL))
    server_socket.listen(1)

    # Get local Bluetooth address
    try:
        result = subprocess.run(
            ["hciconfig", "hci0"],
            capture_output=True,
            text=True
        )
        for line in result.stdout.split('\n'):
            if 'BD Address' in line:
                addr = line.split()[2]
                print(f"Bluetooth address: {addr}", file=sys.stderr)
                break
    except:
        pass

    print(f"Listening on RFCOMM channel {RFCOMM_CHANNEL}", file=sys.stderr)
    print("Waiting for connections from obd-gauge...", file=sys.stderr)
    print("", file=sys.stderr)
    print("On obd-gauge, scan for 'claude-zero' and connect.", file=sys.stderr)
    print("Press Ctrl+C to stop.", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    try:
        while True:
            client_socket, addr = server_socket.accept()
            handle_client(client_socket, addr, sim)
    except KeyboardInterrupt:
        print("\nShutting down...", file=sys.stderr)
    finally:
        server_socket.close()

if __name__ == "__main__":
    main()
