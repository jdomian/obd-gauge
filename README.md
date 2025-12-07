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

## Deployment

**Target Device**: claude-go (10.0.0.219)

### Auto-Start on Boot

The gauge starts automatically via `/etc/rc.local`:

```bash
# Start OBD Gauge
sleep 5
SDL_FBDEV=/dev/fb0 /usr/bin/python3 /home/claude/obd-gauge/boost_gauge.py --fps 30 --obd 25 --smooth 0.25 &
```

**Note**: systemd service had issues with SIGHUP when pygame uses fbcon driver. rc.local works reliably.

### Manual Run

```bash
sudo SDL_FBDEV=/dev/fb0 python3 boost_gauge.py --fps 30 --obd 25 --smooth 0.25
```

## Features

- Animated needle with smooth tweening
- Color-coded arcs (vacuum blue / boost green-red)
- Digital PSI readout
- FPS counter for performance monitoring
- Touchscreen swipe gestures (left/right/up/down + tap)
- Screen carousel with 5 screens (swipe to navigate)
- Screen indicator dots at bottom

## Navigation (2D Grid)

The UI uses a 2D grid navigation system:

```
         Row 0 (Gauges)
    ┌─────┬─────┬─────┐
    │Boost│Temp │Load │  ← Swipe LEFT/RIGHT
    │ PSI │ °F  │  %  │
    └─────┴─────┴─────┘
           ↑ Swipe UP
           ↓ Swipe DOWN
    ┌─────────────────┐
    │  QR / Settings  │  Row 1
    └─────────────────┘
           ↑ Swipe UP
           ↓ Swipe DOWN
    ┌─────────────────┐
    │     SYSTEM      │  Row 2 (Demo Mode, Power)
    └─────────────────┘
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
| 0 | Boost Pressure | -15 to +25 PSI | Blue (vacuum) → Green → Red (boost) |
| 1 | Coolant Temp | 100-260°F | Blue (cold) → Green (normal) → Red (hot) |
| 2 | Engine Load | 0-100% | Blue (idle) → Green (normal) → Red (heavy) |

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
| `boost_gauge.py` | Main boost gauge display |
| `display.py` | Pygame display wrapper |
| `touch.py` | Touch gesture handler |
| `start.sh` | Wrapper script (sets SDL env vars) |
| `config/settings.json` | Gauge configuration |

## Configuration

`config/settings.json`:
```json
{
  "gauge": {
    "min_psi": -15,
    "max_psi": 25,
    "smoothing": 0.25
  },
  "display": {
    "fps": 30,
    "brightness": 100
  },
  "obd": {
    "rate_hz": 25,
    "device": "/dev/rfcomm0"
  }
}
```

## Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--fps` | 30 | Display refresh rate |
| `--obd` | 25 | OBD2 data rate (Hz) |
| `--smooth` | 0.25 | Needle smoothing (0.1-0.3) |

## Performance

At `--fps 30 --obd 25`:
- CPU: ~35% (pygame 1.9.6 on Pi Zero 2W)
- FPS: 30.1-30.3 (stable)
- Smooth needle animation
- Minimal input lag

## Documentation

- `docs/obd-optimization.md` - OBD2 data rates and tweening
- `docs/hardware.md` - Pi Zero 2W + HyperPixel setup

## Dependencies

```
pygame>=2.0.0
hyperpixel2r>=0.0.1
obd>=0.7.1
```

**Note**: System pygame 1.9.6 works fine. Pip-installed 2.6.1 also available.

## Known Issues / Gotchas

### pygame 2.6.1 `border_radius` Keyword Bug

**Problem**: `pygame.draw.rect()` with `border_radius=N` keyword argument crashes on Pi's pygame 2.6.1:
```python
# CRASHES with: TypeError: rect() takes no keyword arguments
pygame.draw.rect(screen, color, rect, border_radius=14)
```

**Solution**: Use the `_draw_capsule()` helper method that draws rounded rectangles using gfxdraw circles + rectangles:
```python
# Works on all pygame versions
self._draw_capsule(color, rect)           # Filled
self._draw_capsule(color, rect, 2)        # Outline only
```

**Note**: This affects pygame 2.6.1 on Raspberry Pi OS. Desktop pygame may support `border_radius`.

### HyperPixel 2r Brightness

The HyperPixel 2r has a **binary backlight** (on/off via GPIO) with no PWM dimming. The app uses software dimming via a semi-transparent overlay instead.

## Current Status

- [x] Gauge display working
- [x] Auto-start on boot (rc.local)
- [x] Cleaned up RPi5 cruft
- [x] Touchscreen swipe gestures working
- [x] Screen carousel (swipe left/right to switch screens)
- [x] Display rendering correctly on 480x480 circular screen
- [x] 2D grid navigation (gauges row + settings row)
- [x] 3 gauge screens (Boost, Coolant Temp, Engine Load)
- [x] Generic gauge renderer with color zones
- [x] Settings screen UI
- [x] WiFi hotspot mode (tap to start, phone connects)
- [x] Web-based settings page (192.168.4.1:8080)
- [ ] OBD2 Bluetooth connection
- [ ] Real data from OBD2 PIDs
- [ ] Settings save/load (partially working)

## Changelog

### 2025-12-07 (Evening) - Milestone: WiFi Hotspot + Web Settings Working
- **WiFi hotspot mode working!** Tap on Settings screen to start/stop
- **Web settings page accessible** at 192.168.4.1:8080 from phone
- Fixed Python import path issue - modules weren't found when run via rc.local
- Added `sys.path.insert()` to ensure sibling modules load regardless of working directory
- Phone now prompted to "Connect Anyway" (no internet) which is expected behavior

### 2025-12-07 (Afternoon) - System Screen + pygame Compatibility Fix
- **Fixed pygame 2.6.1 crash** - `border_radius` keyword not supported on Pi
- Added `_draw_capsule()` helper for pygame-compatible rounded rectangles
- **System screen (Row 2)** now renders correctly with Demo Mode toggle
- Added 500ms navigation cooldown to prevent accidental power button taps after swipe
- Added pending action pattern for clean reboot/shutdown (executes after pygame.quit())
- Fixed reboot button freeze bug

### 2025-12-06 (Evening) - Milestone: 2D Grid Navigation + Multi-Gauge
- **2D grid navigation system** - Row 0 for gauges, Row 1 for settings
- **3 working gauges**: Boost PSI, Coolant Temp, Engine Load
- **Generic gauge renderer** with customizable ranges and color zones
- **Settings screen** with PID selection UI (placeholder)
- Swipe UP/DOWN to switch between gauges and settings rows
- Swipe LEFT/RIGHT to navigate within a row
- All gauges animate with smooth needle tweening
- Simulated data for testing (boost cycle, temp fluctuation, load response)

### 2025-12-06 (Afternoon) - Milestone: Touchscreen Working
- **Touchscreen working!** Swipe left/right/up/down and tap all detected correctly
- Fixed gesture detection bug: was resetting touch start on every drag event
- Fixed framebuffer stride issue: 720x480 virtual vs 480x480 physical display
- Touch uses `hyperpixel2r` library with `disable-touch` overlay for Python I2C access

### 2025-12-06
- Removed Pi 5 / claude-portable leftovers (opencv, Pillow, psutil, camera config)
- Deployed to claude-go (10.0.0.219)
- Fixed auto-start: switched from systemd to rc.local (fbcon + systemd = SIGHUP issues)
- Disabled getty@tty1 to prevent console interference
- Verified boot-to-gauge in under 10 seconds

## License

Personal project for RS7 gauge display.
