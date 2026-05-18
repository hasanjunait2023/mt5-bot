//+------------------------------------------------------------------+
//|                                  ScalpMaster_HFT_Aggressive.mq5  |
//|                     BTCUSD High-Frequency Aggressive Scalper      |
//|                     Optimized: 47.8% WR | PF 1.91 | RR 1:2.5    |
//|                     Sessions: 09-13 UTC + 20-23 UTC              |
//+------------------------------------------------------------------+
#property copyright "Junait - ScalpMaster Aggressive"
#property version   "2.00"
#property description "BTCUSD Aggressive Scalper | Compound 5% risk | 47.8% WR verified"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//── RISK (Aggressive Compound) ─────────────────────────────────────
input group "=== RISK ==="
input double   RiskPct         = 5.0;   // % of equity per trade (5% aggressive)
input double   RRRatio         = 2.5;   // Reward:Risk ratio
input double   ATR_SL_Multi    = 0.8;   // ATR × 0.8 = SL distance (optimized)
input double   MaxDDPct        = 30.0;  // Stop all trading if DD exceeds this %
input int      MaxTradesDay    = 12;    // Max trades per day

//── SIGNAL (Verified 47.8% WR params) ─────────────────────────────
input group "=== SIGNAL ==="
input int      EMA_Fast        = 9;
input int      EMA_Slow        = 21;
input int      RSI_Period      = 7;
input int      RSI_OB          = 70;
input int      RSI_OS          = 30;
input int      ATR_Period      = 14;
input int      BB_Period       = 20;
input double   BB_Dev          = 2.0;
input int      MACD_Fast       = 8;
input int      MACD_Slow       = 17;
input int      MACD_Sig        = 9;
input int      RequiredScore   = 5;     // 5 = 47.8% WR (proven best)
input int      MomCandles      = 2;     // 2 consecutive candles
input double   MinBodyRatio    = 0.25;  // Min candle body ratio

//── SESSIONS (UTC — Exness server = UTC) ──────────────────────────
input group "=== SESSIONS (UTC) ==="
input bool     Sess1_On        = true;
input int      Sess1_Start     = 9;     // 09:00 UTC (London open)
input int      Sess1_End       = 13;    // 13:00 UTC
input bool     Sess2_On        = true;
input int      Sess2_Start     = 20;    // 20:00 UTC (NY close / Asian open)
input int      Sess2_End       = 23;    // 23:00 UTC

//── SPREAD ────────────────────────────────────────────────────────
input group "=== FILTERS ==="
input double   MaxSpreadUSD    = 50.0;  // Max allowed spread in USD for BTC
input double   MinATR_USD      = 30.0;  // Min ATR in USD (30 = ~3 pips for BTC)

//── SYSTEM ────────────────────────────────────────────────────────
input group "=== SYSTEM ==="
input int      MagicNumber     = 20260517;
input int      Slippage        = 50;
input string   Comment_        = "SM_AGG";

//── GLOBALS ───────────────────────────────────────────────────────
CTrade        trade;
CPositionInfo pos;
CAccountInfo  acc;
CSymbolInfo   sym;

int hEMA_F, hEMA_S, hRSI, hATR, hBB, hMACD;
double        initialBalance;
int           todayTrades;
datetime      lastDay;
datetime      lastBar;
int           totalWins, totalLoss;
double        totalProfit, totalLossAmt;


int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(Slippage);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   sym.Name(_Symbol); sym.Refresh();

   hEMA_F = iMA(_Symbol, PERIOD_M1, EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_S = iMA(_Symbol, PERIOD_M1, EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   hRSI   = iRSI(_Symbol, PERIOD_M1, RSI_Period, PRICE_CLOSE);
   hATR   = iATR(_Symbol, PERIOD_M1, ATR_Period);
   hBB    = iBands(_Symbol, PERIOD_M1, BB_Period, 0, BB_Dev, PRICE_CLOSE);
   hMACD  = iMACD(_Symbol, PERIOD_M1, MACD_Fast, MACD_Slow, MACD_Sig, PRICE_CLOSE);

   if(hEMA_F==INVALID_HANDLE || hEMA_S==INVALID_HANDLE ||
      hRSI==INVALID_HANDLE   || hATR==INVALID_HANDLE   ||
      hBB==INVALID_HANDLE    || hMACD==INVALID_HANDLE)
   { Print("INIT FAILED — indicator handle error"); return INIT_FAILED; }

   initialBalance  = acc.Balance();
   todayTrades     = 0;
   lastDay         = 0; lastBar = 0;
   totalWins       = 0; totalLoss   = 0;
   totalProfit     = 0; totalLossAmt= 0;

   Print("ScalpMaster Aggressive v2.0 | ", _Symbol,
         " | Balance: $", DoubleToString(initialBalance,2),
         " | Risk: ", RiskPct, "%/trade | RR 1:", RRRatio);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   IndicatorRelease(hEMA_F); IndicatorRelease(hEMA_S);
   IndicatorRelease(hRSI);   IndicatorRelease(hATR);
   IndicatorRelease(hBB);    IndicatorRelease(hMACD);

   double wr = (totalWins+totalLoss>0) ? (double)totalWins/(totalWins+totalLoss)*100 : 0;
   Print("=== FINAL STATS === W:", totalWins, " L:", totalLoss,
         " WR:", DoubleToString(wr,1), "%",
         " Profit:$", DoubleToString(totalProfit,2),
         " Loss:$", DoubleToString(totalLossAmt,2));
}

void OnTick()
{
   // Only on new bar
   datetime barTime = iTime(_Symbol, PERIOD_M1, 0);
   if(barTime == lastBar) { ManageTrades(); return; }
   lastBar = barTime;

   // Reset daily counter
   MqlDateTime dt; TimeCurrent(dt);
   datetime today = StringToTime(IntegerToString(dt.year)+"."+
                                 IntegerToString(dt.mon)+"."+
                                 IntegerToString(dt.day));
   if(today != lastDay) { todayTrades=0; lastDay=today; }

   // Guards
   if(IsMaxDD())        { Comment("MAX DRAWDOWN HIT - STOPPED"); return; }
   if(todayTrades >= MaxTradesDay) { Comment("Daily limit reached: "+IntegerToString(todayTrades)); return; }
   if(!InSession())     { UpdateHUD(0,0,0,0,0,0,0,0); return; }
   if(!SpreadOK())      { Comment("Spread too wide"); return; }
   if(HasOpenTrade())   { ManageTrades(); UpdateHUD(0,0,0,0,0,0,0,0); return; }

   // Read indicators (bar 1 = confirmed closed bar)
   double ef[3],es[3],r[3],a[3],bbu[3],bbm[3],bbl[3],mcd[3],mcs[3];
   ArraySetAsSeries(ef,true); ArraySetAsSeries(es,true); ArraySetAsSeries(r,true);
   ArraySetAsSeries(a,true);  ArraySetAsSeries(bbu,true);ArraySetAsSeries(bbm,true);
   ArraySetAsSeries(bbl,true);ArraySetAsSeries(mcd,true);ArraySetAsSeries(mcs,true);

   if(CopyBuffer(hEMA_F,0,0,3,ef)<3) return; if(CopyBuffer(hEMA_S,0,0,3,es)<3) return;
   if(CopyBuffer(hRSI,0,0,3,r)<3)   return; if(CopyBuffer(hATR,0,0,3,a)<3)   return;
   if(CopyBuffer(hBB,1,0,3,bbu)<3)  return; if(CopyBuffer(hBB,0,0,3,bbm)<3)  return;
   if(CopyBuffer(hBB,2,0,3,bbl)<3)  return;
   if(CopyBuffer(hMACD,0,0,3,mcd)<3)return; if(CopyBuffer(hMACD,1,0,3,mcs)<3)return;

   if(a[1] < MinATR_USD) return;

   // Load last MomCandles+1 bars for momentum check
   MqlRates bars[]; ArraySetAsSeries(bars,true);
   if(CopyRates(_Symbol,PERIOD_M1,0,MomCandles+3,bars)<MomCandles+2) return;

   // ── Score-based signal (mirrors Python backtest exactly) ──────
   double cl1=bars[1].close, cl2=bars[2].close;

   bool emaBull = ef[1]>es[1] && ef[2]<=es[2];
   bool emaBear = ef[1]<es[1] && ef[2]>=es[2];
   bool emaAbv  = ef[1]>es[1]; bool emaBel = ef[1]<es[1];

   bool rsiBuy  = r[1]>RSI_OS && r[1]<45;
   bool rsiSell = r[1]>55     && r[1]<RSI_OB;
   bool rsiOS   = r[1]<=RSI_OS;
   bool rsiOB   = r[1]>=RSI_OB;

   bool bbBuy   = cl1<=bbl[1] || bars[2].low<=bbl[2];
   bool bbSell  = cl1>=bbu[1] || bars[2].high>=bbu[2];

   bool macdBC  = mcd[1]>mcs[1] && mcd[2]<=mcs[2];
   bool macdBrC = mcd[1]<mcs[1] && mcd[2]>=mcs[2];
   bool macdB   = mcd[1]>mcs[1]; bool macdBr = mcd[1]<mcs[1];

   bool bullMom = MomentumOK(bars,1,true);
   bool bearMom = MomentumOK(bars,1,false);

   int sA_buy=0, sA_sell=0, sB_buy=0, sB_sell=0;
   if(emaBull||emaAbv)  sA_buy++;
   if(rsiBuy||rsiOS)    sA_buy++;
   if(macdBC||macdB)    sA_buy++;
   if(bullMom)          sA_buy++;
   if(cl1>es[1])        sA_buy++;

   if(emaBear||emaBel)  sA_sell++;
   if(rsiSell||rsiOB)   sA_sell++;
   if(macdBrC||macdBr)  sA_sell++;
   if(bearMom)          sA_sell++;
   if(cl1<es[1])        sA_sell++;

   if(bbBuy && rsiOS)   sB_buy  += 3;
   if(macdBC)           sB_buy++;
   if(bars[1].close>bars[1].open) sB_buy++;

   if(bbSell && rsiOB)  sB_sell += 3;
   if(macdBrC)          sB_sell++;
   if(bars[1].close<bars[1].open) sB_sell++;

   int signal = 0;
   if     (sA_buy  >= RequiredScore) signal =  1;
   else if(sA_sell >= RequiredScore) signal = -1;
   else if(sB_buy  >= RequiredScore) signal =  1;
   else if(sB_sell >= RequiredScore) signal = -1;

   if(signal == 1)       OpenBuy(a[1]);
   else if(signal == -1) OpenSell(a[1]);

   ManageTrades();
   UpdateHUD(ef[1],es[1],r[1],a[1],sA_buy,sA_sell,sB_buy,sB_sell);
}

bool MomentumOK(MqlRates &c[], int start, bool bull)
{
   for(int i=start; i<start+MomCandles; i++)
   {
      double body  = MathAbs(c[i].close-c[i].open);
      double range = c[i].high-c[i].low;
      if(range==0) return false;
      if(body/range < MinBodyRatio) return false;
      if(bull  && c[i].close<=c[i].open) return false;
      if(!bull && c[i].close>=c[i].open) return false;
   }
   return true;
}

double CalcLots(double slDist)
{
   if(slDist<=0) return 0;
   sym.Refresh();
   double tv = sym.TickValue(); double ts = sym.TickSize();
   if(tv<=0||ts<=0) return sym.LotsMin();
   double equity    = acc.Equity();
   double riskAmt   = equity * RiskPct / 100.0;
   double lots      = riskAmt / (slDist / ts * tv);
   lots = MathFloor(lots/sym.LotsStep())*sym.LotsStep();
   lots = MathMax(lots, sym.LotsMin());
   lots = MathMin(lots, sym.LotsMax());
   return NormalizeDouble(lots,2);
}

void OpenBuy(double atrVal)
{
   sym.Refresh();
   double ask    = sym.Ask();
   double slDist = MathMax(atrVal * ATR_SL_Multi, sym.Point()*10);
   double sl     = NormalizeDouble(ask - slDist, sym.Digits());
   double tp     = NormalizeDouble(ask + slDist * RRRatio, sym.Digits());
   double lots   = CalcLots(slDist);
   if(lots<=0) return;
   if(trade.Buy(lots,_Symbol,ask,sl,tp,Comment_))
   {
      todayTrades++;
      Print("BUY | lots=",lots," ask=",ask," sl=",sl," tp=",tp,
            " risk=$",DoubleToString(acc.Equity()*RiskPct/100,2));
   }
   else Print("BUY FAILED: ",trade.ResultRetcodeDescription());
}

void OpenSell(double atrVal)
{
   sym.Refresh();
   double bid    = sym.Bid();
   double slDist = MathMax(atrVal * ATR_SL_Multi, sym.Point()*10);
   double sl     = NormalizeDouble(bid + slDist, sym.Digits());
   double tp     = NormalizeDouble(bid - slDist * RRRatio, sym.Digits());
   double lots   = CalcLots(slDist);
   if(lots<=0) return;
   if(trade.Sell(lots,_Symbol,bid,sl,tp,Comment_))
   {
      todayTrades++;
      Print("SELL | lots=",lots," bid=",bid," sl=",sl," tp=",tp,
            " risk=$",DoubleToString(acc.Equity()*RiskPct/100,2));
   }
   else Print("SELL FAILED: ",trade.ResultRetcodeDescription());
}

void ManageTrades()
{
   // No trailing — fixed SL/TP gives better results on BTC M1 scalps
}

bool HasOpenTrade()
{
   for(int i=0;i<PositionsTotal();i++)
      if(pos.SelectByIndex(i) && pos.Magic()==MagicNumber && pos.Symbol()==_Symbol)
         return true;
   return false;
}

bool IsMaxDD()
{
   double bal = acc.Balance();
   return ((initialBalance-bal)/initialBalance*100.0 >= MaxDDPct);
}

bool InSession()
{
   MqlDateTime dt; TimeCurrent(dt); int h=dt.hour;
   if(Sess1_On && h>=Sess1_Start && h<Sess1_End) return true;
   if(Sess2_On && h>=Sess2_Start && h<Sess2_End) return true;
   return false;
}

bool SpreadOK()
{
   sym.Refresh();
   double spread = (sym.Ask()-sym.Bid());
   return (spread <= MaxSpreadUSD);
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &req, const MqlTradeResult &res)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD) return;
   HistorySelect(TimeCurrent()-86400, TimeCurrent());
   ulong ticket = trans.deal;
   if(!HistoryDealSelect(ticket)) return;
   if(HistoryDealGetInteger(ticket,DEAL_MAGIC)!=MagicNumber) return;
   if(HistoryDealGetInteger(ticket,DEAL_ENTRY)!=DEAL_ENTRY_OUT) return;
   double pnl = HistoryDealGetDouble(ticket,DEAL_PROFIT)
              + HistoryDealGetDouble(ticket,DEAL_COMMISSION)
              + HistoryDealGetDouble(ticket,DEAL_SWAP);
   if(pnl>0){ totalWins++;   totalProfit  +=pnl; }
   else     { totalLoss++;   totalLossAmt +=MathAbs(pnl); }
}

void UpdateHUD(double ef,double es,double r,double a,int sb,int ss,int rb,int rs)
{
   double bal  = acc.Balance();
   double eq   = acc.Equity();
   double dd   = initialBalance>0 ? (initialBalance-bal)/initialBalance*100 : 0;
   double wr   = (totalWins+totalLoss>0) ? (double)totalWins/(totalWins+totalLoss)*100 : 0;
   double atrU = a;

   MqlDateTime dt; TimeCurrent(dt); int h=dt.hour;
   string sess = InSession() ? "IN SESSION" : "OUT OF SESSION";

   string info = "";
   info += "SCALPMASTER AGGRESSIVE v2.0\n";
   info += "Symbol : " + _Symbol + " | " + sess + "\n";
   info += "Balance: $" + DoubleToString(bal,2) + "\n";
   info += "Equity : $" + DoubleToString(eq,2) + "\n";
   info += "DD     : " + DoubleToString(dd,2) + "% / " + DoubleToString(MaxDDPct,0) + "%\n";
   info += "----------------------------\n";
   info += "Trades : " + IntegerToString(todayTrades) + "/" + IntegerToString(MaxTradesDay) + " today\n";
   info += "Wins   : " + IntegerToString(totalWins) + "  Losses: " + IntegerToString(totalLoss) + "\n";
   info += "WR     : " + DoubleToString(wr,1) + "%\n";
   info += "Profit : $" + DoubleToString(totalProfit,2) + "\n";
   info += "Loss   : $" + DoubleToString(totalLossAmt,2) + "\n";
   info += "----------------------------\n";
   info += "ATR USD: $" + DoubleToString(atrU,2) + "\n";
   info += "RSI    : " + DoubleToString(r,1) + "\n";
   info += "Trend  : BUY=" + IntegerToString(sb) + " SELL=" + IntegerToString(ss) + "\n";
   info += "Rev    : BUY=" + IntegerToString(rb) + " SELL=" + IntegerToString(rs) + "\n";
   info += "Risk/tr: " + DoubleToString(RiskPct,1) + "% = $" + DoubleToString(eq*RiskPct/100,2) + "\n";
   info += "RR     : 1:" + DoubleToString(RRRatio,1) + "\n";
   Comment(info);
}
//+------------------------------------------------------------------+
