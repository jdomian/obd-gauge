# Hardware Setup Guide

## Device Access

| Property | Value |
|----------|-------|
| **Hostname** | claude-go |
| **IP Address** | DHCP (check router for current IP) |
| **SSH** | `ssh claude@<ip>` (passwordless from claude-server) |
| **OS** | Debian 11 (bullseye) / Raspberry Pi OS |
| **Architecture** | aarch64 (ARM64) |

## Components

### Raspberry Pi Zero 2W
- **CPU**: Quad-core ARM Cortex-A53 @ 1GHz
- **RAM**: 512MB
- **Connectivity**: WiFi 802.11 b/g/n, Bluetooth 4.2

### HyperPixel 2.1 Round Display
- **Resolution**: 480x480 pixels (physical)
- **Virtual FB**: 720x480 pixels (requires stride padding when writing raw)
- **Shape**: Circular (2.1" diameter)
- **Refresh**: 60 Hz
- **Interface**: DPI (parallel RGB, ~19 MHz signal)
- **Touch**: Capacitive touchscreen (I2C, requires `disable-touch` overlay for Python access)
- **Framebuffer**: /dev/fb0 (RGB565, 16bpp)

### OBDLink MX+ Adapter
- **MAC**: 00:04:3E:88:EE:C0
- **PIN**: 1234
- **Connection**: Bluetooth Classic (SPP)
- **Supported Protocols**: All OBD-II (CAN, ISO, VPW, PWM)
- **Data Rate**: 20-30 Hz single PID

## Display Configuration

### /boot/config.txt (Known-Good)
```ini
# Use Legacy GL Driver (FKMS) - REQUIRED for HyperPixel 2r
# DO NOT switch to KMS (vc4-kms-v3d) - it does not work with this display
dtoverlay=vc4-fkms-v3d
max_framebuffers=2

# HyperPixel 2.1 Round - disable kernel touch driver for Python I2C access
dtoverlay=hyperpixel2r:disable-touch

# DPI timing parameters - REQUIRED, do not remove
enable_dpi_lcd=1
dpi_group=2
dpi_mode=87
dpi_output_format=0x7f216
dpi_timings=480 0 10 16 55 480 0 15 60 15 0 0 0 60 0 19200000 6
dtparam=i2c_arm=on
gpu_mem=64
```

### SDL Environment
```bash
export SDL_FBDEV=/dev/fb0
export SDL_VIDEODRIVER=fbcon    # DO NOT change to 'dummy'
```

**Critical**: `SDL_VIDEODRIVER` must be `fbcon`. Changing to `dummy` breaks pygame's native fullscreen display management.

## Display Driver Notes

### FKMS vs KMS

This project uses **FKMS** (`vc4-fkms-v3d`), NOT KMS (`vc4-kms-v3d`).

| Driver | Status | Notes |
|--------|--------|-------|
| `vc4-fkms-v3d` | **Working** | Legacy driver, uses manual DPI timings in config.txt |
| `vc4-kms-v3d` | **Broken** | Does not work with HyperPixel 2r on Pi Zero 2W |
| `vc4-kms-dpi-hyperpixel2r` | **Broken** | KMS overlay, incompatible |

### Resolution / Signal Integrity Fix

The HyperPixel 2.1 Round can exhibit resolution/alignment artifacts that look like interlacing. This is a **hardware issue**, not software.

**Cause**: The FPC ribbon cable contacts at the bottom of the display can short against the LCD's metal backing plate, causing signal interference on the ~19 MHz DPI parallel lines.

**Fix**: Apply electrical tape over the bottom of the FPC ribbon / ground tab area to insulate it from the metal backing plate. This restores full 480x480 resolution.

This has been confirmed on two separate screens - same issue, same fix.

## Pygame Optimization

### Hardware Acceleration Flags
```python
pygame.display.set_mode(
    (480, 480),
    pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.NOFRAME | pygame.HWSURFACE
)
```

### Driver Selection
The app uses `fbcon` exclusively. Other drivers are not supported:
- `fbcon` - Framebuffer console (the working driver)
- `kmsdrm` - Does not work with HyperPixel 2r FKMS config
- `dummy` - Breaks native pygame display management

## Power Requirements

- Pi Zero 2W: 5V @ 500mA typical, 1A peak
- HyperPixel 2.1: Additional ~200mA
- **Total**: 5V @ 1-1.5A recommended

## Mounting Considerations

- Display is circular, requires custom bezel/mount
- 40-pin GPIO completely occupied by HyperPixel
- I2C available for touch (if overlay enabled)
- USB for power and optional OBD cable (if not BT)
- **Important**: Ensure FPC ribbon contacts at bottom of display do not touch the metal backing plate (insulate with electrical tape)

## Thermal Notes

- Pi Zero 2W runs hot under sustained load
- 60 FPS @ ~60% CPU is sustainable without heatsink (CPU governor set to `performance`)
- Enclosure should allow airflow

## Touchscreen Setup

### Boot Config
```ini
# In /boot/config.txt - disable kernel touch driver so Python can access I2C
dtoverlay=hyperpixel2r:disable-touch
```

### Python Library
```bash
# Install hyperpixel2r-python
git clone https://github.com/pimoroni/hyperpixel2r-python
cd hyperpixel2r-python
sudo ./install.sh
```

### Touch Callback Pattern
```python
from hyperpixel2r import Touch

touch = Touch()

@touch.on_touch
def handle_touch(touch_id, x, y, state):
    # state=True: finger down or dragging
    # state=False: finger lifted
    # x, y: 0-480 coordinates
    pass
```

### Gesture Detection Bug Fix
The touch callback fires continuously during a drag (state=True for every position update).
To detect swipes correctly:
1. Only capture `touch_start` on the FIRST touch event (when start is None)
2. Track `touch_current` position during drag
3. Calculate delta from start to current on touch up (state=False)

```python
touch_start = None
touch_current = None

def handle_touch(touch_id, x, y, state):
    global touch_start, touch_current
    if state:  # Touch down or drag
        if touch_start is None:  # Only on FIRST touch
            touch_start = (x, y)
        touch_current = (x, y)  # Always update current
    else:  # Touch up
        if touch_start and touch_current:
            dx = touch_current[0] - touch_start[0]
            dy = touch_current[1] - touch_start[1]
            # Now dx/dy reflect the actual swipe distance
        touch_start = None
        touch_current = None
```

## Framebuffer Stride Issue

The HyperPixel 2r reports 480x480 but has a virtual framebuffer of 720x480.
When writing raw to `/dev/fb0`, each row must be padded:

```python
# Physical: 480x480, Virtual: 720x480, 16bpp
fb_stride = 720 * 2      # 1440 bytes per row in FB
screen_stride = 480 * 2  # 960 bytes per row in surface
padding = fb_stride - screen_stride  # 480 bytes padding

with open('/dev/fb0', 'wb') as fb:
    for y in range(480):
        row_start = y * screen_stride
        fb.write(raw_data[row_start:row_start + screen_stride])
        fb.write(b'\x00' * padding)
```

Without this fix, the display appears garbled/scrunched with terminal bleeding through.

---

**Last Updated:** 2026-02-04
