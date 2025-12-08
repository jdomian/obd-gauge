#!/usr/bin/env python3
"""
Virtual Accelerator Pedal

Keyboard-controlled throttle input for OBD simulator.
Updates shared state file that simulator reads.

Controls:
    UP      - Increase throttle 5%
    DOWN    - Decrease throttle 5%
    SPACE   - Wide Open Throttle (WOT) - 100%
    R       - Reset to idle (0%)
    1-9     - Set throttle to 10%-90%
    0       - Set throttle to 100%
    Q       - Quit

Physics Model:
    - RPM follows throttle with inertia
    - Boost builds progressively above ~3000 RPM
    - Speed increases based on RPM and gear ratio
"""

import sys
import os
import json
import time
import tty
import termios
import select
from pathlib import Path

# Shared state file (same as simulator)
STATE_FILE = "/tmp/obd_sim_state.json"

# Physics constants (RS7 4.0T characteristics)
IDLE_RPM = 660
REDLINE_RPM = 7000
MAX_BOOST_PSI = 22  # APR Stage 1 peak boost
BOOST_THRESHOLD_RPM = 2500  # Turbos start spooling
FULL_BOOST_RPM = 4000  # Full boost available

# Atmospheric pressure (St. Louis elevation ~140m)
BARO_KPA = 99

# Response rates (per update cycle ~50ms)
RPM_RISE_RATE = 200  # RPM increase per cycle at WOT
RPM_FALL_RATE = 150  # RPM decrease per cycle (engine braking)
BOOST_RISE_RATE = 2.0  # PSI increase per cycle
BOOST_FALL_RATE = 3.0  # PSI decrease per cycle (wastegate opens fast)


def kpa_from_boost_psi(boost_psi):
    """Convert boost PSI (relative to atmosphere) to MAP kPa (absolute)."""
    return BARO_KPA + (boost_psi / 0.145038)


def get_key():
    """Get a single keypress without waiting for Enter."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        # Check if input is available
        if select.select([sys.stdin], [], [], 0.05)[0]:
            ch = sys.stdin.read(1)
            # Handle arrow keys (escape sequences)
            if ch == '\x1b':
                ch += sys.stdin.read(2)
            return ch
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def load_state():
    """Load current state from file."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {
            "throttle": 0.0,
            "rpm": IDLE_RPM,
            "map_kpa": 38,
            "coolant_c": 75,
            "speed_kph": 0,
            "intake_temp_c": 25,
            "voltage": 14.3,
            "baro_kpa": BARO_KPA,
        }


def save_state(state):
    """Save state to file."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def calculate_target_rpm(throttle):
    """Calculate target RPM based on throttle position."""
    # Simple linear mapping for now
    # 0% throttle = idle, 100% throttle = redline
    return IDLE_RPM + (throttle / 100.0) * (REDLINE_RPM - IDLE_RPM)


def calculate_boost(rpm, throttle):
    """Calculate boost pressure based on RPM and throttle."""
    if rpm < BOOST_THRESHOLD_RPM or throttle < 20:
        # Below threshold or light throttle = vacuum
        # More vacuum at lower throttle
        vacuum_psi = -12 + (throttle / 100.0) * 4  # -12 to -8 PSI
        return vacuum_psi

    # Calculate boost based on RPM and throttle
    rpm_factor = min(1.0, (rpm - BOOST_THRESHOLD_RPM) / (FULL_BOOST_RPM - BOOST_THRESHOLD_RPM))
    throttle_factor = (throttle - 20) / 80.0  # 20-100% throttle maps to 0-1

    target_boost = MAX_BOOST_PSI * rpm_factor * throttle_factor
    return target_boost


def calculate_speed(rpm, current_speed):
    """Calculate vehicle speed based on RPM (simplified)."""
    # Assume we're in a gear that gives ~30 mph per 1000 RPM
    # (This is roughly 4th gear in an RS7)
    target_speed = (rpm / 1000.0) * 30

    # Smooth transition
    speed_diff = target_speed - current_speed
    return current_speed + speed_diff * 0.1


def update_physics(state):
    """Update RPM, boost, speed based on current throttle."""
    throttle = state["throttle"]
    current_rpm = state["rpm"]

    # Calculate target RPM
    target_rpm = calculate_target_rpm(throttle)

    # Move RPM toward target with inertia
    if current_rpm < target_rpm:
        # Accelerating
        rate = RPM_RISE_RATE * (throttle / 100.0 + 0.3)  # Faster at higher throttle
        new_rpm = min(target_rpm, current_rpm + rate)
    else:
        # Decelerating
        new_rpm = max(target_rpm, current_rpm - RPM_FALL_RATE)

    # Clamp to valid range
    new_rpm = max(IDLE_RPM, min(REDLINE_RPM, new_rpm))
    state["rpm"] = int(new_rpm)

    # Calculate boost
    target_boost = calculate_boost(new_rpm, throttle)
    current_boost = (state["map_kpa"] - BARO_KPA) * 0.145038  # Convert MAP to boost PSI

    if target_boost > current_boost:
        # Building boost (turbo spool)
        new_boost = min(target_boost, current_boost + BOOST_RISE_RATE)
    else:
        # Dropping boost (wastegate/throttle lift)
        new_boost = max(target_boost, current_boost - BOOST_FALL_RATE)

    state["map_kpa"] = int(kpa_from_boost_psi(new_boost))

    # Calculate speed
    state["speed_kph"] = int(calculate_speed(new_rpm, state["speed_kph"]))

    # Update voltage (slight drop under load)
    state["voltage"] = round(14.4 - (throttle / 100.0) * 0.3, 1)

    return state


def draw_display(state):
    """Draw the accelerator pedal display."""
    throttle = state["throttle"]
    rpm = state["rpm"]
    boost_psi = (state["map_kpa"] - state["baro_kpa"]) * 0.145038
    speed = state["speed_kph"]

    # Clear screen and move cursor to top
    sys.stdout.write("\033[H\033[J")

    # Title
    print("╔════════════════════════════════════════════════════╗")
    print("║     🏎️  RS7 VIRTUAL ACCELERATOR PEDAL  🏎️          ║")
    print("╠════════════════════════════════════════════════════╣")

    # Throttle bar
    bar_width = 40
    filled = int(throttle / 100.0 * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)

    # Color based on throttle position
    if throttle >= 90:
        color = "\033[91m"  # Red
    elif throttle >= 50:
        color = "\033[93m"  # Yellow
    else:
        color = "\033[92m"  # Green

    print(f"║  THROTTLE: {color}{bar}\033[0m {throttle:5.1f}% ║")

    # RPM bar
    rpm_pct = (rpm - IDLE_RPM) / (REDLINE_RPM - IDLE_RPM) * 100
    rpm_filled = int(rpm_pct / 100.0 * bar_width)
    rpm_bar = "█" * rpm_filled + "░" * (bar_width - rpm_filled)

    if rpm >= 6000:
        rpm_color = "\033[91m"  # Red - shift!
    elif rpm >= 4500:
        rpm_color = "\033[93m"  # Yellow
    else:
        rpm_color = "\033[92m"  # Green

    print(f"║  RPM:      {rpm_color}{rpm_bar}\033[0m {rpm:5d}  ║")

    # Boost bar (scale: -15 to +25 PSI)
    boost_min, boost_max = -15, 25
    boost_pct = (boost_psi - boost_min) / (boost_max - boost_min) * 100
    boost_filled = int(max(0, min(100, boost_pct)) / 100.0 * bar_width)
    boost_bar = "█" * boost_filled + "░" * (bar_width - boost_filled)

    if boost_psi > 15:
        boost_color = "\033[91m"  # Red - high boost
    elif boost_psi > 0:
        boost_color = "\033[93m"  # Yellow - positive boost
    else:
        boost_color = "\033[96m"  # Cyan - vacuum

    boost_str = f"{boost_psi:+5.1f}" if boost_psi != 0 else " 0.0 "
    print(f"║  BOOST:    {boost_color}{boost_bar}\033[0m {boost_str}PSI║")

    # Speed
    print(f"║  SPEED:    {speed:3d} km/h  ({int(speed * 0.621371):3d} mph)                 ║")

    print("╠════════════════════════════════════════════════════╣")
    print("║  CONTROLS:                                         ║")
    print("║    ↑/↓    Throttle +/- 5%                          ║")
    print("║    SPACE  WOT (100%)                               ║")
    print("║    R      Reset to idle                            ║")
    print("║    1-9    Set 10%-90%                              ║")
    print("║    0      Set 100%                                 ║")
    print("║    Q      Quit                                     ║")
    print("╚════════════════════════════════════════════════════╝")

    sys.stdout.flush()


def main():
    print("Starting Virtual Accelerator Pedal...")
    print(f"State file: {STATE_FILE}")
    print("Press any key to begin (Q to quit)")

    # Initialize state
    state = load_state()
    state["throttle"] = 0.0
    state["rpm"] = IDLE_RPM
    state["speed_kph"] = 0
    save_state(state)

    # Hide cursor
    sys.stdout.write("\033[?25l")

    try:
        while True:
            # Handle input
            key = get_key()

            if key:
                if key.lower() == 'q':
                    break
                elif key == '\x1b[A':  # Up arrow
                    state["throttle"] = min(100, state["throttle"] + 5)
                elif key == '\x1b[B':  # Down arrow
                    state["throttle"] = max(0, state["throttle"] - 5)
                elif key == ' ':  # Space - WOT
                    state["throttle"] = 100
                elif key.lower() == 'r':  # Reset
                    state["throttle"] = 0
                elif key in '123456789':
                    state["throttle"] = int(key) * 10
                elif key == '0':
                    state["throttle"] = 100

            # Update physics
            state = update_physics(state)

            # Save state for simulator to read
            save_state(state)

            # Update display
            draw_display(state)

            # Target ~20 Hz update rate
            time.sleep(0.05)

    except KeyboardInterrupt:
        pass
    finally:
        # Show cursor and reset terminal
        sys.stdout.write("\033[?25h")
        sys.stdout.write("\033[0m")
        print("\n\nAccelerator pedal stopped.")


if __name__ == "__main__":
    main()
