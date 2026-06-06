"""One-shot fleet analysis — per-agent health + real trade record from the bridge.
Run on VPS (needs bridge localhost:8090). Read-only."""
import json, time, urllib.request, collections, os
from datetime import datetime, timezone

BASE = "/home/trader/mt5-bot"
SECRET = ""
for ln in open(f"{BASE}/.env"):
    if ln.startswith("MT5_BRIDGE_SECRET="):
        SECRET = ln.split("=", 1)[1].strip()
H = {"X-API-Key": SECRET} if SECRET else {}

AGENTS = {  # magic -> (id, name, strategy)
    20260100: ("mtf_live", "Elon Musk", "Momentum MTF EMA M1/M3/M15"),
    20260600: ("jtcc", "Warren Buffett", "Confluence ICT/SMC A+"),
    20260700: ("iconic", "George Soros", "FX Macro G7 strength 28pr"),
    20260522: ("scalp", "Isaac Newton", "Gold Scalper GS11/07/01/12"),
    20260603: ("gsvp", "Albert Einstein", "Volume-Profile M15"),
    20260800: ("asia_fade", "Masayoshi Son", "Asia JPY range fade"),
    20261300: ("confluence", "Sundar Pichai", "Multi-Strat S13+S19"),
    20260900: ("m3strength", "Mayank Raj", "Strength-Scalp 28pr M3"),
}


def get(path):
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(BASE_URL := "http://localhost:8090" + path, headers=H), timeout=20))
    except Exception as e:
        return {"_err": str(e)}


now = time.time()
acct = get("/account/info")
posr = get("/positions/open")
deals = get("/history/deals?days=90")
orch = json.load(open(f"{BASE}/logs/_orchestrator_state.json"))
orch_by = {s["id"]: s for s in orch.get("services", [])}

pos_by = collections.defaultdict(list)
for p in posr.get("positions", []):
    pos_by[int(p.get("magic", 0))].append(p)

D = deals.get("deals", [])
print(f"ACCOUNT: login {acct.get('login')} {acct.get('server')} bal ${acct.get('balance')} eq ${acct.get('equity')}")
print(f"deals pulled (90d): {len(D)} | open positions: {len(posr.get('positions', []))}\n")


def window(magic, since):
    cl = [x for x in D if int(x.get("magic", 0)) == magic and x.get("entry") == 1 and x.get("time", 0) >= since]
    pnl = sum((x.get("profit", 0) + x.get("swap", 0) + x.get("commission", 0)) for x in cl)
    w = sum(1 for x in cl if (x.get("profit", 0) + x.get("swap", 0) + x.get("commission", 0)) > 0)
    return len(cl), round(pnl, 2), w


all_magics = sorted(set(int(x.get("magic", 0)) for x in D) | set(pos_by) | set(AGENTS))
for m in all_magics:
    if m == 0:
        continue
    idn, name, strat = AGENTS.get(m, ("UNKNOWN", "??", "unmapped magic"))
    svc = orch_by.get(idn, {})
    # per-symbol over 90d
    cl = [x for x in D if int(x.get("magic", 0)) == m and x.get("entry") == 1]
    bysym = collections.defaultdict(lambda: [0, 0.0, 0])
    for x in cl:
        p = x.get("profit", 0) + x.get("swap", 0) + x.get("commission", 0)
        s = x.get("symbol", "?"); bysym[s][0] += 1; bysym[s][1] += p
        if p > 0: bysym[s][2] += 1
    n90, p90, w90 = window(m, now - 90 * 86400)
    n30, p30, w30 = window(m, now - 30 * 86400)
    n7, p7, w7 = window(m, now - 7 * 86400)
    last = max([x.get("time", 0) for x in D if int(x.get("magic", 0)) == m] + [0])
    lasts = datetime.fromtimestamp(last, tz=timezone.utc).strftime("%m-%d %H:%M") if last else "never"
    opn = pos_by.get(m, [])
    opnl = round(sum(p.get("profit", 0) for p in opn), 2)
    wr90 = round(w90 / n90 * 100) if n90 else None
    print(f"=== {name} ({idn}) magic {m} — {strat}")
    print(f"    health: orch={svc.get('status','NOT-IN-ORCH')} pid={svc.get('pid')} restarts={svc.get('restarts')}")
    print(f"    90d: {n90} closes  ${p90:+.2f}  WR {wr90}%   | 30d: {n30}cl ${p30:+.2f}  | 7d: {n7}cl ${p7:+.2f}")
    print(f"    open now: {len(opn)} pos  float ${opnl:+.2f}   | last deal: {lasts}")
    if bysym:
        top = sorted(bysym.items(), key=lambda k: k[1][1])
        for s, v in top:
            print(f"        {s:8s} {v[0]:3d}cl  ${v[1]:+8.2f}  W{v[2]}/{v[0]-v[2]}L")
    print()
