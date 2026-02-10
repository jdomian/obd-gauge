#!/bin/bash
# Deploy OBD gauge to device and restart (~3 sec vs 30+ sec reboot)
DEVICE_IP="${1:-10.0.0.219}"
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude 'backups' \
  /home/claude/obd-gauge/ claude@$DEVICE_IP:~/obd-gauge/
ssh claude@$DEVICE_IP "~/obd-gauge/restart.sh"
