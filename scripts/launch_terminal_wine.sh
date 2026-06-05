#!/bin/bash
# Launch the MT5 terminal under wine-staging, supervised by the orchestrator.
# After reboot: starts Xvfb at :10, resets the wineserver so it binds to the
# correct display, then launches terminal64.exe.
# Stays alive while terminal is running (orchestrator process-health check).

WINE_BIN="${WINE_BIN:-/opt/wine-staging/bin/wine}"
MT5_EXE="${MT5_EXE:-/home/trader/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe}"
WINESRV="${WINE_BIN%/wine}/wineserver"

export WINEPREFIX="${WINEPREFIX:-/home/trader/.wine}"
export DISPLAY="${DISPLAY:-:10}"
export WINEDEBUG="${WINEDEBUG:-fixme-all,err-toolbar}"

# -- 1. Ensure virtual display :10 exists ------------------------------------
if ! DISPLAY=:10 xdpyinfo >/dev/null 2>&1; then
    echo "Starting Xvfb at :10..."
    Xvfb :10 -screen 0 1920x1080x24 +extension GLX +render -noreset &
    sleep 4
fi

# -- 2. Kill existing wineserver so fresh one starts with DISPLAY=:10 --------
# The boot-time wineserver has no DISPLAY and blocks X11 driver from loading.
pkill -f "terminal64.exe" 2>/dev/null || true
"$WINESRV" -k 2>/dev/null || true
sleep 3

# -- 3. Launch terminal (wine preloader exits after handoff - don't use exec) -
echo "Launching terminal64.exe with DISPLAY=$DISPLAY..."
"$WINE_BIN" "$MT5_EXE" /portable &

# -- 4. Wait for terminal64.exe to appear in process table (up to 90s) -------
waited=0
while [ $waited -lt 90 ] && ! pgrep -f "terminal64.exe" >/dev/null 2>&1; do
    sleep 3
    waited=$((waited + 3))
done

if ! pgrep -f "terminal64.exe" >/dev/null 2>&1; then
    echo "terminal64.exe never appeared -- aborting"
    exit 1
fi

echo "terminal64.exe running -- watching..."

# -- 5. Stay alive while terminal is running ---------------------------------
while pgrep -f "terminal64.exe" >/dev/null 2>&1; do
    sleep 5
done

echo "terminal64.exe exited -- service exiting for restart"
