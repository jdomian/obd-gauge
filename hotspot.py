"""
Hotspot Management for OBD-Gauge Settings

Creates an on-demand WiFi access point for phone-based configuration.
Uses hostapd + dnsmasq on Raspberry Pi Zero 2W.

SSID: obd-gauge (no password)
IP: 192.168.4.1
"""

import subprocess
import time
import os

HOTSPOT_SSID = "obd-gauge"
HOTSPOT_IP = "192.168.4.1"
HOTSPOT_SUBNET = "192.168.4.0/24"
INTERFACE = "wlan0"

# Config file paths
HOSTAPD_CONF = "/etc/hostapd/hostapd.conf"
DNSMASQ_CONF = "/etc/dnsmasq.d/hotspot.conf"


def _run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)


def is_hostapd_installed() -> bool:
    """Check if hostapd is installed."""
    result = _run("which hostapd", check=False)
    return result.returncode == 0


def is_hotspot_active() -> bool:
    """Check if hotspot is currently running."""
    result = _run("systemctl is-active hostapd", check=False)
    return result.stdout.strip() == "active"


def create_hostapd_config():
    """Create hostapd configuration file."""
    config = f"""# OBD-Gauge Hotspot Configuration
interface={INTERFACE}
driver=nl80211
ssid={HOTSPOT_SSID}
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=0
"""

    # Write config (requires sudo)
    try:
        with open("/tmp/hostapd.conf", "w") as f:
            f.write(config)
        _run(f"sudo cp /tmp/hostapd.conf {HOSTAPD_CONF}")
        _run(f"sudo chmod 644 {HOSTAPD_CONF}")
        print(f"Created {HOSTAPD_CONF}")
        return True
    except Exception as e:
        print(f"Failed to create hostapd config: {e}")
        return False


def create_dnsmasq_config():
    """Create dnsmasq DHCP configuration for hotspot."""
    config = f"""# OBD-Gauge Hotspot DHCP
interface={INTERFACE}
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,24h
address=/#/{HOTSPOT_IP}
"""

    try:
        with open("/tmp/hotspot.conf", "w") as f:
            f.write(config)
        _run(f"sudo cp /tmp/hotspot.conf {DNSMASQ_CONF}")
        _run(f"sudo chmod 644 {DNSMASQ_CONF}")
        print(f"Created {DNSMASQ_CONF}")
        return True
    except Exception as e:
        print(f"Failed to create dnsmasq config: {e}")
        return False


def start_hotspot() -> bool:
    """
    Start the WiFi hotspot.

    This stops wpa_supplicant (normal WiFi), configures the interface,
    and starts hostapd + dnsmasq.
    """
    if is_hotspot_active():
        print("Hotspot already active")
        return True

    try:
        print("Starting hotspot...")

        # Stop normal WiFi client services
        _run("sudo systemctl stop wpa_supplicant", check=False)
        _run("sudo systemctl stop dhcpcd", check=False)  # Stop DHCP client too
        time.sleep(0.5)

        # Kill any remaining wpa processes
        _run("sudo killall wpa_supplicant", check=False)
        time.sleep(0.3)

        # Configure interface - flush ALL addresses
        _run(f"sudo ip addr flush dev {INTERFACE}", check=False)
        time.sleep(0.2)
        _run(f"sudo ip addr add {HOTSPOT_IP}/24 dev {INTERFACE}")
        _run(f"sudo ip link set {INTERFACE} up")

        # Ensure configs exist
        if not os.path.exists(HOSTAPD_CONF):
            create_hostapd_config()
        if not os.path.exists(DNSMASQ_CONF):
            create_dnsmasq_config()

        # Start hostapd
        _run("sudo systemctl start hostapd")
        time.sleep(1)

        # Start dnsmasq for DHCP
        _run("sudo systemctl restart dnsmasq")

        print(f"Hotspot started: SSID={HOTSPOT_SSID}, IP={HOTSPOT_IP}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"Failed to start hotspot: {e}")
        print(f"stderr: {e.stderr}")
        # Try to restore normal WiFi
        stop_hotspot()
        return False


def stop_hotspot() -> bool:
    """
    Stop the WiFi hotspot and restore normal WiFi.
    """
    try:
        print("Stopping hotspot...")

        # Stop hostapd
        _run("sudo systemctl stop hostapd", check=False)

        # Stop our dnsmasq config (but don't kill system dnsmasq)
        _run("sudo systemctl restart dnsmasq", check=False)

        # Remove IP from interface
        _run(f"sudo ip addr flush dev {INTERFACE}", check=False)

        # Restart normal WiFi
        _run("sudo systemctl start wpa_supplicant")
        time.sleep(1)

        # Restart dhcpcd to get normal IP
        _run("sudo systemctl restart dhcpcd", check=False)

        print("Hotspot stopped, normal WiFi restored")
        return True

    except subprocess.CalledProcessError as e:
        print(f"Failed to stop hotspot cleanly: {e}")
        return False


def setup_hotspot() -> bool:
    """
    One-time setup for hotspot functionality.
    Installs hostapd if needed and creates config files.
    """
    print("Setting up hotspot...")

    # Check/install hostapd
    if not is_hostapd_installed():
        print("Installing hostapd...")
        try:
            _run("sudo apt-get update")
            _run("sudo apt-get install -y hostapd")
            _run("sudo systemctl unmask hostapd")
            _run("sudo systemctl disable hostapd")  # Don't start on boot
        except subprocess.CalledProcessError as e:
            print(f"Failed to install hostapd: {e}")
            return False

    # Create configs
    create_hostapd_config()
    create_dnsmasq_config()

    # Set hostapd config path
    _run(f'sudo sed -i "s|#DAEMON_CONF=.*|DAEMON_CONF={HOSTAPD_CONF}|" /etc/default/hostapd', check=False)

    print("Hotspot setup complete")
    return True


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python hotspot.py [start|stop|status|setup]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "start":
        start_hotspot()
    elif cmd == "stop":
        stop_hotspot()
    elif cmd == "status":
        if is_hotspot_active():
            print(f"Hotspot ACTIVE: SSID={HOTSPOT_SSID}, IP={HOTSPOT_IP}")
        else:
            print("Hotspot INACTIVE")
    elif cmd == "setup":
        setup_hotspot()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
