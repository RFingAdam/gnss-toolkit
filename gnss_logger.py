#!/usr/bin/env python3
"""
gnss_logger.py

Robust GNSS NMEA logger for Telit modules:

 - Opens serial port at 115200 baud
 - Sends GNSS reset (cold/warm/hot), powers on GNSS, enables NMEA
 - Waits for OK after each AT command, prints responses
 - Logs only the NMEA sentences (plus a “# START HHMMSS” header) to file
 - Prints everything to console
 - Detects and prints first valid GGA fix
 - Runs for a configurable duration (default 15 minutes) then exits
"""

import sys
import time
import argparse
import serial

# Mapping of start modes to AT$GPSR values
RESET_MAP = {
    'cold':  '1',
    'warm':  '2',
    'hot':   '3',
}

def send_at(ser, cmd, timeout=5.0):
    """
    Send an AT command (no trailing CR/LF in `cmd`), wait for "OK" or "ERROR".
    Prints each line received. Returns True if OK, False otherwise.
    """
    full = (cmd + "\r").encode()
    ser.write(full)
    print(f">>> {cmd}")
    deadline = time.time() + timeout
    ok = False
    while time.time() < deadline:
        line = ser.readline().decode('ascii', errors='ignore').strip()
        if not line:
            continue
        print(line)
        if line == "OK":
            ok = True
            break
        if line == "ERROR":
            break
    if not ok:
        print(f"⚠️  No OK for '{cmd}' (timeout/error)")
    return ok

def main():
    p = argparse.ArgumentParser(description="Telit GNSS NMEA Logger")
    p.add_argument('port', help='Serial port (e.g. COM3)')
    p.add_argument('--mode', choices=RESET_MAP.keys(), default='cold',
                   help='GNSS start mode (cold, warm, hot)')
    p.add_argument('--duration', type=int, default=900,
                   help='Logging duration in seconds (default 900)')
    p.add_argument('--output', default='nmea_capture.txt',
                   help='Output file for NMEA log (default nmea_capture.txt)')
    args = p.parse_args()

    # Open serial port
    try:
        ser = serial.Serial(args.port, 115200, timeout=1)
    except Exception as e:
        print(f"⛔ Failed to open {args.port}: {e}")
        sys.exit(1)
    print(f"✔ Opened {args.port} @ 115200 baud")

    # Flush any pending data
    ser.reset_input_buffer()

    # 1) GNSS reset
    reset_val = RESET_MAP[args.mode]
    if not send_at(ser, f"AT$GPSR={reset_val}"):
        print("Continuing despite reset issue...")

    # 2) Power on GNSS and timestamp
    start_utc = time.strftime("%H%M%S", time.gmtime())
    if send_at(ser, "AT$GPSP=1"):
        print(f"⏱ GNSS powered on @ {start_utc} UTC")
    else:
        print("⚠️ Power-on command failed; continuing anyway")

    # 3) Enable NMEA output: GGA, GLL, RMC, GSA, GSV, VTG
    if not send_at(ser, "AT$GPSNMUN=3,1,1,1,1,1,1"):
        print("⚠️ NMEA enable failed; output may be missing")

    # 4) Open log file and write START header
    with open(args.output, 'w') as logf:
        logf.write(f"# START {start_utc}\n")

        first_fix_logged = False
        stop_time = time.time() + args.duration

        # 5) Read loop
        while time.time() < stop_time:
            raw = ser.readline()
            if not raw:
                continue
            try:
                line = raw.decode('ascii', errors='ignore').strip()
            except:
                continue

            # Print every line to console
            print(line)

            # Log only NMEA sentences (lines starting with '$')
            if line.startswith('$'):
                logf.write(line + "\n")

                # Detect first valid GGA fix
                if (not first_fix_logged) and line.startswith(("$GPGGA", "$GNGGA", "$GAGGA", "$GNGNS")):
                    fields = line.split(',')
                    if len(fields) >= 7 and fields[6].isdigit() and int(fields[6]) > 0:
                        t = fields[1].split('.')[0]
                        print(f"🎯 FIRST FIX @ {t} (quality={fields[6]})")
                        first_fix_logged = True

    print(f"✅ Done logging NMEA to {args.output}")
    print("Test concluded.")

if __name__ == "__main__":
    main()
