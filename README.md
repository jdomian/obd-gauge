# OBD-Gauge

Real-time boost gauge display for Pi Zero 2W + HyperPixel 2.1 Round.

Optimized for 2016 Audi RS7 with OBDLink MX+ adapter.

## Hardware

| Component | Details |
|-----------|---------|
| **SBC** | Raspberry Pi Zero 2W |
| **Display** | HyperPixel 2.1 Round (480x480) |
| **OBD Adapter** | OBDLink MX+ (Bluetooth) |
| **Vehicle** | 2016 Audi RS7 4.0T (500kbps CAN) |
| **Power** | USB from vehicle (no battery) |

## Deployment

**Target Device**: claude-go (DHCP)

### Auto-Start on Boot

The gauge starts automatically via `/etc/rc.local`:

```bash
# CPU governor set to performance
# SDL environment configured
# Gauge launched with nice -n -10
```

**Note**: systemd service had issues with SIGHUP when pygame uses fbcon driver. rc.local works reliably.

### Manual Run

```bash
sudo SDL_FBDEV=/dev/fb0 SDL_VIDEODRIVER=fbcon python3 boost_gauge.py
```

## Features

- 60 FPS animated needle with smooth tweening
- Color-coded arcs (vacuum blue / boost green-red)
- Digital PSI readout
- FPS counter for performance monitoring
- Touchscreen swipe gestures (left/right/up/down + tap)
- Screen carousel with multiple screens (swipe to navigate)
- RS7-specific boost and temperature calibration

## Navigation (2D Grid)

```
         Row 0 (Gauges)
    +-----+-----+-----+
    |Boost|Temp |Load |  <- Swipe LEFT/RIGHT
    | PSI | F   |  %  |
    +-----+-----+-----+
           ^ Swipe UP
           v Swipe DOWN
    +-----------------+
    |  QR / Settings  |  Row 1
    +-----------------+
           ^ Swipe UP
           v Swipe DOWN
    +-----------------+
    |     SYSTEM      |  Row 2 (Demo Mode, Power)
    +-----------------+
```

| Gesture | Row 0 (Gauges) | Row 1 (Settings) | Row 2 (System) |
|---------|----------------|------------------|----------------|
| Swipe LEFT | Next gauge | - | - |
| Swipe RIGHT | Prev gauge | - | - |
| Swipe UP | Go to Row 1 | Go to Row 2 | - |
| Swipe DOWN | - | Go to Row 0 | Go to Row 1 |
| Tap | - | Toggle hotspot | Demo/Reboot/Shutdown |

## Screens

### Row 0: Gauges
| Col | Gauge | Range | Color Zones |
|-----|-------|-------|-------------|
| 0 | Boost Pressure | -15 to +25 PSI | Blue (vacuum) -> Green -> Red (boost) |
| 1 | Coolant Temp | 100-260 F | Blue (cold) -> Green (normal) -> Red (hot) |
| 2 | Engine Load | 0-100% | Blue (idle) -> Green (normal) -> Red (heavy) |

### Row 1: Settings / QR
- QR code for WiFi connection (phone auto-connects to gauge hotspot)
- Toggle to start/stop WiFi hotspot
- Bluetooth pairing info

### Row 2: System
- **Demo Mode Toggle** - Enables needle sweep animation for testing
- **Brightness Slider** - Software dimming (10-100%)
- **Shutdown Button** - Graceful power off
- **Reboot Button** - Graceful restart

## Files

| File | Purpose |
|------|---------|
| `boost_gauge.py` | Main gauge display (~3300 lines) |
| `obd_socket.py` | Native Bluetooth OBD2 connection |
| `touch.py` | Touch gesture handler |
| `display.py` | Pygame display wrapper |
| `start.sh` | Wrapper script (sets SDL env vars) |
| `start_gauge.sh` | Boot startup script |
| `config/settings.json` | Gauge configuration |

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

## Settings Web Server

The gauge can be configured via a web interface:

### Method 1: On-Device Hotspot (In Car)

1. Swipe DOWN to Row 1 (Settings screen)
2. Tap to enable WiFi hotspot
3. Connect phone to `OBD-Gauge` WiFi network
4. Scan QR code or browse to `http://192.168.4.1:8080`

### Method 2: Local Network (Development)

```bash
# Start server (binds to 0.0.0.0:8080)
python3 settings_server.py test

# Access from any device on the network
# http://<server-ip>:8080
```

## Performance

At 60 FPS with CPU governor set to `performance`:
- CPU: ~60% (Pi Zero 2W)
- FPS: 59.8-60.2 (stable)
- Smooth needle animation
- Minimal input lag

Key optimizations:
- Surface caching for static elements
- Pre-rendered hub surface
- Batched framebuffer writes (single write per frame)

## Documentation

### Getting Started
- `INSTALL.md` - Complete installation guide
- `CONTRIBUTING.md` - Development workflow
- `CLAUDE.md` - Context for Claude Code sessions

### Technical Docs
- `docs/hardware.md` - Hardware details, display driver config, resolution fix
- `docs/BLUETOOTH_OBD_SETUP.md` - Bluetooth OBD pairing and troubleshooting
- `docs/PERFORMANCE_OPTIMIZATION.md` - Animation & performance learnings
- `docs/obd-optimization.md` - OBD2 data rates and tweening

## Dependencies

```
pygame>=2.0.0
hyperpixel2r>=0.0.1
```

**Note**: System pygame 1.9.6 works fine. Pip-installed 2.6.1 also available.

## Known Issues / Gotchas

### HyperPixel 2r Resolution / Interlacing Artifacts

**Problem**: Display shows interlacing-like artifacts, not rendering at full 480x480.

**Cause**: FPC ribbon cable contacts at bottom of display short against the metal backing plate, causing signal interference on the ~19 MHz DPI lines.

**Fix**: Apply electrical tape over the bottom of the FPC ribbon / ground tab area to insulate from the metal backing plate. Confirmed on two separate screens.

### pygame 2.6.1 `border_radius` Keyword Bug

**Problem**: `pygame.draw.rect()` with `border_radius=N` keyword argument crashes on Pi's pygame 2.6.1.

**Solution**: Use the `_draw_capsule()` helper method.

### HyperPixel 2r Brightness

The HyperPixel 2r has a **binary backlight** (on/off via GPIO) with no PWM dimming. The app uses software dimming via a semi-transparent overlay instead.

### Display Driver Compatibility

**FKMS only.** KMS (`vc4-kms-v3d`) and its associated overlay (`vc4-kms-dpi-hyperpixel2r`) do not work with the HyperPixel 2r on Pi Zero 2W. See `docs/hardware.md` for details.

## Current Status

- [x] 60 FPS gauge display with smooth animation
- [x] Full 480x480 resolution (with electrical tape fix)
- [x] Auto-start on boot (rc.local)
- [x] Touchscreen swipe gestures
- [x] 2D grid navigation (gauges + settings + system rows)
- [x] 3 gauge screens (Boost, Coolant Temp, Engine Load)
- [x] OBD2 Bluetooth connection (OBDLink MX+, native socket)
- [x] RS7 boost and temperature calibration
- [x] WiFi hotspot mode with QR code
- [x] Web-based settings page
- [x] Demo mode for testing without OBD connection

## License

Personal project for RS7 gauge display.
