#!/bin/bash
# Start gauge on virtual terminal 1

# Unbind console from framebuffer
echo 0 > /sys/class/vtconsole/vtcon1/bind 2>/dev/null

# Clear framebuffer
dd if=/dev/zero of=/dev/fb0 bs=4096 count=500 2>/dev/null

# Export SDL environment variables
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0
export PYTHONUNBUFFERED=1
export HOME=/root
export TERM=linux

# Switch to VT1 and run the gauge
cd /home/claude/obd-gauge
exec /usr/bin/python3 boost_gauge.py
