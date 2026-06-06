"""One-shot VPS patcher: add the console router to main.py + nav entry to
navItems.ts (idempotent), and ensure CONSOLE_* env in .env. Run on the VPS."""
import os
import secrets
from pathlib import Path

ROOT = Path("/home/trader/mt5-bot")


def patch(path: Path, anchor: str, insert: str, before: bool):
    text = path.read_text(encoding="utf-8")
    if insert.strip() in text:
        print(f"  skip (already patched): {path.name}")
        return
    if anchor not in text:
        print(f"  ANCHOR MISSING in {path.name}: {anchor!r}")
        return
    if before:
        text = text.replace(anchor, insert + anchor, 1)
    else:
        text = text.replace(anchor, anchor + insert, 1)
    path.write_text(text, encoding="utf-8")
    print(f"  patched: {path.name}")


main = ROOT / "dashboard/backend/main.py"
patch(main,
      "from api import strategy_lab as strategy_lab_api\n",
      "from api import console as console_api\n",
      before=False)
patch(main,
      "app.include_router(ws.router)",
      'app.include_router(console_api.router, prefix="/api")\n',
      before=True)

nav = ROOT / "dashboard/frontend/src/components/layout/navItems.ts"
patch(nav,
      "      { to: '/logs',     label: 'Logs',        icon: 'logs' },\n",
      "      { to: '/console',  label: 'Claude Console', icon: 'terminal' },\n",
      before=True)

# ── .env: ensure CONSOLE_* (idempotent) ──────────────────────────────────
env = ROOT / ".env"
content = env.read_text(encoding="utf-8") if env.exists() else ""
lines = content.splitlines()
have = {ln.split("=", 1)[0].strip() for ln in lines if "=" in ln and not ln.strip().startswith("#")}

add = []
if "CONSOLE_PASSWORD" not in have:
    pw = secrets.token_urlsafe(18)
    add.append(f"CONSOLE_PASSWORD={pw}")
    print(f"  GENERATED CONSOLE_PASSWORD={pw}")
else:
    print("  CONSOLE_PASSWORD already set (unchanged)")
if "CONSOLE_ALLOWED_IPS" not in have:
    add.append("CONSOLE_ALLOWED_IPS=103.248.204.253")
    print("  set CONSOLE_ALLOWED_IPS=103.248.204.253")
else:
    print("  CONSOLE_ALLOWED_IPS already set (unchanged)")

if add:
    block = "\n# Claude Code Console (browser-driven Claude Code on the VPS)\n" + "\n".join(add) + "\n"
    with env.open("a", encoding="utf-8") as f:
        f.write(block)
    print("  .env updated")
print("DONE")
