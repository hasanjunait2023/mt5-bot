# Urban Forex — Iconic Trader Program: Final Strategy Spec & Build Plan

Source: NotebookLM notebook `4898da73-2ca1-486d-83e3-071343953ae1` (47 sources, Navin Prithyani).
Raw extraction: `urbanforex_iconic_research.md`. Date: 2026-05-21.
> Knowledge is AI-extracted from the course (Gemini/NotebookLM). Trade logic is the course's; engineering judgment and verdicts are mine.

---

## PART A — Complete Mechanical Spec (now fully specified)

**Core model:** Trade *with* institutions ("Big Boys"). They can't fill huge orders at once, so they trap retail liquidity (stop-hunts, fake breakouts) inside ranges ("money spots") and resume the real trend. We detect the accumulation and enter on their side.

### A1. Timeframe framework — "Two-Timeframe Rule"
Never skip more than one TF between analysis and entry.
- **Bias / correlation / fundamentals:** D1
- **Setup (Set 1/Set 2):** 4H or 60m or 15m
- **Entry timing:** the next TF down — 4H→60m, 60m→15m, 15m→3m ("cheese trade")
- **"60-minute anticipation trade" = 60/15:** setup on 60m, entry on 15m. Develops over hours→days; needs a Purpose (news/session) to travel its 50–100 pip target.

### A2. The setup — Set 1 / Set 2 (downtrend example)
1. **Set 1:** pullback fails to make a new low (trend pullback fails) → price is not cheap enough for Big Boys.
2. **Set 2 / money spot:** Big Boys push price *above* Set 1 to get a better price + build liquidity → sideways **range/congestion**.
3. Real downtrend resumes out of the money spot on a **high-volume** break.

**Three designs:**
- **Type 1 (line break):** range/money spot forms *above* the Set 1 line. Entry from the range once it holds.
- **Type 2 (ranging near line):** range forms *just below* the line; ends with a **sharp fake spike** through the line (stop-hunt) then runs. Entry after the spike trap.
- **Type 3 (run-away):** price never builds Set 2, just runs to a new low. **NO TRADE.**

### A3. Test 1 / Test 2 (the trigger inside the money spot)
- Pullback starts with a **V-formation**, then small counter-pushes.
- **Test 1:** first swing against intended entry (a high, for a sell).
- **Test 2:** second push that probes **slightly beyond Test 1** (slight higher-high for a sell / lower-low for a buy) to hunt stops.
- **Confirmation:** Test 2 must occur on **dead/low volume**. Price moves but no volume = no counter-strength left → enter. **If Test 2 volume spikes → cancel.**

### A4. Volume rules (quantified — directly codeable)
- Indicator: default **Volume + 20-period MA**, same settings on both analysis TFs. (Course recommends FXCM/OANDA data — see volume caveat in Part B.)
- **High Volume Pop:** *collective* (multi-bar) rise vs the prior sideways range, sitting **noticeably above the 20-MA**. NOT the single biggest "spike in the sky" (that = Big Boys cashing out → reversal).
- **Low Volume Pullback:** pullback bars must stay **below the pop** and ideally below 20-MA; must not match/challenge/exceed the pop. If they do → counter-traders are in → stand aside.
- **Dead volume @ Test 2:** lower than Test 1 → final go signal.

### A5. Correlation / currency strength
- Layout: **6 charts** of one currency group side-by-side.
- Strength numbers: **±7 scale**, read from **D1**, use **previous day's** close-of-day reading.
- Thresholds: **±5 = strong (A-class eligible)**; **±1 = neutral (downgrades to B-class)**.
- **Leader pair** = the one that pulls back the *least* (e.g. 50% vs others' 80–100%), holds ground, ranges first.
- **Entry timing:** only when the leader AND sister pairs finish digestion and **roll over together** ("group roll-over").

### A6. A / B / C classification (the filter)
| Class | Volume Pop | Purpose (orange/red news or session) | Correlation (D1 ±) | Action |
|-------|:---:|:---:|:---:|--------|
| **A** | ✅ | ✅ | strong (±5) | hold aggressively, target brand-new extreme; pick cleanest-angle pair |
| **B** | ✅ | ✅ | neutral (±1) | take profit at SNR/ATR/Fib; no home runs |
| **C** | pattern only | ❌ | none/contradicts | **stand aside**; if forced, exit fast / stop-to-zero. All-C day = day off |

### A7. Sessions & news
- Session opens (trade *near* these): **Frankfurt 07:00 London, London 08:00 London, NY forex 08:00 NY, NYSE 09:30 NY, Tokyo/Sydney 09:00 local**.
- **Trade only** near a session open OR a scheduled big news event (that's the "Purpose").
- **Stay out:** dead zones (midnight, mid-US-session lull), gray-folder / bank-holiday days, all-C-class days.
- **News filter:** Forex Factory / FXStreet, **orange (medium) + red (high) only**, **G7 currencies only** (USD EUR GBP JPY AUD NZD CHF). High-volume break with no orange/red news = weak Purpose, won't travel.
- **Around a release:** never enter on-the-spot; let the initial spike **digest**; enter after volatility settles into the money spot.

### A8. Entry / SL / TP / RR (mechanical)
- **Entry order type:** **manual market** only (no pending limit/stop) — trigger must be read live (Test 2 dead volume + group roll-over).
- **Stop-loss:** just outside the **Set 2 money spot / Test 2 trap extreme**, sized within the *two* analysis TFs. Never drop to a 3rd micro-TF for a tighter stop (→ 50/50 survival, premature stop-out).
- **Take-profit:**
  - Scale out **10/20/30%** at intermediate ranges / structural highs-lows.
  - **A-class:** hold to the origin extreme / brand-new high-low.
  - **B-class:** exit at SNR / ATR / Fib.
  - **Stop-to-zero** the moment momentum dies / sideways drag starts.
- **R:R:** bread-and-butter **1.5R–2R**; "make a lot of money, not a lot of Rs." 10R+ ONLY via Eclipse.

### A9. Special setups
- **Eclipse (the home run):** 60m setup + a 3m cheese trade align in the same direction *with news Purpose*. Instead of scaling out, **scale IN** on every minor pullback → 10–20R. Only with volume+news+correlation backing.
- **Trend Pullback Failure (reversal):** after Set 2 *also* fails to make a new extreme and digests the whole prior move → trend reverses. Don't enter on the flip; wait for digestion/congestion; aggressive entry on fake-breakout spike back into range, conservative on clean new-trend breakout. Target brand-new extreme.

### A10. Early-exit conditions (any one)
Sideways drag after entry • whole correlation group ranging simultaneously • C-class (exit fast, stop-to-zero) • B-class reaching SNR/ATR/Fib.

---

## PART B — Algorithmic feasibility (honest engineering verdict)

| Component | Codeable? | Notes |
|----------|:---:|------|
| Sessions gate | ✅ easy | reuse SessionClock |
| News/Purpose (orange+red, G7) | ✅ easy | economic-calendar API (ForexFactory/FXStreet) |
| Currency strength ±7, D1, leader pick | ✅ medium | reuse Alpha Desk / EMA-strength scanner |
| Volume pop / low-pullback / dead-Test2 | ⚠️ codeable but EDGE-RISKY | see caveat |
| Trend + Set 1 (failed new extreme) | ✅ medium | swing structure |
| Set 2 money spot (range/congestion) | 🟡 hard | ATR-compressed range detection |
| Test 1 / Test 2 (probe beyond + dead vol) | 🟡 hard | swing + volume compare |
| Type 1/2/3 discrimination | 🔴 hardest | Type 3 only knowable late; needs objective thresholds or it repaints |
| Entry/SL/TP/scale-out, Eclipse scale-in | ✅ medium | standard order logic |

🔴 **THE make-or-break — volume.** The entire edge rests on volume, and the course itself admits forex has no central exchange. MT5 gives **broker tick volume**, not true institutional volume. It's a usable proxy and is *exactly* codeable (tick volume + 20-MA), but whether it carries the claimed edge in spot FX is **unproven and must be backtested per broker/symbol**. Treat any "this always works" framing with the same skepticism that already killed the Elite-family WR claims in this project ([[project-jtcc-validation]]). No win-rate/expectancy exists in the course — we generate our own.

**Overall:** The *measurable confluence layer* (sessions+news+strength+volume) is clean to build and reuse. The *pattern layer* (Set1/2, Test1/2, Type discrimination) is the hard, attrition-prone part. Recommend building measurable layer first, validate volume edge early, only then invest in pattern detection.

---

## PART C — The Build Plan (phased, gated)

**Reuse map:** Alpha Desk (confluence scorer) · ICT_2022_EA (sweep/MSS/OB — ~70% conceptual overlap) · SessionClock · MTF backtest harness (APPLY_COSTS) · dashboard (integration mandatory).

### Phase 1 — Confluence Engine (measurable filters) ⟶ 1 module
Build `iconic_confluence` (Python): session gate + news gate (orange/red G7) + D1 currency-strength (±7, leader pick) + tick-volume pop/low/dead detector (20-MA). Output: per-pair **A/B/C score** + leader flag. *Extend Alpha Desk rather than start fresh.*
**Gate:** scores reproduce sensibly on recent data; volume signal is non-random.

### Phase 2 — Pattern Detector (Python, on MTF data)
Trend + Set 1 (failed extreme) + Set 2 money-spot (range) + Test 1/Test 2 (probe + dead volume) + Type 1/2/3 label. Pure detector, no orders yet. Define **objective thresholds** for every fuzzy term (range = N bars within X·ATR; "slightly beyond" = k pips/ATR; etc.).
**Gate:** detector marks setups on historical charts that match hand-labelled examples.

### Phase 3 — Backtest with REAL costs (their harness)
Combine Phase 1+2 → simulate entry/SL/TP/scale-out + Eclipse, **APPLY_COSTS = on**, per symbol (start G7 majors: EURUSD, GBPUSD, USDJPY, etc.). Report PF, DD, expectancy, trade count.
**Gate (project standard):** **PF ≥ 1.3**, DD within 20% cap, enough trades. Expect heavy attrition — likely survives only on a subset of symbols. **Go/No-go per symbol here.** If volume adds no edge, strip it and re-test pattern+correlation only.

### Phase 4 — EA build (only on passing symbols)
MQL5 EA in `inspection_ea/` → Strategy Tester validate → `ready_ea/`. Conventions: **1% risk/trade, 6% DD, equity-based sizing**, scale-out 10/20/30, Eclipse scale-in, stop-to-zero on drag. Pending-order vs market: codify the live trigger as a market entry on confirmed Test 2 + group roll-over.
**Gate:** Strategy Tester matches Python backtest within tolerance.

### Phase 5 — Dashboard integration (mandatory, definition-of-done)
New page/section: live A/B/C scoreboard per pair, leader highlight, active money-spots, session/news state, Eclipse alerts, EA P&L. Premium glass design-system. Optional Telegram topic for A-class/Eclipse alerts.

### Phase 6 — Paper → Live via promotion gate
Paper-trade tracker (1% / measured RR), `promotion_gate.can_go_live` fail-closed, then live with 6% DD guard.

---

## PART D — Risks & decision points
1. **Volume edge in spot FX** — biggest unknown; validate in Phase 1/3, be ready to drop it.
2. **Type 3 / repaint** — discretionary "no-trade" cases hard to pre-classify; risk of look-ahead bias. Strict same-bar/closed-bar rules.
3. **Discretion loss** — course is semi-discretionary; mechanizing will lose some context the human eye uses. Accept lower fidelity, prove with backtest.
4. **Overlap** — may be cheaper to *extend ICT_2022_EA + Alpha Desk* than build standalone. Evaluate after Phase 2.

## PART E — Recommended immediate next step
Start **Phase 1 (Confluence Engine)** — it's high-reuse, low-risk, and immediately answers the volume question before we invest in the hard pattern detector. I can scaffold it against the existing Alpha Desk + harness on your go-ahead.
