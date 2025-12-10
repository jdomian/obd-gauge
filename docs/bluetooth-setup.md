# OBD Gauge Bluetooth Setup Guide

## Overview

This document details how to connect a Raspberry Pi Zero 2 W to an OBDLink MX+ Bluetooth OBD2 adapter. **Both USB and onboard Bluetooth can work** with proper configuration.

## Hardware

| Component | Details |
|-----------|---------|
| **Pi** | Raspberry Pi Zero 2 W |
| **OBD Adapter** | OBDLink MX+ (MAC: 00:04:3E:88:EE:C0) |
| **USB BT Adapter** | TP-Link UB500 (Realtek RTL8761B) |
| **Onboard BT** | BCM43436 (UART bus) |
| **Protocol** | Bluetooth Classic SPP (Serial Port Profile) |

---

## USB Bluetooth (TP-Link UB500 / RTL8761B) - RECOMMENDED

### The Problem We Solved

The RTL8761B USB adapter appeared broken - it would pair but return **empty data**. Root cause identified via deep research:

**Missing `rtl8761bu_config.bin`** caused RFCOMM credit-based flow control deadlock. The OBDLink had data to send but was waiting for "credits" that never came.

### Evidence (Before Fix)
```
dmesg:
Bluetooth: hci0: RTL: loading rtl_bt/rtl8761bu_config.bin
Direct firmware load failed with error -2
cfg_sz -2, total sz 29924    ← NEGATIVE = BROKEN
```

### Evidence (After Fix)
```
dmesg:
Bluetooth: hci0: RTL: loading rtl_bt/rtl8761bu_config.bin
cfg_sz 25, total sz 29949    ← POSITIVE = WORKING
```

### USB Setup Steps

#### Step 1: Fix Firmware Files

The kernel requests `rtl8761bu_*` files but only `rtl8761b_*` exist. Create symlinks for BOTH:

```bash
cd /lib/firmware/rtl_bt/

# Create BOTH symlinks (fw AND config!)
sudo ln -sf rtl8761b_fw.bin rtl8761bu_fw.bin
sudo ln -sf rtl8761b_config.bin rtl8761bu_config.bin

# Verify
ls -la rtl8761bu_*
```

**CRITICAL**: The `config.bin` symlink was missing! This caused the empty data bug.

#### Step 2: Disable USB Autosuspend

The RTL8761B has a hardware bug where it fails to resume after USB suspend:

```bash
echo 'options btusb enable_autosuspend=0' | sudo tee /etc/modprobe.d/btusb.conf
```

#### Step 3: Disable Onboard Bluetooth (Optional but Recommended)

Reduces RF interference and ensures USB adapter is always hci0:

```bash
# Add to /boot/config.txt:
dtoverlay=disable-bt

# Disable UART bluetooth service
sudo systemctl disable hciuart

sudo reboot
```

#### Step 4: Reload Driver

```bash
sudo modprobe -r btusb
sudo modprobe btusb

# Verify firmware loaded correctly
dmesg | grep -i 'rtl.*config'
# Should show: cfg_sz 25 (positive number!)
```

#### Step 5: Connect to OBDLink

```bash
# Bring up adapter
sudo hciconfig hci0 up

# Scan (press OBDLink pairing button first)
sudo hcitool -i hci0 scan

# Pair and trust
bluetoothctl pair 00:04:3E:88:EE:C0
bluetoothctl trust 00:04:3E:88:EE:C0

# Bind RFCOMM
sudo rfcomm -i hci0 bind 0 00:04:3E:88:EE:C0 1

# Test
python3 -c "
import serial, time
ser = serial.Serial('/dev/rfcomm0', 38400, timeout=3)
ser.write(b'ATZ\r'); time.sleep(1)
print(ser.read(200))
"
```

### USB Advantages
- More stable than onboard (dedicated radio, no WiFi interference)
- Better range with external antenna
- Can be positioned for optimal reception

### Verified Working (2025-12-10)

Successfully tested against both:
1. **OBD Simulator on claude-zero** (D8:3A:DD:D7:49:88)
2. **Real OBDLink MX+ in RS7** (00:04:3E:88:EE:C0)

Test results via USB Bluetooth:
```
=== ELM327 Init ===
ATZ (reset): ELM327 v1.4b
ATI (version): ELM327 v1.4b

=== Vehicle Data ===
Voltage: 14.3V
Protocol: A6 (CAN 500kbps)
RPM (raw): 41 0C 0A 50
RPM (parsed): 660
Coolant (raw): 41 05 73
Coolant (parsed): 75°C
Throttle (raw): 41 11 00
Speed (raw): 41 0D 00
```

---

## OBD Simulator (for testing without car)

A Bluetooth OBD simulator runs on **claude-zero** (10.0.0.174) that emulates an ELM327 adapter. This allows testing the full Bluetooth stack without needing the car.

### Simulator Details
- **Host**: claude-zero (Pi 5)
- **MAC**: D8:3A:DD:D7:49:88
- **Service**: `bt_dbus_server.py` in `~/obd-gauge/simulator/`
- **Emulates**: ELM327 v1.4b with realistic OBD2 responses

### Testing Against Simulator

From obd-gauge Pi (10.0.0.219):
```bash
# Connect to simulator instead of real OBDLink
sudo rfcomm -i hci0 bind 0 D8:3A:DD:D7:49:88 1

# Run test CLI
python3 ~/obd-gauge/scripts/obd-test-cli.py
```

---

## Onboard Bluetooth (BCM43436) - FALLBACK

The Pi Zero 2 W's onboard Bluetooth works for RFCOMM but has stability issues:
- Shares 2.4GHz radio with WiFi (RF contention)
- Connection drops after seconds to minutes
- "hardware error 0x00" in dmesg

### When to Use Onboard
- USB adapter unavailable
- Short test sessions
- WiFi not needed (can disable to reduce interference)

## Setup Steps

### Step 1: Enable Onboard Bluetooth

By default, some Pi images disable onboard Bluetooth. Check `/boot/config.txt`:

```bash
# Check if disabled
grep "disable-bt" /boot/config.txt
```

If you see `dtoverlay=disable-bt`, comment it out:

```bash
sudo sed -i 's/^dtoverlay=disable-bt/#dtoverlay=disable-bt/' /boot/config.txt
sudo reboot
```

### Step 2: Verify Bluetooth Adapters

After reboot, check available adapters:

```bash
hciconfig -a
```

Expected output:
```
hci1:   Type: Primary  Bus: UART          # <-- Onboard (USE THIS)
        BD Address: B8:27:EB:40:65:C4

hci0:   Type: Primary  Bus: USB           # <-- USB adapter (if plugged in)
        BD Address: 0C:EF:15:BF:3F:A7
```

**Important:** Use `hci1` (UART) for OBD connections, NOT `hci0` (USB).

### Step 3: Scan for OBDLink

Put OBDLink MX+ in pairing mode (press button until fast blinking), then scan:

```bash
sudo hciconfig hci1 up
sudo hcitool -i hci1 scan --flush
```

Expected output:
```
Scanning ...
    00:04:3E:88:EE:C0   OBDLink MX+ 29398
```

### Step 4: Pair and Trust

```bash
# Pair (may show "not available" but still works)
bluetoothctl pair 00:04:3E:88:EE:C0

# Trust for auto-reconnect
bluetoothctl trust 00:04:3E:88:EE:C0
```

### Step 5: Bind RFCOMM Device

This creates `/dev/rfcomm0` that can be used like a serial port:

```bash
# Release any existing binding
sudo rfcomm release 0 2>/dev/null

# Bind using onboard Bluetooth (hci1), channel 1
sudo rfcomm -i hci1 bind 0 00:04:3E:88:EE:C0 1

# Verify
rfcomm -a
```

Expected output:
```
rfcomm0: B8:27:EB:40:65:C4 -> 00:04:3E:88:EE:C0 channel 1 clean
```

### Step 6: Test Connection

```python
import serial
import time

ser = serial.Serial('/dev/rfcomm0', 38400, timeout=3)

def cmd(c):
    ser.reset_input_buffer()
    ser.write((c + '\r').encode())
    time.sleep(0.8)
    return ser.read(200).decode(errors='ignore').strip()

# Initialize ELM327
result = cmd('ATZ')
print(f'ATZ: {result}')  # Should show "ELM327 v1.4b"

cmd('ATE0')  # Echo off

# Read voltage
print(f'Voltage: {cmd("ATRV")}')  # e.g., "14.7V"

# Read RPM (PID 010C)
print(f'RPM: {cmd("010C")}')  # Raw hex response

ser.close()
```

## Working Configuration Summary

| Setting | Value |
|---------|-------|
| Bluetooth Adapter | hci1 (onboard UART, BCM43436) |
| OBDLink MAC | 00:04:3E:88:EE:C0 |
| RFCOMM Channel | 1 |
| Baud Rate | 38400 |
| Device Path | /dev/rfcomm0 |
| Timeout | 2-3 seconds recommended |

## Verified OBD Commands

These commands were successfully tested:

| Command | Response | Meaning |
|---------|----------|---------|
| ATZ | ELM327 v1.4b | ELM327 reset/version |
| ATRV | 14.7V | Battery voltage |
| 010C | 41 0C 0A 5C | RPM (0x0A5C = 664 RPM) |
| 0105 | 41 05 7F | Coolant temp (0x7F = 87°C) |

## Troubleshooting

### "Device not available" during pairing

This is normal! The pairing may still succeed. Continue with `rfcomm bind`.

### Empty responses from /dev/rfcomm0

1. Check you're using hci1 (UART), not hci0 (USB)
2. Ensure OBDLink LED is solid blue (connected), not blinking
3. Try longer timeouts (3+ seconds)
4. Release and re-bind: `sudo rfcomm release 0 && sudo rfcomm -i hci1 bind 0 00:04:3E:88:EE:C0 1`

### Connection drops after a few seconds

The BCM43436 shares radio with WiFi. If you experience drops:
1. Move closer to the OBD adapter
2. Check for 2.4GHz WiFi interference
3. Consider disabling WiFi if not needed (but you'll lose SSH!)

### rfcomm shows "closed" instead of "clean"

The connection was established but dropped. Re-bind and try again quickly.

## Boot Script (Persistent Setup)

To auto-bind RFCOMM on boot, create `/etc/systemd/system/rfcomm-bind.service`:

```ini
[Unit]
Description=Bind RFCOMM for OBDLink MX+
After=bluetooth.target
Wants=bluetooth.target

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 5
ExecStart=/usr/bin/rfcomm -i hci1 bind 0 00:04:3E:88:EE:C0 1
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Enable with:
```bash
sudo systemctl daemon-reload
sudo systemctl enable rfcomm-bind.service
```

## Key Learnings

1. **USB Bluetooth adapters (RTL8761B) have broken RFCOMM on Linux** - don't waste time on them for SPP
2. **Onboard UART Bluetooth works** - just need to enable it in config.txt
3. **Use `rfcomm bind` + pyserial**, not PyBluez sockets - more reliable
4. **Fresh scan before pairing** helps discover the device
5. **OBDLink pairing mode** (fast blinking) makes discovery more reliable
6. **hci1 = UART (onboard), hci0 = USB** - always verify with `hciconfig -a`

## Related Files

- `/boot/config.txt` - Bluetooth enable/disable
- `/dev/rfcomm0` - Serial port for OBD communication
- `/lib/firmware/brcm/` - BCM43436 firmware (onboard)
- `/lib/firmware/rtl_bt/` - RTL8761B firmware (USB, doesn't help RFCOMM)

---

*Last Updated: 2025-12-10*
*Tested on: Raspberry Pi Zero 2 W with OBDLink MX+*
