//+------------------------------------------------------------------+
//| Strategy 14 — Stoch Deep Cross + Trend  (Notion #4 WINNER)       |
//| GBPUSD · H1 · Risk 1.0%                                          |
//|                                                                  |
//| Notion backtest (Yahoo GBPUSD=X, 60d H1): WR 66.7% (2W/1L),      |
//|   +4.39%, PF 5.26, maxDD 0.98%. Deep pullback in strong trend.   |
//|                                                                  |
//| Entry needs ALL 5 (BUY; SELL = mirror):                           |
//|   1 EMA20>EMA50>EMA200  (trend)                                   |
//|   2 Stoch deep cross: K[2]<=D[2], K[1]>D[1], K[2]<20              |
//|   3 Close > EMA50                                                 |
//|   4 confirming candle: Close[1] > Open[1]                         |
//|   5 ATR% filter (see MinATRpct note below)                        |
//| Exit : SL = Low[1] - ATR*0.3 (BUY) / High[1] + ATR*0.3 (SELL)     |
//|        TP = entry +/- SLdist*2.5  (fixed; live == tested).        |
//|                                                                  |
//| MOD / KNOWN UNCERTAINTY: the Notion pseudocode uses `row.ATR_pct` |
//|   with threshold 0.2 but never defines its scaling, and the      |
//|   original Yahoo backtest script is not in this repo. We define  |
//|   ATR% = ATR/Close*100 and expose MinATRpct. Default 0.0 = filter |
//|   OFF so the strategy is not silently strangled; CALIBRATE this   |
//|   in Strategy Tester before trusting it (see summary).            |
//| Decisions on CLOSED H1 bars (shift1=last closed, shift2=prev).   |
//| Source spec: Notion 364bbf27-1afa-81a0-a7ff-f04dda44463d.        |
//+------------------------------------------------------------------+
#property copyright "FxVault"
#property version   "1.00"
#include <Trade\Trade.mqh>

input double RiskPct      = 1.0;
input double StochDeepBuy  = 20.0;   // K[2] must be below this for BUY
input double StochDeepSell = 80.0;   // K[2] must be above this for SELL
input double SL_ATR_Mult   = 0.3;
input double RR            = 2.5;
input double MinATRpct     = 0.0;    // ATR/Close*100 floor; 0 = OFF (see note)
input int    Max_Spread    = 25;     // points
input int    MaxTradesDay  = 3;
input long   MagicNumber   = 20261400;

CTrade trade;
int ema20, ema50, ema200, stochH, atrH;
double pip;
datetime lastH1Bar = 0;
datetime today     = 0;
int      todayTrades = 0;

int OnInit()
{
   pip = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   ema20  = iMA(_Symbol, PERIOD_H1,  20, 0, MODE_EMA, PRICE_CLOSE);
   ema50  = iMA(_Symbol, PERIOD_H1,  50, 0, MODE_EMA, PRICE_CLOSE);
   ema200 = iMA(_Symbol, PERIOD_H1, 200, 0, MODE_EMA, PRICE_CLOSE);
   stochH = iStochastic(_Symbol, PERIOD_H1, 14, 3, 3, MODE_SMA, STO_LOWHIGH);
   atrH   = iATR(_Symbol, PERIOD_H1, 14);
   if(ema20==INVALID_HANDLE || ema50==INVALID_HANDLE || ema200==INVALID_HANDLE ||
      stochH==INVALID_HANDLE || atrH==INVALID_HANDLE) return INIT_FAILED;
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) {}

double CalcLot(double sl_dist)
{
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_usd = equity * RiskPct / 100.0;
   double tick_val = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_sz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double lot_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double min_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(sl_dist <= 0 || tick_sz <= 0) return min_lot;
   double raw = risk_usd / (sl_dist / tick_sz * tick_val);
   return MathMax(min_lot, MathMin(max_lot, MathFloor(raw / lot_step) * lot_step));
}

bool HavePosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(PositionSelectByTicket(t) &&
         PositionGetInteger(POSITION_MAGIC) == MagicNumber &&
         PositionGetString(POSITION_SYMBOL) == _Symbol) return true;
   }
   return false;
}

void CheckDailyReset()
{
   MqlDateTime tm; TimeGMT(tm);
   datetime d = StringToTime(StringFormat("%04d.%02d.%02d", tm.year, tm.mon, tm.day));
   if(d != today) { today = d; todayTrades = 0; }
}

void OnTick()
{
   CheckDailyReset();

   datetime b = iTime(_Symbol, PERIOD_H1, 0);
   if(b == lastH1Bar) return;
   lastH1Bar = b;

   if(HavePosition() || todayTrades >= MaxTradesDay) return;

   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) -
                    SymbolInfoDouble(_Symbol, SYMBOL_BID)) / _Point;
   if(spread > Max_Spread) return;

   double e20[], e50[], e200[], k[], d[], at[];
   ArraySetAsSeries(e20,true);  ArraySetAsSeries(e50,true);
   ArraySetAsSeries(e200,true); ArraySetAsSeries(k,true);
   ArraySetAsSeries(d,true);    ArraySetAsSeries(at,true);
   if(CopyBuffer(ema20, 0, 0, 3, e20)  < 3) return;
   if(CopyBuffer(ema50, 0, 0, 3, e50)  < 3) return;
   if(CopyBuffer(ema200,0, 0, 3, e200) < 3) return;
   if(CopyBuffer(stochH,0, 0, 3, k)    < 3) return;   // 0 = %K (main)
   if(CopyBuffer(stochH,1, 0, 3, d)    < 3) return;   // 1 = %D (signal)
   if(CopyBuffer(atrH,  0, 0, 3, at)   < 3) return;

   double o1 = iOpen (_Symbol, PERIOD_H1, 1);
   double h1 = iHigh (_Symbol, PERIOD_H1, 1);
   double l1 = iLow  (_Symbol, PERIOD_H1, 1);
   double c1 = iClose(_Symbol, PERIOD_H1, 1);
   double atr = at[1];
   if(atr <= 0 || c1 <= 0) return;

   // ATR% volatility filter — see header note on scaling uncertainty
   double atr_pct = atr / c1 * 100.0;
   if(MinATRpct > 0.0 && atr_pct < MinATRpct) return;

   bool bull_cross = (k[2] <= d[2]) && (k[1] > d[1]) && (k[2] < StochDeepBuy);
   bool bear_cross = (k[2] >= d[2]) && (k[1] < d[1]) && (k[2] > StochDeepSell);

   bool strong_up = e20[1] > e50[1] && e50[1] > e200[1] && c1 > e50[1];
   bool strong_dn = e20[1] < e50[1] && e50[1] < e200[1] && c1 < e50[1];

   bool buy  = bull_cross && strong_up && c1 > o1;
   bool sell = bear_cross && strong_dn && c1 < o1;
   if(!buy && !sell) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(buy)
   {
      double sl   = l1 - atr * SL_ATR_Mult;
      double dist = ask - sl;
      if(dist <= 0) return;
      double tp   = NormalizeDouble(ask + dist * RR, _Digits);
      double lot  = CalcLot(dist);
      if(trade.Buy(lot, _Symbol, ask, NormalizeDouble(sl,_Digits), tp, "S14_BUY"))
         todayTrades++;
   }
   else
   {
      double sl   = h1 + atr * SL_ATR_Mult;
      double dist = sl - bid;
      if(dist <= 0) return;
      double tp   = NormalizeDouble(bid - dist * RR, _Digits);
      double lot  = CalcLot(dist);
      if(trade.Sell(lot, _Symbol, bid, NormalizeDouble(sl,_Digits), tp, "S14_SELL"))
         todayTrades++;
   }
}
