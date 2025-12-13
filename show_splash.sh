#!/bin/bash
# Ultra-fast boot splash - just cat pre-rendered raw data to framebuffer
cat /home/claude/obd-gauge/splash.raw > /dev/fb0
echo "Splash displayed"
