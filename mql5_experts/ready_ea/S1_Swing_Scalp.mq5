//+------------------------------------------------------------------+
//| Strategy 1 v2 — Swing Scalp (validated, PF 2.55 in backtest)     |
//| XAUUSD · London+NY · Risk 1.0%                                   |
//|                                                                  |
//| Entry  : H4 EMA200 bias (dist>30p) + M15 EMA21 cross + RSI14     |
//| Exit   : TRAILING RUNNER — bank 25% at +30/+60/+120, BE after    |
//|          first, lock +60 after +120, final 25% trails 100p off   |
//|          peak. NO fixed TP (uncapped winners = the v2 edge).     |
//|                                                                  |
//| NOTE: This EA mirrors backtest_runner.py::backtest_s1_v2 exactly. |
//|       v1's OB/FVG layers were NOT in the validated backtest and   |
//|       are intentionally removed so live == tested.                |
//+------------------------------------------------------------------+
#property copyright "FxVault"
#property version   "2.00"
#include <Trade\Trade.mqh>

input double RiskPct     = 1.0;
input int    SL_Pips     = 60;     // fixed SL (matches backtest)
input int    Max_Spread  = 30;
input int    MaxTrades   = 5;      // max trades per day
input int    TimeExitHrs = 48;     // time-based exit
input long   MagicNumber = 20260102;

// trailing-runner config (pips) — must match backtest_s1_v2 PARTS/TRAIL
int    PART_LV[3] = {30, 60, 120};
double PART_FR    = 0.25;          // close 25% at each level
int    TRAIL_PIPS = 100;

CTrade trade;
int h4ema200, m15ema21, m15rsi14;

datetime lastM15Bar = 0;
datetime lastH4Bar  = 0;
int      h4BiasDir  = 0;
int      todayTrades = 0;
datetime today       = 0;

ulong    openTicket  = 0;
double   openPrice   = 0;
double   initLot     = 0;
datetime entryTime   = 0;
int      posType     = -1;
double   peakPips    = 0;
double   slPips      = 0;          // Python convention: SL = entry - slPips*pip (BUY)
bool     partsDone[3] = {false, false, false};
bool     beSet       = false;
double   pip;

int OnInit()
{
   pip = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   h4ema200 = iMA(_Symbol, PERIOD_H4,  200, 0, MODE_EMA, PRICE_CLOSE);
   m15ema21 = iMA(_Symbol, PERIOD_M15,  21, 0, MODE_EMA, PRICE_CLOSE);
   m15rsi14 = iRSI(_Symbol, PERIOD_M15, 14, PRICE_CLOSE);
   if(h4ema200 == INVALID_HANDLE || m15ema21 == INVALID_HANDLE ||
      m15rsi14 == INVALID_HANDLE) return INIT_FAILED;
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) {}

bool InSession()
{
   MqlDateTime tm; TimeGMT(tm);
   return (tm.hour >= 7 && tm.hour < 12) || (tm.hour >= 13 && tm.hour < 17);
}

void CheckDailyReset()
{
   MqlDateTime tm; TimeGMT(tm);
   datetime d = StringToTime(StringFormat("%04d.%02d.%02d", tm.year, tm.mon, tm.day));
   if(d != today) { today = d; todayTrades = 0; }
}

double CalcLot(int sl_pips)
{
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_usd = equity * RiskPct / 100.0;
   double tick_val = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_sz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double lot_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double min_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double sl_price = sl_pips * pip;
   if(sl_price <= 0 || tick_sz <= 0) return min_lot;
   double raw = risk_usd / (sl_price / tick_sz * tick_val);
   return MathMax(min_lot, MathMin(max_lot, MathFloor(raw / lot_step) * lot_step));
}

void RefreshH4Bias()
{
   datetime bar = iTime(_Symbol, PERIOD_H4, 0);
   if(bar == lastH4Bar) return;
   lastH4Bar = bar;
   double ema[]; ArraySetAsSeries(ema, true);     // ema[1] = last closed H4 bar
   if(CopyBuffer(h4ema200, 0, 0, 2, ema) < 2) { h4BiasDir = 0; return; }
   double price = iClose(_Symbol, PERIOD_H4, 1);  // last closed H4 close
   double dist  = MathAbs(price - ema[1]) / pip;
   if(dist < 30) { h4BiasDir = 0; return; }
   h4BiasDir = (price > ema[1]) ? 1 : -1;
}

bool CheckM15Trigger(int dir)
{
   // Decision is made on COMPLETED bars only — exactly like the backtest,
   // which iterates closed M15 bars (row = just-closed bar, prev = the one
   // before it). shift 0 is the still-forming bar and must NOT be used.
   double ema[], rsi[];                    // dynamic → ArraySetAsSeries valid
   ArraySetAsSeries(ema, true); ArraySetAsSeries(rsi, true);
   if(CopyBuffer(m15ema21, 0, 0, 3, ema) < 3) return false;  // [1]=last closed,[2]=prev
   if(CopyBuffer(m15rsi14, 0, 0, 2, rsi) < 2) return false;  // [1]=last closed bar RSI
   double c1 = iClose(_Symbol, PERIOD_M15, 1);   // last CLOSED bar  (= backtest "row")
   double c2 = iClose(_Symbol, PERIOD_M15, 2);   // prev CLOSED bar  (= backtest "prev")
   bool cross  = (dir == 1) ? (c2 <= ema[2] && c1 > ema[1])
                            : (c2 >= ema[2] && c1 < ema[1]);
   bool rsi_ok = (dir == 1) ? (rsi[1] >= 40 && rsi[1] <= 65)
                            : (rsi[1] >= 35 && rsi[1] <= 60);
   return cross && rsi_ok;
}

//--- trailing-runner exit (mirrors backtest_s1_v2) -------------------
void ManageOpenTrade()
{
   if(openTicket == 0) return;
   if(!PositionSelectByTicket(openTicket)) { openTicket = 0; return; }

   int    type     = (int)PositionGetInteger(POSITION_TYPE);
   double bid      = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask      = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double cur      = (type == POSITION_TYPE_BUY) ? bid : ask;
   double pnl_pips = (type == POSITION_TYPE_BUY) ? (cur - openPrice) / pip
                                                 : (openPrice - cur) / pip;
   double vol      = PositionGetDouble(POSITION_VOLUME);
   double min_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);

   if(pnl_pips > peakPips) peakPips = pnl_pips;

   // progressive partials (25% each) + BE after first + lock +60 after +120
   for(int i = 0; i < 3; i++)
   {
      if(!partsDone[i] && pnl_pips >= PART_LV[i])
      {
         double close_v = NormalizeDouble(initLot * PART_FR, 2);
         close_v = MathMax(close_v, min_lot);
         if(close_v < vol) trade.PositionClosePartial(openTicket, close_v);
         partsDone[i] = true;
         if(i == 0 && !beSet) { slPips = -2;  beSet = true; }
         if(i == 2)           { slPips = MathMin(slPips, -60); }
      }
   }

   // runner trailing stop: active once all 3 partials banked
   if(partsDone[0] && partsDone[1] && partsDone[2])
   {
      double trail_lock = -(peakPips - TRAIL_PIPS);
      slPips = MathMin(slPips, trail_lock);
   }

   // SL price from slPips (Python: SL = entry -/+ slPips*pip)
   double sl_price = (type == POSITION_TYPE_BUY) ? openPrice - slPips * pip
                                                 : openPrice + slPips * pip;

   bool hit_sl = (type == POSITION_TYPE_BUY) ? (bid <= sl_price)
                                             : (ask >= sl_price);
   bool time_exit = (TimeCurrent() - entryTime) >= (long)TimeExitHrs * 3600;

   if(hit_sl || time_exit)
   {
      trade.PositionClose(openTicket);
      openTicket = 0;
      return;
   }

   // keep broker SL synced (safety net if EA/MT5 restarts mid-trade)
   double cur_sl = PositionGetDouble(POSITION_SL);
   double want_sl = NormalizeDouble(sl_price, _Digits);
   if(MathAbs(cur_sl - want_sl) > pip * 0.5)
      trade.PositionModify(openTicket, want_sl, 0.0);
}

void SeekSignal()
{
   if(openTicket != 0) return;
   if(h4BiasDir == 0) return;
   if(todayTrades >= MaxTrades) return;
   if(!InSession()) return;

   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) -
                    SymbolInfoDouble(_Symbol, SYMBOL_BID)) / pip;
   if(spread > Max_Spread) return;

   datetime m15bar = iTime(_Symbol, PERIOD_M15, 0);
   if(m15bar == lastM15Bar) return;
   lastM15Bar = m15bar;

   int dir = h4BiasDir;
   if(!CheckM15Trigger(dir)) return;

   double bid  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double lot  = CalcLot(SL_Pips);
   double sl_d = SL_Pips * pip;

   bool ok = false;
   if(dir == 1)
      ok = trade.Buy(lot, _Symbol, ask,
                     NormalizeDouble(ask - sl_d, _Digits), 0.0, "S1v2_BUY");
   else
      ok = trade.Sell(lot, _Symbol, bid,
                      NormalizeDouble(bid + sl_d, _Digits), 0.0, "S1v2_SELL");

   if(ok)
   {
      openTicket = trade.ResultOrder();
      openPrice  = (dir == 1) ? ask : bid;
      initLot    = lot;
      entryTime  = TimeCurrent();
      posType    = (dir == 1) ? POSITION_TYPE_BUY : POSITION_TYPE_SELL;
      peakPips   = 0;
      slPips     = SL_Pips;          // positive = SL below entry (loss side)
      beSet      = false;
      partsDone[0] = partsDone[1] = partsDone[2] = false;
      todayTrades++;
   }
}

void OnTick()
{
   CheckDailyReset();
   RefreshH4Bias();
   ManageOpenTrade();
   SeekSignal();
}
