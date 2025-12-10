#!/usr/bin/env python3
"""
OBD Simulator Controller - Interactive CLI

Control the simulated car values with your keyboard:
  HOLD keys to increase values (like pressing a pedal)
  RELEASE to let values decay naturally

Controls:
  T = Throttle (0-100%)
  R = RPM (660-7500)
  B = Boost/MAP (38-250 kPa)
  S = Speed (0-250 km/h)

  UP/DOWN = Adjust selected value faster
  SPACE = Rev bomb (instant max RPM burst)
  0 = Reset to idle
  Q = Quit

The values are written to /tmp/obd_sim_state.json which the
Bluetooth OBD simulator reads when the gauge requests PIDs.
"""

import sys
import os
import json
import time
import select
import termios
import tty
import threading

# State file shared with simulator
STATE_FILE = "/tmp/obd_sim_state.json"

# Value limits
LIMITS = {
    "throttle": (0, 100),      # %
    "rpm": (660, 7500),        # RPM (660 = idle)
    "map_kpa": (38, 250),      # kPa (38 = idle vacuum, 250 = max boost)
    "speed_kph": (0, 280),     # km/h
    "coolant_c": (75, 105),    # °C
    "intake_temp_c": (20, 80), # °C
    "voltage": (12.0, 14.8),   # V
}

# Rate of change per tick (50ms)
RATES = {
    "throttle": {"up": 8, "down": 15},    # Fast up, faster down
    "rpm": {"up": 400, "down": 600},      # RPM climb and fall
    "map_kpa": {"up": 15, "down": 25},    # Boost builds, then bleeds
    "speed_kph": {"up": 5, "down": 3},    # Speed slower to change
}

# Default idle state
DEFAULT_STATE = {
    "throttle": 0.0,
    "rpm": 660,
    "map_kpa": 38,
    "coolant_c": 75,
    "speed_kph": 0,
    "intake_temp_c": 25,
    "voltage": 14.3,
    "baro_kpa": 99,
}


class SimController:
    def __init__(self):
        self.state = DEFAULT_STATE.copy()
        self.keys_held = set()
        self.running = True
        self.connected_clients = 0
        self.last_pid_request = None
        self.last_pid_time = 0

        # Load existing state if present
        self._load_state()

    def _load_state(self):
        """Load state from file if it exists."""
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE) as f:
                    loaded = json.load(f)
                    self.state.update(loaded)
        except:
            pass

    def _save_state(self):
        """Write state to file."""
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(self.state, f)
        except Exception as e:
            print(f"\rError saving state: {e}")

    def _clamp(self, key, value):
        """Clamp value to limits."""
        if key in LIMITS:
            lo, hi = LIMITS[key]
            return max(lo, min(hi, value))
        return value

    def update(self):
        """Update state based on held keys."""

        # Throttle
        if 't' in self.keys_held:
            self.state["throttle"] += RATES["throttle"]["up"]
        else:
            self.state["throttle"] -= RATES["throttle"]["down"]
        self.state["throttle"] = self._clamp("throttle", self.state["throttle"])

        # RPM - follows throttle with some lag
        if 'r' in self.keys_held or self.state["throttle"] > 10:
            target_rpm = 660 + (self.state["throttle"] / 100) * 6840
            if 'r' in self.keys_held:
                target_rpm = 7500  # Direct override
            if self.state["rpm"] < target_rpm:
                self.state["rpm"] += RATES["rpm"]["up"]
        else:
            self.state["rpm"] -= RATES["rpm"]["down"]
        self.state["rpm"] = self._clamp("rpm", self.state["rpm"])

        # Boost - builds with throttle and RPM
        if 'b' in self.keys_held or (self.state["throttle"] > 50 and self.state["rpm"] > 2500):
            if 'b' in self.keys_held:
                self.state["map_kpa"] += RATES["map_kpa"]["up"] * 2
            else:
                self.state["map_kpa"] += RATES["map_kpa"]["up"]
        else:
            self.state["map_kpa"] -= RATES["map_kpa"]["down"]
        self.state["map_kpa"] = self._clamp("map_kpa", self.state["map_kpa"])

        # Speed - slower response, tied to throttle
        if 's' in self.keys_held or self.state["throttle"] > 30:
            if 's' in self.keys_held:
                self.state["speed_kph"] += RATES["speed_kph"]["up"] * 3
            else:
                self.state["speed_kph"] += RATES["speed_kph"]["up"]
        else:
            self.state["speed_kph"] -= RATES["speed_kph"]["down"]
        self.state["speed_kph"] = self._clamp("speed_kph", self.state["speed_kph"])

        # Coolant - slowly rises under load
        if self.state["rpm"] > 3000:
            self.state["coolant_c"] += 0.1
        else:
            self.state["coolant_c"] -= 0.05
        self.state["coolant_c"] = self._clamp("coolant_c", self.state["coolant_c"])

        # Intake temp - rises with boost
        if self.state["map_kpa"] > 101:  # Under boost
            self.state["intake_temp_c"] += 0.5
        else:
            self.state["intake_temp_c"] -= 0.2
        self.state["intake_temp_c"] = self._clamp("intake_temp_c", self.state["intake_temp_c"])

        # Save to file
        self._save_state()

    def reset_to_idle(self):
        """Reset all values to idle."""
        self.state = DEFAULT_STATE.copy()
        self._save_state()

    def rev_bomb(self):
        """Instant max RPM burst."""
        self.state["rpm"] = 7500
        self.state["throttle"] = 100
        self._save_state()

    def render(self):
        """Render the current state display."""
        # Calculate boost PSI (MAP - 101 kPa atmospheric)
        boost_psi = (self.state["map_kpa"] - 101) * 0.145

        # Build display
        lines = []
        lines.append("\033[2J\033[H")  # Clear screen
        lines.append("╔══════════════════════════════════════════════════════════╗")
        lines.append("║           OBD SIMULATOR CONTROLLER - RS7 4.0T            ║")
        lines.append("╠══════════════════════════════════════════════════════════╣")

        # Throttle bar
        throttle_bar = "█" * int(self.state["throttle"] / 5) + "░" * (20 - int(self.state["throttle"] / 5))
        t_active = "▶" if 't' in self.keys_held else " "
        lines.append(f"║ {t_active}[T] THROTTLE: [{throttle_bar}] {self.state['throttle']:5.1f}%         ║")

        # RPM bar
        rpm_pct = (self.state["rpm"] - 660) / (7500 - 660) * 100
        rpm_bar = "█" * int(rpm_pct / 5) + "░" * (20 - int(rpm_pct / 5))
        r_active = "▶" if 'r' in self.keys_held else " "
        lines.append(f"║ {r_active}[R] RPM:      [{rpm_bar}] {self.state['rpm']:5.0f}          ║")

        # Boost bar (centered at 0 PSI)
        if boost_psi >= 0:
            boost_bar = "░" * 10 + "█" * min(10, int(boost_psi / 2.2))
            boost_bar = boost_bar.ljust(20, "░")
        else:
            vac_bars = min(10, int(abs(boost_psi) / 2))
            boost_bar = "░" * (10 - vac_bars) + "▓" * vac_bars + "░" * 10
        b_active = "▶" if 'b' in self.keys_held else " "
        lines.append(f"║ {b_active}[B] BOOST:    [{boost_bar}] {boost_psi:+5.1f} PSI       ║")

        # Speed bar
        speed_pct = self.state["speed_kph"] / 280 * 100
        speed_bar = "█" * int(speed_pct / 5) + "░" * (20 - int(speed_pct / 5))
        s_active = "▶" if 's' in self.keys_held else " "
        mph = self.state["speed_kph"] * 0.621
        lines.append(f"║ {s_active}[S] SPEED:    [{speed_bar}] {mph:5.0f} MPH        ║")

        lines.append("╠══════════════════════════════════════════════════════════╣")
        lines.append(f"║  Coolant: {self.state['coolant_c']:5.1f}°C    Intake: {self.state['intake_temp_c']:5.1f}°C    Volts: {self.state['voltage']:.1f}V  ║")
        lines.append("╠══════════════════════════════════════════════════════════╣")
        lines.append("║  HOLD keys to increase • RELEASE to decay naturally      ║")
        lines.append("║  [SPACE] Rev bomb   [0] Reset to idle   [Q] Quit         ║")
        lines.append("╚══════════════════════════════════════════════════════════╝")

        # Connection status
        if time.time() - self.last_pid_time < 2:
            lines.append(f"\n  📡 CONNECTED - Last PID: {self.last_pid_request}")
        else:
            lines.append("\n  ⏳ Waiting for gauge connection...")

        return "\n".join(lines)


def watch_pid_requests(controller):
    """Background thread to watch for PID requests in simulator logs."""
    # This would ideally read from the simulator's log output
    # For now, we just check if the state file is being accessed
    last_mtime = 0
    while controller.running:
        try:
            if os.path.exists(STATE_FILE):
                mtime = os.path.getmtime(STATE_FILE)
                if mtime != last_mtime:
                    last_mtime = mtime
            time.sleep(0.1)
        except:
            pass


def get_key():
    """Get keypress without blocking, return None if no key."""
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1).lower()
    return None


def main():
    print("Starting OBD Simulator Controller...")
    print("Make sure the BT simulator (bt_dbus_server.py) is running!")
    print()

    controller = SimController()

    # Save terminal settings
    old_settings = termios.tcgetattr(sys.stdin)

    try:
        # Set terminal to raw mode
        tty.setcbreak(sys.stdin.fileno())

        last_render = 0

        while controller.running:
            # Check for keypress
            key = get_key()

            if key:
                if key == 'q':
                    controller.running = False
                elif key == '0':
                    controller.reset_to_idle()
                elif key == ' ':
                    controller.rev_bomb()
                elif key in ('t', 'r', 'b', 's'):
                    controller.keys_held.add(key)

            # Check for key releases (approximation - clear after short delay)
            # In a real implementation, we'd use proper key up/down detection

            # Update physics
            controller.update()

            # Render at ~5fps (slower, easier to read)
            now = time.time()
            if now - last_render > 0.2:
                print(controller.render(), end="", flush=True)
                last_render = now

            # Small sleep
            time.sleep(0.05)

            # Decay key holds (simple approximation)
            # Keys auto-release after not being pressed
            controller.keys_held.clear()

    except KeyboardInterrupt:
        pass
    finally:
        # Restore terminal
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        print("\n\nController stopped. State preserved in", STATE_FILE)


if __name__ == "__main__":
    main()
