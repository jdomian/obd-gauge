# OBD Gauge - Claude Code Context

## Project Overview

Real-time OBD2 gauge display for Raspberry Pi Zero 2W + HyperPixel 2.1 Round (480x480 circular display).
Optimized for 2016 Audi RS7 with OBDLink MX+ Bluetooth adapter.

## Quick Reference

| Property | Value |
|----------|-------|
| **Target Device** | claude-go (DHCP - check router for IP) |
| **Dev Server** | claude-server (10.0.0.99) |
| **Main File** | `boost_gauge.py` (~3300 lines) |
| **Config** | `config/settings.json` |
| **Auto-start** | `/etc/rc.local` (systemd has SIGHUP issues with fbcon) |
| **Display Driver** | FKMS (`vc4-fkms-v3d`) - DO NOT use KMS |
| **SDL Driver** | `fbcon` - DO NOT change to `dummy` |

## Hardware

| Component | Details |
|-----------|---------|
| **SBC** | Raspberry Pi Zero 2W (512MB RAM) |
| **Display** | HyperPixel 2.1 Round (480x480, DPI interface) |
| **OBD** | OBDLink MX+ (BT MAC: 00:04:3E:88:EE:C0, PIN: 1234) |
| **Vehicle** | 2016 Audi RS7 4.0T (500kbps CAN) |

No battery (PiSugar removed). Powered via USB from vehicle.

## Deployment Workflow

```bash
# From claude-server (10.0.0.99)
rsync -avz --exclude '.git' --exclude '__pycache__' \
  /home/claude/obd-gauge/ claude@<device-ip>:~/obd-gauge/

# Restart the gauge app
ssh claude@<device-ip> "sudo reboot"
```

## Architecture

```
boost_gauge.py     - Main app: rendering, touch, OBD, navigation
obd_socket.py      - Native Bluetooth OBD2 connection (not python-obd library)
touch.py           - Gesture detection wrapper for hyperpixel2r
display.py         - Pygame initialization helpers
gauges.py          - Gauge configuration classes
conversions.py     - Unit conversions (kPa->PSI, C->F)
hotspot.py         - WiFi hotspot management
settings_server.py - Web-based settings UI
```

## Critical: Do NOT Change

1. **Display driver**: Must be `vc4-fkms-v3d` (FKMS). KMS (`vc4-kms-v3d`) does not work.
2. **SDL_VIDEODRIVER**: Must be `fbcon`. `dummy` breaks pygame display management.
3. **DPI timings**: The `dpi_timings` line in config.txt is required. Do not remove.
4. **gpu_mem**: Keep at 64. Pi Zero 2W only has 512MB total.

See `docs/hardware.md` for the full known-good `/boot/config.txt`.

## Key Technical Quirks

### Display Resolution Fix (Hardware)
The HyperPixel 2.1 Round can show resolution/interlacing artifacts. This is caused by FPC ribbon contacts shorting against the metal backing plate. Fix: electrical tape over the bottom contacts. See `docs/hardware.md` for details.

### Framebuffer Stride Issue
The HyperPixel 2r has a 720x480 virtual framebuffer but 480x480 physical display:
```python
# In _flip() method - must pad each row when writing to /dev/fb0
fb_stride = 720 * 2      # 1440 bytes per row
screen_stride = 480 * 2  # 960 bytes per row
# Pad each row with (720-480)*2 = 480 bytes
```

### pygame 2.6.1 border_radius Bug
`pygame.draw.rect()` with `border_radius=N` crashes on Pi. Use `_draw_capsule()` helper instead.

### Touch Input
Uses `hyperpixel2r` library with `disable-touch` overlay for Python I2C access:
```ini
# /boot/config.txt
dtoverlay=hyperpixel2r:disable-touch
```

## Performance Optimizations (Critical)

These optimizations achieve 60 FPS:

1. **Surface Caching** (`_label_cache`) - Perimeter labels pre-rendered once
2. **Pre-rendered Hub** (`_hub_surface`) - Center circle drawn once, blitted each frame
3. **Batched FB Writes** (`_fb_buffer`) - Single write instead of 480 row writes
4. **CPU Governor** - Set to `performance` in rc.local

```python
# Key methods for performance
self._init_hub_surface()       # Pre-render center hub
self._get_cached_labels()      # Get/create cached label surfaces
self._flip()                   # Batched framebuffer write
```

## Navigation System

2D grid: swipe LEFT/RIGHT for gauges, UP/DOWN for rows

```
Row 0: Gauge carousel (Boost, Coolant, Load)
Row 1: Settings/QR screen
Row 2: System (Demo mode, Brightness, Shutdown)
```

## Configuration

`config/settings.json`:
```json
{
  "gauges": [
    {"position": 0, "pid": "THROTTLE_POS", "label": "THROTTLE", "min": 0, "max": 100},
    {"position": 1, "pid": "COOLANT_TEMP", "label": "COOLANT", "min": 100, "max": 260},
    {"position": 2, "pid": "BOOST", "label": "BOOST", "min": -20, "max": 30}
  ],
  "display": {"fps": 60, "smoothing": 0.25, "dial_background": "audi"},
  "obd": {"rate_hz": 25, "bt_device_mac": "00:04:3E:88:EE:C0"}
}
```

## Common Tasks

### Add a New Gauge
1. Add entry to `config/settings.json` gauges array
2. Implement PID query in `obd_socket.py` if not standard

### Change Visual Style
- Dial backgrounds: `assets/dials/dial_background_*.png`
- Needle styles: `assets/needles/needle_*.png` (or use procedural in `_draw_needle()`)

### Debug OBD Connection
```bash
ssh claude@<device-ip>
bluetoothctl
> connect 00:04:3E:88:EE:C0  # OBDLink MX+ MAC
```

## Related Documentation

| Doc | Purpose |
|-----|---------|
| `docs/hardware.md` | Pi Zero 2W + HyperPixel setup, display fix, framebuffer details |
| `docs/BLUETOOTH_OBD_SETUP.md` | Complete OBD pairing and troubleshooting |
| `docs/PERFORMANCE_OPTIMIZATION.md` | Animation timing learnings from aa-torque |
| `INSTALL.md` | Fresh installation guide |
| `CONTRIBUTING.md` | Development workflow |

## Troubleshooting

### Display shows interlacing / resolution artifacts
Apply electrical tape over FPC ribbon contacts at bottom of display. See `docs/hardware.md`.

### App won't start / black screen
Check framebuffer: `cat /dev/urandom > /dev/fb0` should show noise on display.

### Slow animations
Verify performance optimizations are in place (surface caching, batched writes). Check CPU governor is `performance`.

## Backups

- `backups/claude-go-20260120/` - Jan 20, 2026 known-good state (boot config, rc.local, full app)
- `backups/claude-go-20260204/` - Feb 4, 2026 pre-session state

---

**Last Updated:** 2026-02-04
