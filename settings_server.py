"""
Settings Web Server for OBD-Gauge

Provides a mobile-friendly web interface for configuring gauges.
Runs on-demand when user accesses the QR settings screen.

Endpoints:
    GET  /           - Settings webpage
    GET  /api/config - Current configuration
    POST /api/config - Save configuration
    GET  /api/pids   - Available PIDs
    GET  /api/styles - Available dial/needle styles
"""

import json
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs
from conversions import CONVERSION_NAMES

# Server configuration
HOST = "0.0.0.0"
PORT = 8080
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config", "settings.json")

# Available PIDs for selection
AVAILABLE_PIDS = [
    {"id": "BOOST", "name": "Boost Pressure", "unit": "PSI", "min": -15, "max": 25},
    {"id": "COOLANT_TEMP", "name": "Coolant Temp", "unit": "°F", "min": 100, "max": 260},
    {"id": "ENGINE_LOAD", "name": "Engine Load", "unit": "%", "min": 0, "max": 100},
    {"id": "INTAKE_TEMP", "name": "Intake Air Temp", "unit": "°F", "min": 0, "max": 200},
    {"id": "RPM", "name": "Engine RPM", "unit": "RPM", "min": 0, "max": 8000},
    {"id": "THROTTLE_POS", "name": "Throttle Position", "unit": "%", "min": 0, "max": 100},
    {"id": "OIL_TEMP", "name": "Oil Temperature", "unit": "°F", "min": 100, "max": 300},
    {"id": "FUEL_PRESSURE", "name": "Fuel Pressure", "unit": "PSI", "min": 0, "max": 100},
    {"id": "MAF", "name": "Mass Air Flow", "unit": "g/s", "min": 0, "max": 500},
    {"id": "TIMING_ADVANCE", "name": "Timing Advance", "unit": "°", "min": -10, "max": 50},
    {"id": "VOLTAGE", "name": "Battery Voltage", "unit": "V", "min": 10, "max": 16},
]

# Available styles
DIAL_STYLES = [
    {"id": "audi3", "name": "Audi"},
    {"id": "audi", "name": "Audi Classic"},
    {"id": "audi4", "name": "Audi Sport"},
    {"id": "bmw", "name": "BMW"},
    {"id": "skoda", "name": "Skoda"},
    {"id": "dark", "name": "Dark"},
    {"id": "minimal", "name": "Minimal"},
    {"id": "empty", "name": "Empty"},
]

NEEDLE_STYLES = [
    {"id": "audi3", "name": "Audi"},
    {"id": "audi4", "name": "Audi Sport"},
    {"id": "bmw", "name": "BMW"},
    {"id": "skoda", "name": "Skoda"},
    {"id": "dark", "name": "Dark"},
    {"id": "default", "name": "Default"},
]


def load_config() -> dict:
    """Load configuration from file."""
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return get_default_config()


def save_config(config: dict) -> bool:
    """Save configuration to file."""
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Failed to save config: {e}")
        return False


def get_default_config() -> dict:
    """Get default configuration."""
    return {
        "gauges": [
            {
                "position": 0,
                "pid": "BOOST",
                "label": "BOOST",
                "needle": "audi3",
                "conversion": "none",
                "min": -15,
                "max": 25
            },
            {
                "position": 1,
                "pid": "COOLANT_TEMP",
                "label": "COOLANT",
                "needle": "audi3",
                "conversion": "c_to_f",
                "min": 100,
                "max": 260
            },
            {
                "position": 2,
                "pid": "ENGINE_LOAD",
                "label": "LOAD",
                "needle": "audi3",
                "conversion": "none",
                "min": 0,
                "max": 100
            }
        ],
        "display": {
            "fps": 30,
            "smoothing": 0.25,
            "dial_background": "audi3",
            "demo_mode": True
        },
        "obd": {
            "rate_hz": 25,
            "bt_device_mac": "",
            "bt_device_name": ""
        }
    }


class SettingsHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for settings API."""

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/" or self.path == "/index.html":
            self.send_settings_page()
        elif self.path == "/api/config":
            self.send_json(load_config())
        elif self.path == "/api/pids":
            self.send_json(AVAILABLE_PIDS)
        elif self.path == "/api/styles":
            self.send_json({
                "dials": DIAL_STYLES,
                "needles": NEEDLE_STYLES,
                "conversions": [{"id": k, "name": v} for k, v in CONVERSION_NAMES.items()]
            })
        else:
            self.send_error(404)

    def do_POST(self):
        """Handle POST requests."""
        if self.path == "/api/config":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")

            try:
                new_config = json.loads(body)
                if save_config(new_config):
                    self.send_json({"success": True})
                else:
                    self.send_json({"success": False, "error": "Failed to save"}, 500)
            except json.JSONDecodeError:
                self.send_json({"success": False, "error": "Invalid JSON"}, 400)
        else:
            self.send_error(404)

    def send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def send_settings_page(self):
        """Send the settings HTML page."""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(SETTINGS_HTML.encode("utf-8"))

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


# Embedded HTML for settings page (mobile-friendly)
SETTINGS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>OBD-Gauge Settings</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 16px;
            max-width: 600px;
            margin: 0 auto;
        }
        h1 { text-align: center; margin-bottom: 20px; color: #fff; font-size: 24px; }
        h2 { font-size: 18px; margin: 20px 0 10px; color: #ffd700; border-bottom: 1px solid #333; padding-bottom: 5px; }
        .section { background: #252540; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
        .gauge-section { border-left: 4px solid #ffd700; }
        label { display: block; margin-bottom: 4px; font-size: 14px; color: #aaa; }
        select, input[type="text"], input[type="number"] {
            width: 100%; padding: 12px; margin-bottom: 12px;
            border: 1px solid #444; border-radius: 8px;
            background: #1a1a2e; color: #fff; font-size: 16px;
        }
        select:focus, input:focus { outline: none; border-color: #ffd700; }
        .row { display: flex; gap: 12px; }
        .row > * { flex: 1; }
        .slider-container { margin-bottom: 12px; }
        input[type="range"] { width: 100%; margin-top: 8px; }
        .slider-value { text-align: right; font-size: 14px; color: #ffd700; }
        button {
            width: 100%; padding: 16px; margin-top: 20px;
            background: #ffd700; color: #1a1a2e;
            border: none; border-radius: 12px;
            font-size: 18px; font-weight: bold; cursor: pointer;
        }
        button:active { background: #e6c200; }
        .status { text-align: center; padding: 10px; margin-top: 10px; border-radius: 8px; }
        .status.success { background: #1a4d1a; color: #4caf50; }
        .status.error { background: #4d1a1a; color: #f44336; }
        .loading { text-align: center; padding: 40px; color: #888; }
        /* Toggle switch */
        .switch { position: relative; display: inline-block; width: 50px; height: 28px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider-toggle {
            position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
            background-color: #444; transition: .3s; border-radius: 28px;
        }
        .slider-toggle:before {
            position: absolute; content: ""; height: 20px; width: 20px; left: 4px; bottom: 4px;
            background-color: white; transition: .3s; border-radius: 50%;
        }
        input:checked + .slider-toggle { background-color: #4caf50; }
        input:checked + .slider-toggle:before { transform: translateX(22px); }
    </style>
</head>
<body>
    <h1>🏎️ OBD-Gauge Settings</h1>
    <div id="app"><div class="loading">Loading...</div></div>

    <script>
        let config = null;
        let styles = null;
        let pids = null;

        async function loadData() {
            try {
                const [configRes, stylesRes, pidsRes] = await Promise.all([
                    fetch('/api/config'),
                    fetch('/api/styles'),
                    fetch('/api/pids')
                ]);
                config = await configRes.json();
                styles = await stylesRes.json();
                pids = await pidsRes.json();
                render();
            } catch (e) {
                document.getElementById('app').innerHTML = '<div class="status error">Failed to load settings</div>';
            }
        }

        function render() {
            const app = document.getElementById('app');
            app.innerHTML = `
                <div class="section">
                    <h2>🎨 Global Style</h2>
                    <label>Dial Background</label>
                    <select id="dial_bg" onchange="updateConfig()">
                        ${styles.dials.map(s => `<option value="${s.id}" ${config.display.dial_background === s.id ? 'selected' : ''}>${s.name}</option>`).join('')}
                    </select>
                </div>

                ${config.gauges.map((g, i) => `
                <div class="section gauge-section">
                    <h2>Gauge ${i + 1}</h2>
                    <label>PID</label>
                    <select id="pid_${i}" onchange="updateGauge(${i})">
                        ${pids.map(p => `<option value="${p.id}" ${g.pid === p.id ? 'selected' : ''}>${p.name}</option>`).join('')}
                    </select>
                    <label>Label</label>
                    <input type="text" id="label_${i}" value="${g.label}" onchange="updateGauge(${i})">
                    <div class="row">
                        <div>
                            <label>Needle Style</label>
                            <select id="needle_${i}" onchange="updateGauge(${i})">
                                ${styles.needles.map(s => `<option value="${s.id}" ${g.needle === s.id ? 'selected' : ''}>${s.name}</option>`).join('')}
                            </select>
                        </div>
                        <div>
                            <label>Conversion</label>
                            <select id="conv_${i}" onchange="updateGauge(${i})">
                                ${styles.conversions.map(c => `<option value="${c.id}" ${g.conversion === c.id ? 'selected' : ''}>${c.name}</option>`).join('')}
                            </select>
                        </div>
                    </div>
                    <div class="row">
                        <div>
                            <label>Min Value</label>
                            <input type="number" id="min_${i}" value="${g.min}" onchange="updateGauge(${i})">
                        </div>
                        <div>
                            <label>Max Value</label>
                            <input type="number" id="max_${i}" value="${g.max}" onchange="updateGauge(${i})">
                        </div>
                    </div>
                </div>
                `).join('')}

                <div class="section">
                    <h2>⚙️ Performance</h2>
                    <div class="row">
                        <div>
                            <label>Display FPS</label>
                            <select id="fps" onchange="updateConfig()">
                                ${[15, 30, 60].map(f => `<option value="${f}" ${config.display.fps === f ? 'selected' : ''}>${f} FPS</option>`).join('')}
                            </select>
                        </div>
                        <div>
                            <label>OBD Rate</label>
                            <select id="obd_rate" onchange="updateConfig()">
                                ${[10, 15, 20, 25, 30].map(r => `<option value="${r}" ${config.obd.rate_hz === r ? 'selected' : ''}>${r} Hz</option>`).join('')}
                            </select>
                        </div>
                    </div>
                    <div class="slider-container">
                        <label>Needle Smoothing</label>
                        <input type="range" id="smoothing" min="0.1" max="0.5" step="0.05" value="${config.display.smoothing}" onchange="updateConfig()">
                        <div class="slider-value" id="smoothing_val">${config.display.smoothing}</div>
                    </div>
                </div>

                <div class="section">
                    <h2>🎬 Demo Mode</h2>
                    <div class="row" style="align-items: center;">
                        <div style="flex: 2;">
                            <label style="margin-bottom: 0;">Needle Sweep Test</label>
                            <div style="font-size: 12px; color: #888;">Animate gauges when OBD not connected</div>
                        </div>
                        <div style="flex: 1; text-align: right;">
                            <label class="switch">
                                <input type="checkbox" id="demo_mode" ${config.display.demo_mode ? 'checked' : ''} onchange="updateConfig()">
                                <span class="slider-toggle"></span>
                            </label>
                        </div>
                    </div>
                </div>

                <button onclick="saveConfig()">💾 Save Settings</button>
                <div id="status"></div>
            `;

            document.getElementById('smoothing').oninput = function() {
                document.getElementById('smoothing_val').textContent = this.value;
            };
        }

        function updateGauge(i) {
            config.gauges[i].pid = document.getElementById(`pid_${i}`).value;
            config.gauges[i].label = document.getElementById(`label_${i}`).value;
            config.gauges[i].needle = document.getElementById(`needle_${i}`).value;
            config.gauges[i].conversion = document.getElementById(`conv_${i}`).value;
            config.gauges[i].min = parseInt(document.getElementById(`min_${i}`).value);
            config.gauges[i].max = parseInt(document.getElementById(`max_${i}`).value);
        }

        function updateConfig() {
            config.display.dial_background = document.getElementById('dial_bg').value;
            config.display.fps = parseInt(document.getElementById('fps').value);
            config.display.smoothing = parseFloat(document.getElementById('smoothing').value);
            config.display.demo_mode = document.getElementById('demo_mode').checked;
            config.obd.rate_hz = parseInt(document.getElementById('obd_rate').value);
        }

        async function saveConfig() {
            updateConfig();
            config.gauges.forEach((_, i) => updateGauge(i));

            const status = document.getElementById('status');
            try {
                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(config)
                });
                const data = await res.json();
                if (data.success) {
                    status.className = 'status success';
                    status.textContent = '✓ Settings saved! Changes will apply on next gauge refresh.';
                } else {
                    throw new Error(data.error);
                }
            } catch (e) {
                status.className = 'status error';
                status.textContent = '✗ Failed to save: ' + e.message;
            }
        }

        loadData();
    </script>
</body>
</html>
"""


# Server instance (for controlling from main app)
_server = None
_server_thread = None


def start_server():
    """Start the settings web server in a background thread."""
    global _server, _server_thread

    if _server is not None:
        print("Settings server already running")
        return

    try:
        _server = HTTPServer((HOST, PORT), SettingsHandler)
        _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
        _server_thread.start()
        print(f"Settings server started at http://{HOST}:{PORT}")
        print(f"Server socket: {_server.server_address}")
    except Exception as e:
        print(f"Failed to start settings server: {e}")
        _server = None


def stop_server():
    """Stop the settings web server."""
    global _server, _server_thread

    if _server is None:
        return

    _server.shutdown()
    _server = None
    _server_thread = None
    print("Settings server stopped")


def is_server_running() -> bool:
    """Check if server is running."""
    return _server is not None


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Test mode - run server standalone
        print(f"Starting settings server at http://localhost:{PORT}")
        print("Press Ctrl+C to stop")
        server = HTTPServer((HOST, PORT), SettingsHandler)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping...")
    else:
        print("Usage: python settings_server.py test")
