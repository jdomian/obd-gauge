#!/bin/bash
# OBD Simulator Control - Change values via CLI
# Usage: ./sim-ctrl.sh <command> [value]
#
# Commands:
#   rpm <value>      - Set RPM (660-7000)
#   boost <value>    - Set boost PSI (-15 to 25), auto-calculates MAP
#   throttle <value> - Set throttle % (0-100)
#   coolant <value>  - Set coolant temp C (50-110)
#   speed <value>    - Set speed km/h (0-300)
#   wot              - Wide Open Throttle (throttle=100, rpm=6000, boost=20)
#   idle             - Return to idle (throttle=0, rpm=660, vacuum)
#   show             - Show current state

STATE_FILE="/tmp/obd_sim_state.json"

# Initialize state file if missing
if [ ! -f "$STATE_FILE" ]; then
    echo '{"throttle":0,"rpm":660,"map_kpa":38,"coolant_c":75,"speed_kph":0,"intake_temp_c":25,"voltage":14.3,"baro_kpa":99}' > "$STATE_FILE"
fi

case "$1" in
    rpm)
        if [ -z "$2" ]; then echo "Usage: $0 rpm <660-7000>"; exit 1; fi
        jq ".rpm = $2" "$STATE_FILE" > /tmp/state_tmp.json && mv /tmp/state_tmp.json "$STATE_FILE"
        echo "RPM set to $2"
        ;;
    boost)
        if [ -z "$2" ]; then echo "Usage: $0 boost <-15 to 25 PSI>"; exit 1; fi
        # Convert PSI to MAP kPa: MAP = (boost_psi * 6.895) + 99
        MAP_KPA=$(echo "$2 * 6.895 + 99" | bc -l | cut -d. -f1)
        jq ".map_kpa = $MAP_KPA" "$STATE_FILE" > /tmp/state_tmp.json && mv /tmp/state_tmp.json "$STATE_FILE"
        echo "Boost set to $2 PSI (MAP: ${MAP_KPA} kPa)"
        ;;
    throttle)
        if [ -z "$2" ]; then echo "Usage: $0 throttle <0-100>"; exit 1; fi
        jq ".throttle = $2" "$STATE_FILE" > /tmp/state_tmp.json && mv /tmp/state_tmp.json "$STATE_FILE"
        echo "Throttle set to $2%"
        ;;
    coolant)
        if [ -z "$2" ]; then echo "Usage: $0 coolant <50-110 C>"; exit 1; fi
        jq ".coolant_c = $2" "$STATE_FILE" > /tmp/state_tmp.json && mv /tmp/state_tmp.json "$STATE_FILE"
        echo "Coolant temp set to $2°C"
        ;;
    speed)
        if [ -z "$2" ]; then echo "Usage: $0 speed <0-300 km/h>"; exit 1; fi
        jq ".speed_kph = $2" "$STATE_FILE" > /tmp/state_tmp.json && mv /tmp/state_tmp.json "$STATE_FILE"
        echo "Speed set to $2 km/h"
        ;;
    wot|WOT)
        jq '.throttle = 100 | .rpm = 6000 | .map_kpa = 237' "$STATE_FILE" > /tmp/state_tmp.json && mv /tmp/state_tmp.json "$STATE_FILE"
        echo "WOT! Throttle=100%, RPM=6000, Boost=+20 PSI"
        ;;
    idle|IDLE)
        jq '.throttle = 0 | .rpm = 660 | .map_kpa = 38' "$STATE_FILE" > /tmp/state_tmp.json && mv /tmp/state_tmp.json "$STATE_FILE"
        echo "Idle: Throttle=0%, RPM=660, Vacuum=-9 PSI"
        ;;
    show|status)
        echo "=== Simulator State ==="
        cat "$STATE_FILE" | jq .
        # Calculate boost PSI from MAP
        MAP=$(cat "$STATE_FILE" | jq -r '.map_kpa')
        BOOST=$(echo "($MAP - 99) / 6.895" | bc -l | xargs printf "%.1f")
        echo "Boost PSI: $BOOST"
        ;;
    *)
        echo "OBD Simulator Control"
        echo "Usage: $0 <command> [value]"
        echo ""
        echo "Commands:"
        echo "  rpm <660-7000>     Set engine RPM"
        echo "  boost <-15 to 25>  Set boost PSI"
        echo "  throttle <0-100>   Set throttle %"
        echo "  coolant <50-110>   Set coolant temp C"
        echo "  speed <0-300>      Set speed km/h"
        echo "  wot                Wide Open Throttle preset"
        echo "  idle               Return to idle preset"
        echo "  show               Show current state"
        ;;
esac
