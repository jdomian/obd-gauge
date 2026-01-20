#!/bin/bash
export SDL_FBDEV=/dev/fb0
export SDL_VIDEODRIVER=fbcon
cd /home/claude/obd-gauge
exec /usr/bin/python3 boost_gauge.py --fps 30 --obd 25 --smooth 0.25
