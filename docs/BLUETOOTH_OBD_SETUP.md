# OBD Gauge Bluetooth Setup - 2016 Audi RS7

## Overview

This document covers connecting the OBD Gauge display (Pi Zero 2W) to the OBDLink MX+ adapter via Bluetooth for real-time vehicle data.

## Hardware

| Component | Details |
|-----------|---------|
| **Gauge Pi** | Raspberry Pi Zero 2W @ 10.0.0.219 |
| **Display** | HyperPixel 2.1 Round (480x480) |
| **OBD Adapter** | OBDLink MX+ (Bluetooth SPP) |
| **OBD MAC Address** | `00:04:3E:88:EE:C0` |
| **OBD Device Name** | `OBDLink MX+ 29398` |
| **Vehicle** | 2016 Audi RS7 4.0T |
| **CAN Protocol** | ISO 15765-4 CAN 500 (Protocol 6) |

## Key Files

| File | Purpose |
|------|---------|
| `/home/claude/obd-gauge/obd_socket.py` | Bluetooth socket + OBD communication |
| `/home/claude/obd-gauge/boost_gauge.py` | Main gauge display application |
| `/home/claude/obd-gauge/config/settings.json` | Gauge configuration (PIDs, MAC, etc.) |
| `/etc/systemd/system/obd-gauge.service` | Systemd service for auto-start |

## Working Configuration

### settings.json
```json
{
  "gauges": [
    {"position": 0, "pid": "THROTTLE_POS", "label": "THROTTLE", "conversion": "none", "min": 0, "max": 100},
    {"position": 1, "pid": "COOLANT_TEMP", "label": "COOLANT", "conversion": "none", "min": 100, "max": 260},
    {"position": 2, "pid": "BOOST", "label": "BOOST", "conversion": "none", "min": -15, "max": 25}
  ],
  "display": {
    "fps": 60,
    "smoothing": 0.25,
    "dial_background": "audi3",
    "demo_mode": false
  },
  "obd": {
    "rate_hz": 25,
    "bt_device_mac": "00:04:3E:88:EE:C0",
    "bt_device_name": "OBDLink MX+ 29398"
  }
}
```

### OBD PIDs Used

| PID | Name | OBD Code | Notes |
|-----|------|----------|-------|
| THROTTLE_POS | Throttle Position | 0111 | 0-100% |
| COOLANT_TEMP | Coolant Temperature | 0105 | Already converted to °F in code |
| BOOST | Boost Pressure | 010B (MAP) | Calculated: MAP - 101.325 kPa → PSI |
| RPM | Engine RPM | 010C | For shift light |

## Critical Fixes Applied

### 1. PyBluez → Native Python Socket
**Problem:** PyBluez `bluetooth.BluetoothSocket()` returns `[Errno 77] File descriptor in bad state` on newer kernels.

**Solution:** Use native Python socket:
```python
import socket
sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
sock.connect((mac_address, 1))  # Channel 1 for SPP
```

### 2. Protocol Auto-Detect → Force CAN 500
**Problem:** `ATSP0` (auto-detect) returns "STOPPED" responses on RS7.

**Solution:** Force protocol 6 (CAN 500 kbps):
```python
INIT_COMMANDS = [
    ("ATZ", 2.0),      # Reset
    ("ATE0", 0.5),     # Echo off
    ("ATL0", 0.5),     # Linefeeds off
    ("ATS0", 0.5),     # Spaces off
    ("ATH0", 0.5),     # Headers off
    ("ATSP6", 1.0),    # Force CAN 500 protocol (RS7)
]
```

### 3. Coolant Double-Conversion Bug
**Problem:** Coolant showed 368°F instead of ~190°F.

**Cause:** `obd_socket.py` converts C→F, then `boost_gauge.py` applied `c_to_f` conversion AGAIN.

**Solution:** Set `"conversion": "none"` in settings.json for COOLANT_TEMP.

### 4. Bluetooth Pairing
**Problem:** Standard `bluetoothctl pair` command hangs.

**Solution:** Use btmgmt:
```bash
sudo btmgmt pair -c 3 -t 0 00:04:3E:88:EE:C0
```

### 5. Fast Query Timeout Too Aggressive (2025-12-10)
**Problem:** Connection establishes but polling immediately fails with 5 consecutive errors.

**Root Cause:** `timeout=0.1` in `query_pid()` for fast queries was too aggressive for Bluetooth SPP latency.

**Solution:** Changed fast timeout from 0.1s to 0.3s in `obd_socket.py` line 356:
```python
# Before:
response = self._send_command(pid, timeout=0.1 if fast else 0.5)

# After:
response = self._send_command(pid, timeout=0.3 if fast else 0.5)
```

### 6. query_fast() Method Placement Bug (2025-12-10)
**Problem:** `'OBDSocket' object has no attribute 'query_fast'` error.

**Root Cause:** The `query_fast()` method was incorrectly placed OUTSIDE the `OBDSocket` class (at line 642) with wrong indentation.

**Solution:** Removed incorrectly placed function and re-inserted it inside the class after `query_all()` method (around line 461).

**Correct placement:**
```python
class OBDSocket:
    # ... other methods ...

    def query_all(self) -> OBDData:
        # ...

    def query_fast(self) -> OBDData:  # MUST be inside class with proper indent
        """Query single PIDs with throttle prioritized for responsiveness."""
        # Implementation here

    def start_polling(self):
        # ...
```

## Performance Tuning

### Polling Speed
- OBDLink MX+ achieves ~19 Hz for single PID queries
- Current implementation rotates through 3 PIDs (Throttle, MAP, RPM)
- Effective rate: ~6-7 Hz per gauge

### Timeout Settings (obd_socket.py)
```python
# Command timeout (default)
def _send_command(self, cmd: str, timeout: float = 0.3)

# Socket timeout after connection
self.socket.settimeout(0.5)
```

### Smoothing
`smoothing` in settings.json controls needle animation:
- 0.15 = very responsive but choppy
- 0.25 = balanced (current)
- 0.5+ = smooth but laggy

## WiFi/Bluetooth Interference

The Pi Zero 2W shares 2.4GHz radio for both WiFi and Bluetooth. Heavy Bluetooth activity (OBD polling) can cause WiFi dropouts.

**Symptoms:**
- SSH connections drop during OBD operations
- WiFi reconnects after Bluetooth activity stops

**Workarounds:**
- Use 5GHz WiFi if available (Pi Zero 2W only supports 2.4GHz though)
- Accept occasional SSH drops during active gauges
- Physical access for debugging when needed

## Startup Sequence

1. Pi boots, gauge service starts via rc.local/systemd
2. Gauge auto-connects to saved OBD device (from settings.json)
3. Bluetooth pairing happens automatically if device is known
4. ELM327 initialization sequence runs
5. Polling loop starts, updating gauge values

## Manual Testing Commands

### Test Bluetooth Connection
```bash
# On gauge Pi
bluetoothctl scan on
bluetoothctl pair 00:04:3E:88:EE:C0
bluetoothctl trust 00:04:3E:88:EE:C0
```

### Test Raw OBD Communication
```bash
# Quick throttle speed test
python3 << 'EOF'
import socket, time
MAC = '00:04:3E:88:EE:C0'
sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
sock.connect((MAC, 1))
sock.settimeout(0.2)

def send(cmd):
    sock.send((cmd + '\r').encode())
    resp = ''
    while '>' not in resp:
        try: resp += sock.recv(256).decode()
        except: break
    return resp

send('ATZ'); time.sleep(0.5)
send('ATE0'); send('ATSP6')
print('Polling throttle...')
for i in range(20):
    r = send('0111')
    print(f'{i}: {r.strip()}')
sock.close()
EOF
```

## Known Issues

### 1. Gauge Lag / Value Skipping
**Status:** ONGOING (working on optimization)

**Symptom:** Throttle gauge skips from 11% directly to 88%, doesn't show intermediate values.

**Root Cause:** Each PID query takes ~50-150ms over Bluetooth. When querying 3 PIDs in rotation, each gauge only updates at ~6-7 Hz.

**Potential Solutions:**
- Query only one "fast" PID (throttle) at high rate, others slower
- Implement predictive smoothing
- Accept limitation of Bluetooth SPP throughput

### 2. WiFi Drops During Bluetooth Activity
**Status:** Known limitation of Pi Zero 2W shared 2.4GHz radio.

**Workaround:** SSH sessions may disconnect. Use physical access when doing heavy BT testing.

### 3. Display Format Issues
**Fixed:** Boost now shows decimals correctly (`.1f` format always applied).

## RS7-Specific Notes

### CAN Bus
- RS7 uses CAN 500 kbps (ISO 15765-4)
- Protocol must be forced with `ATSP6` - auto-detect fails
- Some PIDs may not respond (fuel system info, etc.)

### Temperature Accuracy
- OBD coolant temp may differ from dash by ~5-10°F
- This is normal - different sensors in different locations

### Boost Calculation
- Boost PSI = (MAP kPa - 101.325) × 0.145038
- MAP sensor reads absolute pressure
- At idle: ~30-40 kPa (vacuum)
- At boost: 150+ kPa (positive pressure)

## Troubleshooting

### "Bluetooth error: [Errno 77]"
**Cause:** PyBluez incompatibility with newer kernels.
**Fix:** Use native `socket.AF_BLUETOOTH` instead of PyBluez BluetoothSocket.

### "STOPPED" or "NO DATA" Responses
**Cause:** Wrong protocol or PIDs not supported.
**Fix:** Force protocol 6 with `ATSP6`. Verify PIDs are supported on vehicle.

### Gauge Shows Wrong Values
1. Check `conversion` setting in settings.json (should be "none" if code already converts)
2. Verify MIN/MAX values are appropriate for the sensor range
3. Check if data is being parsed correctly in obd_socket.py

### Can't Connect to OBD Adapter
1. Make sure car is ON (accessory or running)
2. Check adapter LED is blinking (waiting for connection)
3. Verify MAC address: `bluetoothctl scan on`
4. Try manual pairing: `sudo btmgmt pair -c 3 -t 0 <MAC>`
5. Check Bluetooth is up: `hciconfig hci0 up`

## File Locations Summary

### On Gauge Pi (10.0.0.219)
```
/home/pi/obd-gauge/
├── boost_gauge.py          # Main application
├── obd_socket.py           # Bluetooth + OBD communication
├── config/
│   └── settings.json       # Configuration
├── assets/
│   ├── dials/              # Dial background images
│   └── needles/            # Needle images
└── docs/
    └── BLUETOOTH_OBD_SETUP.md  # This file
```

### On Claude Server (10.0.0.99)
```
/home/claude/obd-gauge/     # Development copy
├── (same structure)
└── simulator/              # OBD simulator tools
```

## Quick Commands Reference

```bash
# SSH to gauge Pi
ssh claude@10.0.0.219

# Check Bluetooth status
hciconfig hci0
bluetoothctl devices

# View gauge logs
journalctl -u obd-gauge -f

# Restart gauge service
sudo systemctl restart obd-gauge

# Test OBD manually
sudo rfcomm connect 0 00:04:3E:88:EE:C0 1 &
picocom /dev/rfcomm0 -b 115200

# Kill stuck connections
sudo pkill rfcomm
sudo hciconfig hci0 reset
```

## Version History

| Date | Change |
|------|--------|
| 2025-12-10 | Initial documentation - BT connection working, performance optimization in progress |
| 2025-12-10 (Evening) | Fixed fast query timeout (0.1s→0.3s), fixed query_fast method placement bug, added aa-torque analysis |

---

**Last Updated:** 2025-12-10 (Evening)
**Hardware:** Pi Zero 2W + HyperPixel 2.1 Round + OBDLink MX+
**Vehicle:** 2016 Audi RS7 4.0T (APR Stage 1)
