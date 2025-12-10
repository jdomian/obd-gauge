#!/bin/bash
# OBD Bluetooth Connection Script
# Supports both USB (RTL8761B) and onboard (BCM43436) Bluetooth

OBD_MAC="00:04:3E:88:EE:C0"

# Auto-detect adapter: prefer USB (hci0) if available
if hciconfig hci0 2>/dev/null | grep -q "Bus: USB"; then
    HCI_ADAPTER="hci0"
    ADAPTER_TYPE="USB (RTL8761B)"
elif hciconfig hci1 2>/dev/null | grep -q "Bus: UART"; then
    HCI_ADAPTER="hci1"
    ADAPTER_TYPE="Onboard UART (BCM43436)"
else
    # Fallback to hci0
    HCI_ADAPTER="hci0"
    ADAPTER_TYPE="Unknown"
fi

# Allow override via argument
if [ "$1" == "usb" ]; then
    HCI_ADAPTER="hci0"
    ADAPTER_TYPE="USB (forced)"
elif [ "$1" == "uart" ] || [ "$1" == "onboard" ]; then
    HCI_ADAPTER="hci1"
    ADAPTER_TYPE="Onboard UART (forced)"
fi

echo "=== OBD Bluetooth Connection Script ==="
echo "Adapter: $HCI_ADAPTER ($ADAPTER_TYPE)"
echo "Target:  $OBD_MAC (OBDLink MX+)"
echo ""

# Ensure adapter is up
echo "[1/4] Bringing up $HCI_ADAPTER..."
sudo hciconfig $HCI_ADAPTER up
sudo hciconfig $HCI_ADAPTER piscan

# Scan for device (optional but helps)
echo "[2/4] Scanning for OBDLink..."
if sudo hcitool -i $HCI_ADAPTER scan --flush 2>/dev/null | grep -q "$OBD_MAC"; then
    echo "      Found OBDLink MX+"
else
    echo "      Warning: OBDLink not found in scan (may still connect)"
    echo "      Make sure OBDLink is in pairing mode (fast blinking)"
fi

# Pair and trust
echo "[3/4] Pairing and trusting..."
bluetoothctl pair $OBD_MAC 2>/dev/null
bluetoothctl trust $OBD_MAC 2>/dev/null

# Bind RFCOMM
echo "[4/4] Binding RFCOMM..."
sudo rfcomm release 0 2>/dev/null
sudo rfcomm -i $HCI_ADAPTER bind 0 $OBD_MAC 1
sleep 1

# Check status
echo ""
echo "=== Status ==="
rfcomm -a

# Quick test
echo ""
echo "=== Quick Test ==="
python3 << 'PYEOF'
import serial
import time

try:
    ser = serial.Serial('/dev/rfcomm0', 38400, timeout=3)
    ser.reset_input_buffer()
    ser.write(b'ATZ\r')
    time.sleep(1)
    response = ser.read(200).decode(errors='ignore').strip()

    if 'ELM' in response:
        print(f"Connected: {response}")
        ser.write(b'ATRV\r')
        time.sleep(0.5)
        voltage = ser.read(100).decode(errors='ignore').strip()
        print(f"Voltage: {voltage}")
        print("\n=== SUCCESS! OBD connection ready ===")
    else:
        print(f"No ELM response: {response}")

    ser.close()
except Exception as e:
    print(f"Connection failed: {e}")
PYEOF
