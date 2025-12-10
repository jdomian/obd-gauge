#!/usr/bin/env python3
"""
OBD-Gauge - Boost Gauge Display for Pi Zero 2W + HyperPixel 2.1 Round

Optimized for:
- 2016 Audi RS7 4.0T (500 kbps CAN bus)
- OBDLink MX+ adapter (20-30 Hz single PID)
- HyperPixel 2.1 Round (480x480 @ 60Hz)

Recommended: --fps 30 --obd 25 --smooth 0.25
"""

import os
import sys

# Ensure we can import sibling modules regardless of working directory
# (fixes imports when run via rc.local or from different directory)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import signal
import pygame
from pygame import gfxdraw
import math
import time
import json
import threading
import subprocess
from touch import TouchHandler, GestureType

# Import our new modules
try:
    from hotspot import start_hotspot, stop_hotspot, is_hotspot_active
    from settings_server import start_server, stop_server
    from bt_manager import (get_bt_status, scan_devices, pair_device, connect_obd, BTStatus,
                            create_obd_connection, has_socket_support)
    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Some modules not available: {e}")
    MODULES_AVAILABLE = False
    has_socket_support = lambda: False

# Import OBD socket module for direct Bluetooth communication
try:
    from obd_socket import OBDSocket, ConnectionState, OBDData
    OBD_SOCKET_AVAILABLE = True
except ImportError as e:
    print(f"Warning: OBD socket module not available: {e}")
    OBD_SOCKET_AVAILABLE = False
    OBDSocket = None
    ConnectionState = None
    OBDData = None

# Try to import QR code library
try:
    import qrcode
    from PIL import Image
    QR_AVAILABLE = True
except ImportError:
    print("Warning: qrcode[pil] library not installed. Run: pip install qrcode[pil]")
    QR_AVAILABLE = False

class BoostGaugeTest:
    def __init__(self):
        self._dim_overlay = None  # Must init before first _flip
        self._init_display()
        self.screen.fill((0, 0, 0))
        self._flip()

        self.center = (240, 240)
        self._running = False
        self._clock = pygame.time.Clock()

        # Colors
        self.BLACK = (0, 0, 0)
        self.WHITE = (255, 255, 255)
        self.GRAY = (60, 60, 60)
        self.DARK_GRAY = (30, 30, 40)
        self.ORANGE = (255, 107, 0)
        self.GREEN = (0, 255, 0)
        self.YELLOW = (255, 255, 0)
        self.RED = (255, 0, 0)
        self.BLUE = (0, 150, 255)
        self.GOLD = (255, 215, 0)

        # Audi MMI Color Palette
        self.AUDI_BLACK = (10, 10, 10)
        self.AUDI_DARK = (26, 26, 26)
        self.AUDI_CHARCOAL = (37, 37, 37)
        self.AUDI_RED = (187, 10, 30)
        self.AUDI_RED_LIGHT = (204, 26, 46)
        self.AUDI_RED_DIM = (100, 5, 15)
        self.AUDI_WHITE = (255, 255, 255)
        self.AUDI_GRAY = (160, 160, 160)
        self.AUDI_GRAY_MUTED = (96, 96, 96)
        self.AUDI_GREEN = (0, 200, 83)
        self.AUDI_AMBER = (255, 179, 0)
        self.AUDI_DIVIDER = (51, 51, 51)

        # Settings file path
        self._settings_path = os.path.join(os.path.dirname(__file__), "config", "settings.json")

        # Load settings from config file (gauges, display, etc.)
        self._load_settings()

        # Gauge settings (fallback/defaults, overridden by settings.json)
        self.min_psi = -15  # Vacuum
        self.max_psi = 25   # Boost
        self.current_psi = -10.0  # Displayed value (smoothed)
        self.target_psi = -10.0   # Target value from OBD2

        # Tweening settings - optimized for RS7 + OBDLink MX+
        # RS7 uses 500kbps high-speed CAN bus
        # OBDLink MX+ can deliver 20-30 Hz for single PID on modern CAN vehicles
        # Smoothing 0.25 = responsive for fast data, minimal latency feel
        self.smoothing = 0.25  # How fast needle catches up (0.1 = slow, 0.3 = fast)
        self.last_update = time.time()

        # Animation
        self.start_angle = 135   # Bottom left
        self.end_angle = 405     # Bottom right (wrap around)
        self.sweep_angle = 270

        # Font
        pygame.font.init()
        self._font_large = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        self._font_medium = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        self._font_small = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        self._font_tiny = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)

        # FPS tracking
        self.frame_count = 0
        self.fps_timer = time.time()
        self.fps = 0

        # 2D Screen grid navigation (vertical swipe down to access settings)
        # Row 0: Gauges (boost, temp, engine load, SHIFT LIGHT) - 4+ columns
        # Row 1: Bluetooth - 1 column
        # Row 2: WiFi/Settings/QR - 1 column (shows connection status, SSID, IP)
        # Row 3: System (Brightness/Reboot/Restart) - 1 column
        self.screen_col = 0  # Current column
        self.screen_row = 0  # Current row
        self.row_cols = [4, 1, 1, 1]  # Number of columns per row
        self.num_rows = 4    # 4 rows (gauges + bluetooth + wifi/settings + system)

        # Brightness setting (10-100%)
        self.brightness = 100
        self.min_brightness = 10
        self.max_brightness = 100
        self._dim_overlay = None  # Software dimming overlay

        # QR code surface (generated once)
        self.qr_surface = None
        self._generate_qr_code()

        # Hotspot/server state
        self.hotspot_active = False
        self.server_active = False
        self.hotspot_starting = False
        self.hotspot_stopping = False
        self.client_connected = False
        self.client_check_thread = None

        # Bluetooth state
        self.bt_status = None
        self.bt_scanning = False
        self.bt_devices = []
        self.bt_selected_device = 0

        # Demo/test mode - needle sweep animation when not connected to OBD
        self.demo_mode = True  # Start with demo mode ON
        self.demo_time = 0.0   # For animation timing

        # OBD Socket Connection (new socket-based approach)
        self.obd_connection = None  # OBDSocket instance
        self.obd_state = "disconnected"  # disconnected, connecting, connected, error
        self.obd_state_msg = ""
        self.obd_connected = False
        self.obd_connecting = False
        self.obd_connecting_mac = None  # MAC of device being connected
        self.obd_connecting_name = None  # Name of device being connected
        self.obd_connected_address = None  # Address/MAC of connected device (persists after connect)
        self.obd_connected_name = None     # Name of connected device (e.g., "Simulator", "OBDLink MX+")

        # Pending system action (reboot/shutdown) - executed after clean exit
        self._pending_action = None  # 'reboot' or 'shutdown'

        # Cooldown timer to prevent accidental taps after screen navigation
        self._nav_cooldown = 0  # timestamp when cooldown ends

        # Gauge data (simulated for now)
        self.boost_psi = -10.0
        self.boost_target = -10.0
        self.coolant_temp = 180.0  # °F
        self.coolant_target = 180.0
        self.engine_load = 25.0  # %
        self.engine_load_target = 25.0

        # Settings state
        self.settings_selection = 0  # Which setting is highlighted (0=Gauge1, 1=Gauge2, 2=Back)
        self.settings_items = ['Gauge 1 PID', 'Gauge 2 PID', 'Back']
        self.selected_pid_indices = [0, 1]  # Index into available_pids for each gauge

        # Available PIDs for selection - (id, name, unit, min, max, color_zones)
        # color_zones: list of (start_pct, end_pct, color_name)
        self.available_pids = [
            ('BOOST', 'Boost Pressure', 'PSI', -15, 25, 'boost'),
            ('COOLANT_TEMP', 'Coolant Temp', '°F', 100, 260, 'temp'),
            ('ENGINE_LOAD', 'Engine Load', '%', 0, 100, 'load'),
            ('INTAKE_TEMP', 'Intake Air Temp', '°F', 0, 200, 'temp'),
            ('RPM', 'Engine RPM', 'RPM', 0, 8000, 'rpm'),
            ('THROTTLE_POS', 'Throttle Position', '%', 0, 100, 'load'),
            ('OIL_TEMP', 'Oil Temperature', '°F', 100, 300, 'temp'),
            ('FUEL_PRESSURE', 'Fuel Pressure', 'PSI', 0, 100, 'fuel'),
        ]

        # Color zone presets for different PID types
        self.color_zone_presets = {
            'boost': [
                (0.0, 0.375, self.BLUE),   # Vacuum: -15 to 0
                (0.375, 0.75, self.GREEN), # Low boost: 0-15
                (0.75, 1.0, self.RED),     # High boost: 15-25
            ],
            'temp': [
                (0.0, 0.3, self.BLUE),     # Cold
                (0.3, 0.7, self.GREEN),    # Normal
                (0.7, 1.0, self.RED),      # Hot
            ],
            'load': [
                (0.0, 0.3, self.BLUE),     # Light
                (0.3, 0.7, self.GREEN),    # Normal
                (0.7, 1.0, self.RED),      # Heavy
            ],
            'rpm': [
                (0.0, 0.4, self.BLUE),     # Idle/low
                (0.4, 0.75, self.GREEN),   # Normal
                (0.75, 1.0, self.RED),     # Redline
            ],
            'fuel': [
                (0.0, 0.3, self.RED),      # Low pressure (bad)
                (0.3, 0.8, self.GREEN),    # Normal
                (0.8, 1.0, self.YELLOW),   # High
            ],
        }

        # Simulated values for live preview (keyed by PID id)
        self.simulated_values = {
            'BOOST': -10.0,
            'COOLANT_TEMP': 180.0,
            'ENGINE_LOAD': 25.0,
            'INTAKE_TEMP': 85.0,
            'RPM': 2500.0,
            'THROTTLE_POS': 15.0,
            'OIL_TEMP': 210.0,
            'FUEL_PRESSURE': 45.0,
        }

        # Shift Light Settings (RS7 4.0T redline is ~6800, APR tune safe to 7000)
        self.shift_rpm_target = 6500   # When to shift (BRIGHT RED FLASH)
        self.shift_rpm_warning = 500   # RPM before target to show yellow warning
        self.shift_strobe_hz = 10      # Flash rate when over-revving
        self.shift_flash_state = False # Toggle for strobe effect
        self.shift_last_flash = 0      # Time of last flash toggle
        self.current_rpm = 0.0         # Smoothed RPM for display
        self.target_rpm = 0.0          # Target RPM from OBD

        # Touch handler - initialized at module level to avoid GPIO conflicts
        # See end of file for touch setup
        print("Touch will be initialized at module level")

    def _load_settings(self):
        """Load gauge and display settings from settings.json.

        This is called at startup and can be called again to reload settings
        (e.g., after Web UI makes changes).
        """
        # Default gauge configurations (used if settings.json is missing or incomplete)
        self.gauge_configs = [
            {"position": 0, "pid": "BOOST", "label": "BOOST", "min": -15, "max": 25, "conversion": "none", "color_preset": "boost"},
            {"position": 1, "pid": "COOLANT_TEMP", "label": "COOLANT", "min": 100, "max": 260, "conversion": "c_to_f", "color_preset": "temp"},
            {"position": 2, "pid": "ENGINE_LOAD", "label": "LOAD", "min": 0, "max": 100, "conversion": "none", "color_preset": "load"},
        ]

        # Display settings defaults
        self.target_fps = 30
        self.demo_mode = True
        self.dial_background = "default"

        try:
            if os.path.exists(self._settings_path):
                with open(self._settings_path) as f:
                    settings = json.load(f)

                # Load gauge configurations
                if "gauges" in settings and isinstance(settings["gauges"], list):
                    loaded_gauges = []
                    for g in settings["gauges"]:
                        gauge_config = {
                            "position": g.get("position", len(loaded_gauges)),
                            "pid": g.get("pid", "BOOST"),
                            "label": g.get("label", g.get("pid", "GAUGE")),
                            "min": g.get("min", 0),
                            "max": g.get("max", 100),
                            "conversion": g.get("conversion", "none"),
                            "color_preset": g.get("color_preset", self._get_color_preset_for_pid(g.get("pid", ""))),
                            "needle": g.get("needle", "default"),
                        }
                        loaded_gauges.append(gauge_config)

                    if loaded_gauges:
                        # Sort by position
                        self.gauge_configs = sorted(loaded_gauges, key=lambda x: x["position"])
                        print(f"[Settings] Loaded {len(self.gauge_configs)} gauge configs")

                # Load display settings
                display = settings.get("display", {})
                self.target_fps = display.get("fps", 30)
                self.smoothing = display.get("smoothing", 0.25)
                self.demo_mode = display.get("demo_mode", True)
                self.dial_background = display.get("dial_background", "default")

                print(f"[Settings] Display: fps={self.target_fps}, demo={self.demo_mode}, dial={self.dial_background}")

                # Update row_cols based on number of gauges (+ shift light)
                # Row 0: Gauges (+ shift light), Row 1: Bluetooth, Row 2: WiFi/Settings, Row 3: System
                num_gauges = len(self.gauge_configs)
                self.row_cols = [num_gauges + 1, 1, 1, 1]  # 4 rows now

        except Exception as e:
            print(f"[Settings] Failed to load settings: {e}")
            # Keep defaults on error

    def _get_color_preset_for_pid(self, pid):
        """Get default color preset based on PID type."""
        pid_upper = pid.upper()
        if "TEMP" in pid_upper or "OIL" in pid_upper:
            return "temp"
        elif "BOOST" in pid_upper:
            return "boost"
        elif "RPM" in pid_upper:
            return "rpm"
        elif "FUEL" in pid_upper:
            return "fuel"
        else:
            return "load"

    def reload_settings(self):
        """Reload settings from file. Call this when Web UI updates settings.json."""
        print("[Settings] Reloading settings...")
        self._load_settings()
        # Re-initialize simulated values for any new PIDs
        for gauge in self.gauge_configs:
            pid = gauge["pid"]
            if pid not in self.simulated_values:
                self.simulated_values[pid] = (gauge["min"] + gauge["max"]) / 2
        print("[Settings] Reload complete")

    def _save_bt_device(self, mac, name):
        """Save Bluetooth device to settings for auto-connect on next startup."""
        try:
            settings_path = os.path.join(os.path.dirname(__file__), "config", "settings.json")
            if os.path.exists(settings_path):
                with open(settings_path) as f:
                    settings = json.load(f)

                # Update OBD settings with the device
                if "obd" not in settings:
                    settings["obd"] = {}
                settings["obd"]["bt_device_mac"] = mac
                settings["obd"]["bt_device_name"] = name or "OBD Device"

                # Disable demo mode since we have a real device
                if "display" in settings:
                    settings["display"]["demo_mode"] = False

                # Disable simulator since we're using real BT
                if "simulator" in settings:
                    settings["simulator"]["enabled"] = False

                with open(settings_path, 'w') as f:
                    json.dump(settings, f, indent=2)
                print(f"[Settings] Saved BT device: {name} ({mac})")
        except Exception as e:
            print(f"[Settings] Failed to save BT device: {e}")

    def _generate_qr_code(self):
        """Generate single QR code for WiFi auto-connect."""
        if not QR_AVAILABLE:
            return

        try:
            # WiFi QR code format - auto-connects phone to WiFi network
            # Format: WIFI:T:nopass;S:obd-gauge;H:false;;
            # After connecting, phone can navigate to 192.168.4.1:8080
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=6,
                border=2,
            )
            qr.add_data("WIFI:T:nopass;S:obd-gauge;H:false;;")
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="white", back_color="black")
            qr_size = qr_img.size
            qr_data = qr_img.convert("RGB").tobytes()
            self.qr_surface = pygame.image.fromstring(qr_data, qr_size, "RGB")

            print(f"QR code generated: {qr_size[0]}x{qr_size[1]}")
        except Exception as e:
            print(f"Failed to generate QR code: {e}")
            self.qr_surface = None

    def _draw_capsule(self, color, rect, outline_width=0):
        """Draw a capsule/pill-shaped rectangle (pygame 2.6.1 compatible).

        Since pygame 2.6.1 doesn't support border_radius keyword,
        we draw capsules manually using circles + rectangle.

        Args:
            color: Fill or outline color
            rect: pygame.Rect defining the capsule bounds
            outline_width: If 0, filled. If > 0, outline only.
        """
        x, y, w, h = rect.x, rect.y, rect.width, rect.height
        radius = h // 2  # For a capsule, radius = half height

        if outline_width == 0:
            # Filled capsule: two filled circles + rectangle
            gfxdraw.filled_circle(self.screen, x + radius, y + radius, radius, color)
            gfxdraw.filled_circle(self.screen, x + w - radius, y + radius, radius, color)
            pygame.draw.rect(self.screen, color, (x + radius, y, w - h, h))
        else:
            # Outline only: two arc circles + lines
            gfxdraw.aacircle(self.screen, x + radius, y + radius, radius, color)
            gfxdraw.aacircle(self.screen, x + w - radius, y + radius, radius, color)
            pygame.draw.line(self.screen, color, (x + radius, y), (x + w - radius, y), outline_width)
            pygame.draw.line(self.screen, color, (x + radius, y + h - 1), (x + w - radius, y + h - 1), outline_width)

    # ============= Audi MMI UI Helper Functions =============

    def _draw_audi_header(self, text, y=55):
        """Draw Audi MMI style header with red underline accent."""
        # Header text in white
        title = self._font_medium.render(text, True, self.AUDI_WHITE)
        title_rect = title.get_rect(center=(240, y))
        self.screen.blit(title, title_rect)
        # Red underline accent
        underline_width = title_rect.width + 20
        underline_x = 240 - underline_width // 2
        pygame.draw.line(self.screen, self.AUDI_RED, (underline_x, y + 18), (underline_x + underline_width, y + 18), 2)

    def _draw_audi_button(self, text, rect, active=False, pressed=False, color_scheme="default"):
        """Draw Audi MMI style button.

        Args:
            text: Button label
            rect: pygame.Rect for button bounds
            active: If True, button has brighter styling
            pressed: If True, button is being pressed
            color_scheme: "default", "red", "green", or "blue"
        """
        # Color schemes
        schemes = {
            "default": {"bg": self.AUDI_CHARCOAL, "border": self.AUDI_GRAY, "active_bg": self.AUDI_DARK, "active_border": self.AUDI_RED},
            "red": {"bg": (60, 20, 20), "border": self.AUDI_RED_DIM, "active_bg": (80, 30, 30), "active_border": self.AUDI_RED},
            "green": {"bg": (20, 50, 30), "border": (0, 100, 40), "active_bg": (30, 70, 40), "active_border": self.AUDI_GREEN},
            "blue": {"bg": (20, 35, 55), "border": (0, 80, 140), "active_bg": (30, 50, 75), "active_border": self.BLUE},
        }
        scheme = schemes.get(color_scheme, schemes["default"])

        if pressed:
            bg_color = self.AUDI_RED
            border_color = self.AUDI_RED_LIGHT
        elif active:
            bg_color = scheme["active_bg"]
            border_color = scheme["active_border"]
        else:
            bg_color = scheme["bg"]
            border_color = scheme["border"]

        # Draw button background
        pygame.draw.rect(self.screen, bg_color, rect)
        pygame.draw.rect(self.screen, border_color, rect, 2)

        # Draw text
        text_color = self.AUDI_WHITE if active or pressed else self.AUDI_GRAY
        btn_text = self._font_small.render(text, True, text_color)
        btn_rect = btn_text.get_rect(center=rect.center)
        self.screen.blit(btn_text, btn_rect)

    def _draw_audi_list_item(self, y, name, subtitle=None, selected=False, connected=False, paired=False):
        """Draw Audi MMI style list item row.

        Args:
            y: Y position for the item
            name: Main text
            subtitle: Secondary text (e.g., MAC address)
            selected: If True, item is highlighted
            connected: If True, show green indicator
            paired: If True, show "PAIRED" label
        """
        item_height = 50

        # Selection background
        if selected:
            # Red left accent bar
            pygame.draw.rect(self.screen, self.AUDI_RED, (75, y - 2, 4, item_height - 4))
            # Subtle red tint background
            pygame.draw.rect(self.screen, (40, 15, 15), (80, y - 2, 320, item_height - 4))
            name_color = self.AUDI_WHITE
            subtitle_color = self.AUDI_GRAY
        else:
            name_color = self.AUDI_GRAY
            subtitle_color = self.AUDI_GRAY_MUTED

        # Connection status indicator
        if connected:
            indicator_color = self.AUDI_GREEN
        elif paired:
            indicator_color = self.AUDI_AMBER
        else:
            indicator_color = self.AUDI_GRAY_MUTED
        gfxdraw.aacircle(self.screen, 100, y + 18, 6, indicator_color)
        gfxdraw.filled_circle(self.screen, 100, y + 18, 6, indicator_color)

        # Name text
        name_surface = self._font_small.render(name[:22], True, name_color)
        self.screen.blit(name_surface, (115, y))

        # Subtitle (MAC address)
        if subtitle:
            sub_surface = self._font_tiny.render(subtitle, True, subtitle_color)
            self.screen.blit(sub_surface, (115, y + 22))

        # Paired label on right
        if paired and not connected:
            paired_surface = self._font_tiny.render("PAIRED", True, self.AUDI_AMBER)
            self.screen.blit(paired_surface, (355, y + 8))
        elif connected:
            conn_surface = self._font_tiny.render("CONNECTED", True, self.AUDI_GREEN)
            self.screen.blit(conn_surface, (340, y + 8))

        # Divider line
        pygame.draw.line(self.screen, self.AUDI_DIVIDER, (85, y + item_height - 5), (395, y + item_height - 5), 1)

    def _draw_audi_screen_background(self):
        """Draw the standard Audi MMI dark background for settings screens."""
        gfxdraw.filled_circle(self.screen, 240, 240, 220, self.AUDI_BLACK)
        gfxdraw.aacircle(self.screen, 240, 240, 220, self.AUDI_CHARCOAL)

    def _draw_audi_nav_hints(self, hints):
        """Draw navigation hints at bottom of screen.

        Args:
            hints: List of strings like ["↓ gauges", "← bluetooth"] or single string
        """
        # Handle both list and string input
        if isinstance(hints, list):
            hint_text = "   ".join(hints)
        else:
            hint_text = hints
        hint_surface = self._font_tiny.render(hint_text, True, self.AUDI_GRAY_MUTED)
        hint_rect = hint_surface.get_rect(center=(240, 450))
        self.screen.blit(hint_surface, hint_rect)

    # ============= End Audi MMI Helpers =============

    def _get_wifi_info(self):
        """Get current WiFi connection info (non-blocking, background thread updates).

        Returns:
            dict: {connected: bool, ssid: str, ip: str}
        """
        # Initialize cache if not exists
        if not hasattr(self, '_wifi_info_cache'):
            self._wifi_info_cache = {"connected": False, "ssid": "", "ip": ""}
            self._wifi_info_time = 0
            self._wifi_info_updating = False

        # Start background update if needed (non-blocking)
        now = time.time()
        if not self._wifi_info_updating and (now - self._wifi_info_time > 5):
            self._wifi_info_updating = True
            thread = threading.Thread(target=self._update_wifi_info_background, daemon=True)
            thread.start()

        return self._wifi_info_cache

    def _update_wifi_info_background(self):
        """Background thread to update WiFi info without blocking UI."""
        info = {"connected": False, "ssid": "", "ip": ""}

        try:
            # Get SSID using iwgetid
            result = subprocess.run(
                ["iwgetid", "-r"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                info["ssid"] = result.stdout.strip()
                info["connected"] = True

            # Get IP address for wlan0
            if info["connected"]:
                result = subprocess.run(
                    ["hostname", "-I"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0 and result.stdout.strip():
                    # Get first IP (usually the wlan0 IP)
                    ips = result.stdout.strip().split()
                    if ips:
                        info["ip"] = ips[0]
        except Exception as e:
            print(f"Error getting WiFi info: {e}")

        # Update cache
        self._wifi_info_cache = info
        self._wifi_info_time = time.time()
        self._wifi_info_updating = False

    def _on_enter_qr_screen(self):
        """Called when entering the QR settings screen."""
        # Don't auto-start anymore - user taps to start
        pass

    def _on_exit_qr_screen(self):
        """Called when leaving the QR settings screen."""
        # Stop hotspot if active when leaving screen
        if self.hotspot_active or self.server_active:
            self._stop_hotspot_async()

    def _start_hotspot_async(self):
        """Start hotspot in background thread to avoid UI freeze."""
        if self.hotspot_starting or self.hotspot_active:
            return

        def start_thread():
            self.hotspot_starting = True
            try:
                if MODULES_AVAILABLE:
                    print("Starting hotspot...")
                    self.hotspot_active = start_hotspot()
                    if self.hotspot_active:
                        start_server()
                        self.server_active = True
                        print("Hotspot and server started!")
                        # Start client monitoring
                        self._start_client_monitor()
            except Exception as e:
                print(f"Failed to start hotspot: {e}")
                self.hotspot_active = False
            finally:
                self.hotspot_starting = False

        thread = threading.Thread(target=start_thread, daemon=True)
        thread.start()

    def _stop_hotspot_async(self):
        """Stop hotspot in background thread."""
        if self.hotspot_stopping:
            return

        def stop_thread():
            self.hotspot_stopping = True
            try:
                if self.server_active:
                    stop_server()
                    self.server_active = False
                if self.hotspot_active:
                    stop_hotspot()
                    self.hotspot_active = False
                self.client_connected = False
                print("Hotspot stopped!")
            except Exception as e:
                print(f"Failed to stop hotspot: {e}")
            finally:
                self.hotspot_stopping = False

        thread = threading.Thread(target=stop_thread, daemon=True)
        thread.start()

    def _start_client_monitor(self):
        """Monitor for client connections/disconnections."""
        def monitor_thread():
            import subprocess
            last_connected = False
            while self.hotspot_active and self.screen_row == 1 and self.screen_col == 0:
                try:
                    # Check connected clients via arp or hostapd
                    result = subprocess.run(
                        ["arp", "-i", "wlan0", "-n"],
                        capture_output=True, text=True, timeout=2
                    )
                    # Count lines with valid MACs (skip header)
                    lines = [l for l in result.stdout.strip().split('\n') if ':' in l]
                    connected = len(lines) > 0

                    if connected and not last_connected:
                        print("Client connected!")
                        self.client_connected = True
                    elif not connected and last_connected:
                        print("Client disconnected - stopping hotspot...")
                        self.client_connected = False
                        # Auto-stop when client disconnects
                        self._stop_hotspot_async()
                        break

                    last_connected = connected
                except Exception as e:
                    print(f"Monitor error: {e}")

                time.sleep(2)  # Check every 2 seconds

        self.client_check_thread = threading.Thread(target=monitor_thread, daemon=True)
        self.client_check_thread.start()

    def _on_enter_bt_screen(self):
        """Called when entering the Bluetooth screen."""
        if MODULES_AVAILABLE:
            try:
                self.bt_status = get_bt_status()
                print(f"BT Status: {self.bt_status}")
            except Exception as e:
                print(f"Failed to get BT status: {e}")

    def _start_bt_scan(self):
        """Start Bluetooth device scan in background thread."""
        if self.bt_scanning:
            return

        # Auto-disable demo mode when scanning for real devices
        if self.demo_mode:
            self.demo_mode = False
            print("Demo mode auto-disabled for BT scan")

        def scan_thread():
            self.bt_scanning = True
            try:
                if MODULES_AVAILABLE:
                    self.bt_devices = scan_devices(timeout=10)
                    print(f"Found {len(self.bt_devices)} devices")
            except Exception as e:
                print(f"BT scan failed: {e}")
            finally:
                self.bt_scanning = False

        thread = threading.Thread(target=scan_thread, daemon=True)
        thread.start()

    def _set_brightness(self, brightness):
        """Set display brightness (10-100%) via software dimming."""
        self.brightness = max(self.min_brightness, min(self.max_brightness, brightness))
        # Create/update dim overlay surface
        self._update_dim_overlay()
        print(f"Brightness set to {self.brightness}%")

    def _update_dim_overlay(self):
        """Create a dim overlay surface for software brightness control."""
        if self.brightness >= 100:
            self._dim_overlay = None
        else:
            # Create circular overlay matching the round display
            self._dim_overlay = pygame.Surface((480, 480), pygame.SRCALPHA)
            # Alpha: 0 = transparent, 255 = opaque
            # brightness 100 = alpha 0, brightness 10 = alpha 230 (90% dark)
            alpha = int(255 * (1 - self.brightness / 100))
            gfxdraw.filled_circle(self._dim_overlay, 240, 240, 240, (0, 0, 0, alpha))

    def handle_touch(self, x, y, state):
        """Handle raw touch events from hyperpixel2r library."""
        if state:  # Touch down / drag
            # Only set start on FIRST touch (not during drag)
            if not hasattr(self, '_touch_start_x') or self._touch_start_x is None:
                self._touch_start_x = x
                self._touch_start_y = y
                self._touch_start_time = time.time()
            # Always track current position
            self._touch_current_x = x
            self._touch_current_y = y

            # Handle drag on brightness slider (row 2)
            if self.screen_row == 2:
                self._handle_brightness_drag(x, y)
        else:  # Touch up
            if hasattr(self, '_touch_start_x') and self._touch_start_x is not None:
                dx = self._touch_current_x - self._touch_start_x
                dy = self._touch_current_y - self._touch_start_y
                duration = (time.time() - self._touch_start_time) * 1000

                SWIPE_THRESHOLD = 50
                old_row = self.screen_row
                old_col = self.screen_col

                # Determine if horizontal or vertical swipe
                if abs(dx) > abs(dy) and abs(dx) > SWIPE_THRESHOLD:
                    # Horizontal swipe - navigate columns within current row
                    num_cols = self.row_cols[self.screen_row]
                    if num_cols > 1:
                        if dx < 0:  # Swipe left = next column
                            new_col = (self.screen_col + 1) % num_cols
                        else:  # Swipe right = prev column
                            new_col = (self.screen_col - 1) % num_cols

                        # Handle screen transitions for row 1
                        if self.screen_row == 1:
                            # Leaving QR screen (col 0)
                            if self.screen_col == 0 and new_col != 0:
                                self._on_exit_qr_screen()
                            # Entering QR screen (col 0)
                            if new_col == 0 and self.screen_col != 0:
                                self._on_enter_qr_screen()
                            # Entering BT screen (col 1)
                            if new_col == 1 and self.screen_col != 1:
                                self._on_enter_bt_screen()

                        self.screen_col = new_col
                        print(f"SWIPE {'LEFT' if dx < 0 else 'RIGHT'} -> Row {self.screen_row}, Col {self.screen_col}")

                elif abs(dy) > abs(dx) and abs(dy) > SWIPE_THRESHOLD:
                    # Vertical swipe - navigate rows
                    if dy < 0:  # Swipe up = go to next row
                        if self.screen_row < self.num_rows - 1:
                            new_row = self.screen_row + 1
                            # Handle transitions
                            if self.screen_row == 1 and self.screen_col == 0:
                                self._on_exit_qr_screen()
                            self.screen_row = new_row
                            # Clamp column to valid range for new row
                            self.screen_col = min(self.screen_col, self.row_cols[new_row] - 1)
                            # Handle entering new row
                            if new_row == 1 and self.screen_col == 0:
                                self._on_enter_qr_screen()
                            elif new_row == 1 and self.screen_col == 1:
                                self._on_enter_bt_screen()
                            # Set cooldown to prevent accidental taps after navigation
                            self._nav_cooldown = time.time() + 0.5  # 500ms cooldown
                            print(f"SWIPE UP -> Row {self.screen_row}, Col {self.screen_col}")
                    else:  # Swipe down = go to prev row
                        if self.screen_row > 0:
                            new_row = self.screen_row - 1
                            # Handle transitions
                            if self.screen_row == 1 and self.screen_col == 0:
                                self._on_exit_qr_screen()
                            self.screen_row = new_row
                            # Clamp column to valid range for new row
                            self.screen_col = min(self.screen_col, self.row_cols[new_row] - 1)
                            # Handle entering new row
                            if new_row == 1 and self.screen_col == 0:
                                self._on_enter_qr_screen()
                            elif new_row == 1 and self.screen_col == 1:
                                self._on_enter_bt_screen()
                            # Set cooldown to prevent accidental taps after navigation
                            self._nav_cooldown = time.time() + 0.5  # 500ms cooldown
                            print(f"SWIPE DOWN -> Row {self.screen_row}, Col {self.screen_col}")

                elif abs(dx) < 20 and abs(dy) < 20 and duration < 300:
                    # Tap detected
                    print(f"TAP detected at ({x}, {y}) on Row {self.screen_row}, Col {self.screen_col}")
                    self._handle_tap(x, y)
                else:
                    # No gesture matched
                    print(f"NO GESTURE: dx={dx:.1f}, dy={dy:.1f}, dur={duration:.0f}ms")

            # Reset for next gesture
            self._touch_start_x = None
            self._touch_start_y = None

    def _handle_brightness_drag(self, x, y):
        """Handle drag on brightness slider."""
        # Slider is centered, 300px wide, y=215 on system screen
        slider_left = 90
        slider_right = 390
        slider_width = slider_right - slider_left
        slider_y = 215  # Center of slider

        # Only respond if touch is near the slider vertically
        if slider_left <= x <= slider_right and abs(y - slider_y) < 30:
            # Map x position to brightness value
            pct = (x - slider_left) / slider_width
            new_brightness = int(self.min_brightness + pct * (self.max_brightness - self.min_brightness))
            self._set_brightness(new_brightness)

    def _handle_tap(self, x, y):
        """Handle tap gesture - context-dependent actions."""
        if self.screen_row == 1 and self.screen_col == 0:
            # QR Settings screen - tap to toggle hotspot
            if 150 < y < 350:
                # Tap on center area toggles hotspot
                if not self.hotspot_active and not self.hotspot_starting:
                    print("Tap -> Starting hotspot...")
                    self._start_hotspot_async()
                elif self.hotspot_active and not self.hotspot_stopping:
                    print("Tap -> Stopping hotspot...")
                    self._stop_hotspot_async()
        elif self.screen_row == 1 and self.screen_col == 1:
            # Bluetooth screen - tap zones for SCAN and PAIR/DISCONNECT
            # Reset disconnect confirm if tapping elsewhere
            if y <= 310 or x < 240:
                self.disconnect_confirm = False

            if y > 310:
                # Bottom area - buttons (moved up from 350)
                if x < 240:
                    # Left side - SCAN (disabled when connected)
                    if not self.obd_connected:
                        print("Tap -> Starting BT scan...")
                        self._start_bt_scan()
                    else:
                        print("Tap -> SCAN disabled while connected")
                else:
                    # Right side - CONNECT or DISCONNECT
                    if self.obd_connected:
                        # Already connected - handle disconnect with confirmation
                        if getattr(self, 'disconnect_confirm', False):
                            # Second tap - actually disconnect
                            print("Tap -> DISCONNECT confirmed!")
                            self.disconnect_confirm = False
                            self.disconnect_obd_socket()
                        else:
                            # First tap - ask for confirmation
                            print("Tap -> DISCONNECT requested, tap again to confirm")
                            self.disconnect_confirm = True
                    elif self.bt_devices and self.bt_selected_device < len(self.bt_devices):
                        device = self.bt_devices[self.bt_selected_device]
                        if not self.obd_connecting:
                            print(f"Tap -> Connecting OBD to {device.name}...")
                            # Start connection in background thread (includes pairing)
                            self._start_obd_connection_async(device.mac, device.name)
            elif 150 < y < 330 and self.bt_devices:
                # Device list area - select device
                # Calculate which device was tapped
                list_start_y = 160
                item_height = 55  # Matches display item height
                idx = int((y - list_start_y) / item_height)
                if 0 <= idx < min(len(self.bt_devices), 3):  # Max 3 items shown
                    self.bt_selected_device = idx
                    print(f"Selected device: {self.bt_devices[idx].name} ({self.bt_devices[idx].mac})")
        elif self.screen_row == 2:
            # System screen - demo toggle, brightness slider, or power buttons
            if y >= 80 and y <= 140:
                # Demo mode toggle area (top)
                if x >= 280 and x <= 400:
                    # Toggle demo mode
                    self.demo_mode = not self.demo_mode
                    print(f"Demo mode: {'ON' if self.demo_mode else 'OFF'}")
            elif y >= 195 and y <= 235:
                # Brightness slider area
                self._handle_brightness_drag(x, y)
            elif y >= 335 and y <= 390:
                # Power button area - check cooldown to prevent accidental taps after swipe
                if time.time() < self._nav_cooldown:
                    print(f"Tap ignored (cooldown active)")
                    return
                if x < 220:
                    # Shutdown button (left side)
                    print("Tap -> SHUTDOWN requested...")
                    self._graceful_shutdown()
                elif x > 260:
                    # Reboot button (right side)
                    print("Tap -> REBOOT requested...")
                    self._graceful_reboot()

    def _graceful_shutdown(self):
        """Gracefully shutdown the Pi."""
        # Show shutdown message
        self.screen.fill(self.BLACK)
        gfxdraw.filled_circle(self.screen, 240, 240, 200, self.DARK_GRAY)
        msg = self._font_medium.render("Shutting down...", True, self.RED)
        msg_rect = msg.get_rect(center=(240, 240))
        self.screen.blit(msg, msg_rect)
        self._flip()

        # Set pending action and stop main loop - action executed after clean exit
        self._pending_action = 'shutdown'
        self._running = False

    def _graceful_reboot(self):
        """Gracefully reboot the Pi."""
        # Show reboot message
        self.screen.fill(self.BLACK)
        gfxdraw.filled_circle(self.screen, 240, 240, 200, self.DARK_GRAY)
        msg = self._font_medium.render("Rebooting...", True, self.BLUE)
        msg_rect = msg.get_rect(center=(240, 240))
        self.screen.blit(msg, msg_rect)
        self._flip()

        # Set pending action and stop main loop - action executed after clean exit
        self._pending_action = 'reboot'
        self._running = False

    def _exit(self, sig, frame):
        self._running = False
        print("\nExiting!...")
        # Clean up hotspot/server if active
        if self.server_active or self.hotspot_active:
            self._on_exit_qr_screen()
        print("Goodbye!\n")

    def _init_display(self):
        self._rawfb = False

        if os.getenv('SDL_VIDEODRIVER'):
            print(f"Using driver: {os.getenv('SDL_VIDEODRIVER')}")
            pygame.display.init()
            size = (pygame.display.Info().current_w, pygame.display.Info().current_h)
            if size == (480, 480):
                size = (640, 480)
            self.screen = pygame.display.set_mode(size, pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.NOFRAME | pygame.HWSURFACE)
            return

        for driver in ['kmsdrm', 'fbcon', 'directfb', 'svgalib']:
            os.putenv('SDL_VIDEODRIVER', driver)
            try:
                pygame.display.init()
                size = (pygame.display.Info().current_w, pygame.display.Info().current_h)
                if size == (480, 480):
                    size = (640, 480)
                self.screen = pygame.display.set_mode(size, pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.NOFRAME | pygame.HWSURFACE)
                print(f"Using driver: {driver}, size: {size}")
                return
            except pygame.error as e:
                print(f'Driver "{driver}" failed: {e}')
                continue

        print("Falling back to raw framebuffer")
        self._rawfb = True
        os.putenv('SDL_VIDEODRIVER', 'dummy')
        pygame.display.init()
        self.screen = pygame.Surface((480, 480))

    def _flip(self):
        # Apply software dimming overlay if brightness < 100%
        if self._dim_overlay is not None:
            self.screen.blit(self._dim_overlay, (0, 0))
        
        if self._rawfb:
            fbdev = os.getenv('SDL_FBDEV', '/dev/fb0')
            # HyperPixel 2r has 480x480 physical but 720x480 virtual framebuffer
            # We need to pad each row to match the stride
            surface = self.screen.convert(16, 0)
            raw_data = surface.get_buffer().raw

            # Physical: 480x480, Virtual: 720x480, 16bpp = 2 bytes per pixel
            fb_stride = 720 * 2  # bytes per row in framebuffer
            screen_stride = 480 * 2  # bytes per row in our surface
            padding = fb_stride - screen_stride  # extra bytes per row

            with open(fbdev, 'wb') as fb:
                for y in range(480):
                    row_start = y * screen_stride
                    row_end = row_start + screen_stride
                    fb.write(raw_data[row_start:row_end])
                    fb.write(b'\x00' * padding)  # pad to match stride
        else:
            pygame.display.flip()

    def _get_point(self, origin, angle, distance):
        """Get point at angle and distance from origin."""
        r = math.radians(angle)
        x = origin[0] + distance * math.cos(r)
        y = origin[1] + distance * math.sin(r)
        return int(x), int(y)

    def _draw_arc(self, center, radius, start_angle, end_angle, color, thickness=3):
        """Draw an arc segment."""
        for angle in range(int(start_angle), int(end_angle), 2):
            x1, y1 = self._get_point(center, angle, radius)
            x2, y2 = self._get_point(center, angle + 2, radius)
            pygame.draw.line(self.screen, color, (x1, y1), (x2, y2), thickness)

    def _draw_needle(self, psi):
        """Draw the gauge needle."""
        # Map PSI to angle
        psi_range = self.max_psi - self.min_psi
        psi_normalized = (psi - self.min_psi) / psi_range
        angle = self.start_angle + (psi_normalized * self.sweep_angle)

        # Needle points
        tip = self._get_point(self.center, angle, 160)
        base_left = self._get_point(self.center, angle + 90, 15)
        base_right = self._get_point(self.center, angle - 90, 15)
        tail = self._get_point(self.center, angle + 180, 30)

        # Draw needle (filled polygon)
        pygame.draw.polygon(self.screen, self.RED, [tip, base_left, tail, base_right])
        pygame.draw.polygon(self.screen, self.WHITE, [tip, base_left, tail, base_right], 2)

        # Center hub
        gfxdraw.aacircle(self.screen, 240, 240, 20, self.GRAY)
        gfxdraw.filled_circle(self.screen, 240, 240, 20, self.GRAY)
        gfxdraw.aacircle(self.screen, 240, 240, 10, self.WHITE)
        gfxdraw.filled_circle(self.screen, 240, 240, 10, self.WHITE)

    def _draw_gauge_face(self):
        """Draw the static gauge face elements."""
        # Outer ring
        gfxdraw.aacircle(self.screen, 240, 240, 220, self.GRAY)
        gfxdraw.aacircle(self.screen, 240, 240, 218, self.GRAY)

        # Arc segments (vacuum = blue, boost = gradient)
        # Vacuum zone (-15 to 0)
        vacuum_end_angle = self.start_angle + (15/40 * self.sweep_angle)
        self._draw_arc(self.center, 190, self.start_angle, vacuum_end_angle, self.BLUE, 8)

        # Low boost (0 to 15) - green to yellow
        boost_mid_angle = self.start_angle + (30/40 * self.sweep_angle)
        self._draw_arc(self.center, 190, vacuum_end_angle, boost_mid_angle, self.GREEN, 8)

        # High boost (15 to 25) - yellow to red
        self._draw_arc(self.center, 190, boost_mid_angle, self.start_angle + self.sweep_angle, self.RED, 8)

        # Tick marks and labels
        for psi in range(-15, 26, 5):
            psi_normalized = (psi - self.min_psi) / (self.max_psi - self.min_psi)
            angle = self.start_angle + (psi_normalized * self.sweep_angle)

            # Major tick
            inner = self._get_point(self.center, angle, 165)
            outer = self._get_point(self.center, angle, 185)
            pygame.draw.line(self.screen, self.WHITE, inner, outer, 3)

            # Label
            label_pos = self._get_point(self.center, angle, 140)
            label = self._font_small.render(str(psi), True, self.WHITE)
            label_rect = label.get_rect(center=label_pos)
            self.screen.blit(label, label_rect)

        # Minor ticks
        for psi in range(-15, 26, 1):
            if psi % 5 != 0:
                psi_normalized = (psi - self.min_psi) / (self.max_psi - self.min_psi)
                angle = self.start_angle + (psi_normalized * self.sweep_angle)
                inner = self._get_point(self.center, angle, 175)
                outer = self._get_point(self.center, angle, 185)
                pygame.draw.line(self.screen, self.GRAY, inner, outer, 1)

    def _draw_digital_readout(self, psi):
        """Draw digital PSI readout."""
        # Background box (no border_radius for pygame 1.9)
        pygame.draw.rect(self.screen, self.GRAY, (170, 300, 140, 60))
        pygame.draw.rect(self.screen, self.WHITE, (170, 300, 140, 60), 2)

        # PSI value
        if psi >= 0:
            color = self.RED if psi > 15 else self.GREEN
            text = f"+{psi:.1f}"
        else:
            color = self.BLUE
            text = f"{psi:.1f}"

        psi_surface = self._font_medium.render(text, True, color)
        psi_rect = psi_surface.get_rect(center=(240, 330))
        self.screen.blit(psi_surface, psi_rect)

        # Unit label
        unit_surface = self._font_small.render("PSI", True, self.WHITE)
        unit_rect = unit_surface.get_rect(center=(240, 375))
        self.screen.blit(unit_surface, unit_rect)

    def _draw_fps(self):
        """Draw FPS counter."""
        fps_text = f"FPS: {self.fps:.1f}"
        fps_surface = self._font_small.render(fps_text, True, self.YELLOW)
        self.screen.blit(fps_surface, (10, 10))

    def _draw_screen_indicator(self):
        """Draw dots at bottom showing current screen position in grid."""
        dot_y = 460
        dot_spacing = 15

        # Draw dots for current row
        num_cols = self.row_cols[self.screen_row]
        start_x = 240 - (num_cols - 1) * dot_spacing // 2

        for i in range(num_cols):
            x = start_x + i * dot_spacing
            color = self.WHITE if i == self.screen_col else self.GRAY
            gfxdraw.aacircle(self.screen, x, dot_y, 4, color)
            gfxdraw.filled_circle(self.screen, x, dot_y, 4, color)

        # Row indicator on the left side
        row_indicator_x = 25
        row_indicator_y = 240
        row_spacing = 20

        for i in range(self.num_rows):
            y = row_indicator_y + (i - 1) * row_spacing
            color = self.WHITE if i == self.screen_row else self.GRAY
            gfxdraw.aacircle(self.screen, row_indicator_x, y, 4, color)
            gfxdraw.filled_circle(self.screen, row_indicator_x, y, 4, color)

    def _draw_generic_gauge(self, value, min_val, max_val, unit, title, color_zones=None):
        """Draw a generic gauge with customizable range and colors."""
        # Default color zones if not specified
        if color_zones is None:
            # Default: blue low, green mid, red high
            color_zones = [
                (0.0, 0.33, self.BLUE),
                (0.33, 0.66, self.GREEN),
                (0.66, 1.0, self.RED),
            ]

        # Outer ring
        gfxdraw.aacircle(self.screen, 240, 240, 220, self.GRAY)
        gfxdraw.aacircle(self.screen, 240, 240, 218, self.GRAY)

        # Draw colored arc zones
        for start_pct, end_pct, color in color_zones:
            start_a = self.start_angle + (start_pct * self.sweep_angle)
            end_a = self.start_angle + (end_pct * self.sweep_angle)
            self._draw_arc(self.center, 190, start_a, end_a, color, 8)

        # Calculate tick interval based on range
        val_range = max_val - min_val
        if val_range <= 50:
            major_step = 5
        elif val_range <= 200:
            major_step = 20
        elif val_range <= 1000:
            major_step = 100
        else:
            major_step = 1000

        # Tick marks and labels
        for val in range(int(min_val), int(max_val) + 1, major_step):
            val_normalized = (val - min_val) / (max_val - min_val)
            angle = self.start_angle + (val_normalized * self.sweep_angle)

            # Major tick
            inner = self._get_point(self.center, angle, 165)
            outer = self._get_point(self.center, angle, 185)
            pygame.draw.line(self.screen, self.WHITE, inner, outer, 3)

            # Label
            label_pos = self._get_point(self.center, angle, 140)
            label = self._font_small.render(str(val), True, self.WHITE)
            label_rect = label.get_rect(center=label_pos)
            self.screen.blit(label, label_rect)

        # Draw needle
        val_normalized = max(0, min(1, (value - min_val) / (max_val - min_val)))
        angle = self.start_angle + (val_normalized * self.sweep_angle)

        tip = self._get_point(self.center, angle, 160)
        base_left = self._get_point(self.center, angle + 90, 15)
        base_right = self._get_point(self.center, angle - 90, 15)
        tail = self._get_point(self.center, angle + 180, 30)

        pygame.draw.polygon(self.screen, self.RED, [tip, base_left, tail, base_right])
        pygame.draw.polygon(self.screen, self.WHITE, [tip, base_left, tail, base_right], 2)

        # Center hub - Audi MMI style
        gfxdraw.aacircle(self.screen, 240, 240, 20, self.AUDI_CHARCOAL)
        gfxdraw.filled_circle(self.screen, 240, 240, 20, self.AUDI_CHARCOAL)
        gfxdraw.aacircle(self.screen, 240, 240, 10, self.AUDI_RED)
        gfxdraw.filled_circle(self.screen, 240, 240, 10, self.AUDI_RED)

        # Digital readout - Audi MMI style
        pygame.draw.rect(self.screen, self.AUDI_CHARCOAL, (170, 300, 140, 60))
        pygame.draw.rect(self.screen, self.AUDI_DIVIDER, (170, 300, 140, 60), 2)

        # Determine color based on position in range
        val_pct = (value - min_val) / (max_val - min_val)
        display_color = self.GREEN
        for start_pct, end_pct, color in color_zones:
            if start_pct <= val_pct <= end_pct:
                display_color = color
                break

        text = f"{value:.0f}" if abs(value) >= 10 else f"{value:.1f}"
        val_surface = self._font_medium.render(text, True, display_color)
        val_rect = val_surface.get_rect(center=(240, 330))
        self.screen.blit(val_surface, val_rect)

        # Unit and title - Audi MMI style
        unit_surface = self._font_small.render(unit, True, self.AUDI_GRAY)
        unit_rect = unit_surface.get_rect(center=(240, 375))
        self.screen.blit(unit_surface, unit_rect)

        title_surface = self._font_small.render(title, True, self.AUDI_WHITE)
        title_rect = title_surface.get_rect(center=(240, 60))
        self.screen.blit(title_surface, title_rect)

    def _draw_temp_gauge(self, temp):
        """Draw coolant temperature gauge (100-260°F)."""
        # Color zones: cold=blue, normal=green, hot=red
        color_zones = [
            (0.0, 0.3, self.BLUE),    # Cold: 100-148°F
            (0.3, 0.7, self.GREEN),   # Normal: 148-212°F
            (0.7, 1.0, self.RED),     # Hot: 212-260°F
        ]
        self._draw_generic_gauge(temp, 100, 260, "°F", "COOLANT TEMP", color_zones)

    def _draw_load_gauge(self, load):
        """Draw engine load gauge (0-100%)."""
        # Color zones: idle=blue, normal=green, high=red
        color_zones = [
            (0.0, 0.3, self.BLUE),    # Light: 0-30%
            (0.3, 0.7, self.GREEN),   # Normal: 30-70%
            (0.7, 1.0, self.RED),     # Heavy: 70-100%
        ]
        self._draw_generic_gauge(load, 0, 100, "%", "ENGINE LOAD", color_zones)

    def _draw_configured_gauge(self, gauge_config):
        """Draw a gauge based on configuration from settings.json.

        Args:
            gauge_config: Dict with keys: pid, label, min, max, conversion, color_preset
        """
        pid = gauge_config.get("pid", "BOOST")
        label = gauge_config.get("label", pid)
        min_val = gauge_config.get("min", 0)
        max_val = gauge_config.get("max", 100)
        conversion = gauge_config.get("conversion", "none")
        color_preset = gauge_config.get("color_preset", "load")

        # Get current value from simulated_values (updated by demo mode or OBD)
        raw_value = self.simulated_values.get(pid, (min_val + max_val) / 2)

        # Apply conversion if needed
        if conversion == "c_to_f":
            # Celsius to Fahrenheit
            value = raw_value * 9/5 + 32
        elif conversion == "kpa_to_psi":
            # kPa to PSI (for boost)
            value = raw_value * 0.145038
        elif conversion == "bar_to_psi":
            # Bar to PSI
            value = raw_value * 14.5038
        else:
            value = raw_value

        # Get color zones from preset
        color_zones = self.color_zone_presets.get(color_preset, self.color_zone_presets['load'])

        # Determine unit based on PID or config
        unit = self._get_unit_for_pid(pid, conversion)

        # Draw the gauge
        self._draw_generic_gauge(value, min_val, max_val, unit, label, color_zones)

    def _get_unit_for_pid(self, pid, conversion="none"):
        """Get display unit for a PID."""
        pid_upper = pid.upper()
        if "TEMP" in pid_upper:
            return "°F" if conversion == "c_to_f" else "°C"
        elif "BOOST" in pid_upper or "PRESSURE" in pid_upper:
            return "PSI"
        elif "RPM" in pid_upper:
            return "RPM"
        elif "THROTTLE" in pid_upper or "LOAD" in pid_upper:
            return "%"
        elif "SPEED" in pid_upper:
            return "MPH"
        else:
            return ""

    def _draw_shift_light_screen(self):
        """Draw full-screen shift light for peripheral vision.

        FULL-SCREEN peripheral vision indicator:
        - BLACK: Below warning zone (clean, no distraction)
        - YELLOW GLOW: Approaching target (RPM - warning threshold)
        - BRIGHT RED FLASH: At target RPM - ENTIRE SCREEN FLASHES RED
        - RAPID STROBE: Over rev - alternating red/white flash

        Performance critical: minimize rendering for <16ms frame time.
        """
        # Get current RPM (from OBD data or simulated values)
        rpm = self.simulated_values.get('RPM', 0)

        # Update smoothed RPM for display
        dt = 1.0 / 30.0  # Assume ~30 FPS
        rpm_diff = rpm - self.current_rpm
        self.current_rpm += rpm_diff * 0.3  # Fast response for shift light

        now = time.time()
        warning_start = self.shift_rpm_target - self.shift_rpm_warning

        # Determine screen color based on RPM
        if rpm >= self.shift_rpm_target:
            # OVER TARGET - BRIGHT RED or STROBE
            if rpm > self.shift_rpm_target + 200:
                # OVER-REV - RAPID STROBE (red/white)
                strobe_period = 1.0 / self.shift_strobe_hz
                if now - self.shift_last_flash >= strobe_period:
                    self.shift_flash_state = not self.shift_flash_state
                    self.shift_last_flash = now

                if self.shift_flash_state:
                    bg_color = (255, 255, 255)  # WHITE flash
                else:
                    bg_color = (255, 0, 0)  # RED flash
            else:
                # AT TARGET - SOLID BRIGHT RED
                bg_color = (255, 0, 0)
        elif rpm >= warning_start:
            # WARNING ZONE - YELLOW GLOW (intensity increases approaching target)
            warning_pct = (rpm - warning_start) / self.shift_rpm_warning
            # Fade from dark to yellow
            intensity = int(warning_pct * 255)
            bg_color = (intensity, intensity, 0)  # Yellow
        else:
            # BELOW WARNING - BLACK (no distraction)
            bg_color = (0, 0, 0)

        # Fill entire screen with color (fastest possible operation)
        self.screen.fill(bg_color)

        # Small RPM readout in bottom corner (not the focus, just reference)
        # Use contrasting color for visibility
        if bg_color == (0, 0, 0):
            text_color = (80, 80, 80)  # Dim gray on black
        elif bg_color[0] > 200 or bg_color[1] > 200:  # Bright background
            text_color = (0, 0, 0)  # Black text
        else:
            text_color = (255, 255, 255)  # White text

        # RPM number - large enough to glance at but not the focus
        rpm_text = self._font_large.render(f"{int(self.current_rpm)}", True, text_color)
        rpm_rect = rpm_text.get_rect(center=(240, 400))
        self.screen.blit(rpm_text, rpm_rect)

        # Shift target indicator (small)
        target_text = self._font_tiny.render(f"SHIFT @ {self.shift_rpm_target}", True, text_color)
        target_rect = target_text.get_rect(center=(240, 440))
        self.screen.blit(target_text, target_rect)

        # Draw circular mask to maintain round display appearance
        # (Only draw edges to save performance - center is already filled)
        for angle in range(0, 360, 2):
            for r in range(220, 240):
                x = int(240 + r * math.cos(math.radians(angle)))
                y = int(240 + r * math.sin(math.radians(angle)))
                if 0 <= x < 480 and 0 <= y < 480:
                    self.screen.set_at((x, y), (0, 0, 0))

    def _draw_mini_gauge_preview(self, center_x, center_y, pid_info):
        """Draw a small preview gauge for PID selection."""
        pid_id, name, unit, min_val, max_val, color_preset = pid_info
        radius = 60

        # Get color zones
        color_zones = self.color_zone_presets.get(color_preset, self.color_zone_presets['load'])

        # Outer ring
        gfxdraw.aacircle(self.screen, center_x, center_y, radius, self.GRAY)

        # Draw colored arc zones (smaller)
        for start_pct, end_pct, color in color_zones:
            start_a = self.start_angle + (start_pct * self.sweep_angle)
            end_a = self.start_angle + (end_pct * self.sweep_angle)
            for angle in range(int(start_a), int(end_a), 4):
                x1, y1 = self._get_point((center_x, center_y), angle, radius - 8)
                x2, y2 = self._get_point((center_x, center_y), angle + 4, radius - 8)
                pygame.draw.line(self.screen, color, (x1, y1), (x2, y2), 4)

        # Get simulated value
        value = self.simulated_values.get(pid_id, (min_val + max_val) / 2)

        # Draw mini needle
        val_normalized = max(0, min(1, (value - min_val) / (max_val - min_val)))
        angle = self.start_angle + (val_normalized * self.sweep_angle)

        tip = self._get_point((center_x, center_y), angle, radius - 15)
        base = (center_x, center_y)
        pygame.draw.line(self.screen, self.RED, base, tip, 3)

        # Center dot
        gfxdraw.aacircle(self.screen, center_x, center_y, 5, self.WHITE)
        gfxdraw.filled_circle(self.screen, center_x, center_y, 5, self.WHITE)

        # Value text below
        val_text = f"{value:.0f}" if abs(value) >= 10 else f"{value:.1f}"
        val_surface = self._font_small.render(f"{val_text} {unit}", True, self.WHITE)
        val_rect = val_surface.get_rect(center=(center_x, center_y + radius + 15))
        self.screen.blit(val_surface, val_rect)

    def _draw_qr_settings_screen(self):
        """Draw the WiFi/Settings screen - Audi MMI style.

        Shows current WiFi connection status at top, then hotspot controls below.
        """
        # Audi MMI dark background
        self._draw_audi_screen_background()

        # Audi MMI header with red underline
        self._draw_audi_header("WIFI / SETTINGS")

        # Get current WiFi info
        wifi_info = self._get_wifi_info()

        # === WiFi Status Section (top) ===
        wifi_y = 95  # Starting Y position

        # WiFi connection status indicator
        if wifi_info["connected"]:
            # Connected - show green with SSID and IP
            status_color = self.AUDI_GREEN
            status_icon = "●"

            # SSID row
            ssid_text = f"{status_icon} {wifi_info['ssid']}"
            ssid_surface = self._font_small.render(ssid_text, True, status_color)
            ssid_rect = ssid_surface.get_rect(center=(240, wifi_y))
            self.screen.blit(ssid_surface, ssid_rect)

            # IP row
            ip_text = wifi_info["ip"]
            ip_surface = self._font_small.render(ip_text, True, self.AUDI_GRAY)
            ip_rect = ip_surface.get_rect(center=(240, wifi_y + 28))
            self.screen.blit(ip_surface, ip_rect)

        else:
            # Not connected - show warning
            status_color = self.AUDI_AMBER
            status_text = "○ WiFi Not Connected"
            status_surface = self._font_small.render(status_text, True, status_color)
            status_rect = status_surface.get_rect(center=(240, wifi_y + 14))
            self.screen.blit(status_surface, status_rect)

        # Divider line
        divider_y = wifi_y + 60
        pygame.draw.line(self.screen, self.AUDI_DIVIDER, (80, divider_y), (400, divider_y), 1)

        # === Hotspot Section (below divider) ===
        hotspot_y_base = divider_y + 20

        if self.hotspot_starting:
            # Starting hotspot - show spinner with Audi amber
            dots = "." * (int(time.time() * 3) % 4)
            status_text = self._font_small.render(f"Starting hotspot{dots}", True, self.AUDI_AMBER)
            status_rect = status_text.get_rect(center=(240, hotspot_y_base + 80))
            self.screen.blit(status_text, status_rect)

        elif self.hotspot_stopping:
            # Stopping hotspot
            dots = "." * (int(time.time() * 3) % 4)
            status_text = self._font_small.render(f"Stopping{dots}", True, self.AUDI_AMBER)
            status_rect = status_text.get_rect(center=(240, hotspot_y_base + 80))
            self.screen.blit(status_text, status_rect)

        elif self.hotspot_active:
            # Hotspot is ON - show QR code (smaller to fit)
            if self.qr_surface:
                # Draw card background for QR
                card_rect = pygame.Rect(160, hotspot_y_base + 5, 160, 160)
                pygame.draw.rect(self.screen, self.AUDI_CHARCOAL, card_rect)
                pygame.draw.rect(self.screen, self.AUDI_DIVIDER, card_rect, 1)

                # Scale QR to fit
                qr_scaled = pygame.transform.scale(self.qr_surface, (140, 140))
                qr_rect = qr_scaled.get_rect(center=(240, hotspot_y_base + 85))
                self.screen.blit(qr_scaled, qr_rect)

            # Connection status below QR
            if self.client_connected:
                conn_color = self.AUDI_GREEN
                conn_text = "● Phone Connected"
            else:
                conn_color = self.AUDI_AMBER
                conn_text = "○ Scan QR to connect"

            conn_surface = self._font_tiny.render(conn_text, True, conn_color)
            conn_rect = conn_surface.get_rect(center=(240, hotspot_y_base + 180))
            self.screen.blit(conn_surface, conn_rect)

            # Tap to stop hint
            hint = self._font_tiny.render("tap to stop hotspot", True, self.AUDI_GRAY_MUTED)
            hint_rect = hint.get_rect(center=(240, hotspot_y_base + 205))
            self.screen.blit(hint, hint_rect)

        else:
            # Hotspot is OFF - show compact start button
            # Draw tap target with Audi red
            btn_y = hotspot_y_base + 75
            pygame.draw.circle(self.screen, self.AUDI_RED_DIM, (240, btn_y), 55)
            pygame.draw.circle(self.screen, self.AUDI_RED, (240, btn_y), 55, 2)

            # WiFi icon in Audi red (smaller)
            for i, r in enumerate([18, 32, 46]):
                arc_color = self.AUDI_RED if i < 2 else self.AUDI_RED_DIM
                pygame.draw.arc(self.screen, arc_color, (240-r, btn_y-r, r*2, r*2), 0.5, 2.6, 2)

            # Dot at bottom of wifi icon
            gfxdraw.aacircle(self.screen, 240, btn_y + 14, 4, self.AUDI_RED)
            gfxdraw.filled_circle(self.screen, 240, btn_y + 14, 4, self.AUDI_RED)

            # Text below button
            start_text = self._font_tiny.render("TAP TO START HOTSPOT", True, self.AUDI_GRAY)
            start_rect = start_text.get_rect(center=(240, btn_y + 75))
            self.screen.blit(start_text, start_rect)

        # Audi MMI navigation hints (Row 2: WiFi/Settings)
        self._draw_audi_nav_hints(["↑ bluetooth", "↓ system"])

    def _draw_bluetooth_screen(self):
        """Draw the Bluetooth pairing screen - Audi MMI style."""
        # Audi MMI dark background
        self._draw_audi_screen_background()

        # Audi MMI header with red underline
        self._draw_audi_header("BLUETOOTH")

        # Connection status - Show OBD socket status if available, otherwise BT pairing status
        if self.obd_connected or self.obd_connecting or self.obd_state == "error":
            # OBD Socket connection status (takes priority)
            if self.obd_connected:
                status_color = self.AUDI_GREEN
                status_text = "OBD Connected"
            elif self.obd_connecting:
                status_color = self.AUDI_AMBER
                status_text = "Connecting..."
            else:  # error
                status_color = self.AUDI_RED
                status_text = self.obd_state_msg[:25] if self.obd_state_msg else "Error"

            # Status indicator circle
            gfxdraw.aacircle(self.screen, 170, 90, 8, status_color)
            gfxdraw.filled_circle(self.screen, 170, 90, 8, status_color)

            # Device/connection info - Show actual device name if connected
            if self.obd_connected_name:
                device_name = self.obd_connected_name[:22]  # Truncate if too long
            else:
                device_name = "OBD-II Data"
            obd_label = self._font_small.render(device_name, True, self.AUDI_WHITE)
            obd_rect = obd_label.get_rect(midleft=(190, 90))
            self.screen.blit(obd_label, obd_rect)

            # Show address on second line if connected
            if self.obd_connected_address:
                addr_text = self.obd_connected_address[:25]  # Truncate if too long
                addr_surface = self._font_tiny.render(addr_text, True, self.AUDI_GRAY)
                addr_rect = addr_surface.get_rect(midleft=(190, 112))
                self.screen.blit(addr_surface, addr_rect)
                # Status text on third line
                status_surface = self._font_tiny.render(status_text, True, status_color)
                status_rect = status_surface.get_rect(midleft=(190, 130))
                self.screen.blit(status_surface, status_rect)
            else:
                # Status text on second line (no address)
                status_surface = self._font_tiny.render(status_text, True, status_color)
                status_rect = status_surface.get_rect(midleft=(190, 115))
                self.screen.blit(status_surface, status_rect)

        elif self.bt_status:
            if self.bt_status.connected:
                status_color = self.AUDI_GREEN
                status_text = "Connected"
            elif self.bt_status.paired:
                status_color = self.AUDI_AMBER
                status_text = "Paired (not connected)"
            else:
                status_color = self.AUDI_RED
                status_text = "Not paired"

            # Status indicator circle
            gfxdraw.aacircle(self.screen, 170, 100, 8, status_color)
            gfxdraw.filled_circle(self.screen, 170, 100, 8, status_color)

            # Device name
            device_name = self.bt_status.device_name if self.bt_status.device_name else "No device"
            name_surface = self._font_small.render(device_name, True, self.AUDI_WHITE)
            name_rect = name_surface.get_rect(midleft=(190, 100))
            self.screen.blit(name_surface, name_rect)

            # Status text
            status_surface = self._font_tiny.render(status_text, True, status_color)
            status_rect = status_surface.get_rect(midleft=(190, 125))
            self.screen.blit(status_surface, status_rect)
        else:
            no_status = self._font_small.render("Status unknown", True, self.AUDI_GRAY)
            no_rect = no_status.get_rect(center=(240, 110))
            self.screen.blit(no_status, no_rect)

        # Divider line - Audi subtle gray
        pygame.draw.line(self.screen, self.AUDI_DIVIDER, (80, 145), (400, 145), 1)

        # Device list or scanning message
        if self.bt_scanning:
            # Scanning animation with Audi amber
            dots = "." * (int(time.time() * 3) % 4)
            scan_text = self._font_small.render(f"Scanning{dots}", True, self.AUDI_AMBER)
            scan_rect = scan_text.get_rect(center=(240, 220))
            self.screen.blit(scan_text, scan_rect)
        elif self.bt_devices:
            # Show device list with Audi MMI styling
            list_y = 160
            item_height = 55  # Taller items to fit MAC address
            for i, device in enumerate(self.bt_devices[:3]):  # Max 3 devices
                # Determine if this device is connected/paired
                is_connected = (self.obd_connected and
                               self.obd_connected_address and
                               device.mac in self.obd_connected_address)
                is_paired = device.paired
                is_selected = (i == self.bt_selected_device)

                # Use the Audi list item helper
                self._draw_audi_list_item(
                    y=list_y + i * item_height,
                    name=device.name[:22] if len(device.name) > 22 else device.name,
                    subtitle=device.mac,
                    selected=is_selected,
                    connected=is_connected,
                    paired=is_paired
                )
        else:
            # No devices - Audi gray text
            no_dev = self._font_small.render("Tap SCAN to find devices", True, self.AUDI_GRAY)
            no_rect = no_dev.get_rect(center=(240, 220))
            self.screen.blit(no_dev, no_rect)

        # Buttons with Audi styling
        btn_y = 340
        btn_rect_left = pygame.Rect(70, btn_y, 140, 50)
        btn_rect_right = pygame.Rect(270, btn_y, 140, 50)

        # SCAN button (left) - disabled while connected
        scan_active = not self.obd_connected
        self._draw_audi_button("SCAN", btn_rect_left, active=scan_active, color_scheme="default")

        # Right button - changes based on connection state
        if self.obd_connected:
            # Connected: Show red DISCONNECT button
            if getattr(self, 'disconnect_confirm', False):
                btn_text = "CONFIRM?"
                self._draw_audi_button(btn_text, btn_rect_right, active=True, pressed=True, color_scheme="red")
            else:
                btn_text = "DISCONNECT"
                self._draw_audi_button(btn_text, btn_rect_right, active=True, color_scheme="red")
        elif self.obd_connecting:
            # Connecting: Show amber connecting state
            btn_text = "CONNECTING"
            # Draw custom connecting state with amber
            pygame.draw.rect(self.screen, self.AUDI_CHARCOAL, btn_rect_right)
            pygame.draw.rect(self.screen, self.AUDI_AMBER, btn_rect_right, 2)
            text_surface = self._font_small.render(btn_text, True, self.AUDI_AMBER)
            text_rect = text_surface.get_rect(center=btn_rect_right.center)
            self.screen.blit(text_surface, text_rect)
        else:
            # Not connected: Show green CONNECT button
            btn_text = "CONNECT" if self.bt_devices else "PAIR"
            self._draw_audi_button(btn_text, btn_rect_right, active=True, color_scheme="green")

        # Audi MMI navigation hints
        self._draw_audi_nav_hints(["↑ gauges", "↓ wifi/settings"])

    def _draw_brightness_screen(self):
        """Draw the system settings screen (demo mode, brightness, power) - Audi MMI style."""
        # Audi MMI dark background
        self._draw_audi_screen_background()

        # Audi MMI header with red underline
        self._draw_audi_header("SYSTEM")

        # Demo Mode toggle (top section)
        demo_label = self._font_small.render("Demo Mode", True, self.AUDI_WHITE)
        demo_label_rect = demo_label.get_rect(midleft=(90, 100))
        self.screen.blit(demo_label, demo_label_rect)

        # Toggle button for demo mode - Audi style
        toggle_x = 340
        toggle_y = 100
        toggle_width = 60
        toggle_height = 28
        toggle_rect = pygame.Rect(toggle_x - toggle_width//2, toggle_y - toggle_height//2, toggle_width, toggle_height)

        if self.demo_mode:
            # ON state - Audi red background, knob on right
            self._draw_capsule(self.AUDI_RED_DIM, toggle_rect)  # Filled
            self._draw_capsule(self.AUDI_RED, toggle_rect, 2)  # Outline
            knob_pos = toggle_x + toggle_width//2 - 14
            on_text = self._font_tiny.render("ON", True, self.AUDI_RED)
        else:
            # OFF state - dark background, knob on left
            self._draw_capsule(self.AUDI_CHARCOAL, toggle_rect)  # Filled
            self._draw_capsule(self.AUDI_GRAY_MUTED, toggle_rect, 2)  # Outline
            knob_pos = toggle_x - toggle_width//2 + 14
            on_text = self._font_tiny.render("OFF", True, self.AUDI_GRAY_MUTED)

        # Draw toggle knob
        gfxdraw.aacircle(self.screen, knob_pos, toggle_y, 10, self.AUDI_WHITE)
        gfxdraw.filled_circle(self.screen, knob_pos, toggle_y, 10, self.AUDI_WHITE)

        # Demo mode description
        demo_desc = self._font_tiny.render("Needle sweep test animation", True, self.AUDI_GRAY)
        demo_desc_rect = demo_desc.get_rect(midleft=(90, 125))
        self.screen.blit(demo_desc, demo_desc_rect)

        # Divider after demo mode - Audi subtle gray
        pygame.draw.line(self.screen, self.AUDI_DIVIDER, (100, 150), (380, 150), 1)

        # Brightness section (moved down)
        bright_label = self._font_small.render("Brightness", True, self.AUDI_WHITE)
        bright_rect = bright_label.get_rect(midleft=(90, 180))
        self.screen.blit(bright_label, bright_rect)

        # Current percentage - Audi red accent
        pct_text = self._font_small.render(f"{self.brightness}%", True, self.AUDI_RED)
        pct_rect = pct_text.get_rect(midright=(390, 180))
        self.screen.blit(pct_text, pct_rect)

        # Slider track
        slider_y = 215
        slider_left = 90
        slider_right = 390
        slider_width = slider_right - slider_left

        # Track background - Audi dark
        pygame.draw.rect(self.screen, self.AUDI_DARK, (slider_left, slider_y - 10, slider_width, 20))
        pygame.draw.rect(self.screen, self.AUDI_DIVIDER, (slider_left, slider_y - 10, slider_width, 20), 1)

        # Filled portion - Audi red gradient
        fill_pct = (self.brightness - self.min_brightness) / (self.max_brightness - self.min_brightness)
        fill_width = int(slider_width * fill_pct)
        if fill_width > 0:
            pygame.draw.rect(self.screen, self.AUDI_RED, (slider_left, slider_y - 10, fill_width, 20))

        # Slider knob - White with red center
        knob_x = slider_left + fill_width
        gfxdraw.aacircle(self.screen, knob_x, slider_y, 12, self.AUDI_WHITE)
        gfxdraw.filled_circle(self.screen, knob_x, slider_y, 12, self.AUDI_WHITE)
        gfxdraw.aacircle(self.screen, knob_x, slider_y, 8, self.AUDI_RED)
        gfxdraw.filled_circle(self.screen, knob_x, slider_y, 8, self.AUDI_RED)

        # Min/max labels
        min_label = self._font_tiny.render("10%", True, self.AUDI_GRAY_MUTED)
        self.screen.blit(min_label, (slider_left, slider_y + 15))
        max_label = self._font_tiny.render("100%", True, self.AUDI_GRAY_MUTED)
        max_rect = max_label.get_rect(topright=(slider_right, slider_y + 15))
        self.screen.blit(max_label, max_rect)

        # Note about brightness
        bright_note = self._font_tiny.render("(Software dimming for night driving)", True, self.AUDI_GRAY_MUTED)
        bright_note_rect = bright_note.get_rect(center=(240, 255))
        self.screen.blit(bright_note, bright_note_rect)

        # Divider before power
        pygame.draw.line(self.screen, self.AUDI_DIVIDER, (100, 280), (380, 280), 1)

        # Power section label
        power_label = self._font_small.render("Power", True, self.AUDI_WHITE)
        power_rect = power_label.get_rect(center=(240, 305))
        self.screen.blit(power_label, power_rect)

        # Shutdown button (left) - Audi red style
        shutdown_btn_rect = pygame.Rect(70, 335, 150, 55)
        self._draw_audi_button("SHUTDOWN", shutdown_btn_rect, active=True, color_scheme="red")

        # Reboot button (right) - Audi default style
        reboot_btn_rect = pygame.Rect(260, 335, 150, 55)
        self._draw_audi_button("REBOOT", reboot_btn_rect, active=True, color_scheme="default")

        # Audi MMI navigation hints
        self._draw_audi_nav_hints(["↑ wifi/settings"])

    def _draw_settings_screen(self):
        """Draw the old settings screen - now redirects to QR screen."""
        # This method kept for backwards compatibility
        # Now we use separate QR and BT screens
        self._draw_qr_settings_screen()

    def _draw_placeholder_screen(self, screen_num):
        """Draw placeholder screen with unique color per screen."""
        # Different colors for each screen
        colors = [
            ((128, 0, 255), (40, 0, 80)),    # Screen 1: Purple
            ((0, 200, 100), (0, 60, 30)),    # Screen 2: Green
            ((255, 100, 0), (80, 30, 0)),    # Screen 3: Orange
            ((0, 150, 255), (0, 40, 80)),    # Screen 4: Blue
        ]
        idx = (screen_num - 1) % len(colors)
        ring_color, fill_color = colors[idx]

        gfxdraw.aacircle(self.screen, 240, 240, 200, ring_color)
        gfxdraw.filled_circle(self.screen, 240, 240, 200, fill_color)

        # Text showing screen number
        text = self._font_medium.render(f"Screen {screen_num}", True, self.WHITE)
        text_rect = text.get_rect(center=(240, 200))
        self.screen.blit(text, text_rect)

        # Navigation hints
        hint = self._font_small.render("Swipe LEFT = next, RIGHT = prev", True, self.GRAY)
        hint_rect = hint.get_rect(center=(240, 280))
        self.screen.blit(hint, hint_rect)

    def _update_value(self, attr_name, target, dt):
        """Smoothly interpolate any gauge value toward target.

        Uses exponential easing for natural gauge movement.
        attr_name: name of attribute to update (e.g. 'boost_psi')
        target: target value to tween toward
        dt: delta time since last frame
        """
        current = getattr(self, attr_name)

        # Exponential easing: move a percentage of remaining distance each frame
        diff = target - current

        # Adjust smoothing by delta time for frame-rate independence
        ease_factor = 1.0 - math.pow(1.0 - self.smoothing, dt * 60)

        new_value = current + diff * ease_factor

        # Snap to target if very close
        if abs(diff) < 0.01:
            new_value = target

        setattr(self, attr_name, new_value)

    # =========================================================================
    # OBD Socket Connection Methods
    # =========================================================================

    def _obd_state_callback(self, state, msg):
        """Called by OBDSocket when connection state changes."""
        if ConnectionState:
            self.obd_state = state.value
        else:
            self.obd_state = str(state)
        self.obd_state_msg = msg
        was_connecting = self.obd_connecting
        self.obd_connected = (state == ConnectionState.CONNECTED) if ConnectionState else False
        self.obd_connecting = (state == ConnectionState.CONNECTING or
                               state == ConnectionState.INITIALIZING) if ConnectionState else False
        print(f"[OBD] State: {self.obd_state} - {msg}")

        # Persist connected device info for display
        if self.obd_connected and was_connecting:
            self.obd_connected_address = self.obd_connecting_mac
            self.obd_connected_name = self.obd_connecting_name or "Unknown"
            print(f"[OBD] Connected to: {self.obd_connected_name} ({self.obd_connected_address})")

        # Save device to settings when successfully connected via BT (not simulator)
        if self.obd_connected and was_connecting and self.obd_connecting_mac:
            # Check if it's a real BT MAC (not TCP address like 10.0.0.x:port)
            if ':' in self.obd_connecting_mac and not '.' in self.obd_connecting_mac:
                self._save_bt_device(self.obd_connecting_mac, self.obd_connecting_name)
                print(f"[OBD] Saved BT device for auto-connect: {self.obd_connecting_name}")

    def _obd_data_callback(self, data):
        """Called by OBDSocket with new OBD data."""
        if not data:
            return

        # Update gauge targets from OBD data
        self.boost_target = data.boost_psi
        self.coolant_target = data.coolant_temp_f

        # Map engine load from other PIDs if available
        if data.throttle_pos > 0:
            self.engine_load_target = data.throttle_pos

        # Update simulated values for settings preview
        self.simulated_values['BOOST'] = data.boost_psi
        self.simulated_values['COOLANT_TEMP'] = data.coolant_temp_f
        self.simulated_values['INTAKE_TEMP'] = data.intake_temp_c * 9/5 + 32  # C to F
        self.simulated_values['RPM'] = data.rpm
        self.simulated_values['THROTTLE_POS'] = data.throttle_pos

    def _start_obd_connection_async(self, mac, name=None):
        """Start OBD connection process in background (includes pairing).

        Args:
            mac: MAC address (BT) or IP:port (TCP simulator)
            name: Device name (optional, used for saving to settings)
        """
        if self.obd_connecting:
            print("[OBD] Already connecting...")
            return

        # Store for later use in state callback (to save device on successful connect)
        self.obd_connecting_mac = mac
        self.obd_connecting_name = name

        def connection_thread():
            try:
                self.obd_connecting = True
                self.obd_state = "connecting"
                self.obd_state_msg = "Pairing..."

                # First ensure device is paired (this can block)
                if MODULES_AVAILABLE:
                    try:
                        pair_device(mac)
                        self.bt_status = get_bt_status(mac)
                    except Exception as e:
                        print(f"[OBD] Pairing warning: {e}")
                        # Continue anyway - might already be paired

                self.obd_state_msg = f"Connecting to {mac}..."

                # Now do socket connection
                if OBD_SOCKET_AVAILABLE:
                    self._do_socket_connect(mac)
                elif MODULES_AVAILABLE:
                    # Fall back to old rfcomm method
                    print(f"[OBD] Falling back to rfcomm connection")
                    connect_obd(mac)
                    self.obd_state = "connected"
                    self.obd_state_msg = "Connected (rfcomm)"
                else:
                    self.obd_state = "error"
                    self.obd_state_msg = "No connection method available"

            except Exception as e:
                print(f"[OBD] Connection error: {e}")
                self.obd_state = "error"
                self.obd_state_msg = str(e)[:30]
            finally:
                self.obd_connecting = False

        thread = threading.Thread(target=connection_thread, daemon=True)
        thread.start()

    def _do_socket_connect(self, address):
        """Internal: perform socket-based OBD connection (called from thread).

        Args:
            address: Either a Bluetooth MAC (AA:BB:CC:DD:EE:FF) or TCP (host:port)
        """
        # Disconnect existing connection first
        self.disconnect_obd_socket()

        # Determine if TCP or Bluetooth mode
        use_tcp = False
        if address.startswith("tcp:"):
            use_tcp = True
            address = address[4:]  # Remove "tcp:" prefix

        if ":" in address and address.count(":") != 5:  # Not a MAC address
            # TCP mode: host:port
            use_tcp = True
            parts = address.split(":")
            host = parts[0]
            port = int(parts[1]) if len(parts) > 1 else 35000
            addr = host
            channel_or_port = port
        else:
            # Bluetooth mode
            addr = address
            channel_or_port = 1

        try:
            # Create OBDSocket with callbacks
            print(f"[OBD] Connecting via {'TCP' if use_tcp else 'Bluetooth'} to {addr}:{channel_or_port}")
            self.obd_connection = OBDSocket(addr, channel_or_port, use_tcp=use_tcp)
            self.obd_connection.set_state_callback(self._obd_state_callback)
            self.obd_connection.set_data_callback(self._obd_data_callback)

            if self.obd_connection.connect():
                # Start polling at 10 Hz
                self.obd_connection.start_polling(rate_hz=10)
                # Turn off demo mode when connected
                self.demo_mode = False
                print("[OBD] Connected and polling started")
            else:
                self.obd_state = "error"
                self.obd_state_msg = "Connection failed"
                self.obd_connection = None

        except Exception as e:
            print(f"[OBD] Socket connection error: {e}")
            self.obd_state = "error"
            self.obd_state_msg = str(e)[:30]
            self.obd_connection = None

    def connect_obd_socket(self, mac):
        """Connect to OBD adapter using socket-based approach (legacy wrapper)."""
        self._start_obd_connection_async(mac)

    def disconnect_obd_socket(self):
        """Disconnect from OBD adapter."""
        if self.obd_connection:
            try:
                self.obd_connection.disconnect()
            except Exception as e:
                print(f"[OBD] Disconnect error: {e}")
            self.obd_connection = None

        self.obd_connected = False
        self.obd_connecting = False
        self.obd_state = "disconnected"
        self.obd_state_msg = ""
        self.obd_connected_address = None
        self.obd_connected_name = None

    def _simulate_boost(self, t):
        """Simulate boost pressure changes."""
        # Simulate WOT pull: vacuum -> peak boost -> slight drop
        cycle = t % 8  # 8 second cycle

        if cycle < 2:
            # Idle/cruise: vacuum
            return -12 + math.sin(t * 3) * 2
        elif cycle < 3:
            # Throttle tip-in: rapid rise
            progress = (cycle - 2)
            return -12 + (progress * 35)  # -12 to +23
        elif cycle < 5:
            # Peak boost with flutter
            return 20 + math.sin(t * 10) * 3
        elif cycle < 6:
            # Lift off: rapid drop
            progress = (cycle - 5)
            return 20 - (progress * 25)
        else:
            # Coast down
            progress = (cycle - 6) / 2
            return -5 - (progress * 7)

    def run(self, target_fps=None, obd_rate=10):
        """Main loop with FPS benchmark.

        target_fps: Display refresh rate (defaults to settings.json value)
        obd_rate: Simulated OBD2 data rate (updates per second)
        """
        # Use settings.json fps if not explicitly overridden
        if target_fps is None:
            target_fps = getattr(self, 'target_fps', 30)

        self._running = True
        signal.signal(signal.SIGINT, self._exit)

        # Auto-connect to OBD device on startup
        # Priority: 1. Simulator (if enabled), 2. Saved BT device (if configured)
        try:
            import json
            import os
            settings_path = os.path.join(os.path.dirname(__file__), "config", "settings.json")
            if os.path.exists(settings_path):
                with open(settings_path) as f:
                    settings = json.load(f)

                sim_config = settings.get("simulator", {})
                obd_config = settings.get("obd", {})

                if sim_config.get("enabled") and sim_config.get("address"):
                    # Simulator mode - connect to TCP simulator
                    sim_addr = sim_config["address"]
                    print(f"[OBD] Auto-connecting to simulator at {sim_addr}...")
                    self._start_obd_connection_async(sim_addr, "Simulator")
                elif obd_config.get("bt_device_mac"):
                    # Real OBD mode - connect to saved Bluetooth device
                    bt_mac = obd_config["bt_device_mac"]
                    bt_name = obd_config.get("bt_device_name", "OBD Device")
                    print(f"[OBD] Auto-connecting to saved BT device: {bt_name} ({bt_mac})...")
                    self.demo_mode = False  # Disable demo mode for real OBD
                    self._start_obd_connection_async(bt_mac, bt_name)
                else:
                    print("[OBD] No OBD device configured - starting in demo mode")
        except Exception as e:
            print(f"[OBD] Could not load OBD config: {e}")

        start_time = time.time()
        last_frame_time = start_time
        last_obd_time = start_time
        obd_interval = 1.0 / obd_rate  # Time between OBD2 updates

        print(f"Starting boost gauge test at {target_fps} FPS target...")
        print(f"Simulating OBD2 data at {obd_rate} Hz (needle will tween between updates)")
        print("Press Ctrl+C to stop and see results")

        while self._running:
            current_time = time.time()
            dt = current_time - last_frame_time
            last_frame_time = current_time

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                    break
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self._running = False
                        break

            # OBD data update:
            # - If OBD connected: data arrives via _obd_data_callback (threaded)
            # - If demo_mode: simulate data here
            # - Otherwise: hold current values
            if current_time - last_obd_time >= obd_interval:
                t = current_time - start_time

                if self.demo_mode and not self.obd_connected:
                    # Demo mode: simulate boost/temp/load animation
                    self.boost_target = self._simulate_boost(t)
                    self.coolant_target = 180 + math.sin(t * 0.5) * 20  # 160-200°F
                    self.engine_load_target = 30 + math.sin(t * 2) * 25 + (20 if self.boost_target > 5 else 0)

                    # Update all simulated values for live preview in settings
                    self.simulated_values['BOOST'] = self.boost_target
                    self.simulated_values['COOLANT_TEMP'] = self.coolant_target
                    self.simulated_values['ENGINE_LOAD'] = self.engine_load_target
                    self.simulated_values['INTAKE_TEMP'] = 70 + math.sin(t * 0.3) * 30  # 40-100°F
                    self.simulated_values['RPM'] = 2000 + math.sin(t * 1.5) * 1500 + (2000 if self.boost_target > 5 else 0)
                    self.simulated_values['THROTTLE_POS'] = max(5, min(100, 15 + self.boost_target * 3))
                    self.simulated_values['OIL_TEMP'] = 200 + math.sin(t * 0.2) * 30
                    self.simulated_values['FUEL_PRESSURE'] = 40 + math.sin(t * 0.8) * 15
                # When OBD connected, data arrives via _obd_data_callback

                last_obd_time = current_time

            # Smoothly tween all gauges toward target
            self._update_value('boost_psi', self.boost_target, dt)
            self._update_value('coolant_temp', self.coolant_target, dt)
            self._update_value('engine_load', self.engine_load_target, dt)

            # Clear screen
            self.screen.fill(self.BLACK)

            # Draw based on 2D grid position
            if self.screen_row == 0:
                # Row 0: Gauge screens (dynamically from gauge_configs)
                if self.screen_col < len(self.gauge_configs):
                    # Draw configured gauge
                    gauge = self.gauge_configs[self.screen_col]
                    self._draw_configured_gauge(gauge)
                elif self.screen_col == len(self.gauge_configs):
                    # Shift light is always last (full-screen peripheral vision indicator)
                    self._draw_shift_light_screen()
            elif self.screen_row == 1:
                # Row 1: Bluetooth screen (only)
                self._draw_bluetooth_screen()
            elif self.screen_row == 2:
                # Row 2: WiFi/Settings/QR screen
                self._draw_qr_settings_screen()
            elif self.screen_row == 3:
                # Row 3: System screen (Brightness/Reboot/Restart)
                self._draw_brightness_screen()

            self._draw_fps()
            self._draw_screen_indicator()

            # Update display
            self._flip()

            # FPS tracking
            self.frame_count += 1
            if time.time() - self.fps_timer >= 1.0:
                self.fps = self.frame_count / (time.time() - self.fps_timer)
                self.frame_count = 0
                self.fps_timer = time.time()
                print(f"  FPS: {self.fps:.1f}")

            # Frame rate limiting
            self._clock.tick(target_fps)

        # Cleanup OBD connection
        if self.obd_connection:
            print("Disconnecting OBD...")
            self.disconnect_obd_socket()

        # Final stats
        total_time = time.time() - start_time
        print(f"\n=== BENCHMARK RESULTS ===")
        print(f"Total runtime: {total_time:.1f}s")
        print(f"Average FPS: {self.fps:.1f}")
        print(f"Target FPS: {target_fps}")

        pygame.quit()

        # Execute pending system action after clean pygame exit
        if self._pending_action == 'reboot':
            print("Executing reboot...")
            os.system("sudo reboot")
        elif self._pending_action == 'shutdown':
            print("Executing shutdown...")
            os.system("sudo shutdown -h now")

        sys.exit(0)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="""
Boost Gauge Animation Test - Optimized for RS7 + OBDLink MX+

RS7 CAN Bus: 500 kbps high-speed CAN
OBDLink MX+ realistic rate: 20-30 Hz for single PID on modern CAN cars
Recommended settings: --fps 30 --obd 25 --smooth 0.25

With OBDLink MX+ at 25Hz, tweening barely needed - data is fast enough!
    """, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--fps', type=int, default=None,
                       help='Target display FPS (default: from settings.json, or 60)')
    parser.add_argument('--obd', type=int, default=25,
                       help='Simulated OBD2 data rate Hz (default: 25, realistic for OBDLink MX+)')
    parser.add_argument('--smooth', type=float, default=None,
                       help='Smoothing factor 0.1-0.3 (default: from settings.json, or 0.15)')
    args = parser.parse_args()

    gauge = BoostGaugeTest()

    # Override smoothing only if specified on command line
    if args.smooth is not None:
        gauge.smoothing = args.smooth

    # Initialize touch at module level BEFORE run() - same pattern as working clock-ytsc.py
    try:
        from hyperpixel2r import Touch
        touch = Touch()

        @touch.on_touch
        def handle_touch(touch_id, x, y, state):
            gauge.handle_touch(x, y, state)

        print("Touch initialized!")
    except Exception as e:
        print(f"Touch init failed: {e}")

    gauge.run(target_fps=args.fps, obd_rate=args.obd)
