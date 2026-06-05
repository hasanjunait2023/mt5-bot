#!/bin/bash
# Launch the MT5 terminal under wine-staging so it stays supervised by the
# orchestrator. If the terminal dies (crash, OOM, etc.) the orchestrator
# restarts this script and the terminal comes back automatically.
#
# The bridge depends_on this service so it won't start until the terminal is
# alive.  Give the terminal ~90s grace after start before the bridge tries.

set -e

WINE_BIN="${WINE_BIN:-/opt/wine-staging/bin/wine}"
MT5_EXE="${MT5_EXE:-/home/trader/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe}"

export WINEPREFIX="${WINEPREFIX:-/home/trader/.wine}"
export DISPLAY="${DISPLAY:-:10}"
export WINEDEBUG="${WINEDEBUG:-fixme-all,err-toolbar}"

# Kill any stale terminal process before relaunching to avoid duplicate windows.
pkill -f "terminal64.exe" 2>/dev/null || true
sleep 3

exec "$WINE_BIN" "$MT5_EXE" /portable
