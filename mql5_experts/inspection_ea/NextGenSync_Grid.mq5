//+------------------------------------------------------------------+
//| NextGenSync_Grid.mq5                                              |
//|                                                                   |
//| Spec source: video analysis "NextGen Sync" + Claude EA prompt     |
//| (Bengali docs 2026-05-19).                                        |
//|                                                                   |
//| Strategy: averaging-down GRID with MA trend filter + basket TP.   |
//|   - MA-cross trend filter decides BUY-only / SELL-only / NONE     |
//|   - Open the first position in the allowed direction              |
//|   - Every GridGapPips of ADVERSE move opens the next layer        |
//|     (same direction; classic averaging-down)                      |
//|   - Each position carries its own broker SL (safety net)          |
//|   - "Basket Take Profit": when total floating PnL across all      |
//|     magic-matching positions >= BasketTP_USD, close them ALL      |
//|   - New entries are BLOCKED when MarginLevel <= MarginStopPct OR  |
//|     equity-drawdown >= MaxDD_Pct (the latter also closes all)     |
//|                                                                   |
//| **GRID RISK WARNING (read this — the spec itself flags it):**     |
//| Averaging-down grids look profitable in ranging markets but blow  |
//| up in strong trends because they keep doubling exposure on losers |
//| until margin runs out. This EA is intentionally placed in         |
//| inspection_ea/ — it MUST pass a real-cost backtest gate (PF>1,    |
//| DD <= 20%) before promotion to ready_ea/demo. Do not run live     |
//| without validation. The kill-switches below are last-line         |
//| defence, not a substitute for an edge.                            |
//+------------------------------------------------------------------+
#property copyright "FxVault — NextGen Sync (grid)"
#property version   "1.00"
#property description "Averaging-down grid + MA trend filter + basket TP + DD/margin kill-switch"
#include <Trade\Trade.mqh>

// ── GRID ────────────────────────────────────────────────────────────
input group "=== GRID ==="
input double GridGapPips     = 15.0;   // adverse-move gap between layers (pips)
input double BaseLot         = 0.01;   // lot per layer
input int    MaxGridLayers   = 10;     // hard cap on simultaneous positions
input bool   ScaleLotByEquity = false; // if true: lot = BaseLot * (equity/$1000)

// ── TREND FILTER (MA crossover) ─────────────────────────────────────
input group "=== TREND FILTER ==="
input ENUM_TIMEFRAMES TrendTF = PERIOD_M15;
input int    MAFastPeriod    = 20;
input int    MASlowPeriod    = 50;
enum DirMode { DIR_AUTO = 0, DIR_BUY_ONLY = 1, DIR_SELL_ONLY = -1, DIR_BOTH = 2 };
input DirMode AllowedDir     = DIR_AUTO;  // AUTO = follow MA cross

// ── EXITS ───────────────────────────────────────────────────────────
input group "=== EXITS ==="
input double SL_PerPos_Pips  = 200.0;  // per-position broker SL (safety net, wide)
input double BasketTP_USD    = 5.0;    // close ALL when total floating PnL >= this
input bool   BasketTP_PctEq  = false;  // if true: BasketTP_USD interpreted as % of equity

// ── RISK / KILL-SWITCHES ────────────────────────────────────────────
input group "=== RISK CONTROL ==="
input double MarginStopPct   = 200.0;  // block new entries when margin level <= this %
input double MaxDD_Pct       = 20.0;   // close all + halt when equity DD from peak >= this %
input double MaxSpreadPips   = 30.0;   // skip entries when spread > this

// ── HOUSEKEEPING ────────────────────────────────────────────────────
input group "=== HOUSEKEEPING ==="
input long   MagicNumber     = 20260700;
input string TradeComment    = "NGS_Grid";
input int    Slippage        = 30;     // points

CTrade trade;
int    maFast = INVALID_HANDLE, maSlow = INVALID_HANDLE;
double pip;
double equityPeak = 0.0;
bool   halted = false;                 // set when DD kill-switch trips


int OnInit()
{
   pip = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(Slippage);
   maFast = iMA(_Symbol, TrendTF, MAFastPeriod, 0, MODE_EMA, PRICE_CLOSE);
   maSlow = iMA(_Symbol, TrendTF, MASlowPeriod, 0, MODE_EMA, PRICE_CLOSE);
   if(maFast == INVALID_HANDLE || maSlow == INVALID_HANDLE)
   {
      Print("[NGS] iMA init failed"); return INIT_FAILED;
   }
   equityPeak = AccountInfoDouble(ACCOUNT_EQUITY);
   Print("[NGS] Init OK | pip=", DoubleToString(pip, _Digits),
         " gap=", GridGapPips, "p  baseLot=", BaseLot,
         " basketTP=$", BasketTP_USD, " maxLayers=", MaxGridLayers);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {}

// ── trend direction from MA cross (last CLOSED bar) ─────────────────
// returns +1 = bullish, -1 = bearish, 0 = unknown
int TrendDir()
{
   double f[], s[]; ArraySetAsSeries(f, true); ArraySetAsSeries(s, true);
   if(CopyBuffer(maFast, 0, 0, 2, f) < 2) return 0;
   if(CopyBuffer(maSlow, 0, 0, 2, s) < 2) return 0;
   if(f[1] > s[1]) return  1;     // last closed bar: fast above slow → bullish
   if(f[1] < s[1]) return -1;
   return 0;
}

int AllowedSide()
{
   if(AllowedDir == DIR_BUY_ONLY)  return  1;
   if(AllowedDir == DIR_SELL_ONLY) return -1;
   if(AllowedDir == DIR_BOTH)      return  TrendDir();   // either side allowed; trend just hints
   return TrendDir();                                    // AUTO: follow trend
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

// ── inspect this EA's open positions (by magic+symbol) ─────────────
// dir output: 0 = none, +1 = BUY layers, -1 = SELL layers
void InspectPositions(int &countOut, int &dirOut,
                      double &avgPriceOut, double &floatingPnlOut,
                      double &worstPriceOut)
{
   countOut = 0; dirOut = 0;
   avgPriceOut = 0; floatingPnlOut = 0; worstPriceOut = 0;
   double sumLotPrice = 0, sumLot = 0;
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
      double volume = PositionGetDouble(POSITION_VOLUME);
      double profit = PositionGetDouble(POSITION_PROFIT)
                    + PositionGetDouble(POSITION_SWAP);
      sumLotPrice  += price * volume;
      sumLot       += volume;
      floatingPnlOut += profit;
      countOut++;
      if(type == POSITION_TYPE_BUY)
      {
         anyBuy = true;
         if(price < worstBuy) worstBuy = price;    // lowest BUY entry
      }
      else
      {
         anySell = true;
         if(price > worstSell) worstSell = price;  // highest SELL entry
      }
   }
   if(sumLot > 0) avgPriceOut = sumLotPrice / sumLot;
   if(anyBuy && !anySell)      { dirOut =  1; worstPriceOut = worstBuy; }
   else if(anySell && !anyBuy) { dirOut = -1; worstPriceOut = worstSell; }
   // mixed directions (shouldn't happen with this EA's logic): leave dir=0
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
      PrintFormat("[NGS] Closed %d position(s) — %s", closed, reason);
   return closed > 0;
}

// open one grid layer (+1 BUY / -1 SELL)
bool OpenLayer(int dir)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double spread_p = (ask - bid) / pip;
   if(spread_p > MaxSpreadPips) return false;
   double lot = LotSize();
   double sl  = 0.0;
   if(SL_PerPos_Pips > 0)
      sl = (dir == 1) ? ask - SL_PerPos_Pips * pip
                      : bid + SL_PerPos_Pips * pip;
   bool ok;
   if(dir == 1)
      ok = trade.Buy(lot, _Symbol, ask, NormalizeDouble(sl, _Digits),
                     0.0, TradeComment);
   else
      ok = trade.Sell(lot, _Symbol, bid, NormalizeDouble(sl, _Digits),
                      0.0, TradeComment);
   if(ok)
      PrintFormat("[NGS] +Layer %s lot=%.2f @%.*f sl=%.*f",
                  dir==1 ? "BUY" : "SELL", lot, _Digits,
                  dir==1 ? ask : bid, _Digits, sl);
   else
      PrintFormat("[NGS] OpenLayer failed (ret=%d desc=%s)",
                  trade.ResultRetcode(), trade.ResultRetcodeDescription());
   return ok;
}

// ── kill-switches ───────────────────────────────────────────────────
// equity-DD kill-switch: close all + halt the EA
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
         PrintFormat("[NGS] *** DD KILL-SWITCH *** dd=%.2f%% >= %.2f%% — halting",
                     dd, MaxDD_Pct);
         CloseAllOurs("DD kill-switch");
         halted = true;
      }
      return true;
   }
   return false;
}

// margin halt: block NEW entries (existing positions keep running)
bool MarginBlocksEntries()
{
   double marginLevel = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   if(marginLevel <= 0) return false;   // no open margin
   if(marginLevel < MarginStopPct)
   {
      static datetime lastWarn = 0;
      if(TimeCurrent() - lastWarn > 60)
      {
         PrintFormat("[NGS] margin level %.0f%% < %.0f%% — blocking new layers",
                     marginLevel, MarginStopPct);
         lastWarn = TimeCurrent();
      }
      return true;
   }
   return false;
}


void OnTick()
{
   // ── 1) DD kill-switch — overrides everything ───────────────────
   if(CheckDDKillSwitch()) return;
   if(halted)              return;     // sticky halt until reload

   // ── 2) basket take-profit ──────────────────────────────────────
   int    pcount; int dir; double avg, pnl, worst;
   InspectPositions(pcount, dir, avg, pnl, worst);
   double tp_threshold = BasketTP_PctEq
                         ? AccountInfoDouble(ACCOUNT_EQUITY) * BasketTP_USD / 100.0
                         : BasketTP_USD;
   if(pcount > 0 && pnl >= tp_threshold)
   {
      PrintFormat("[NGS] Basket TP hit: pnl=$%.2f >= $%.2f — closing %d",
                  pnl, tp_threshold, pcount);
      CloseAllOurs("Basket TP");
      return;
   }

   // ── 3) blocked from new entries? ───────────────────────────────
   if(MarginBlocksEntries()) return;
   if(pcount >= MaxGridLayers) return;

   // ── 4) entry / next-layer decision ─────────────────────────────
   if(pcount == 0)
   {
      // grid empty → open first layer in allowed direction (if any)
      int side = AllowedSide();
      if(side == 1 || side == -1)
         OpenLayer(side);
      return;
   }

   // grid already has positions in direction `dir`. Add next layer
   // only when price has moved GridGapPips AGAINST that direction
   // past the worst existing entry (classic averaging-down trigger).
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double trigger_dist = GridGapPips * pip;
   if(dir == 1)
   {
      // worst BUY = lowest entry; trigger when ask has fallen another gap below it
      if(ask <= worst - trigger_dist) OpenLayer(1);
   }
   else if(dir == -1)
   {
      // worst SELL = highest entry; trigger when bid has risen another gap above it
      if(bid >= worst + trigger_dist) OpenLayer(-1);
   }
}
