#!/usr/bin/env python3
"""
OBD Test CLI - Interactive keyboard-based PID tester
Hold keys to continuously poll PIDs, release to stop

Keys:
  R - RPM
  T - Throttle Position
  B - Boost Pressure (MAP sensor)
  S - Speed
  C - Coolant Temperature
  O - Oil Temperature
  V - Voltage
  I - Intake Air Temperature
  L - Engine Load
  F - Fuel Level

  A - All gauges (continuous refresh)
  Q - Quit

  SPACE - Single poll of all
"""

import serial
import sys
import time
import select
import termios
import tty

# OBD2 PIDs we care about for the RS7
PIDS = {
    'r': {'pid': '010C', 'name': 'RPM', 'parse': lambda d: f"{((d[0]*256)+d[1])/4:.0f} RPM"},
    't': {'pid': '0111', 'name': 'Throttle', 'parse': lambda d: f"{d[0]*100/255:.1f}%"},
    'b': {'pid': '010B', 'name': 'Boost/MAP', 'parse': lambda d: f"{d[0]} kPa ({(d[0]-101)*0.145:.1f} PSI)"},
    's': {'pid': '010D', 'name': 'Speed', 'parse': lambda d: f"{d[0]} km/h ({d[0]*0.621:.0f} mph)"},
    'c': {'pid': '0105', 'name': 'Coolant', 'parse': lambda d: f"{d[0]-40}°C ({(d[0]-40)*9/5+32:.0f}°F)"},
    'o': {'pid': '015C', 'name': 'Oil Temp', 'parse': lambda d: f"{d[0]-40}°C ({(d[0]-40)*9/5+32:.0f}°F)"},
    'v': {'pid': 'ATRV', 'name': 'Voltage', 'parse': lambda d: d},  # Special AT command
    'i': {'pid': '010F', 'name': 'Intake Air', 'parse': lambda d: f"{d[0]-40}°C ({(d[0]-40)*9/5+32:.0f}°F)"},
    'l': {'pid': '0104', 'name': 'Load', 'parse': lambda d: f"{d[0]*100/255:.1f}%"},
    'f': {'pid': '012F', 'name': 'Fuel Level', 'parse': lambda d: f"{d[0]*100/255:.1f}%"},
}

class OBDConnection:
    def __init__(self, port='/dev/rfcomm0', baud=38400):
        self.ser = serial.Serial(port, baud, timeout=1)
        time.sleep(0.5)
        self._init_elm()

    def _init_elm(self):
        """Initialize ELM327"""
        self.cmd('ATZ')  # Reset
        time.sleep(0.5)
        self.cmd('ATE0')  # Echo off
        self.cmd('ATL0')  # Linefeeds off
        self.cmd('ATS0')  # Spaces off (for easier parsing)
        self.cmd('ATH0')  # Headers off
        self.cmd('ATSP6') # Protocol 6 (CAN 500kbps)

    def cmd(self, command):
        """Send command and get response"""
        self.ser.reset_input_buffer()
        self.ser.write((command + '\r').encode())
        time.sleep(0.1)
        response = self.ser.read(500).decode(errors='ignore')
        return response.replace('>', '').replace('\r', '').replace('\n', ' ').strip()

    def get_pid(self, pid_info):
        """Get and parse a PID"""
        pid = pid_info['pid']

        # Handle AT commands (voltage)
        if pid.startswith('AT'):
            raw = self.cmd(pid)
            return pid_info['parse'](raw)

        raw = self.cmd(pid)

        # Parse hex response like "410C0A50"
        # Remove the echo (41 XX) and get data bytes
        try:
            # Find response after "41"
            if '41' in raw:
                idx = raw.index('41')
                hex_data = raw[idx:].replace(' ', '')
                # Skip "41XX" (response header)
                data_hex = hex_data[4:]
                # Convert pairs to bytes
                data_bytes = [int(data_hex[i:i+2], 16) for i in range(0, len(data_hex), 2)]
                if data_bytes:
                    return pid_info['parse'](data_bytes)
            return f"NO DATA ({raw})"
        except Exception as e:
            return f"ERROR: {e} ({raw})"

    def close(self):
        self.ser.close()


def get_key_nonblocking():
    """Get a keypress without blocking"""
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1).lower()
    return None


def main():
    print("=" * 50)
    print("  OBD Test CLI - RS7 Gauge Tester")
    print("=" * 50)
    print()
    print("Connecting to /dev/rfcomm0...")

    try:
        obd = OBDConnection()
    except Exception as e:
        print(f"Connection failed: {e}")
        print("\nMake sure RFCOMM is bound:")
        print("  sudo rfcomm -i hci0 bind 0 <MAC> 1")
        sys.exit(1)

    print("Connected!")
    print()
    print("Keys:")
    print("  R=RPM  T=Throttle  B=Boost  S=Speed  C=Coolant")
    print("  O=Oil  V=Voltage   I=Intake L=Load   F=Fuel")
    print("  A=All (continuous)  SPACE=Poll all once  Q=Quit")
    print()
    print("-" * 50)

    # Set terminal to raw mode for keypress detection
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())

        continuous_mode = False
        running = True

        while running:
            key = get_key_nonblocking()

            if key == 'q':
                running = False
                continue

            if key == 'a':
                continuous_mode = not continuous_mode
                if continuous_mode:
                    print("\n[Continuous mode ON - press A to stop]")
                else:
                    print("\n[Continuous mode OFF]")
                continue

            if key == ' ':
                # Poll all once
                print("\n--- All Gauges ---")
                for k, pid_info in PIDS.items():
                    val = obd.get_pid(pid_info)
                    print(f"  {pid_info['name']}: {val}")
                print("-" * 30)
                continue

            if key and key in PIDS:
                # Single PID poll
                pid_info = PIDS[key]
                val = obd.get_pid(pid_info)
                print(f"{pid_info['name']}: {val}")
                continue

            if continuous_mode:
                # Refresh all gauges
                sys.stdout.write("\033[2J\033[H")  # Clear screen
                print("=== CONTINUOUS MODE (press A to stop) ===\n")
                for k, pid_info in PIDS.items():
                    val = obd.get_pid(pid_info)
                    print(f"  [{k.upper()}] {pid_info['name']:12}: {val}")
                print(f"\n  Last update: {time.strftime('%H:%M:%S')}")
                time.sleep(0.5)
            else:
                time.sleep(0.05)  # Small delay when idle

    finally:
        # Restore terminal
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        obd.close()
        print("\nDisconnected.")


if __name__ == '__main__':
    main()
