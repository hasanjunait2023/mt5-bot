//+------------------------------------------------------------------+
//| NGS_Range.mq5 — Phase 7D: regime-gated averaging grid             |
//|                                                                   |
//| Why this EA exists:                                                |
//|   1. NGS_Grid live demo went 89 closed @ PF 2.63 in ranging gold, |
//|      then BLEW UP to 786 closed @ PF 0.85 once gold trended,      |
//|      dropping account 24% before DD kill-switch fired.            |
//|   2. Backtest of NGS_Grid (36 configs) and NGS_Pyramid (300+      |
//|      configs across v1/v2/v3/Single) all failed PF > 1.2 gate.    |
//|   3. Pattern is clear: grid mechanic has a REAL edge in RANGING   |
//|      regimes and ZERO edge in trending ones. ADX > 20 = trend on  |
//|      = blow-up territory.                                          |
//|                                                                   |
//| NGS_Range design: only run the grid when ADX < AdxEntryMax, and  |
//| IMMEDIATELY close all positions when ADX crosses above            |
//| AdxEscapeMin AND is rising (don't wait for the DD kill-switch     |
//| because by then the damage is already in). Plus tighter MaxDD     |
//| and maxLayers as the last line of defence.                        |
//|                                                                   |
//| This EA stays in inspection_ea/ until Python validation passes    |
//| (PF > 1.2, DD <= 15% post-cost). NO demo deploy before validation.|
//+------------------------------------------------------------------+
#property copyright "FxVault — NGS Range"
#property version   "1.00"
#property description "Range-gated averaging grid: ADX entry + ADX escape + tight MaxDD"
#include <Trade\Trade.mqh>

// ── GRID (same mechanic as NGS_Grid) ────────────────────────────────
input group "=== GRID ==="
input double GridGapPips     = 15.0;   // adverse-move gap between layers (pips)
input double BaseLot         = 0.01;
input int    MaxGridLayers   = 4;      // tighter than Grid's 5-10
input bool   ScaleLotByEquity = false;

// ── ADX REGIME GATES (the new bit) ──────────────────────────────────
input group "=== ADX REGIME ==="
input ENUM_TIMEFRAMES AdxTF        = PERIOD_M15;
input int    AdxPeriod             = 14;
input double AdxEntryMax           = 20.0;   // open NEW grid only if ADX <= this
input double AdxEscapeMin          = 25.0;   // close ALL if ADX >= this AND rising
input int    AdxRiseLookback       = 3;      // bars to confirm "rising"
input int    PostEscapeCooldownBars = 12;    // wait N M5 bars after escape

// ── TREND FILTER (MA crossover, last CLOSED bar) ────────────────────
input group "=== TREND FILTER ==="
input ENUM_TIMEFRAMES TrendTF = PERIOD_M15;
input int    MAFastPeriod    = 20;
input int    MASlowPeriod    = 50;
enum DirMode { DIR_AUTO = 0, DIR_BUY_ONLY = 1, DIR_SELL_ONLY = -1, DIR_BOTH = 2 };
input DirMode AllowedDir     = DIR_AUTO;

// ── EXITS ───────────────────────────────────────────────────────────
input group "=== EXITS ==="
input double SL_PerPos_Pips  = 150.0;  // per-position SL (tighter than Grid's 200)
input double BasketTP_USD    = 5.0;    // close ALL when basket PnL >= this (validated PF 1.29)
input bool   BasketTP_PctEq  = false;

// ── RISK / KILL-SWITCHES (tighter than Grid) ────────────────────────
input group "=== RISK CONTROL ==="
input double MarginStopPct   = 300.0;
input double MaxDD_Pct       = 10.0;   // validated config; tight enough to bound damage
input double MaxSpreadPips   = 25.0;

// ── HOUSEKEEPING ────────────────────────────────────────────────────
input group "=== HOUSEKEEPING ==="
input long   MagicNumber     = 20260900;  // distinct from Grid 20260700, Pyramid 20260800
input string TradeComment    = "NGS_Range";
input int    Slippage        = 30;

CTrade trade;
int    maFast = INVALID_HANDLE, maSlow = INVALID_HANDLE, adxH = INVALID_HANDLE;
double pip;
double equityPeak = 0.0;
bool   halted = false;
datetime cooldownUntil = 0;


int OnInit()
{
   pip = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(Slippage);
   maFast = iMA (_Symbol, TrendTF, MAFastPeriod, 0, MODE_EMA, PRICE_CLOSE);
   maSlow = iMA (_Symbol, TrendTF, MASlowPeriod, 0, MODE_EMA, PRICE_CLOSE);
   adxH   = iADX(_Symbol, AdxTF, AdxPeriod);
   if(maFast == INVALID_HANDLE || maSlow == INVALID_HANDLE ||
      adxH == INVALID_HANDLE)
   {
      Print("[Range] indicator init failed"); return INIT_FAILED;
   }
   equityPeak = AccountInfoDouble(ACCOUNT_EQUITY);
   PrintFormat("[Range] Init OK | gap=%.1fp baseLot=%.2f maxL=%d "
               "ADX entry<=%.0f escape>=%.0f maxDD=%.1f%%",
               GridGapPips, BaseLot, MaxGridLayers,
               AdxEntryMax, AdxEscapeMin, MaxDD_Pct);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {}


// ── trend dir (last closed M15 bar) ────────────────────────────────
int TrendDir()
{
   double f[], s[]; ArraySetAsSeries(f, true); ArraySetAsSeries(s, true);
   if(CopyBuffer(maFast, 0, 0, 2, f) < 2) return 0;
   if(CopyBuffer(maSlow, 0, 0, 2, s) < 2) return 0;
   if(f[1] > s[1]) return  1;
   if(f[1] < s[1]) return -1;
   return 0;
}

int AllowedSide()
{
   if(AllowedDir == DIR_BUY_ONLY)  return  1;
   if(AllowedDir == DIR_SELL_ONLY) return -1;
   if(AllowedDir == DIR_BOTH)      return TrendDir();
   return TrendDir();
}


// ── ADX helpers ────────────────────────────────────────────────────
// Returns most recent CLOSED-bar ADX (buffer 0). -1 on failure.
double AdxNow()
{
   double a[]; ArraySetAsSeries(a, true);
   if(CopyBuffer(adxH, 0, 0, 2, a) < 2) return -1.0;
   return a[1];     // last closed bar
}

// True if ADX is RISING over AdxRiseLookback closed bars.
bool AdxRising()
{
   int need = MathMax(2, AdxRiseLookback + 1);
   double a[]; ArraySetAsSeries(a, true);
   if(CopyBuffer(adxH, 0, 0, need, a) < need) return false;
   // a[1] is most recent closed bar, a[need-1] is oldest
   return a[1] > a[need - 1];
}


double LotSize()
{
   double lot = BaseLot;
   if(ScaleLotByEquity)
      lot = BaseLot * (AccountInfoDouble(ACCOUNT_EQUITY) / 1000.0);
   double info_min  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double info_max  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double info_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lot = MathMax(info_min, MathMin(info_max,
                MathFloor(lot / info_step) * info_step));
   return NormalizeDouble(lot, 2);
}

void InspectPositions(int &countOut, int &dirOut,
                      double &floatingPnlOut, double &worstPriceOut)
{
   countOut = 0; dirOut = 0; floatingPnlOut = 0; worstPriceOut = 0;
   bool   anyBuy = false, anySell = false;
   double worstBuy = 1e18, worstSell = -1e18;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)     continue;
      int    type   = (int)PositionGetInteger(POSITION_TYPE);
      double price  = PositionGetDouble(POSITION_PRICE_OPEN);
      floatingPnlOut += PositionGetDouble(POSITION_PROFIT)
                      + PositionGetDouble(POSITION_SWAP);
      countOut++;
      if(type == POSITION_TYPE_BUY)
      {
         anyBuy = true;
         if(price < worstBuy) worstBuy = price;     // averaging: lowest BUY
      }
      else
      {
         anySell = true;
         if(price > worstSell) worstSell = price;   // averaging: highest SELL
      }
   }
   if(anyBuy && !anySell)      { dirOut =  1; worstPriceOut = worstBuy; }
   else if(anySell && !anyBuy) { dirOut = -1; worstPriceOut = worstSell; }
}

bool CloseAllOurs(const string reason)
{
   int closed = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)     continue;
      if(trade.PositionClose(ticket)) closed++;
   }
   if(closed > 0)
      PrintFormat("[Range] Closed %d position(s) — %s", closed, reason);
   return closed > 0;
}

bool OpenLayer(int dir)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double spread_p = (ask - bid) / pip;
   if(spread_p > MaxSpreadPips) return false;
   double lot = LotSize();
   double sl  = (dir == 1) ? ask - SL_PerPos_Pips * pip
                            : bid + SL_PerPos_Pips * pip;
   bool ok;
   if(dir == 1)
      ok = trade.Buy(lot, _Symbol, ask, NormalizeDouble(sl, _Digits),
                     0.0, TradeComment);
   else
      ok = trade.Sell(lot, _Symbol, bid, NormalizeDouble(sl, _Digits),
                      0.0, TradeComment);
   if(ok)
      PrintFormat("[Range] +Layer %s lot=%.2f @%.*f",
                  dir == 1 ? "BUY" : "SELL", lot, _Digits,
                  dir == 1 ? ask : bid);
   return ok;
}

bool CheckDDKillSwitch()
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity > equityPeak) equityPeak = equity;
   if(equityPeak <= 0) return false;
   double dd = (equityPeak - equity) / equityPeak * 100.0;
   if(dd >= MaxDD_Pct)
   {
      if(!halted)
      {
         PrintFormat("[Range] *** DD KILL-SWITCH *** dd=%.2f%% >= %.2f%%",
                     dd, MaxDD_Pct);
         CloseAllOurs("DD kill-switch");
         halted = true;
      }
      return true;
   }
   return false;
}

bool MarginBlocksEntries()
{
   double m = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   if(m <= 0) return false;
   return (m < MarginStopPct);
}


void OnTick()
{
   // 1) DD kill-switch
   if(CheckDDKillSwitch()) return;
   if(halted)              return;

   // 2) Basket TP
   int    pcount; int dir; double pnl, worst;
   InspectPositions(pcount, dir, pnl, worst);
   double tp_threshold = BasketTP_PctEq
                         ? AccountInfoDouble(ACCOUNT_EQUITY) * BasketTP_USD / 100.0
                         : BasketTP_USD;
   if(pcount > 0 && pnl >= tp_threshold)
   {
      PrintFormat("[Range] Basket TP hit: pnl=$%.2f >= $%.2f — closing %d",
                  pnl, tp_threshold, pcount);
      CloseAllOurs("Basket TP");
      return;
   }

   // 3) *** ADX ESCAPE *** — if regime turned to trend, close all NOW.
   double adx_v = AdxNow();
   if(pcount > 0 && adx_v >= AdxEscapeMin && AdxRising())
   {
      PrintFormat("[Range] *** ADX ESCAPE *** ADX=%.1f rising — closing %d",
                  adx_v, pcount);
      CloseAllOurs("ADX escape (regime trend onset)");
      cooldownUntil = TimeCurrent() + PostEscapeCooldownBars * 5 * 60;
      return;
   }

   // 4) entry blockers
   if(MarginBlocksEntries()) return;
   if(pcount >= MaxGridLayers) return;
   if(TimeCurrent() < cooldownUntil) return;   // post-escape cool-down

   // 5) entry / next-layer
   if(pcount == 0)
   {
      // ADX ENTRY GATE — only start grid if regime is ranging
      if(adx_v <= 0 || adx_v > AdxEntryMax)
      {
         static datetime lastSkip = 0;
         if(TimeCurrent() - lastSkip > 300)
         {
            PrintFormat("[Range] skip entry: ADX=%.1f > %.1f (not ranging)",
                        adx_v, AdxEntryMax);
            lastSkip = TimeCurrent();
         }
         return;
      }
      int side = AllowedSide();
      if(side == 1 || side == -1) OpenLayer(side);
      return;
   }

   // averaging next layer on adverse move (same as Grid)
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double trigger_dist = GridGapPips * pip;
   if(dir == 1 && ask <= worst - trigger_dist) OpenLayer(1);
   else if(dir == -1 && bid >= worst + trigger_dist) OpenLayer(-1);
}
