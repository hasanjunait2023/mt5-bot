//+------------------------------------------------------------------+
//| Strategy 13 — 5-Way Confluence Premium  (Notion #1 WINNER)       |
//| BTCUSD · H1 · Risk 1.0%                                          |
//|                                                                  |
//| Notion backtest (Yahoo BTC-USD, 60d H1): 3/3 wins, +7.72%,       |
//|   PF inf, 0% DD.  SMALL SAMPLE — Notion itself states realistic  |
//|   live expectation is 70-80% WR, not 100%. Treat as A+-only,     |
//|   low-frequency (3-5 signals/month).                             |
//|                                                                  |
//| Entry needs ALL 5 (BUY; SELL = mirror):                           |
//|   1 EMA9>EMA20>EMA50>EMA200                                       |
//|   2 (EMA9-EMA50)/Close > 0.003   (trend-strength spread)          |
//|   3 MACD>0 AND MACD>Signal AND Hist rising (shift1>shift2)        |
//|   4 RSI in 45-65 (BUY) / 35-55 (SELL)                             |
//|   5 near EMA20 (|C-EMA20|/C < 0.005) AND body>50% range AND       |
//|     close in trade direction                                     |
//| Exit : SL = EMA50 price level , TP = entry + (entry-SL)*2.5       |
//|        (fixed; backtest used fixed SL/TP → live == tested).       |
//|                                                                  |
//| MOD: SL=EMA50 can collapse to ~0 when price hugs EMA50, which     |
//|   would size an enormous lot. MinSL_ATRfrac floors the SL        |
//|   distance at a fraction of ATR(14) as a safety rail.            |
//| Decisions on CLOSED H1 bars (shift1=last closed, shift2=prev).   |
//| Source spec: Notion 364bbf27-1afa-818a-8d9c-c731bbb56d81.        |
//+------------------------------------------------------------------+
#property copyright "FxVault"
#property version   "1.00"
#include <Trade\Trade.mqh>

input double RiskPct        = 1.0;
input double SpreadMinFrac  = 0.003;  // (EMA9-EMA50)/Close threshold
input double NearEMA20Frac  = 0.005;  // |Close-EMA20|/Close max
input double BodyMinFrac    = 0.50;   // candle body / range min
input double MinSL_ATRfrac  = 0.50;   // SL floor = ATR(14)*this (safety)
input double RR             = 2.5;
input int    Max_Spread     = 400;    // points; BTC spreads are wide
input int    MaxTradesDay   = 3;
input long   MagicNumber    = 20261300;

CTrade trade;
int ema9, ema20, ema50, ema200, macdH, rsiH, atrH;
double pip;
datetime lastH1Bar = 0;
datetime today     = 0;
int      todayTrades = 0;

int OnInit()
{
   pip = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(50);
   ema9   = iMA(_Symbol, PERIOD_H1,   9, 0, MODE_EMA, PRICE_CLOSE);
   ema20  = iMA(_Symbol, PERIOD_H1,  20, 0, MODE_EMA, PRICE_CLOSE);
   ema50  = iMA(_Symbol, PERIOD_H1,  50, 0, MODE_EMA, PRICE_CLOSE);
   ema200 = iMA(_Symbol, PERIOD_H1, 200, 0, MODE_EMA, PRICE_CLOSE);
   macdH  = iMACD(_Symbol, PERIOD_H1, 12, 26, 9, PRICE_CLOSE);
   rsiH   = iRSI(_Symbol, PERIOD_H1, 14, PRICE_CLOSE);
   atrH   = iATR(_Symbol, PERIOD_H1, 14);
   if(ema9==INVALID_HANDLE || ema20==INVALID_HANDLE || ema50==INVALID_HANDLE ||
      ema200==INVALID_HANDLE || macdH==INVALID_HANDLE || rsiH==INVALID_HANDLE ||
      atrH==INVALID_HANDLE) return INIT_FAILED;
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

   double e9[], e20[], e50[], e200[], mc[], sg[], rs[], at[];
   ArraySetAsSeries(e9,true);  ArraySetAsSeries(e20,true);
   ArraySetAsSeries(e50,true); ArraySetAsSeries(e200,true);
   ArraySetAsSeries(mc,true);  ArraySetAsSeries(sg,true);
   ArraySetAsSeries(rs,true);  ArraySetAsSeries(at,true);
   if(CopyBuffer(ema9,  0, 0, 3, e9)   < 3) return;
   if(CopyBuffer(ema20, 0, 0, 3, e20)  < 3) return;
   if(CopyBuffer(ema50, 0, 0, 3, e50)  < 3) return;
   if(CopyBuffer(ema200,0, 0, 3, e200) < 3) return;
   if(CopyBuffer(macdH, 0, 0, 3, mc)   < 3) return;   // 0 = MACD main
   if(CopyBuffer(macdH, 1, 0, 3, sg)   < 3) return;   // 1 = signal
   if(CopyBuffer(rsiH,  0, 0, 3, rs)   < 3) return;
   if(CopyBuffer(atrH,  0, 0, 3, at)   < 3) return;

   double o1 = iOpen (_Symbol, PERIOD_H1, 1);
   double h1 = iHigh (_Symbol, PERIOD_H1, 1);
   double l1 = iLow  (_Symbol, PERIOD_H1, 1);
   double c1 = iClose(_Symbol, PERIOD_H1, 1);
   double rng = h1 - l1;
   if(rng <= 0 || c1 <= 0) return;
   double body = MathAbs(c1 - o1);

   double hist1 = mc[1] - sg[1];
   double hist2 = mc[2] - sg[2];

   bool stack_up   = e9[1] > e20[1] && e20[1] > e50[1] && e50[1] > e200[1];
   bool stack_dn   = e9[1] < e20[1] && e20[1] < e50[1] && e50[1] < e200[1];
   bool spread_up  = (e9[1] - e50[1]) / c1 > SpreadMinFrac;
   bool spread_dn  = (e50[1] - e9[1]) / c1 > SpreadMinFrac;
   bool macd_bull  = mc[1] > 0 && mc[1] > sg[1] && hist1 > hist2;
   bool macd_bear  = mc[1] < 0 && mc[1] < sg[1] && hist1 < hist2;
   bool rsi_buy    = rs[1] > 45 && rs[1] < 65;
   bool rsi_sell   = rs[1] > 35 && rs[1] < 55;
   bool near20     = MathAbs(c1 - e20[1]) / c1 < NearEMA20Frac;
   bool strong     = body > rng * BodyMinFrac;

   bool buy  = stack_up && spread_up && macd_bull && rsi_buy &&
               near20 && strong && c1 > o1;
   bool sell = stack_dn && spread_dn && macd_bear && rsi_sell &&
               near20 && strong && c1 < o1;
   if(!buy && !sell) return;

   double atr     = at[1];
   double ask     = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid     = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double minSL   = atr * MinSL_ATRfrac;

   if(buy)
   {
      double sl = e50[1];                              // SL at EMA50 level
      double dist = ask - sl;
      if(dist < minSL) dist = minSL;                   // safety floor
      sl = NormalizeDouble(ask - dist, _Digits);
      double tp = NormalizeDouble(ask + dist * RR, _Digits);
      double lot = CalcLot(dist);
      if(trade.Buy(lot, _Symbol, ask, sl, tp, "S13_BUY"))
         todayTrades++;
   }
   else
   {
      double sl = e50[1];
      double dist = sl - bid;
      if(dist < minSL) dist = minSL;
      sl = NormalizeDouble(bid + dist, _Digits);
      double tp = NormalizeDouble(bid - dist * RR, _Digits);
      double lot = CalcLot(dist);
      if(trade.Sell(lot, _Symbol, bid, sl, tp, "S13_SELL"))
         todayTrades++;
   }
}
