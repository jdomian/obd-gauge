#!/usr/bin/env python3
"""
OBD Handler for socat bridge - reads stdin, writes stdout.

This handler is designed to be called via:
  rfcomm watch hci0 1 socat /dev/rfcomm0,raw,echo=0 EXEC:"python3 -u /path/obd_socat_handler.py"

The socat bridges /dev/rfcomm0 to this script's stdin/stdout.
"""
import sys
import os
import json
from datetime import datetime

# Force unbuffered I/O
sys.stdout.reconfigure(line_buffering=True)
sys.stdin.reconfigure(line_buffering=True)

LOG_FILE = "/tmp/obd_socat_handler.log"

def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.now()}: {msg}\n")

# Load real scan data if available
SCAN_DATA = {}
SCAN_DATA_PATH = "/home/claude/obd-gauge/docs/data/obd_scan_20251207_180326.json"
if os.path.exists(SCAN_DATA_PATH):
    try:
        with open(SCAN_DATA_PATH) as f:
            SCAN_DATA = json.load(f)
        log(f"Loaded scan data from {SCAN_DATA_PATH}")
    except Exception as e:
        log(f"Failed to load scan data: {e}")

# Static responses for common commands
RESPONSES = {
    # AT commands
    "ATZ": "ELM327 v2.1",
    "ATE0": "OK",
    "ATE1": "OK",
    "ATH0": "OK",
    "ATH1": "OK",
    "ATSP0": "OK",
    "ATSP6": "OK",
    "ATRV": "13.8V",
    "ATDPN": "A6",
    "ATL0": "OK",
    "ATL1": "OK",
    "ATS0": "OK",
    "ATS1": "OK",
    "ATST20": "OK",
    "ATAT1": "OK",
    "ATAT2": "OK",
    "AT@1": "OBD-SIM",
    "ATI": "ELM327 v2.1",

    # Supported PIDs
    "0100": "41 00 BE 1F B8 13",  # PIDs 01-20 supported
    "0120": "41 20 80 01 00 01",  # PIDs 21-40 supported

    # Real data from RS7 scan (or fallback)
    "0105": "41 05 78",           # Coolant temp 120C (converted from 78 hex = 120)
    "010C": "41 0C 27 10",        # RPM 2500 (27 10 / 4 = 2500)
    "010D": "41 0D 3C",           # Speed 60 km/h
    "010B": "41 0B 65",           # Intake manifold pressure 101 kPa
    "0111": "41 11 40",           # Throttle position 25%
    "0104": "41 04 32",           # Engine load 20%
    "010F": "41 0F 32",           # Intake air temp 10C
    "0110": "41 10 00 96",        # MAF 15.0 g/s
    "0114": "41 14 80 80",        # O2 sensor bank 1
    "011C": "41 1C 06",           # OBD standard (ISO 15765-4)
    "011F": "41 1F 00 A0",        # Runtime 160 seconds
    "0121": "41 21 00 00",        # Distance with MIL
    "012F": "41 2F 80",           # Fuel level 50%
    "0133": "41 33 65",           # Barometric pressure 101 kPa
    "0142": "41 42 33 58",        # Control module voltage 13.1V
    "0146": "41 46 32",           # Ambient air temp 10C

    # Boost calculation: MAP - Barometric = Boost (will show 0 at idle)
}

def process_command(cmd):
    """Process a command and return response."""
    cmd = cmd.strip().upper()

    # Remove spaces
    cmd = cmd.replace(" ", "")

    # Check direct match first
    if cmd in RESPONSES:
        return RESPONSES[cmd]

    # Check prefix match for AT commands
    for key in RESPONSES:
        if cmd.startswith(key):
            return RESPONSES[key]

    # Generic AT command - return OK
    if cmd.startswith("AT"):
        return "OK"

    # Unknown OBD PID
    if cmd.startswith("01"):
        return "NO DATA"

    # Unknown command
    return "?"

def main():
    log("Handler started")

    # Send initial prompt
    sys.stdout.write(">")
    sys.stdout.flush()
    log("Sent initial prompt")

    buffer = ""

    try:
        while True:
            # Read character by character
            char = sys.stdin.read(1)

            if not char:
                log("EOF received, exiting")
                break

            # Log raw char for debugging
            if char not in '\r\n':
                log(f"Char: {repr(char)}")

            # Check for command terminator (CR or LF)
            if char in '\r\n':
                if buffer:
                    cmd = buffer.strip()
                    log(f"Command: [{cmd}]")

                    response = process_command(cmd)
                    log(f"Response: [{response}]")

                    # Send response with CR/CR/> format (ELM327 style)
                    output = f"{response}\r\r>"
                    sys.stdout.write(output)
                    sys.stdout.flush()

                buffer = ""
            else:
                buffer += char

    except Exception as e:
        log(f"Error: {e}")
    finally:
        log("Handler ended")

if __name__ == "__main__":
    main()
