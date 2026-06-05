//+------------------------------------------------------------------+
//|                                          M3_StrengthScalp.mq5     |
//|   Currency-Strength biased M3 EMA/RSI scalper (GS13).            |
//|                                                                  |
//|   Mirrors trading_agents/scalp/m3strength_agent.py:             |
//|   - Strength: net-pair-win -7..+7 per major from 28 pairs (H1,  |
//|     trailing 6-bar session window), bias = sign(base-quote),    |
//|     trade only when |diff| >= MinDiff.                          |
//|   - Momentum gate: ADR not exhausted (<70% used) + M3 ATR(14)   |
//|     expanding vs its 50-bar SMA.                                |
//|   - Entry: EMA200 trend + 9/15 cross within 2 bars + RSI band,  |
//|     bias-aligned. SL=1.5*ATR, TP=1.5R. Risk = RiskPct of equity.|
//|                                                                  |
//|   Trades the CHART symbol only; reads the other 27 for strength.|
//|   Run the Strategy Tester once per pair you want validated.     |
//+------------------------------------------------------------------+
#property copyright "mt5-bot"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

input double InpRiskPct      = 1.0;     // Risk % of equity per trade
input int    InpMinDiff      = 3;       // Min |strength[base]-strength[quote]|
input double InpSlAtr        = 1.5;     // SL = InpSlAtr * ATR(14)
input double InpTpRR         = 1.5;     // TP = InpTpRR * SL distance
input double InpAdrUsedMax   = 0.70;    // Skip if today's range > this fraction of ADR
input double InpAtrExpansion = 1.10;    // ATR(14) must exceed this * SMA50(ATR)
input int    InpRsiBuyLo     = 50;
input int    InpRsiBuyHi     = 70;
input int    InpRsiSellLo    = 30;
input int    InpRsiSellHi    = 50;
input int    InpSessionWin   = 6;       // trailing H1 bars for the strength window
input string InpSuffix       = "";      // broker symbol suffix (auto-detected if empty)
input long   InpMagic        = 20260900;

CTrade   trade;
string   gSuffix      = "";
int      hEma9, hEma15, hEma200, hRsi, hAtr;

// 8 majors
string   CCY[8] = {"USD","EUR","GBP","JPY","AUD","NZD","CAD","CHF"};
// 28 pairs as currency-index pairs (base,quote) in conventional quote order.
int      gBase[28], gQuote[28];
string   gRoot[28] = {
   "EURUSD","GBPUSD","AUDUSD","NZDUSD","USDJPY","USDCAD","USDCHF",
   "EURGBP","EURJPY","EURCHF","EURAUD","EURNZD","EURCAD",
   "GBPJPY","GBPCHF","GBPAUD","GBPNZD","GBPCAD",
   "AUDJPY","AUDNZD","AUDCAD","AUDCHF",
   "NZDJPY","NZDCAD","NZDCHF",
   "CADJPY","CADCHF","CHFJPY"
};

datetime gLastBar = 0;

//+------------------------------------------------------------------+
int CcyIndex(string c)
{
   for(int i=0;i<8;i++) if(CCY[i]==c) return i;
   return -1;
}

//+------------------------------------------------------------------+
int OnInit()
{
   // Detect broker suffix from the chart symbol (e.g. "EURUSDm" -> "m").
   gSuffix = InpSuffix;
   if(gSuffix=="")
   {
      string s = _Symbol;
      if(StringLen(s) > 6) gSuffix = StringSubstr(s, 6);
   }

   for(int i=0;i<28;i++)
   {
      string root = gRoot[i];
      gBase[i]  = CcyIndex(StringSubstr(root,0,3));
      gQuote[i] = CcyIndex(StringSubstr(root,3,3));
   }

   hEma9   = iMA(_Symbol, PERIOD_M3, 9,   0, MODE_EMA, PRICE_CLOSE);
   hEma15  = iMA(_Symbol, PERIOD_M3, 15,  0, MODE_EMA, PRICE_CLOSE);
   hEma200 = iMA(_Symbol, PERIOD_M3, 200, 0, MODE_EMA, PRICE_CLOSE);
   hRsi    = iRSI(_Symbol, PERIOD_M3, 14, PRICE_CLOSE);
   hAtr    = iATR(_Symbol, PERIOD_M3, 14);

   if(hEma9==INVALID_HANDLE || hEma15==INVALID_HANDLE || hEma200==INVALID_HANDLE ||
      hRsi==INVALID_HANDLE  || hAtr==INVALID_HANDLE)
   {
      Print("Indicator handle init failed");
      return(INIT_FAILED);
   }

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Net-pair-win strength for all 8 majors (-7..+7).                 |
//+------------------------------------------------------------------+
bool ComputeStrength(int &score[])
{
   ArrayResize(score,8);
   ArrayInitialize(score,0);
   int win = InpSessionWin;
   double eps = 2e-4;

   for(int i=0;i<28;i++)
   {
      string sym = gRoot[i] + gSuffix;
      double c[];
      ArraySetAsSeries(c,true);
      // need win completed bars: copy from shift 1 (skip forming bar)
      int got = CopyClose(sym, PERIOD_H1, 1, win, c);
      if(got < 2) continue;                       // symbol missing/no data
      double first = c[got-1];                    // oldest in window
      double last  = c[0];                         // newest completed
      if(first==0) continue;
      double ret = (last-first)/MathAbs(first);
      int v = 0;
      if(ret >  eps) v = 1;
      else if(ret < -eps) v = -1;
      if(v!=0)
      {
         if(gBase[i]>=0)  score[gBase[i]]  += v;
         if(gQuote[i]>=0) score[gQuote[i]] -= v;
      }
   }
   return true;
}

//+------------------------------------------------------------------+
//| ADR-used fraction (today's D1 range / avg last 14 completed).    |
//+------------------------------------------------------------------+
double AdrUsedFrac()
{
   double dh[], dl[];
   ArraySetAsSeries(dh,true); ArraySetAsSeries(dl,true);
   if(CopyHigh(_Symbol, PERIOD_D1, 0, 16, dh) < 16) return 0.0;   // unknown -> allow
   if(CopyLow(_Symbol,  PERIOD_D1, 0, 16, dl) < 16) return 0.0;
   double sum=0; int n=0;
   for(int s=1; s<=14; s++) { sum += (dh[s]-dl[s]); n++; }
   double adr = (n>0)? sum/n : 0.0;
   if(adr<=0) return 0.0;
   double today = dh[0]-dl[0];
   return today/adr;
}

//+------------------------------------------------------------------+
bool CrossedWithin2(int direction)
{
   double e9[], e15[];
   ArraySetAsSeries(e9,true); ArraySetAsSeries(e15,true);
   if(CopyBuffer(hEma9, 0, 0, 5, e9) < 5)  return false;
   if(CopyBuffer(hEma15,0, 0, 5, e15) < 5) return false;
   // check cross at completed shift 1 and 2
   for(int sh=1; sh<=2; sh++)
   {
      double prevd = e9[sh+1]-e15[sh+1];
      double curd  = e9[sh]  -e15[sh];
      if(direction==1  && prevd<0 && curd>=0) return true;
      if(direction==-1 && prevd>0 && curd<=0) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
bool HasOpenPosition()
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol &&
         (long)PositionGetInteger(POSITION_MAGIC)==InpMagic)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
double CalcLots(double slDistance)
{
   if(slDistance<=0) return 0.0;
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskUsd  = equity * InpRiskPct / 100.0;
   double tickVal  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal<=0 || tickSize<=0) return 0.0;
   double valuePerLot = (slDistance/tickSize)*tickVal;
   if(valuePerLot<=0) return 0.0;
   double lots = riskUsd/valuePerLot;
   double maxByEquity = (equity*0.02)/valuePerLot;     // 2% cap
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   lots = MathFloor(lots/step)*step;
   lots = MathMax(vmin, MathMin(lots, MathMin(vmax, maxByEquity)));
   return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
void OnTick()
{
   // act once per new completed M3 bar
   datetime t = iTime(_Symbol, PERIOD_M3, 0);
   if(t==gLastBar) return;
   gLastBar = t;

   if(HasOpenPosition()) return;

   // Bars warmup
   if(Bars(_Symbol, PERIOD_M3) < 260) return;

   // 1. strength bias
   int score[];
   if(!ComputeStrength(score)) return;
   int bi = CcyIndex(StringSubstr(_Symbol,0,3));
   int qi = CcyIndex(StringSubstr(_Symbol,3,3));
   if(bi<0 || qi<0) return;
   int diff = score[bi]-score[qi];
   if(MathAbs(diff) < InpMinDiff) return;
   int dir = (diff>0)? 1 : -1;   // BUY/SELL

   // 2. momentum gate
   if(AdrUsedFrac() > InpAdrUsedMax) return;

   double atrBuf[];
   ArraySetAsSeries(atrBuf,true);
   if(CopyBuffer(hAtr, 0, 0, 60, atrBuf) < 55) return;
   double atrNow = atrBuf[1];                       // completed bar ATR
   double sma=0; for(int s=1;s<=50;s++) sma+=atrBuf[s]; sma/=50.0;
   if(sma<=0 || atrNow < InpAtrExpansion*sma) return;
   if(atrNow<=0) return;

   // 3. entry filters on completed bar (shift 1)
   double e200[], rsiBuf[], cl[];
   ArraySetAsSeries(e200,true); ArraySetAsSeries(rsiBuf,true); ArraySetAsSeries(cl,true);
   if(CopyBuffer(hEma200, 0, 0, 3, e200) < 3) return;
   if(CopyBuffer(hRsi,    0, 0, 3, rsiBuf) < 3) return;
   if(CopyClose(_Symbol, PERIOD_M3, 0, 3, cl) < 3) return;
   double price = cl[1];
   double rsi   = rsiBuf[1];

   bool ok=false;
   if(dir==1)
      ok = (price>e200[1] && CrossedWithin2(1)  && rsi>=InpRsiBuyLo  && rsi<=InpRsiBuyHi);
   else
      ok = (price<e200[1] && CrossedWithin2(-1) && rsi>=InpRsiSellLo && rsi<=InpRsiSellHi);
   if(!ok) return;

   // 4. order
   double slDist = InpSlAtr*atrNow;
   double tpDist = InpTpRR*slDist;
   double lots = CalcLots(slDist);
   if(lots<=0) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int    dig = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   if(dir==1)
   {
      double sl = NormalizeDouble(ask - slDist, dig);
      double tp = NormalizeDouble(ask + tpDist, dig);
      trade.Buy(lots, _Symbol, ask, sl, tp, "M3Strength");
   }
   else
   {
      double sl = NormalizeDouble(bid + slDist, dig);
      double tp = NormalizeDouble(bid - tpDist, dig);
      trade.Sell(lots, _Symbol, bid, sl, tp, "M3Strength");
   }
}
//+------------------------------------------------------------------+
