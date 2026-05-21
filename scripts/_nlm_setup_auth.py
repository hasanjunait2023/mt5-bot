"""One-shot driver: speak MCP JSON-RPC to notebooklm-mcp and call setup_auth.

setup_auth returns immediately after spawning a visible Chrome window for
Google login. We send three messages then exit; the spawned Chrome stays
open for the user to complete login. Profile cookies persist to disk so
future MCP sessions (Claude Code / Codex) start authed.
"""

import json
import os
import subprocess
import sys
import threading
import time

CMD = ["cmd", "/c", "npx", "-y", "notebooklm-mcp@latest"]
ENV = {**os.environ, "NOTEBOOKLM_PROFILE": "standard"}


def writeln(p, obj):
    line = json.dumps(obj) + "\n"
    p.stdin.write(line.encode("utf-8"))
    p.stdin.flush()


def main():
    p = subprocess.Popen(
        CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=ENV, bufsize=0,
    )

    # 1. initialize
    writeln(p, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "setup-auth-driver", "version": "1.0"},
        },
    })

    init_resp = None
    deadline = time.time() + 60
    while time.time() < deadline:
        line = p.stdout.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("id") == 1:
            init_resp = obj
            break
    if not init_resp:
        print("ERROR: no initialize response within 60s", file=sys.stderr)
        p.terminate()
        sys.exit(1)
    print("initialized ok")

    # 2. initialized notification
    writeln(p, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    # 3. call setup_auth
    writeln(p, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "setup_auth", "arguments": {"show_browser": True}},
    })

    # read until id:2 response (setup_auth returns immediately per README)
    tool_resp = None
    deadline = time.time() + 90
    while time.time() < deadline:
        line = p.stdout.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("id") == 2:
            tool_resp = obj
            break

    if tool_resp:
        result = tool_resp.get("result", {})
        # MCP tool result format: { content: [{ type: "text", text: ... }] }
        for block in result.get("content", []):
            if block.get("type") == "text":
                print(block.get("text", ""))
        if tool_resp.get("error"):
            print("ERROR:", tool_resp["error"])
    else:
        print("ERROR: no setup_auth response within 90s", file=sys.stderr)

    # Server can exit now — Chrome window is owned by Patchright, lives independently.
    try:
        p.terminate()
    except Exception:
        pass


if __name__ == "__main__":
    main()
