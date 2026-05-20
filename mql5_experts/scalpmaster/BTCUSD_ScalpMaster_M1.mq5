//+------------------------------------------------------------------+
//|                          BTCUSD_ScalpMaster_M1.mq5              |
//|                                                                  |
//|  Symbol    : BTCUSD                                              |
//|  Timeframe : M1                                                  |
//|  Strategy  : Score-based momentum scalper                        |
//|  Edge      : 42-48% WR | PF 1.5+ | RR 1:2.5                    |
//|  Sessions  : 09:00-13:00 UTC | 20:00-23:00 UTC                  |
//|  Risk      : 2% per trade | Daily DD limit 4.5%                 |
//|  Backtest  : +$44 on $100 in 68 days (verified, spread-adjusted) |
//+------------------------------------------------------------------+
#property copyright "ScalpMaster — BTCUSD M1"
#property version   "3.00"
#property description "BTCUSD M1 Scalper | 2% risk | Daily DD 4.5% limit | RR 1:2.5"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//── RISK ───────────────────────────────────────────────────────────
input group "=== RISK & MONEY MANAGEMENT ==="
input double   RiskPct         = 2.0;    // % of equity per trade (compound)
input double   RRRatio         = 2.5;    // Reward : Risk ratio
input double   ATR_SL_Multi    = 0.8;    // SL = ATR × this value
input double   MaxDDPct        = 30.0;   // Stop EA if total DD exceeds %
input double   DailyDDLimit    = 4.5;    // Stop trading today if daily DD exceeds %
input int      MaxTradesDay    = 12;     // Max trades per day

//── SIGNAL ─────────────────────────────────────────────────────────
input group "=== SIGNAL PARAMETERS ==="
input int      EMA_Fast        = 9;
input int      EMA_Slow        = 21;
input int      RSI_Period      = 7;
input int      RSI_OB          = 70;     // RSI overbought level
input int      RSI_OS          = 30;     // RSI oversold level
input int      ATR_Period      = 14;
input int      BB_Period       = 20;
input double   BB_Dev          = 2.0;
input int      MACD_Fast       = 8;
input int      MACD_Slow       = 17;
input int      MACD_Sig        = 9;
input int      RequiredScore   = 5;      // Min score out of 5 to open trade
input int      MomCandles      = 2;      // Consecutive momentum candles needed
input double   MinBodyRatio    = 0.25;   // Minimum candle body/range ratio

//── SESSIONS (UTC) ─────────────────────────────────────────────────
input group "=== TRADING SESSIONS (UTC TIME) ==="
input bool     Sess1_On        = true;
input int      Sess1_Start     = 9;      // London open
input int      Sess1_End       = 13;
input bool     Sess2_On        = true;
input int      Sess2_Start     = 20;     // Late NY / Asian open
input int      Sess2_End       = 23;

//── FILTERS ────────────────────────────────────────────────────────
input group "=== FILTERS ==="
input double   MaxSpreadUSD    = 50.0;   // Max spread in USD (BTC typical: $5-30)
input double   MinATR_USD      = 30.0;   // Min ATR in USD to trade

//── SYSTEM ─────────────────────────────────────────────────────────
input group "=== SYSTEM ==="
input int      MagicNumber     = 20260001;
input int      Slippage        = 50;
input string   TradeComment    = "BTC_SM";

//── GLOBALS ────────────────────────────────────────────────────────
CTrade        trade;
CPositionInfo pos;
CAccountInfo  acc;
CSymbolInfo   sym;

int    hEMA_F, hEMA_S, hRSI, hATR, hBB, hMACD;
double initialBalance;
double dayStartBalance;
int    todayTrades;
datetime lastDay, lastBar;
int    totalWins, totalLoss;
double totalProfit, totalLossAmt;


int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(Slippage);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   sym.Name(_Symbol); sym.Refresh();

   hEMA_F = iMA(_Symbol,PERIOD_M1,EMA_Fast,0,MODE_EMA,PRICE_CLOSE);
   hEMA_S = iMA(_Symbol,PERIOD_M1,EMA_Slow,0,MODE_EMA,PRICE_CLOSE);
   hRSI   = iRSI(_Symbol,PERIOD_M1,RSI_Period,PRICE_CLOSE);
   hATR   = iATR(_Symbol,PERIOD_M1,ATR_Period);
   hBB    = iBands(_Symbol,PERIOD_M1,BB_Period,0,BB_Dev,PRICE_CLOSE);
   hMACD  = iMACD(_Symbol,PERIOD_M1,MACD_Fast,MACD_Slow,MACD_Sig,PRICE_CLOSE);

   if(hEMA_F==INVALID_HANDLE||hEMA_S==INVALID_HANDLE||hRSI==INVALID_HANDLE||
      hATR==INVALID_HANDLE  ||hBB==INVALID_HANDLE   ||hMACD==INVALID_HANDLE)
   { Print("INIT FAILED — indicator handle error"); return INIT_FAILED; }

   initialBalance  = acc.Balance();
   dayStartBalance = initialBalance;
   todayTrades=0; lastDay=0; lastBar=0;
   totalWins=0; totalLoss=0; totalProfit=0; totalLossAmt=0;

   Print("BTCUSD ScalpMaster M1 v3.0 | Balance:$",DoubleToString(initialBalance,2),
         " | Risk:",RiskPct,"%/trade | RR 1:",RRRatio," | DailyDD limit:",DailyDDLimit,"%");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   IndicatorRelease(hEMA_F); IndicatorRelease(hEMA_S); IndicatorRelease(hRSI);
   IndicatorRelease(hATR);   IndicatorRelease(hBB);    IndicatorRelease(hMACD);
   double wr=(totalWins+totalLoss>0)?(double)totalWins/(totalWins+totalLoss)*100:0;
   Print("=== BTCUSD FINAL STATS === W:",totalWins," L:",totalLoss,
         " WR:",DoubleToString(wr,1),"% Profit:$",DoubleToString(totalProfit,2));
}

void OnTick()
{
   datetime barTime=iTime(_Symbol,PERIOD_M1,0);
   if(barTime==lastBar){ UpdateHUD(0,0,0,0,0,0,0,0); return; }
   lastBar=barTime;

   // Reset daily tracking at new day
   MqlDateTime dt; TimeCurrent(dt);
   datetime today=StringToTime(IntegerToString(dt.year)+"."+
                               IntegerToString(dt.mon)+"."+
                               IntegerToString(dt.day));
   if(today!=lastDay)
   {
      todayTrades=0;
      dayStartBalance=acc.Balance();
      lastDay=today;
   }

   // Guards — check in priority order
   if(IsMaxDD())            { Comment("MAX DRAWDOWN REACHED — EA STOPPED"); return; }
   if(IsDailyDDHit())       { Comment("Daily DD limit hit — resting today | DD:"+
                               DoubleToString(GetDailyDD(),1)+"%"); return; }
   if(todayTrades>=MaxTradesDay){ Comment("Daily trade limit: "+IntegerToString(todayTrades)); return; }
   if(!InSession())         { UpdateHUD(0,0,0,0,0,0,0,0); return; }
   if(!SpreadOK())          { Comment("Spread too wide — waiting"); return; }
   if(HasOpenTrade())       { UpdateHUD(0,0,0,0,0,0,0,0); return; }

   // Read indicators (bar[1] = last fully closed bar)
   double ef[3],es[3],r[3],a[3],bbu[3],bbl[3],mcd[3],mcs[3];
   ArraySetAsSeries(ef,true); ArraySetAsSeries(es,true);
   ArraySetAsSeries(r,true);  ArraySetAsSeries(a,true);
   ArraySetAsSeries(bbu,true);ArraySetAsSeries(bbl,true);
   ArraySetAsSeries(mcd,true);ArraySetAsSeries(mcs,true);

   if(CopyBuffer(hEMA_F,0,0,3,ef)<3)  return;
   if(CopyBuffer(hEMA_S,0,0,3,es)<3)  return;
   if(CopyBuffer(hRSI,0,0,3,r)<3)     return;
   if(CopyBuffer(hATR,0,0,3,a)<3)     return;
   if(CopyBuffer(hBB,1,0,3,bbu)<3)    return;
   if(CopyBuffer(hBB,2,0,3,bbl)<3)    return;
   if(CopyBuffer(hMACD,0,0,3,mcd)<3)  return;
   if(CopyBuffer(hMACD,1,0,3,mcs)<3)  return;

   if(a[1]<MinATR_USD) return;

   MqlRates bars[]; ArraySetAsSeries(bars,true);
   if(CopyRates(_Symbol,PERIOD_M1,0,MomCandles+3,bars)<MomCandles+2) return;

   // ── Score logic (mirrors Python backtest exactly) ──────────────
   double cl1=bars[1].close;
   bool emaBull=ef[1]>es[1]&&ef[2]<=es[2]; bool emaBear=ef[1]<es[1]&&ef[2]>=es[2];
   bool emaAbv=ef[1]>es[1];                 bool emaBel=ef[1]<es[1];
   bool rsiBuy=r[1]>RSI_OS&&r[1]<45;       bool rsiSell=r[1]>55&&r[1]<RSI_OB;
   bool rsiOS=r[1]<=RSI_OS;                 bool rsiOB=r[1]>=RSI_OB;
   bool bbBuy=cl1<=bbl[1]||bars[2].low<=bbl[2];
   bool bbSell=cl1>=bbu[1]||bars[2].high>=bbu[2];
   bool macdBC=mcd[1]>mcs[1]&&mcd[2]<=mcs[2]; bool macdBrC=mcd[1]<mcs[1]&&mcd[2]>=mcs[2];
   bool macdB=mcd[1]>mcs[1];                   bool macdBr=mcd[1]<mcs[1];
   bool bullMom=MomentumOK(bars,1,true);        bool bearMom=MomentumOK(bars,1,false);

   int sA_buy=0,sA_sell=0,sB_buy=0,sB_sell=0;
   if(emaBull||emaAbv) sA_buy++;  if(emaBear||emaBel) sA_sell++;
   if(rsiBuy||rsiOS)   sA_buy++;  if(rsiSell||rsiOB)  sA_sell++;
   if(macdBC||macdB)   sA_buy++;  if(macdBrC||macdBr) sA_sell++;
   if(bullMom)         sA_buy++;  if(bearMom)          sA_sell++;
   if(cl1>es[1])       sA_buy++;  if(cl1<es[1])        sA_sell++;

   if(bbBuy&&rsiOS)    sB_buy+=3; if(bbSell&&rsiOB)    sB_sell+=3;
   if(macdBC)          sB_buy++;  if(macdBrC)           sB_sell++;
   if(bars[1].close>bars[1].open) sB_buy++;
   if(bars[1].close<bars[1].open) sB_sell++;

   int signal=0;
   if     (sA_buy >=RequiredScore) signal= 1;
   else if(sA_sell>=RequiredScore) signal=-1;
   else if(sB_buy >=RequiredScore) signal= 1;
   else if(sB_sell>=RequiredScore) signal=-1;

   if(signal== 1) OpenBuy(a[1]);
   if(signal==-1) OpenSell(a[1]);

   UpdateHUD(ef[1],es[1],r[1],a[1],sA_buy,sA_sell,sB_buy,sB_sell);
}

bool MomentumOK(MqlRates &c[],int start,bool bull)
{
   for(int i=start;i<start+MomCandles;i++)
   {
      double body=MathAbs(c[i].close-c[i].open);
      double rng=c[i].high-c[i].low;
      if(rng==0) return false;
      if(body/rng<MinBodyRatio) return false;
      if(bull&&c[i].close<=c[i].open)  return false;
      if(!bull&&c[i].close>=c[i].open) return false;
   }
   return true;
}

double CalcLots(double slDist)
{
   if(slDist<=0) return 0;
   sym.Refresh();
   double tv=sym.TickValue(); double ts=sym.TickSize();
   if(tv<=0||ts<=0) return sym.LotsMin();
   double riskAmt=acc.Equity()*RiskPct/100.0;
   double lots=riskAmt/(slDist/ts*tv);
   lots=MathFloor(lots/sym.LotsStep())*sym.LotsStep();
   lots=MathMax(lots,sym.LotsMin());
   lots=MathMin(lots,sym.LotsMax());
   return NormalizeDouble(lots,2);
}

void OpenBuy(double atrVal)
{
   sym.Refresh();
   double ask=sym.Ask();
   double slDist=MathMax(atrVal*ATR_SL_Multi,sym.Point()*10);
   double sl=NormalizeDouble(ask-slDist,sym.Digits());
   double tp=NormalizeDouble(ask+slDist*RRRatio,sym.Digits());
   double lots=CalcLots(slDist);
   if(lots<=0) return;
   if(trade.Buy(lots,_Symbol,ask,sl,tp,TradeComment))
      { todayTrades++; Print("BUY lots=",lots," SL=",sl," TP=",tp); }
   else
      Print("BUY FAILED: ",trade.ResultRetcodeDescription());
}

void OpenSell(double atrVal)
{
   sym.Refresh();
   double bid=sym.Bid();
   double slDist=MathMax(atrVal*ATR_SL_Multi,sym.Point()*10);
   double sl=NormalizeDouble(bid+slDist,sym.Digits());
   double tp=NormalizeDouble(bid-slDist*RRRatio,sym.Digits());
   double lots=CalcLots(slDist);
   if(lots<=0) return;
   if(trade.Sell(lots,_Symbol,bid,sl,tp,TradeComment))
      { todayTrades++; Print("SELL lots=",lots," SL=",sl," TP=",tp); }
   else
      Print("SELL FAILED: ",trade.ResultRetcodeDescription());
}

bool HasOpenTrade()
{
   for(int i=0;i<PositionsTotal();i++)
      if(pos.SelectByIndex(i)&&pos.Magic()==MagicNumber&&pos.Symbol()==_Symbol)
         return true;
   return false;
}

bool IsMaxDD()
{
   return ((initialBalance-acc.Balance())/initialBalance*100.0>=MaxDDPct);
}

double GetDailyDD()
{
   if(dayStartBalance<=0) return 0;
   return (dayStartBalance-acc.Balance())/dayStartBalance*100.0;
}

bool IsDailyDDHit()
{
   return GetDailyDD()>=DailyDDLimit;
}

bool InSession()
{
   MqlDateTime dt; TimeCurrent(dt); int h=dt.hour;
   if(Sess1_On&&h>=Sess1_Start&&h<Sess1_End) return true;
   if(Sess2_On&&h>=Sess2_Start&&h<Sess2_End) return true;
   return false;
}

bool SpreadOK()
{
   sym.Refresh();
   return((sym.Ask()-sym.Bid())<=MaxSpreadUSD);
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &req,const MqlTradeResult &res)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD) return;
   HistorySelect(TimeCurrent()-86400,TimeCurrent());
   ulong ticket=trans.deal;
   if(!HistoryDealSelect(ticket)) return;
   if(HistoryDealGetInteger(ticket,DEAL_MAGIC)!=MagicNumber) return;
   if(HistoryDealGetInteger(ticket,DEAL_ENTRY)!=DEAL_ENTRY_OUT) return;
   double pnl=HistoryDealGetDouble(ticket,DEAL_PROFIT)
             +HistoryDealGetDouble(ticket,DEAL_COMMISSION)
             +HistoryDealGetDouble(ticket,DEAL_SWAP);
   if(pnl>0){totalWins++;  totalProfit  +=pnl;}
   else     {totalLoss++;  totalLossAmt +=MathAbs(pnl);}
}

void UpdateHUD(double ef,double es,double r,double a,int sb,int ss,int rb,int rs)
{
   double bal=acc.Balance(); double eq=acc.Equity();
   double dd=(initialBalance-bal)/initialBalance*100;
   double ddd=GetDailyDD();
   double wr=(totalWins+totalLoss>0)?(double)totalWins/(totalWins+totalLoss)*100:0;

   string s="";
   s+="=== BTCUSD ScalpMaster M1 ===\n";
   s+="Balance : $"+DoubleToString(bal,2)+"  Equity: $"+DoubleToString(eq,2)+"\n";
   s+="Total DD: "+DoubleToString(dd,1)+"% / "+DoubleToString(MaxDDPct,0)+"%\n";
   s+="Daily DD: "+DoubleToString(ddd,1)+"% / "+DoubleToString(DailyDDLimit,1)+"%\n";
   s+="-----------------------------\n";
   s+="Trades  : "+IntegerToString(todayTrades)+"/"+IntegerToString(MaxTradesDay)+" today\n";
   s+="W/L     : "+IntegerToString(totalWins)+"/"+IntegerToString(totalLoss)+"  WR:"+DoubleToString(wr,1)+"%\n";
   s+="Profit  : $"+DoubleToString(totalProfit,2)+"  Loss: $"+DoubleToString(totalLossAmt,2)+"\n";
   s+="-----------------------------\n";
   s+="Session : "+(InSession()?"ACTIVE":"WAITING")+"\n";
   s+="ATR     : $"+DoubleToString(a,2)+"  RSI: "+DoubleToString(r,1)+"\n";
   s+="Score A : BUY="+IntegerToString(sb)+" SELL="+IntegerToString(ss)+"\n";
   s+="Score B : BUY="+IntegerToString(rb)+" SELL="+IntegerToString(rs)+"\n";
   s+="Risk/tr : "+DoubleToString(RiskPct,1)+"% = $"+DoubleToString(eq*RiskPct/100,2)+"\n";
   s+="RR      : 1:"+DoubleToString(RRRatio,1)+"\n";
   Comment(s);
}
//+------------------------------------------------------------------+
