# OBD Gauge - Claude Code Context

## Project Overview

Real-time OBD2 gauge display for Raspberry Pi Zero 2W + HyperPixel 2.1 Round (480x480 circular display).
Optimized for 2016 Audi RS7 with OBDLink MX+ Bluetooth adapter.

## Quick Reference

| Property | Value |
|----------|-------|
| **Target Device** | claude-go (10.0.0.219) |
| **Dev Server** | claude-server (10.0.0.99) |
| **Main File** | `boost_gauge.py` (~2800 lines) |
| **Config** | `config/settings.json` |
| **Auto-start** | `/etc/rc.local` (systemd has SIGHUP issues with fbcon) |

## Deployment Workflow

```bash
# From claude-server (10.0.0.99)
rsync -avz --exclude '.git' --exclude '__pycache__' \
  /home/claude/obd-gauge/ claude@10.0.0.219:~/obd-gauge/

# Restart the gauge app
ssh claude@10.0.0.219 "sudo systemctl restart obd-gauge"

# Or for manual testing
ssh claude@10.0.0.219 "sudo SDL_FBDEV=/dev/fb0 python3 ~/obd-gauge/boost_gauge.py"
```

## Architecture

```
boost_gauge.py     - Main app: rendering, touch, OBD, navigation
obd_socket.py      - Native Bluetooth OBD2 connection (not python-obd library)
touch.py           - Gesture detection wrapper for hyperpixel2r
display.py         - Pygame initialization helpers
gauges.py          - Gauge configuration classes
conversions.py     - Unit conversions (kPa→PSI, C→F)
hotspot.py         - WiFi hotspot management
settings_server.py - Web-based settings UI
```

## Key Technical Quirks

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

These optimizations were added to achieve 60 FPS:

1. **Surface Caching** (`_label_cache`) - Perimeter labels pre-rendered once
2. **Pre-rendered Hub** (`_hub_surface`) - Center circle drawn once, blitted each frame
3. **Batched FB Writes** (`_fb_buffer`) - Single write instead of 480 row writes

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
ssh claude@10.0.0.219
bluetoothctl
> connect 00:04:3E:88:EE:C0  # OBDLink MX+ MAC
```

## Related Documentation

| Doc | Purpose |
|-----|---------|
| `docs/hardware.md` | Pi Zero 2W + HyperPixel setup, framebuffer details |
| `docs/BLUETOOTH_OBD_SETUP.md` | Complete OBD pairing and troubleshooting |
| `docs/PERFORMANCE_OPTIMIZATION.md` | Animation timing learnings from aa-torque |
| `INSTALL.md` | Fresh installation guide |
| `CONTRIBUTING.md` | Development workflow |

## Troubleshooting

### Pi shows 169.254.x.x IP (DHCP failure)
Configure static IP in `/etc/dhcpcd.conf` on the Pi

### App won't start / black screen
Check framebuffer: `cat /dev/urandom > /dev/fb0` should show noise

### Slow animations
Verify performance optimizations are in place (surface caching, batched writes)

---

**Last Updated:** 2025-12-12
