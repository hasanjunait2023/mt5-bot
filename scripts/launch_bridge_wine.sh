#!/bin/bash
# Launch mt5_bridge.api_server under wine-staging Python so the (Windows-only)
# MetaTrader5 PyPI package can import. Native Linux python cannot.
#
# Requires (one-time, already installed on this VPS):
#   - wine-staging 11+   (/opt/wine-staging/bin/wine)
#   - WINEPREFIX with Windows Python 3.11 (/home/trader/.wine/drive_c/py311/python.exe)
#   - In that wine python: pip install MetaTrader5 fastapi uvicorn pydantic python-dotenv
#   - MT5 terminal running + logged in inside the same WINEPREFIX

set -e

REPO="${REPO_ROOT:-/home/trader/mt5-bot}"
WINE_BIN="${WINE_BIN:-/opt/wine-staging/bin/wine}"
WINE_PY="${WINE_PY:-/home/trader/.wine/drive_c/py311/python.exe}"
PORT="${BRIDGE_PORT:-8090}"

export WINEPREFIX="${WINEPREFIX:-/home/trader/.wine}"
export DISPLAY="${DISPLAY:-:10}"
# Wine python sees the repo via the Z: drive mapping of "/" — pass that as
# PYTHONPATH so `import mt5_bridge` works regardless of CWD. -m would still need
# this; the script form below also benefits when api_server adds sibling imports.
export PYTHONPATH='Z:\home\trader\mt5-bot'
export WINEDEBUG="${WINEDEBUG:-fixme-all,err-toolbar}"

cd "$REPO"
# Use script-form (not -m) so wine python adds the script's directory's parent
# to sys.path automatically — no module-resolution pain.
exec "$WINE_BIN" "$WINE_PY" mt5_bridge/api_server.py --port "$PORT"
