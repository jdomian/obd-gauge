# OBD Gauge Installation Guide

Complete guide to set up the OBD gauge display from scratch.

## Hardware Requirements

| Component | Model | Notes |
|-----------|-------|-------|
| **SBC** | Raspberry Pi Zero 2W | Quad-core ARM Cortex-A53 @ 1GHz, 512MB RAM |
| **Display** | HyperPixel 2.1 Round | 480x480 circular, DPI interface, capacitive touch |
| **OBD Adapter** | OBDLink MX+ | Bluetooth Classic, supports 500kbps CAN |
| **Power** | 5V 2A minimum | USB from vehicle or power bank |
| **Storage** | 8GB+ microSD | Class 10 or faster recommended |

### Alternative OBD Adapters

| Adapter | Compatibility | Notes |
|---------|---------------|-------|
| OBDLink MX+ | Recommended | Fast, reliable, good Bluetooth range |
| OBDLink LX | Compatible | Budget option, same protocol support |
| Generic ELM327 | May work | Slower, less reliable than OBDLink |

## OS Installation

### 1. Download Raspberry Pi OS

Download **Raspberry Pi OS Lite (64-bit)** - Bullseye or newer.

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
4. **Important**: Apply electrical tape over the bottom of the FPC ribbon cable / ground tab area to prevent it from shorting against the metal backing plate. Without this, the display will show resolution/interlacing artifacts.

**Driver Configuration:**

Edit `/boot/config.txt` to include these settings:
```ini
# Disable camera/DSI auto-detect
camera_auto_detect=0
display_auto_detect=0

# Use Legacy GL Driver (FKMS) - REQUIRED for HyperPixel 2r
# DO NOT use vc4-kms-v3d - it does not work with this display
dtoverlay=vc4-fkms-v3d
max_framebuffers=2

# Run in 64-bit mode
arm_64bit=1

# Disable overscan compensation
disable_overscan=1

# HyperPixel 2.1 Round - disable kernel touch driver for Python I2C access
dtoverlay=hyperpixel2r:disable-touch

[all]

# DPI timing parameters - REQUIRED, do not remove any of these
enable_dpi_lcd=1
dpi_group=2
dpi_mode=87
dpi_output_format=0x7f216
dpi_timings=480 0 10 16 55 480 0 15 60 15 0 0 0 60 0 19200000 6
dtparam=i2c_arm=on

# Disable onboard Bluetooth (using USB dongle or OBDLink MX+ directly)
dtoverlay=disable-bt
enable_uart=1
core_freq=250

# GPU memory - keep at 64 (Pi Zero 2W only has 512MB total)
gpu_mem=64
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
# Test run (will show demo mode if OBD not connected)
sudo SDL_FBDEV=/dev/fb0 SDL_VIDEODRIVER=fbcon python3 boost_gauge.py
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
# Lock CPU to maximum frequency
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null

# Wait for system services to settle
sleep 10

# Kill splash screen
pkill fbi 2>/dev/null
sleep 0.5

# Kill any existing instances
pkill -f boost_gauge.py 2>/dev/null

# Unbind console from framebuffer
echo 0 > /sys/class/vtconsole/vtcon1/bind 2>/dev/null

# Start the gauge with high priority
cd /home/claude/obd-gauge
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0
nice -n -10 /usr/bin/python3 boost_gauge.py &
```

Make executable:
```bash
sudo chmod +x /etc/rc.local
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
# Check if running
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
| Black screen | Check `/boot/config.txt` has correct FKMS config (see above) |
| Interlacing / resolution artifacts | Apply electrical tape over FPC ribbon contacts at bottom of display |
| Garbled display | Framebuffer stride issue - code handles this automatically |
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
| Low FPS | Check CPU governor is `performance` |
| High CPU | Ensure surface caching is working |
| Choppy needle | Adjust smoothing in config/settings.json |

## Next Steps

- `docs/hardware.md` - Detailed hardware information and display driver notes
- `docs/BLUETOOTH_OBD_SETUP.md` - OBD connection troubleshooting
- `docs/PERFORMANCE_OPTIMIZATION.md` - Animation tuning

---

**Last Updated:** 2026-02-04
