# OBD2 Optimization Guide for RS7 + OBDLink MX+

## Hardware Configuration

### Vehicle: 2016 Audi RS7 4.0T
- **CAN Bus Speed**: 500 kbps (ISO 15765-4 high-speed CAN)
- **Protocol**: ISO 15765-4 CAN (11-bit ID, 500 kbaud)

### OBD2 Adapter: OBDLink MX+
- **Data Rate**: 20-30 Hz for single PID (vs 5-10 Hz for cheap adapters)
- **Connection**: Bluetooth Classic (SPP)
- **Performance**: 300-1000% faster than competitors

## Optimized Settings

```bash
python3 boost_gauge.py --fps 30 --obd 25 --smooth 0.25
```

| Parameter | Value | Reason |
|-----------|-------|--------|
| `--fps` | 30 | Display refresh (44% CPU, smooth visuals) |
| `--obd` | 25 | OBDLink MX+ realistic rate (20-30 Hz capable) |
| `--smooth` | 0.25 | Responsive tweening, minimal latency feel |

## Boost Pressure Calculation

### PIDs Used
- **0x0B**: Intake Manifold Absolute Pressure (MAP) - 0-255 kPa
- **0x33**: Barometric Pressure - 0-255 kPa

### Formula
```
Boost (kPa) = MAP - Barometric
Boost (PSI) = (MAP - Barometric) * 0.145
```

### Resolution
- Raw: 1 kPa per unit (0-255 range)
- PSI: 0.145 PSI per unit

## Tweening Algorithm

Frame-rate independent exponential easing:

```python
def _update_needle(self, target_psi, dt):
    diff = target_psi - self.current_psi
    # Adjust smoothing by delta time for frame-rate independence
    ease_factor = 1.0 - math.pow(1.0 - self.smoothing, dt * 60)
    self.current_psi += diff * ease_factor
    # Snap to target if very close
    if abs(diff) < 0.01:
        self.current_psi = target_psi
```

### Why This Works
- At 25 Hz OBD data and 30 FPS display, only ~5 frames between updates
- Smoothing 0.25 means needle catches up in ~4-5 frames
- No visible lag, smooth motion even if OBD data is slightly jittery

## Performance Benchmarks (Pi Zero 2W)

| FPS Target | CPU Usage | Notes |
|------------|-----------|-------|
| 30 | ~44% | Recommended - smooth, efficient |
| 60 | ~60% | Matched to display, less tearing |
| 10 | ~30% | Choppy, not recommended for gauges |

## OBDLink MX+ vs Competitors

| Adapter | Single PID Rate | Multi-PID Rate |
|---------|----------------|----------------|
| **OBDLink MX+** | 20-30 Hz | 100+ samples/sec |
| Veepeak BLE+ | 5-10 Hz | 20-30 samples/sec |
| Generic ELM327 | 2-5 Hz | 10-15 samples/sec |

The MX+ is 3-10x faster, making tweening almost unnecessary at single-PID mode.

## Bluetooth Connection

### Pairing (one-time)
```bash
bluetoothctl
> scan on
> pair XX:XX:XX:XX:XX:XX  # OBDLink MAC
> trust XX:XX:XX:XX:XX:XX
> connect XX:XX:XX:XX:XX:XX
```

### Python OBD Library
```python
import obd
connection = obd.OBD("/dev/rfcomm0")  # or auto-detect
```

## Future Improvements

1. **Direct CAN access** - Bypass OBD protocol overhead
2. **Multi-PID batching** - Request boost + intake temp in one call
3. **Predictive display** - Use acceleration to predict boost changes
