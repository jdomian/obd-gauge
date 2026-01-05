"""
PiSugar 3 Battery Client

Interface with PiSugar battery via TCP API (port 8423).
Provides battery percentage, charging status, and power control.
"""

import socket
import time
import subprocess


class PiSugarClient:
    """Client for PiSugar 3 battery management"""

    def __init__(self, host='127.0.0.1', port=8423):
        self.host = host
        self.port = port
        self._battery_cache = None
        self._charging_cache = None
        self._last_query = 0
        self._cache_ttl = 10  # seconds between API calls

    def _query(self, command):
        """Send command to PiSugar server, get response"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((self.host, self.port))
            s.send(f'{command}\n'.encode())
            response = s.recv(1024).decode().strip()
            s.close()
            # Parse "battery: 85.5" -> "85.5"
            if ': ' in response:
                return response.split(': ')[1]
            return response
        except Exception as e:
            # Silently fail - PiSugar may not be present
            return None

    def _refresh_cache(self):
        """Refresh battery and charging status from API"""
        now = time.time()
        if now - self._last_query > self._cache_ttl:
            # Get battery percentage
            result = self._query('get battery')
            if result:
                try:
                    self._battery_cache = float(result)
                except ValueError:
                    pass

            # Get charging status
            result = self._query('get battery_charging')
            self._charging_cache = result == 'true'

            self._last_query = now

    def get_battery(self):
        """Get battery percentage (0-100), cached"""
        self._refresh_cache()
        return self._battery_cache

    def is_charging(self):
        """Check if currently charging, cached"""
        self._refresh_cache()
        return self._charging_cache

    def power_off(self, delay_seconds=3):
        """
        Tell PiSugar to cut power after delay.

        This schedules a power-off so the Pi can finish halting first.
        Uses I2C command to PiSugar MCU.
        """
        try:
            # Try using pisugar-server command first
            result = self._query(f'set_soft_poweroff_timeout {delay_seconds}')

            # Also try direct I2C as backup
            # Register 0x18 with value sets power-off timer
            # Bus 1 is typical for Pi Zero 2W
            subprocess.run(
                ['sudo', 'i2cset', '-y', '1', '0x57', '0x18', str(delay_seconds)],
                capture_output=True,
                timeout=2
            )
        except Exception as e:
            # Best effort - continue with shutdown anyway
            pass

    def is_available(self):
        """Check if PiSugar is responding"""
        result = self._query('get model')
        return result is not None


# Quick test
if __name__ == '__main__':
    client = PiSugarClient()
    if client.is_available():
        print(f"Battery: {client.get_battery():.1f}%")
        print(f"Charging: {client.is_charging()}")
    else:
        print("PiSugar not available")
