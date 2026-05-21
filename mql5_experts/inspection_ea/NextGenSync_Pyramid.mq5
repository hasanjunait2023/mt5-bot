//+------------------------------------------------------------------+
//| NextGenSync_Pyramid.mq5  —  TRACK B: real momentum capture        |
//|                                                                   |
//| Structurally DIFFERENT from NextGenSync_Grid (averaging-down):    |
//|   - Layers added IN trend direction as price extends (pyramid)    |
//|   - Per-position SL is ATR-based and tight (not 200-pip wide)     |
//|   - No fixed per-position TP — runners ride the trend             |
//|   - Exit: TRAILING basket SL — once combined PnL hits activation, |
//|     start trailing peak; if peak - current >= TrailDrawdown_USD,  |
//|     close ALL.                                                    |
//|                                                                   |
//| Magic 20260800 — distinct from NextGenSync_Grid (20260700) so     |
//| both can run side-by-side on demo for honest comparison.          |
//|                                                                   |
//| Discipline: stays in inspection_ea/ until the Python real-cost    |
//| backtest sweep passes (PF > 1.2, DD <= 15%). NO demo deploy       |
//| before validation — same gate every other EA went through.        |
//+------------------------------------------------------------------+
#property copyright "FxVault — NextGen Sync (pyramid)"
#property version   "1.00"
#property description "Trend-direction pyramid + ATR SL + trailing basket SL"
#include <Trade\Trade.mqh>

// ── PYRAMID ─────────────────────────────────────────────────────────
input group "=== PYRAMID ==="
input double GridGapPips     = 20.0;   // favourable-move gap between layers (pips)
input double BaseLot         = 0.01;   // lot per layer
input int    MaxGridLayers   = 6;      // pyramid cap
input bool   ScaleLotByEquity = false; // lot = BaseLot * (equity/$1000)

// ── TREND FILTER (MA crossover, last CLOSED bar) ────────────────────
input group "=== TREND FILTER ==="
input ENUM_TIMEFRAMES TrendTF = PERIOD_M15;
input int    MAFastPeriod    = 20;
input int    MASlowPeriod    = 50;
enum DirMode { DIR_AUTO = 0, DIR_BUY_ONLY = 1, DIR_SELL_ONLY = -1 };
input DirMode AllowedDir     = DIR_AUTO;

// ── PER-POSITION SL (ATR-based, tight) ──────────────────────────────
input group "=== PER-POSITION SL ==="
input ENUM_TIMEFRAMES ATR_TF = PERIOD_M15;
input int    ATR_Period      = 14;
input double SL_ATR_Mult     = 1.5;    // SL distance = 1.5 * ATR (pips)
input double SL_Min_Pips     = 25.0;   // floor (broker stops level safety)
input double SL_Max_Pips     = 150.0;  // ceiling

// ── TRAILING BASKET SL ──────────────────────────────────────────────
input group "=== TRAILING BASKET EXIT ==="
input double TrailActivation_USD = 5.0;  // start trailing once basket PnL >= this
input double TrailDrawdown_USD   = 3.0;  // close all if basket falls from peak by this

// ── RISK / KILL-SWITCHES ────────────────────────────────────────────
input group "=== RISK CONTROL ==="
input double MarginStopPct   = 300.0;  // block new entries when margin level <= this %
input double MaxDD_Pct       = 15.0;   // close all + halt when equity DD >= this %
input double MaxSpreadPips   = 25.0;

// ── HOUSEKEEPING ────────────────────────────────────────────────────
input group "=== HOUSEKEEPING ==="
input long   MagicNumber     = 20260800;
input string TradeComment    = "NGS_Pyramid";
input int    Slippage        = 30;

CTrade trade;
int    maFast = INVALID_HANDLE, maSlow = INVALID_HANDLE, atrH = INVALID_HANDLE;
double pip;
double equityPeak     = 0.0;
double basketPeakPnL  = -1e18;       // peak of combined floating PnL
bool   trailActive    = false;       // true once basket has reached activation
bool   halted         = false;       // sticky after DD-kill


int OnInit()
{
   pip = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(Slippage);
   maFast = iMA(_Symbol, TrendTF, MAFastPeriod, 0, MODE_EMA, PRICE_CLOSE);
   maSlow = iMA(_Symbol, TrendTF, MASlowPeriod, 0, MODE_EMA, PRICE_CLOSE);
   atrH   = iATR(_Symbol, ATR_TF, ATR_Period);
   if(maFast == INVALID_HANDLE || maSlow == INVALID_HANDLE ||
      atrH == INVALID_HANDLE)
   {
      Print("[NGSP] indicator init failed"); return INIT_FAILED;
   }
   equityPeak = AccountInfoDouble(ACCOUNT_EQUITY);
   PrintFormat("[NGSP] Init OK | pip=%.5f gap=%.1fp baseLot=%.2f maxL=%d "
               "SL=%.1fxATR trailAct=$%.2f trailDD=$%.2f",
               pip, GridGapPips, BaseLot, MaxGridLayers, SL_ATR_Mult,
               TrailActivation_USD, TrailDrawdown_USD);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {}

// ── trend direction from MA cross (last CLOSED bar) ─────────────────
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
   return TrendDir();
}

// ── ATR(price units) → SL distance in pips, clamped to [min, max] ──
double AtrSlPips()
{
   double a[]; ArraySetAsSeries(a, true);
   if(CopyBuffer(atrH, 0, 0, 2, a) < 2) return SL_Min_Pips;
   double atr_p = a[1] / pip;                       // ATR in pips
   double sl_p  = atr_p * SL_ATR_Mult;
   return MathMax(SL_Min_Pips, MathMin(SL_Max_Pips, sl_p));
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
// dir: 0=none, +1=BUY pyramid, -1=SELL pyramid
// bestPriceOut: for BUY = HIGHEST entry (latest layer in pyramid);
//               for SELL = LOWEST entry (latest layer in pyramid).
void InspectPositions(int &countOut, int &dirOut,
                      double &floatingPnlOut, double &bestPriceOut)
{
   countOut = 0; dirOut = 0; floatingPnlOut = 0; bestPriceOut = 0;
   bool   anyBuy = false, anySell = false;
   double bestBuy = -1e18, bestSell = 1e18;
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
         if(price > bestBuy) bestBuy = price;     // highest BUY
      }
      else
      {
         anySell = true;
         if(price < bestSell) bestSell = price;   // lowest SELL
      }
   }
   if(anyBuy && !anySell)      { dirOut =  1; bestPriceOut = bestBuy; }
   else if(anySell && !anyBuy) { dirOut = -1; bestPriceOut = bestSell; }
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
      PrintFormat("[NGSP] Closed %d position(s) — %s", closed, reason);
   // reset trailing state when basket is gone
   basketPeakPnL = -1e18;
   trailActive   = false;
   return closed > 0;
}

bool OpenLayer(int dir)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double spread_p = (ask - bid) / pip;
   if(spread_p > MaxSpreadPips) return false;
   double lot    = LotSize();
   double sl_pips = AtrSlPips();
   double sl_px   = (dir == 1) ? ask - sl_pips * pip
                                : bid + sl_pips * pip;
   bool ok;
   if(dir == 1)
      ok = trade.Buy(lot, _Symbol, ask, NormalizeDouble(sl_px, _Digits),
                     0.0, TradeComment);
   else
      ok = trade.Sell(lot, _Symbol, bid, NormalizeDouble(sl_px, _Digits),
                      0.0, TradeComment);
   if(ok)
      PrintFormat("[NGSP] +Layer %s lot=%.2f @%.*f  sl=%.*f (%.1f pips)",
                  dir == 1 ? "BUY" : "SELL", lot, _Digits,
                  dir == 1 ? ask : bid, _Digits, sl_px, sl_pips);
   else
      PrintFormat("[NGSP] OpenLayer failed (ret=%d %s)",
                  trade.ResultRetcode(), trade.ResultRetcodeDescription());
   return ok;
}

// ── trailing basket SL: track peak combined PnL, close all on drop ──
// Returns true if the basket was closed by trailing logic.
bool UpdateTrailingBasket(double pnl)
{
   if(pnl > basketPeakPnL) basketPeakPnL = pnl;
   if(!trailActive && basketPeakPnL >= TrailActivation_USD)
   {
      trailActive = true;
      PrintFormat("[NGSP] Trailing ACTIVATED — peak $%.2f >= $%.2f",
                  basketPeakPnL, TrailActivation_USD);
   }
   if(trailActive && (basketPeakPnL - pnl) >= TrailDrawdown_USD)
   {
      PrintFormat("[NGSP] Trailing CLOSE: peak $%.2f - now $%.2f >= $%.2f",
                  basketPeakPnL, pnl, TrailDrawdown_USD);
      CloseAllOurs("Trailing basket SL");
      return true;
   }
   return false;
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
         PrintFormat("[NGSP] *** DD KILL-SWITCH *** dd=%.2f%% >= %.2f%%",
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
   if(m < MarginStopPct)
   {
      static datetime lastWarn = 0;
      if(TimeCurrent() - lastWarn > 60)
      {
         PrintFormat("[NGSP] margin %.0f%% < %.0f%% — blocking new layers",
                     m, MarginStopPct);
         lastWarn = TimeCurrent();
      }
      return true;
   }
   return false;
}


void OnTick()
{
   // 1) DD kill-switch — terminates everything
   if(CheckDDKillSwitch()) return;
   if(halted)              return;

   // 2) trailing basket exit
   int    pcount; int dir; double pnl, bestPx;
   InspectPositions(pcount, dir, pnl, bestPx);
   if(pcount > 0)
   {
      if(UpdateTrailingBasket(pnl)) return;        // basket just closed
   }
   else
   {
      // no positions → reset trailing state (safety)
      basketPeakPnL = -1e18;
      trailActive   = false;
   }

   // 3) blocked from new entries?
   if(MarginBlocksEntries()) return;
   if(pcount >= MaxGridLayers) return;

   // 4) entry / next-layer
   if(pcount == 0)
   {
      int side = AllowedSide();
      if(side == 1 || side == -1)
         OpenLayer(side);
      return;
   }

   // Pyramid: add next layer when price has extended GridGapPips
   // FURTHER in trend direction past the LATEST (best) layer.
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double trigger_dist = GridGapPips * pip;
   if(dir == 1)
   {
      // bestPx = highest BUY; add when ask is another gap above it
      if(ask >= bestPx + trigger_dist) OpenLayer(1);
   }
   else if(dir == -1)
   {
      // bestPx = lowest SELL; add when bid is another gap below it
      if(bid <= bestPx - trigger_dist) OpenLayer(-1);
   }
}
