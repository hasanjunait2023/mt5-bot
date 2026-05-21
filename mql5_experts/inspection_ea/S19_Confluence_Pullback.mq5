//+------------------------------------------------------------------+
//| Strategy 19 — Confluence Pullback Portfolio (CPP-FX)             |
//| EURUSD / GBPUSD / USDJPY · M15 trade TF + H1 trend · Risk 1%     |
//|                                                                  |
//| MT5-native mirror of trading_agents/strategies/confluence_       |
//| pullback.py — backtest == demo == EA. Pullback-in-strong-trend,  |
//| strict fixed 1:2. Backtest (2y MT5): USDJPY WR 48.6% PF 1.84,    |
//| GBPUSD PF 1.23, EURUSD PF 1.13.                                  |
//|                                                                  |
//| Entry (BUY; SELL = mirror), on the last CLOSED M15 bar (shift1): |
//|   1 H1 trend  : Close[1] > H1_EMA200                              |
//|   2 Strength  : ADX[1] >= ADX_Min  (the core edge)               |
//|   3 +DI[1] > -DI[1]                                               |
//|   4 Pullback  : |Close[1]-EMA21[1]| <= Pullback_ATR * ATR[1]      |
//|   5 Stoch deep cross: K[2]<StochOS, K[2]<=D[2], K[1]>D[1]         |
//|   6 RSI[1] in [RSI_BuyLo, RSI_BuyHi]                              |
//|   7 Candle  : Close[1]>Open[1] and body >= MinBody*range          |
//|   8 Session : UTC hour in London/NY windows                       |
//| Exit : SL = SL_ATR*ATR ; TP = entry +/- 2*SLdist  (strict 1:2).  |
//|                                                                  |
//| Run alongside the Python cpp_live_trader (different magic) or     |
//| standalone. Gold/Silver stay on S1/S15/S18.                       |
//+------------------------------------------------------------------+
#property copyright "FxVault"
#property version   "1.00"
#include <Trade\Trade.mqh>

input double RiskPct      = 1.0;
input double ADX_Min      = 22.0;
input double Pullback_ATR = 0.6;
input double StochOS      = 25.0;   // K[2] below this for BUY
input double StochOB      = 75.0;   // K[2] above this for SELL
input double RSI_BuyLo    = 40.0;
input double RSI_BuyHi    = 68.0;
input double RSI_SellLo   = 32.0;
input double RSI_SellHi   = 60.0;
input double MinBodyFrac  = 0.30;
input double SL_ATR       = 1.5;
input double RR           = 2.0;    // strict 1:2
input int    Max_Spread   = 30;     // points (FX)
input int    MaxTradesDay = 6;
input long   MagicNumber  = 20261900;

CTrade trade;
int hEma21, hEmaH1, hRsi, hAtr, hAdx, hStoch;
datetime lastBar = 0, today = 0;
int todayTrades = 0;

int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(15);
   hEma21 = iMA(_Symbol, PERIOD_M15, 21, 0, MODE_EMA, PRICE_CLOSE);
   hEmaH1 = iMA(_Symbol, PERIOD_H1, 200, 0, MODE_EMA, PRICE_CLOSE);
   hRsi   = iRSI(_Symbol, PERIOD_M15, 14, PRICE_CLOSE);
   hAtr   = iATR(_Symbol, PERIOD_M15, 14);
   hAdx   = iADX(_Symbol, PERIOD_M15, 14);
   hStoch = iStochastic(_Symbol, PERIOD_M15, 14, 3, 3, MODE_SMA, STO_LOWHIGH);
   if(hEma21==INVALID_HANDLE || hEmaH1==INVALID_HANDLE || hRsi==INVALID_HANDLE ||
      hAtr==INVALID_HANDLE || hAdx==INVALID_HANDLE || hStoch==INVALID_HANDLE)
      return INIT_FAILED;
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) {}

double CalcLot(double sl_dist)
{
   double eq      = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk    = eq * RiskPct / 100.0;
   double tickval = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ticksz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double step    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double mn      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(sl_dist <= 0 || ticksz <= 0) return mn;
   double raw = risk / (sl_dist / ticksz * tickval);
   double cap = (eq * 0.02) / (sl_dist / ticksz * tickval);   // 2% hard cap
   double lot = MathFloor(raw / step) * step;
   return MathMax(mn, MathMin(MathMin(mx, cap), lot));
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

bool InSession()
{
   MqlDateTime tm; TimeGMT(tm);
   int h = tm.hour;
   return (h >= 7 && h < 12) || (h >= 13 && h < 17);
}

void OnTick()
{
   CheckDailyReset();

   datetime b = iTime(_Symbol, PERIOD_M15, 0);
   if(b == lastBar) return;
   lastBar = b;

   if(HavePosition() || todayTrades >= MaxTradesDay) return;
   if(!InSession()) return;

   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) -
                    SymbolInfoDouble(_Symbol, SYMBOL_BID)) / _Point;
   if(spread > Max_Spread) return;

   double e21[], eH1[], rsi[], at[], adx[], pdi[], mdi[], k[], d[];
   ArraySetAsSeries(e21,true); ArraySetAsSeries(eH1,true);
   ArraySetAsSeries(rsi,true); ArraySetAsSeries(at,true);
   ArraySetAsSeries(adx,true); ArraySetAsSeries(pdi,true);
   ArraySetAsSeries(mdi,true); ArraySetAsSeries(k,true);
   ArraySetAsSeries(d,true);
   if(CopyBuffer(hEma21, 0, 0, 3, e21) < 3) return;
   if(CopyBuffer(hEmaH1, 0, 0, 3, eH1) < 3) return;
   if(CopyBuffer(hRsi,   0, 0, 3, rsi) < 3) return;
   if(CopyBuffer(hAtr,   0, 0, 3, at)  < 3) return;
   if(CopyBuffer(hAdx,   0, 0, 3, adx) < 3) return;
   if(CopyBuffer(hAdx,   1, 0, 3, pdi) < 3) return;
   if(CopyBuffer(hAdx,   2, 0, 3, mdi) < 3) return;
   if(CopyBuffer(hStoch, 0, 0, 3, k)   < 3) return;
   if(CopyBuffer(hStoch, 1, 0, 3, d)   < 3) return;

   double atr = at[1];
   if(atr <= 0) return;
   if(adx[1] < ADX_Min) return;                        // strong-trend gate

   double c1 = iClose(_Symbol, PERIOD_M15, 1);
   double o1 = iOpen (_Symbol, PERIOD_M15, 1);
   double h1 = iHigh (_Symbol, PERIOD_M15, 1);
   double lw1= iLow  (_Symbol, PERIOD_M15, 1);
   double rng = MathMax(h1 - lw1, _Point);
   double body= MathAbs(c1 - o1) / rng;

   bool up   = c1 > eH1[1];
   bool pull = MathAbs(c1 - e21[1]) <= Pullback_ATR * atr;
   bool buyX = (k[2] < StochOS) && (k[2] <= d[2]) && (k[1] > d[1]) && pdi[1] > mdi[1];
   bool selX = (k[2] > StochOB) && (k[2] >= d[2]) && (k[1] < d[1]) && mdi[1] > pdi[1];

   bool buy  = up  && pull && buyX &&
               rsi[1] >= RSI_BuyLo  && rsi[1] <= RSI_BuyHi &&
               c1 > o1 && body >= MinBodyFrac;
   bool sell = !up && pull && selX &&
               rsi[1] >= RSI_SellLo && rsi[1] <= RSI_SellHi &&
               c1 < o1 && body >= MinBodyFrac;
   if(!buy && !sell) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sld = SL_ATR * atr;

   if(buy)
   {
      double sl = NormalizeDouble(ask - sld, _Digits);
      double tp = NormalizeDouble(ask + RR * sld, _Digits);
      double lot= CalcLot(sld);
      if(trade.Buy(lot, _Symbol, ask, sl, tp, "S19_BUY")) todayTrades++;
   }
   else
   {
      double sl = NormalizeDouble(bid + sld, _Digits);
      double tp = NormalizeDouble(bid - RR * sld, _Digits);
      double lot= CalcLot(sld);
      if(trade.Sell(lot, _Symbol, bid, sl, tp, "S19_SELL")) todayTrades++;
   }
}
