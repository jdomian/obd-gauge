#!/bin/bash
# Simple OBD handler for rfcomm watch
# stdin/stdout are connected to the RFCOMM channel

LOG="/tmp/obd_handler.log"
echo "$(date): Connection started" >> $LOG

# Send initial prompt
printf ">"

buffer=""

# Read character by character with timeout
while true; do
    # Read one char with 30 second timeout
    if ! IFS= read -r -t 30 -n 1 char; then
        echo "$(date): Timeout or EOF" >> $LOG
        break
    fi

    # Check for CR or LF
    if [[ "$char" == $'\r' ]] || [[ "$char" == $'\n' ]] || [[ -z "$char" ]]; then
        # Process command
        cmd=$(echo "$buffer" | tr '[:lower:]' '[:upper:]' | tr -d '\r\n ')

        if [[ -n "$cmd" ]]; then
            echo "$(date): CMD: [$cmd]" >> $LOG

            case "$cmd" in
                ATZ*)
                    printf "ELM327 v2.1\r\r>"
                    ;;
                ATE0*)
                    printf "OK\r\r>"
                    ;;
                ATE1*)
                    printf "OK\r\r>"
                    ;;
                ATH0*|ATH1*)
                    printf "OK\r\r>"
                    ;;
                ATSP*)
                    printf "OK\r\r>"
                    ;;
                ATRV*)
                    printf "13.8V\r\r>"
                    ;;
                ATDPN*)
                    printf "A6\r\r>"
                    ;;
                ATL0*|ATL1*)
                    printf "OK\r\r>"
                    ;;
                ATS0*|ATS1*)
                    printf "OK\r\r>"
                    ;;
                ATST*)
                    printf "OK\r\r>"
                    ;;
                ATAT*)
                    printf "OK\r\r>"
                    ;;
                AT@1*)
                    printf "OBD-SIM\r\r>"
                    ;;
                ATI*)
                    printf "ELM327 v2.1\r\r>"
                    ;;
                0100*)
                    printf "41 00 BE 1F B8 13\r\r>"
                    ;;
                0120*)
                    printf "41 20 80 01 00 01\r\r>"
                    ;;
                0105*)
                    printf "41 05 78\r\r>"
                    ;;
                010C*)
                    printf "41 0C 27 10\r\r>"
                    ;;
                010D*)
                    printf "41 0D 3C\r\r>"
                    ;;
                010B*)
                    printf "41 0B 65\r\r>"
                    ;;
                0111*)
                    printf "41 11 40\r\r>"
                    ;;
                AT*)
                    printf "OK\r\r>"
                    ;;
                01*)
                    # Unknown PID - return NO DATA
                    printf "NO DATA\r\r>"
                    ;;
                *)
                    printf "?\r\r>"
                    ;;
            esac
            echo "$(date): Responded" >> $LOG
        else
            # Empty command, just send prompt
            printf "\r>"
        fi
        buffer=""
    else
        buffer="${buffer}${char}"
    fi
done

echo "$(date): Connection ended" >> $LOG
