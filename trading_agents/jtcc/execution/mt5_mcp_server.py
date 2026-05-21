"""MCP server — exposes MT5 trade actions as Claude Code tools.
Run: python -m trading_agents.jtcc.execution.mt5_mcp_server
"""

from __future__ import annotations

import json
import logging
import sys

log = logging.getLogger("jtcc.mcp_server")


def _respond(request_id: str | None, result: dict) -> None:
    msg = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})
    print(msg, flush=True)


def _error(request_id: str | None, code: int, message: str) -> None:
    msg = json.dumps({"jsonrpc": "2.0", "id": request_id,
                      "error": {"code": code, "message": message}})
    print(msg, flush=True)


TOOLS = [
    {
        "name": "place_trade",
        "description": "Place a trade on MT5 via JTCC. Includes risk validation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "action": {"type": "string", "enum": ["BUY", "SELL"]},
                "sl": {"type": "number"},
                "tp": {"type": "number"},
                "strategy": {"type": "string"},
                "risk_pct": {"type": "number", "default": 1.0},
            },
            "required": ["symbol", "action", "sl", "tp"],
        },
    },
    {
        "name": "close_trade",
        "description": "Close a specific trade by ticket number.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticket": {"type": "integer"}},
            "required": ["ticket"],
        },
    },
    {
        "name": "get_account_info",
        "description": "Get current MT5 account balance, equity, and open positions.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_open_positions",
        "description": "List all open positions on MT5.",
        "inputSchema": {
            "type": "object",
            "properties": {"magic": {"type": "integer"}},
        },
    },
    {
        "name": "get_confluence",
        "description": "Get current JTCC strategy vote confluence for a symbol.",
        "inputSchema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
]


def _handle_tool(name: str, args: dict) -> dict:
    from trading_agents.jtcc.execution import mt5_client as mt5
    from trading_agents.jtcc.execution import risk_manager as risk

    if name == "place_trade":
        ok, reason = risk.can_trade(args["symbol"])
        if not ok:
            return {"success": False, "blocked": True, "reason": reason}
        acc = risk.get_account()
        entry = (args.get("sl", 0) + args.get("tp", 0)) / 2  # approximate
        lot, info = risk.calculate_lot(args["symbol"], entry, args["sl"],
                                       args.get("risk_pct", 1.0))
        if lot <= 0:
            return {"success": False, "error": info}
        return mt5.place_trade(
            symbol=args["symbol"], action=args["action"], lot=lot,
            sl=args["sl"], tp=args["tp"], strategy=args.get("strategy", "MCP"),
        )

    if name == "close_trade":
        return mt5.close_trade(args["ticket"])

    if name == "get_account_info":
        return mt5.get_account_info()

    if name == "get_open_positions":
        return {"positions": mt5.get_open_positions(args.get("magic"))}

    if name == "get_confluence":
        # Read latest signal state from shared state file if available
        import json
        from pathlib import Path
        state_file = Path(__file__).parent.parent.parent.parent / "logs" / "jtcc" / "_jtcc_state.json"
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            symbol = args.get("symbol", "")
            return data.get("confluence", {}).get(symbol, {"message": "No data yet"})
        except Exception:
            return {"message": "JTCC state not available — start main.py first"}

    return {"error": f"Unknown tool: {name}"}


def serve() -> None:
    """Minimal JSON-RPC 2.0 MCP server over stdin/stdout."""
    logging.basicConfig(level=logging.WARNING)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id = req.get("id")
        method = req.get("method", "")

        if method == "initialize":
            _respond(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jtcc-mt5", "version": "1.0.0"},
            })

        elif method == "tools/list":
            _respond(req_id, {"tools": TOOLS})

        elif method == "tools/call":
            params = req.get("params", {})
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            try:
                result = _handle_tool(tool_name, tool_args)
                _respond(req_id, {"content": [{"type": "text", "text": json.dumps(result)}]})
            except Exception as e:
                _error(req_id, -32603, str(e))

        else:
            _error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    serve()
