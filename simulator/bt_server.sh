#!/bin/bash
#
# Bluetooth SPP Server for OBD Simulator
#
# Sets up claude-zero as a Bluetooth SPP server that emulates
# an OBDLink MX+ adapter. The obd-gauge device can connect to
# this instead of a real OBD adapter for testing.
#
# Usage:
#     ./bt_server.sh start     # Start Bluetooth SPP server
#     ./bt_server.sh stop      # Stop server and cleanup
#     ./bt_server.sh status    # Check if running
#     ./bt_server.sh name      # Set device name only
#
# Requirements:
#     - bluetooth service running with -C flag (compat mode)
#     - bluez-utils (sdptool, rfcomm)
#     - Python 3 with simulator.py in same directory
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMULATOR="$SCRIPT_DIR/simulator.py"
DEVICE_NAME="OBDLink MX+ (Sim)"
RFCOMM_CHANNEL=1
PID_FILE="/tmp/obd_sim_bt.pid"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_bluetooth_compat() {
    # Check if bluetooth is running in compatibility mode
    if systemctl is-active --quiet bluetooth; then
        if systemctl cat bluetooth | grep -q '\-C'; then
            log_info "Bluetooth service running with compatibility mode"
            return 0
        else
            log_warn "Bluetooth service may not have compatibility mode (-C flag)"
            log_warn "Check /etc/systemd/system/bluetooth.service.d/override.conf"
        fi
    else
        log_error "Bluetooth service not running!"
        return 1
    fi
}

set_device_name() {
    log_info "Setting Bluetooth device name to: $DEVICE_NAME"

    # Method 1: hciconfig (older)
    if command -v hciconfig &> /dev/null; then
        sudo hciconfig hci0 name "$DEVICE_NAME" 2>/dev/null || true
    fi

    # Method 2: bluetoothctl (newer)
    if command -v bluetoothctl &> /dev/null; then
        echo -e "system-alias $DEVICE_NAME\nquit" | bluetoothctl 2>/dev/null || true
    fi

    # Method 3: Write to machine-info
    echo "PRETTY_HOSTNAME=$DEVICE_NAME" | sudo tee /etc/machine-info > /dev/null 2>&1 || true

    log_info "Device name set. May require Bluetooth restart to take effect."
}

make_discoverable() {
    log_info "Making device discoverable and pairable..."

    bluetoothctl << EOF
power on
discoverable on
pairable on
agent on
default-agent
EOF

    log_info "Device is now discoverable"
}

register_spp() {
    log_info "Registering SPP (Serial Port Profile) on channel $RFCOMM_CHANNEL..."

    # Add Serial Port service record
    # This makes the device show up as a serial port when scanned
    sudo sdptool add --channel=$RFCOMM_CHANNEL SP 2>/dev/null || {
        log_warn "Could not add SPP service record (sdptool may need compat mode)"
    }
}

start_server() {
    log_info "Starting OBD Simulator Bluetooth Server..."

    # Check prerequisites
    check_bluetooth_compat || exit 1

    if [ ! -f "$SIMULATOR" ]; then
        log_error "Simulator not found at: $SIMULATOR"
        exit 1
    fi

    # Check if already running
    if [ -f "$PID_FILE" ]; then
        if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            log_warn "Server already running (PID: $(cat $PID_FILE))"
            exit 0
        fi
        rm -f "$PID_FILE"
    fi

    # Setup Bluetooth
    set_device_name
    make_discoverable
    register_spp

    log_info "Starting rfcomm watch on channel $RFCOMM_CHANNEL..."
    log_info "Waiting for connections..."

    # Use rfcomm watch to handle incoming connections
    # Each connection pipes to simulator.py --stdio
    #
    # rfcomm watch creates /dev/rfcomm0 when a device connects,
    # then runs the specified command with stdio attached to that device

    sudo rfcomm watch hci0 $RFCOMM_CHANNEL "$SIMULATOR --stdio" &
    RFCOMM_PID=$!

    echo $RFCOMM_PID > "$PID_FILE"

    log_info "Server started (PID: $RFCOMM_PID)"
    log_info "Connect from obd-gauge to '$DEVICE_NAME'"

    # Wait for interrupt
    echo ""
    echo "Press Ctrl+C to stop server..."

    trap cleanup INT TERM
    wait $RFCOMM_PID
}

start_server_tcp() {
    # Alternative: TCP server mode (for testing without Bluetooth)
    log_info "Starting OBD Simulator in TCP mode on port 35000..."

    if [ ! -f "$SIMULATOR" ]; then
        log_error "Simulator not found at: $SIMULATOR"
        exit 1
    fi

    python3 "$SIMULATOR" --tcp --port 35000 &
    SIM_PID=$!
    echo $SIM_PID > "$PID_FILE"

    log_info "TCP server started (PID: $SIM_PID)"
    log_info "Connect with: nc $(hostname -I | awk '{print $1}') 35000"

    trap cleanup INT TERM
    wait $SIM_PID
}

stop_server() {
    log_info "Stopping OBD Simulator Server..."

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 $PID 2>/dev/null; then
            sudo kill $PID 2>/dev/null || true
            log_info "Stopped server (PID: $PID)"
        fi
        rm -f "$PID_FILE"
    fi

    # Clean up any rfcomm processes
    sudo pkill -f "rfcomm watch" 2>/dev/null || true
    sudo pkill -f "simulator.py" 2>/dev/null || true

    # Release rfcomm device
    sudo rfcomm release all 2>/dev/null || true

    log_info "Server stopped"
}

cleanup() {
    echo ""
    stop_server
    exit 0
}

show_status() {
    echo "=== OBD Simulator Status ==="
    echo ""

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 $PID 2>/dev/null; then
            echo -e "Server: ${GREEN}RUNNING${NC} (PID: $PID)"
        else
            echo -e "Server: ${RED}STOPPED${NC} (stale PID file)"
        fi
    else
        echo -e "Server: ${YELLOW}NOT STARTED${NC}"
    fi

    echo ""
    echo "Bluetooth Status:"
    bluetoothctl show 2>/dev/null | grep -E "(Name|Powered|Discoverable|Pairable)" || echo "  Unable to query"

    echo ""
    echo "RFCOMM Devices:"
    rfcomm -a 2>/dev/null || echo "  None"

    echo ""
    echo "SPP Service Records:"
    sdptool browse local 2>/dev/null | grep -A5 "Serial Port" || echo "  None registered"
}

# Main
case "${1:-start}" in
    start)
        start_server
        ;;
    tcp)
        start_server_tcp
        ;;
    stop)
        stop_server
        ;;
    status)
        show_status
        ;;
    name)
        set_device_name
        ;;
    restart)
        stop_server
        sleep 1
        start_server
        ;;
    *)
        echo "Usage: $0 {start|stop|status|restart|tcp|name}"
        echo ""
        echo "  start   - Start Bluetooth SPP server"
        echo "  tcp     - Start TCP server (port 35000) for testing"
        echo "  stop    - Stop server"
        echo "  status  - Show server status"
        echo "  restart - Restart server"
        echo "  name    - Set Bluetooth device name only"
        exit 1
        ;;
esac
