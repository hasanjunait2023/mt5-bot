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
//|   STRENGTH SOURCE: the MT5 Strategy Tester's local agent cannot |
//|   sync 28 cross-symbols, so strength is read from a precomputed  |
//|   CSV (Common\Files\strength_h1.csv, from export_strength_csv.py |
//|   — same engine as the live agent). If the CSV is absent the EA  |
//|   falls back to live multi-symbol CopyClose (works on a live     |
//|   chart, not in the tester).                                     |
//+------------------------------------------------------------------+
#property copyright "mt5-bot"
#property version   "1.10"
#property strict

#include <Trade/Trade.mqh>

// Defaults = validated config (2yr MT5 Strategy Tester: USDJPY PF 1.44,
// GBPUSD 1.47, EURJPY 1.34). MinDiff=3 / RR=1.5 FAILED the gate (PF<1.3).
input double InpRiskPct      = 1.0;     // Risk % of equity per trade
input int    InpMinDiff      = 5;       // Min |strength[base]-strength[quote]|
input double InpSlAtr        = 1.5;     // SL = InpSlAtr * ATR(14)
input double InpTpRR         = 2.0;     // TP = InpTpRR * SL distance
input double InpAdrUsedMax   = 0.70;    // Skip if today's range > this fraction of ADR
input double InpAtrExpansion = 1.20;    // ATR(14) must exceed this * SMA50(ATR)
input int    InpRsiBuyLo     = 50;
input int    InpRsiBuyHi     = 70;
input int    InpRsiSellLo    = 30;
input int    InpRsiSellHi    = 50;
input int    InpSessionWin   = 6;       // trailing H1 bars for the strength window
input string InpStrengthCsv  = "strength_h1.csv"; // in Common\Files
input string InpSuffix       = "";      // broker symbol suffix (auto-detected)
input long   InpMagic        = 20260900;

CTrade   trade;
string   gSuffix      = "";
int      hEma9, hEma15, hEma200, hRsi, hAtr;

string   CCY[8] = {"USD","EUR","GBP","JPY","AUD","NZD","CAD","CHF"};
string   gRoot[28] = {
   "EURUSD","GBPUSD","AUDUSD","NZDUSD","USDJPY","USDCAD","USDCHF",
   "EURGBP","EURJPY","EURCHF","EURAUD","EURNZD","EURCAD",
   "GBPJPY","GBPCHF","GBPAUD","GBPNZD","GBPCAD",
   "AUDJPY","AUDNZD","AUDCAD","AUDCHF",
   "NZDJPY","NZDCAD","NZDCHF",
   "CADJPY","CADCHF","CHFJPY"
};
int      gBase[28], gQuote[28];

// strength CSV cache
datetime gT[];
int      gSc[][8];
int      gN = 0;
bool     gHaveCsv = false;

datetime gLastBar = 0;

//+------------------------------------------------------------------+
int CcyIndex(string c){ for(int i=0;i<8;i++) if(CCY[i]==c) return i; return -1; }

//+------------------------------------------------------------------+
bool LoadStrengthCsv()
{
   int fh = FileOpen(InpStrengthCsv, FILE_READ|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh==INVALID_HANDLE) return false;
   // header: time,USD,EUR,GBP,JPY,AUD,NZD,CAD,CHF
   for(int k=0;k<9 && !FileIsLineEnding(fh);k++) FileReadString(fh);
   int cap = 1024;
   ArrayResize(gT, cap);
   ArrayResize(gSc, cap);
   gN = 0;
   while(!FileIsEnding(fh))
   {
      long t = (long)StringToInteger(FileReadString(fh));
      if(t<=0){ // consume rest of line
         while(!FileIsLineEnding(fh) && !FileIsEnding(fh)) FileReadString(fh);
         continue;
      }
      if(gN>=cap){ cap*=2; ArrayResize(gT,cap); ArrayResize(gSc,cap); }
      gT[gN] = (datetime)t;
      for(int c=0;c<8;c++) gSc[gN][c] = (int)StringToInteger(FileReadString(fh));
      gN++;
   }
   FileClose(fh);
   ArrayResize(gT, gN);
   ArrayResize(gSc, gN);
   PrintFormat("Strength CSV loaded: %d rows (%s..%s)", gN,
               (gN>0?TimeToString(gT[0]):"-"), (gN>0?TimeToString(gT[gN-1]):"-"));
   return gN>0;
}

//+------------------------------------------------------------------+
int StrengthIndex(datetime t)
{
   int lo=0, hi=gN-1, res=-1;
   while(lo<=hi){ int mid=(lo+hi)/2; if(gT[mid]<=t){res=mid; lo=mid+1;} else hi=mid-1; }
   return res;
}

//+------------------------------------------------------------------+
//| Live multi-symbol fallback (for running on a live chart).        |
//+------------------------------------------------------------------+
void ComputeStrengthLive(int &score[])
{
   ArrayResize(score,8); ArrayInitialize(score,0);
   double eps = 2e-4;
   for(int i=0;i<28;i++)
   {
      string sym = gRoot[i] + gSuffix;
      double c[]; ArraySetAsSeries(c,true);
      int got = CopyClose(sym, PERIOD_H1, 1, InpSessionWin, c);
      if(got<2) continue;
      double first=c[got-1], last=c[0];
      if(first==0) continue;
      double ret=(last-first)/MathAbs(first);
      int v = (ret>eps)?1:((ret<-eps)?-1:0);
      if(v!=0){ if(gBase[i]>=0) score[gBase[i]]+=v; if(gQuote[i]>=0) score[gQuote[i]]-=v; }
   }
}

//+------------------------------------------------------------------+
//| Strength for chart base/quote at a given time → diff.            |
//+------------------------------------------------------------------+
bool StrengthDiff(datetime t, int &diff)
{
   int bi=CcyIndex(StringSubstr(_Symbol,0,3));
   int qi=CcyIndex(StringSubstr(_Symbol,3,3));
   if(bi<0||qi<0) return false;
   if(gHaveCsv)
   {
      int idx = StrengthIndex(t);
      if(idx<0) return false;
      diff = gSc[idx][bi]-gSc[idx][qi];
      return true;
   }
   int sc[]; ComputeStrengthLive(sc);
   diff = sc[bi]-sc[qi];
   return true;
}

//+------------------------------------------------------------------+
int OnInit()
{
   gSuffix = InpSuffix;
   if(gSuffix=="" && StringLen(_Symbol)>6) gSuffix = StringSubstr(_Symbol,6);

   for(int i=0;i<28;i++)
   {
      gBase[i]  = CcyIndex(StringSubstr(gRoot[i],0,3));
      gQuote[i] = CcyIndex(StringSubstr(gRoot[i],3,3));
   }

   gHaveCsv = LoadStrengthCsv();
   if(!gHaveCsv) Print("strength_h1.csv not found in Common\\Files — using live CopyClose (won't work in tester)");

   hEma9   = iMA(_Symbol, PERIOD_M3, 9,   0, MODE_EMA, PRICE_CLOSE);
   hEma15  = iMA(_Symbol, PERIOD_M3, 15,  0, MODE_EMA, PRICE_CLOSE);
   hEma200 = iMA(_Symbol, PERIOD_M3, 200, 0, MODE_EMA, PRICE_CLOSE);
   hRsi    = iRSI(_Symbol, PERIOD_M3, 14, PRICE_CLOSE);
   hAtr    = iATR(_Symbol, PERIOD_M3, 14);
   if(hEma9==INVALID_HANDLE||hEma15==INVALID_HANDLE||hEma200==INVALID_HANDLE||
      hRsi==INVALID_HANDLE||hAtr==INVALID_HANDLE) return(INIT_FAILED);

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
double AdrUsedFrac()
{
   double dh[], dl[]; ArraySetAsSeries(dh,true); ArraySetAsSeries(dl,true);
   if(CopyHigh(_Symbol,PERIOD_D1,0,16,dh)<16) return 0.0;
   if(CopyLow(_Symbol, PERIOD_D1,0,16,dl)<16) return 0.0;
   double sum=0; for(int s=1;s<=14;s++) sum+=(dh[s]-dl[s]);
   double adr=sum/14.0;
   if(adr<=0) return 0.0;
   return (dh[0]-dl[0])/adr;
}

//+------------------------------------------------------------------+
bool CrossedWithin2(int direction)
{
   double e9[], e15[]; ArraySetAsSeries(e9,true); ArraySetAsSeries(e15,true);
   if(CopyBuffer(hEma9,0,0,5,e9)<5) return false;
   if(CopyBuffer(hEma15,0,0,5,e15)<5) return false;
   for(int sh=1; sh<=2; sh++)
   {
      double prevd=e9[sh+1]-e15[sh+1], curd=e9[sh]-e15[sh];
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
      if(PositionGetTicket(i)==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol &&
         (long)PositionGetInteger(POSITION_MAGIC)==InpMagic) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
double CalcLots(double slDistance)
{
   if(slDistance<=0) return 0.0;
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   double riskUsd=equity*InpRiskPct/100.0;
   double tickVal=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   double tickSize=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(tickVal<=0||tickSize<=0) return 0.0;
   double valuePerLot=(slDistance/tickSize)*tickVal;
   if(valuePerLot<=0) return 0.0;
   double lots=riskUsd/valuePerLot;
   double maxByEquity=(equity*0.02)/valuePerLot;
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   double vmin=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double vmax=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   lots=MathFloor(lots/step)*step;
   lots=MathMax(vmin, MathMin(lots, MathMin(vmax, maxByEquity)));
   return NormalizeDouble(lots,2);
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime t = iTime(_Symbol, PERIOD_M3, 0);
   if(t==gLastBar) return;
   gLastBar = t;
   if(HasOpenPosition()) return;
   if(Bars(_Symbol, PERIOD_M3) < 260) return;

   datetime barT = iTime(_Symbol, PERIOD_M3, 1);   // last completed bar
   int diff;
   if(!StrengthDiff(barT, diff)) return;
   if(MathAbs(diff) < InpMinDiff) return;
   int dir = (diff>0)? 1 : -1;

   if(AdrUsedFrac() > InpAdrUsedMax) return;

   double atrBuf[]; ArraySetAsSeries(atrBuf,true);
   if(CopyBuffer(hAtr,0,0,60,atrBuf)<55) return;
   double atrNow=atrBuf[1];
   double sma=0; for(int s=1;s<=50;s++) sma+=atrBuf[s]; sma/=50.0;
   if(sma<=0 || atrNow < InpAtrExpansion*sma || atrNow<=0) return;

   double e200[], rsiBuf[], cl[];
   ArraySetAsSeries(e200,true); ArraySetAsSeries(rsiBuf,true); ArraySetAsSeries(cl,true);
   if(CopyBuffer(hEma200,0,0,3,e200)<3) return;
   if(CopyBuffer(hRsi,0,0,3,rsiBuf)<3) return;
   if(CopyClose(_Symbol,PERIOD_M3,0,3,cl)<3) return;
   double price=cl[1], rsi=rsiBuf[1];

   bool ok;
   if(dir==1) ok=(price>e200[1] && CrossedWithin2(1)  && rsi>=InpRsiBuyLo  && rsi<=InpRsiBuyHi);
   else       ok=(price<e200[1] && CrossedWithin2(-1) && rsi>=InpRsiSellLo && rsi<=InpRsiSellHi);
   if(!ok) return;

   double slDist=InpSlAtr*atrNow, tpDist=InpTpRR*slDist;
   double lots=CalcLots(slDist);
   if(lots<=0) return;
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK), bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   int dig=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   if(dir==1)
      trade.Buy(lots,_Symbol,ask,NormalizeDouble(ask-slDist,dig),NormalizeDouble(ask+tpDist,dig),"M3Strength");
   else
      trade.Sell(lots,_Symbol,bid,NormalizeDouble(bid+slDist,dig),NormalizeDouble(bid-tpDist,dig),"M3Strength");
}
//+------------------------------------------------------------------+
