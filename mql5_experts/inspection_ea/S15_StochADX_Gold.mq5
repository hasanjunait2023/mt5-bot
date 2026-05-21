//+------------------------------------------------------------------+
//| Strategy 15 IMPROVED — Stoch Deep Cross + ADX  (Notion #5)       |
//| XAUUSD · H1 · Risk 1.0%   ── PROFIT-FACTOR CHAMPION (PF 4.81)    |
//|                                                                  |
//| Notion backtest (Yahoo XAUUSD H1): WR 50% · +29.25% · PF 4.81 ·  |
//|   maxDD 3.06% · 8 trades. ADX filter doubled PF vs base S15.     |
//|                                                                  |
//| Entry (BUY; SELL = mirror):                                       |
//|   0 ADX[1] >= 25  (only trade strong trends — the whole edge)     |
//|   1 +DI[1] > -DI[1]                                               |
//|   2 Stoch deep cross: K[2]<=D[2], K[1]>D[1], K[2]<25              |
//|   3 Close[1] > EMA50[1]                                           |
//| Exit : SL = Low[1] - ATR*0.3 (BUY) / High[1] + ATR*0.3 (SELL)     |
//|        TP = entry +/- SLdist*2.5  (fixed; live == tested).        |
//|                                                                  |
//| Decisions on CLOSED H1 bars (shift1=last closed, shift2=prev).   |
//| Source spec: Notion 364bbf27-1afa-8151-ac14-e394f4e2c477.        |
//+------------------------------------------------------------------+
#property copyright "FxVault"
#property version   "1.00"
#include <Trade\Trade.mqh>

input double RiskPct       = 1.0;
input double ADX_Min        = 25.0;
input double StochDeepBuy   = 25.0;  // K[2] below this for BUY
input double StochDeepSell  = 75.0;  // K[2] above this for SELL
input double SL_ATR_Mult    = 0.3;
input double RR             = 2.5;
input int    Max_Spread     = 60;    // points (Gold)
input int    MaxTradesDay   = 3;
input long   MagicNumber    = 20261500;

CTrade trade;
int ema50, stochH, adxH, atrH;
double pip;
datetime lastH1Bar = 0;
datetime today     = 0;
int      todayTrades = 0;

int OnInit()
{
   pip = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   ema50  = iMA(_Symbol, PERIOD_H1, 50, 0, MODE_EMA, PRICE_CLOSE);
   stochH = iStochastic(_Symbol, PERIOD_H1, 14, 3, 3, MODE_SMA, STO_LOWHIGH);
   adxH   = iADX(_Symbol, PERIOD_H1, 14);
   atrH   = iATR(_Symbol, PERIOD_H1, 14);
   if(ema50==INVALID_HANDLE || stochH==INVALID_HANDLE ||
      adxH==INVALID_HANDLE || atrH==INVALID_HANDLE) return INIT_FAILED;
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

   double e50[], k[], d[], adx[], pdi[], mdi[], at[];
   ArraySetAsSeries(e50,true); ArraySetAsSeries(k,true);
   ArraySetAsSeries(d,true);   ArraySetAsSeries(adx,true);
   ArraySetAsSeries(pdi,true); ArraySetAsSeries(mdi,true);
   ArraySetAsSeries(at,true);
   if(CopyBuffer(ema50, 0, 0, 3, e50) < 3) return;
   if(CopyBuffer(stochH,0, 0, 3, k)   < 3) return;   // 0 = %K
   if(CopyBuffer(stochH,1, 0, 3, d)   < 3) return;   // 1 = %D
   if(CopyBuffer(adxH,  0, 0, 3, adx) < 3) return;   // 0 = ADX main
   if(CopyBuffer(adxH,  1, 0, 3, pdi) < 3) return;   // 1 = +DI
   if(CopyBuffer(adxH,  2, 0, 3, mdi) < 3) return;   // 2 = -DI
   if(CopyBuffer(atrH,  0, 0, 3, at)  < 3) return;

   // ADX strong-trend gate — this filter IS the strategy's edge
   if(adx[1] < ADX_Min) return;

   double l1  = iLow  (_Symbol, PERIOD_H1, 1);
   double h1  = iHigh (_Symbol, PERIOD_H1, 1);
   double c1  = iClose(_Symbol, PERIOD_H1, 1);
   double atr = at[1];
   if(atr <= 0) return;

   bool bull_cross = (k[2] <= d[2]) && (k[1] > d[1]) && (k[2] < StochDeepBuy);
   bool bear_cross = (k[2] >= d[2]) && (k[1] < d[1]) && (k[2] > StochDeepSell);

   bool strong_up = pdi[1] > mdi[1] && c1 > e50[1];
   bool strong_dn = mdi[1] > pdi[1] && c1 < e50[1];

   bool buy  = bull_cross && strong_up;
   bool sell = bear_cross && strong_dn;
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
      if(trade.Buy(lot, _Symbol, ask, NormalizeDouble(sl,_Digits), tp, "S15_BUY"))
         todayTrades++;
   }
   else
   {
      double sl   = h1 + atr * SL_ATR_Mult;
      double dist = sl - bid;
      if(dist <= 0) return;
      double tp   = NormalizeDouble(bid - dist * RR, _Digits);
      double lot  = CalcLot(dist);
      if(trade.Sell(lot, _Symbol, bid, NormalizeDouble(sl,_Digits), tp, "S15_SELL"))
         todayTrades++;
   }
}
