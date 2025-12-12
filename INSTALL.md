# OBD Gauge Installation Guide

Complete guide to set up the OBD gauge display from scratch.

## Hardware Requirements

| Component | Model | Notes |
|-----------|-------|-------|
| **SBC** | Raspberry Pi Zero 2W | Quad-core ARM Cortex-A53 @ 1GHz, 512MB RAM |
| **Display** | HyperPixel 2.1 Round | 480x480 circular, DPI interface, capacitive touch |
| **OBD Adapter** | OBDLink MX+ | Bluetooth Classic, supports 500kbps CAN |
| **Power** | 5V 2A minimum | USB-C or micro-USB depending on Pi model |
| **Storage** | 8GB+ microSD | Class 10 or faster recommended |

### Alternative OBD Adapters

| Adapter | Compatibility | Notes |
|---------|---------------|-------|
| OBDLink MX+ | Recommended | Fast, reliable, good Bluetooth range |
| OBDLink LX | Compatible | Budget option, same protocol support |
| Generic ELM327 | May work | Slower, less reliable than OBDLink |

## OS Installation

### 1. Download Raspberry Pi OS

Download **Raspberry Pi OS Lite (32-bit or 64-bit)** - Bullseye or newer.

Use Raspberry Pi Imager for easiest setup.

### 2. Pre-Boot Configuration

Before first boot, configure on the SD card:

**Enable SSH** - Create empty file:
```bash
touch /boot/ssh
```

**Configure WiFi** - Create `/boot/wpa_supplicant.conf`:
```ini
country=US
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1

network={
    ssid="YourNetworkName"
    psk="YourPassword"
    key_mgmt=WPA-PSK
}
```

### 3. First Boot

1. Insert SD card and power on
2. Wait 1-2 minutes for boot
3. Find IP address (check router or use `ping raspberrypi.local`)
4. SSH in: `ssh pi@<ip-address>` (default password: `raspberry`)

### 4. Initial Setup

```bash
# Change password
passwd

# Update system
sudo apt update && sudo apt upgrade -y

# Set hostname (optional)
sudo hostnamectl set-hostname claude-go

# Create user (optional - match your setup)
sudo adduser claude
sudo usermod -aG sudo claude
```

## Display Driver Installation

### HyperPixel 2.1 Round Setup

**Physical Installation:**
1. Power off Pi
2. Attach HyperPixel HAT to 40-pin GPIO
3. Secure with standoffs if available

**Driver Configuration:**

Edit `/boot/config.txt`:
```ini
# HyperPixel 2.1 Round display
dtoverlay=hyperpixel2r

# Disable kernel touch driver for Python access
dtoverlay=hyperpixel2r:disable-touch

# Recommended for Pi Zero 2W
gpu_mem=128
```

**Reboot:**
```bash
sudo reboot
```

**Verify Display:**
```bash
# Should show random pixels on display
cat /dev/urandom > /dev/fb0
```

## Python Dependencies

### System Packages

```bash
sudo apt install -y \
    python3-pygame \
    python3-pip \
    python3-dev \
    libsdl2-dev \
    libsdl2-image-dev \
    libsdl2-ttf-dev \
    bluetooth \
    bluez \
    bluez-tools
```

### Python Packages

```bash
# hyperpixel2r touch library
git clone https://github.com/pimoroni/hyperpixel2r-python
cd hyperpixel2r-python
sudo ./install.sh
cd ..

# OBD library (optional - we use native socket)
pip3 install obd
```

## Application Installation

### Clone Repository

```bash
cd ~
git clone <repository-url> obd-gauge
cd obd-gauge
```

### Verify Installation

```bash
# Test run (will show error if OBD not connected)
sudo SDL_FBDEV=/dev/fb0 python3 boost_gauge.py --demo
```

## Bluetooth OBD Pairing

### Pair OBDLink MX+

```bash
bluetoothctl
> power on
> agent on
> default-agent
> scan on
# Wait for "OBDLink MX+" to appear
> pair 00:04:3E:XX:XX:XX    # Replace with your device MAC
> trust 00:04:3E:XX:XX:XX
> quit
```

### Update Configuration

Edit `config/settings.json`:
```json
{
  "obd": {
    "bt_device_mac": "00:04:3E:XX:XX:XX",
    "bt_device_name": "OBDLink MX+"
  }
}
```

See `docs/BLUETOOTH_OBD_SETUP.md` for detailed troubleshooting.

## Auto-Start Configuration

### Using rc.local (Recommended)

The systemd service can have issues with SIGHUP when pygame uses fbcon.
rc.local is more reliable:

Edit `/etc/rc.local` (before `exit 0`):
```bash
# Start OBD Gauge
sleep 5
SDL_FBDEV=/dev/fb0 /usr/bin/python3 /home/claude/obd-gauge/boost_gauge.py --fps 30 --obd 25 --smooth 0.25 &
```

Make executable:
```bash
sudo chmod +x /etc/rc.local
```

### Using systemd (Alternative)

Create `/etc/systemd/system/obd-gauge.service`:
```ini
[Unit]
Description=OBD Gauge Display
After=multi-user.target

[Service]
Type=simple
User=root
Environment=SDL_FBDEV=/dev/fb0
ExecStart=/usr/bin/python3 /home/claude/obd-gauge/boost_gauge.py --fps 30
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable obd-gauge
sudo systemctl start obd-gauge
```

### Disable Console on Display

Prevent terminal from appearing behind gauge:
```bash
sudo systemctl disable getty@tty1
```

## Verification

### Test Auto-Start

```bash
sudo reboot
# Wait for boot - gauge should appear automatically
```

### Check Status

```bash
# If using systemd
sudo systemctl status obd-gauge

# If using rc.local
ps aux | grep boost_gauge
```

### Test OBD Connection

1. Turn on vehicle ignition
2. Gauge should connect within 10-30 seconds
3. Check for "OBD Connected" status on settings screen

## Troubleshooting

### Display Issues

| Problem | Solution |
|---------|----------|
| Black screen | Check `/boot/config.txt` has `dtoverlay=hyperpixel2r` |
| Garbled display | Framebuffer stride issue - code should handle this |
| Terminal visible | Disable getty: `sudo systemctl disable getty@tty1` |

### Bluetooth Issues

| Problem | Solution |
|---------|----------|
| Can't find OBDLink | Ensure adapter is powered (vehicle ignition on) |
| Pairing fails | Remove and re-pair in bluetoothctl |
| Connection drops | Check OBD adapter battery/power |

### Performance Issues

| Problem | Solution |
|---------|----------|
| Slow animations | Reduce FPS with `--fps 30` |
| High CPU | Ensure surface caching is working |
| Choppy needle | Adjust smoothing with `--smooth 0.25` |

## Network Configuration (Optional)

For reliable remote access, configure static IP:

Edit `/etc/dhcpcd.conf`:
```ini
interface wlan0
static ip_address=10.0.0.219/24
static routers=10.0.0.1
static domain_name_servers=10.0.0.1
```

## Next Steps

- `docs/hardware.md` - Detailed hardware information
- `docs/BLUETOOTH_OBD_SETUP.md` - OBD connection troubleshooting
- `docs/PERFORMANCE_OPTIMIZATION.md` - Animation tuning
- `CONTRIBUTING.md` - Development workflow

---

**Last Updated:** 2025-12-12
