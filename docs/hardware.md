# Hardware Setup Guide

## Device Access

| Property | Value |
|----------|-------|
| **Hostname** | claude-go |
| **IP Address** | 10.0.0.219 |
| **SSH** | `ssh claude@10.0.0.219` (passwordless from claude-server) |
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
- **Interface**: DPI (parallel RGB)
- **Touch**: Capacitive touchscreen (I2C, requires `disable-touch` overlay for Python access)
- **Framebuffer**: /dev/fb0 (RGB565, 16bpp)

### OBDLink MX+ Adapter
- **Connection**: Bluetooth Classic (SPP)
- **Supported Protocols**: All OBD-II (CAN, ISO, VPW, PWM)
- **Data Rate**: 20-30 Hz single PID

## Display Configuration

### /boot/config.txt
```ini
# HyperPixel 2.1 Round
dtoverlay=hyperpixel2r

# Disable touch driver for Python access
dtoverlay=hyperpixel2r:disable-touch
```

### SDL Environment
```bash
export SDL_FBDEV=/dev/fb0
export SDL_VIDEODRIVER=fbcon
```

## Pygame Optimization

### Hardware Acceleration Flags
```python
pygame.display.set_mode(
    (480, 480),
    pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.NOFRAME | pygame.HWSURFACE
)
```

### Driver Selection (in order of preference)
1. `kmsdrm` - Kernel Mode Setting (best performance)
2. `fbcon` - Framebuffer console
3. `directfb` - DirectFB layer
4. `dummy` + raw FB write - Fallback

## Power Requirements

- Pi Zero 2W: 5V @ 500mA typical, 1A peak
- HyperPixel 2.1: Additional ~200mA
- **Total**: 5V @ 1-1.5A recommended

## Mounting Considerations

- Display is circular, requires custom bezel/mount
- 40-pin GPIO completely occupied by HyperPixel
- I2C available for touch (if overlay enabled)
- USB for power and optional OBD cable (if not BT)

## Thermal Notes

- Pi Zero 2W runs hot under sustained load
- 30 FPS @ 44% CPU is sustainable without heatsink
- 60 FPS @ 60% CPU may need passive cooling
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
