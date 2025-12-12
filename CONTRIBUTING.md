# Contributing to OBD Gauge

## Development Environment

### Infrastructure

| Server | IP | Role |
|--------|-----|------|
| claude-server | 10.0.0.99 | Development, editing, testing |
| claude-go | 10.0.0.219 | Pi Zero 2W target device |

### Requirements

- SSH key access to both servers
- Python 3.9+ knowledge
- Basic pygame understanding

## Development Workflow

### 1. Edit on claude-server

All code changes happen on claude-server:
```bash
cd /home/claude/obd-gauge
# Edit files directly
```

### 2. Test with Simulator (Optional)

For logic testing without Pi hardware:
```bash
python3 boost_gauge.py --demo
```

### 3. Deploy to Pi

```bash
# Sync code to Pi
rsync -avz --exclude '.git' --exclude '__pycache__' \
  /home/claude/obd-gauge/ claude@10.0.0.219:~/obd-gauge/

# Restart the service
ssh claude@10.0.0.219 "sudo systemctl restart obd-gauge"
```

### 4. Monitor Logs

```bash
ssh claude@10.0.0.219 "journalctl -u obd-gauge -f"
```

## Project Structure

```
obd-gauge/
├── boost_gauge.py      # Main application (~2800 lines)
├── obd_socket.py       # Bluetooth OBD2 connection
├── touch.py            # Touch gesture detection
├── display.py          # Pygame initialization
├── gauges.py           # Gauge configurations
├── conversions.py      # Unit conversions
├── hotspot.py          # WiFi hotspot control
├── settings_server.py  # Web settings UI
├── config/
│   └── settings.json   # Runtime configuration
├── assets/
│   ├── dials/          # Background images
│   ├── needles/        # Needle images
│   └── fonts/          # Custom fonts
├── docs/               # Documentation
└── simulator/          # OBD simulator for testing
```

## Code Style

### Python
- Python 3.9+ features OK
- Type hints for function signatures
- Docstrings for public methods
- No external linting enforced (personal project)

### Naming Conventions
- `_private_method()` for internal methods
- `CONSTANT_NAME` for constants
- `snake_case` for variables and functions

## Key Classes and Methods

### BoostGauge (boost_gauge.py)

Main class orchestrating everything:

| Method | Purpose |
|--------|---------|
| `__init__()` | Initialize pygame, surfaces, OBD |
| `run()` | Main loop |
| `_draw_generic_gauge()` | Render a gauge screen |
| `_draw_needle()` | Draw procedural needle |
| `_flip()` | Write to framebuffer (performance critical) |
| `_handle_navigation()` | Process touch gestures |

### Performance-Critical Code

These methods run every frame - optimize carefully:

```python
# Surface caching - don't recreate surfaces
self._label_cache = {}
self._hub_surface = None

# Batched framebuffer write
self._fb_buffer = bytearray(720 * 480 * 2)
```

## Adding Features

### New Gauge Type

1. Add to `config/settings.json`:
```json
{"position": 3, "pid": "NEW_PID", "label": "NEW", "min": 0, "max": 100}
```

2. If custom PID, add query in `obd_socket.py`

### New Visual Element

1. Add drawing code in `_draw_generic_gauge()` or create new method
2. Consider caching if static (see `_init_hub_surface()` pattern)

### New Screen/Row

1. Add row handler in `_handle_navigation()`
2. Create draw method like `_draw_settings_screen()`

## Testing

### On Device
```bash
# Manual run with visible output
ssh claude@10.0.0.219 "sudo SDL_FBDEV=/dev/fb0 python3 ~/obd-gauge/boost_gauge.py"
```

### OBD Simulator
```bash
# Start simulator on another machine
python3 simulator/obd_sim.py
```

### Framebuffer Test
```bash
# Verify display works
ssh claude@10.0.0.219 "cat /dev/urandom > /dev/fb0"
# Should show random pixels
```

## Common Issues

### "Operation not permitted" when killing process
The app runs as root. Use: `sudo pkill -f boost_gauge`

### Changes not appearing
1. Verify rsync completed
2. Restart service: `sudo systemctl restart obd-gauge`
3. Check logs: `journalctl -u obd-gauge -n 50`

### Slow frame rate
Check that caching is working:
- `_label_cache` should be populated
- `_hub_surface` should be non-None
- `_fb_buffer` should exist (batched writes)

## Git Workflow

This is a personal project. Commits are made periodically when:
- Major features are complete
- Before risky changes
- When explicitly requested

```bash
git add -A
git commit -m "Description of changes"
git push
```

---

**Last Updated:** 2025-12-12
