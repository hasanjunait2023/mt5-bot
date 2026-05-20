//+------------------------------------------------------------------+
//|                        MTF_EMA_Scalper_M1.mq5                   |
//|                                                                  |
//|  Strategy : Multi-Timeframe EMA Alignment Scalper               |
//|  Timeframes: M15 (trend) + M3 (momentum) + M1 (entry)          |
//|  EMAs     : 200 (trend), 9 + 15 (crossover)                    |
//|  Entry    : 9/15 cross on M1 when all 3 TFs aligned             |
//|  SL       : Swing high/low of last N bars + ATR buffer          |
//|  TP       : RR 1:2 (configurable)                               |
//|  Sessions : London 08-12 UTC + NY 13-17 UTC                    |
//|  Risk     : 2% per trade | Daily DD 4.5% limit | Max DD 30%    |
//|                                                                  |
//|  Attach to ONE chart per symbol (M1 timeframe).                 |
//|  Works on: all 28 forex pairs, XAUUSD, BTCUSD                  |
//+------------------------------------------------------------------+
#property copyright "MTF EMA Scalper"
#property version   "1.00"
#property description "MTF 200/9/15 EMA | M15+M3+M1 alignment | Swing SL | RR 1:2"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//── RISK ───────────────────────────────────────────────────────────
input group "=== RISK & MONEY MANAGEMENT ==="
input double   RiskPct        = 2.0;    // % of equity per trade (compound)
input double   RRRatio        = 2.0;    // Reward : Risk ratio
input double   MaxDDPct       = 30.0;   // Stop EA if total DD exceeds %
input double   DailyDDLimit   = 4.5;    // Stop trading today if daily DD exceeds %
input int      MaxTradesDay   = 6;      // Max trades per day

//── EMA PARAMETERS ─────────────────────────────────────────────────
input group "=== EMA PARAMETERS ==="
input int      EMA_Trend      = 200;    // Trend EMA on all 3 timeframes
input int      EMA_Fast       = 9;      // Crossover fast EMA
input int      EMA_Slow       = 15;     // Crossover slow EMA

//── FILTERS ────────────────────────────────────────────────────────
input group "=== SIGNAL FILTERS ==="
input bool     UseRSIFilter   = true;
input int      RSI_Period     = 14;
input int      RSI_Buy_Lo     = 45;
input int      RSI_Buy_Hi     = 65;
input int      RSI_Sell_Lo    = 35;
input int      RSI_Sell_Hi    = 55;
input bool     UseATRVolFilter = true;
input int      ATR_Period     = 14;
input int      ATR_Med_Bars   = 20;     // bars to compute ATR rolling median
input bool     UseBodyFilter  = true;
input double   MinBodyRatio   = 0.35;   // crossover candle body >= 35% of range
input bool     UseEMASepFilter = true;  // M3 EMA gap must be expanding

//── STOP LOSS ──────────────────────────────────────────────────────
input group "=== STOP LOSS PLACEMENT ==="
input int      SL_Lookback    = 5;      // bars to scan for swing high/low
input double   SL_ATR_Buffer  = 0.1;   // extra buffer: wick + ATR × this value

//── SESSIONS (UTC) ─────────────────────────────────────────────────
input group "=== TRADING SESSIONS (UTC) ==="
input bool     LondonOn       = true;
input int      London_Start   = 8;
input int      London_End     = 12;
input bool     NYOn           = true;
input int      NY_Start       = 13;
input int      NY_End         = 17;

//── SPREAD FILTER ──────────────────────────────────────────────────
input group "=== SPREAD FILTER ==="
input bool     UseSpreadFilter = true;
input double   MaxSpreadPoints = 30;    // in price points — set per symbol

//── SYSTEM ─────────────────────────────────────────────────────────
input group "=== SYSTEM ==="
input int      MagicNumber    = 20260100;
input int      Slippage       = 30;
input string   TradeComment   = "MTF_EMA";

//── GLOBALS ────────────────────────────────────────────────────────
CTrade        trade;
CPositionInfo pos;
CAccountInfo  acc;
CSymbolInfo   sym;

// M1 handles
int hEMA200_M1, hEMA9_M1, hEMA15_M1, hRSI_M1, hATR_M1;
// M3 handles
int hEMA200_M3, hEMA9_M3, hEMA15_M3;
// M15 handles
int hEMA200_M15, hEMA9_M15, hEMA15_M15;

// Rolling ATR history for median calculation
double atrHistory[];

double initialBalance, dayStartBalance;
int    todayTrades;
datetime lastBar, lastDay;
int    totalWins, totalLoss;
double totalProfit, totalLossAmt;


int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(Slippage);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   sym.Name(_Symbol); sym.Refresh();

   // M1 indicator handles
   hEMA200_M1 = iMA(_Symbol, PERIOD_M1, EMA_Trend, 0, MODE_EMA, PRICE_CLOSE);
   hEMA9_M1   = iMA(_Symbol, PERIOD_M1, EMA_Fast,  0, MODE_EMA, PRICE_CLOSE);
   hEMA15_M1  = iMA(_Symbol, PERIOD_M1, EMA_Slow,  0, MODE_EMA, PRICE_CLOSE);
   hRSI_M1    = iRSI(_Symbol, PERIOD_M1, RSI_Period, PRICE_CLOSE);
   hATR_M1    = iATR(_Symbol, PERIOD_M1, ATR_Period);

   // M3 indicator handles (MT5 builds M3 series internally)
   hEMA200_M3 = iMA(_Symbol, PERIOD_M3, EMA_Trend, 0, MODE_EMA, PRICE_CLOSE);
   hEMA9_M3   = iMA(_Symbol, PERIOD_M3, EMA_Fast,  0, MODE_EMA, PRICE_CLOSE);
   hEMA15_M3  = iMA(_Symbol, PERIOD_M3, EMA_Slow,  0, MODE_EMA, PRICE_CLOSE);

   // M15 indicator handles
   hEMA200_M15 = iMA(_Symbol, PERIOD_M15, EMA_Trend, 0, MODE_EMA, PRICE_CLOSE);
   hEMA9_M15   = iMA(_Symbol, PERIOD_M15, EMA_Fast,  0, MODE_EMA, PRICE_CLOSE);
   hEMA15_M15  = iMA(_Symbol, PERIOD_M15, EMA_Slow,  0, MODE_EMA, PRICE_CLOSE);

   // Validate all handles
   if(hEMA200_M1 ==INVALID_HANDLE || hEMA9_M1  ==INVALID_HANDLE ||
      hEMA15_M1  ==INVALID_HANDLE || hRSI_M1   ==INVALID_HANDLE ||
      hATR_M1    ==INVALID_HANDLE ||
      hEMA200_M3 ==INVALID_HANDLE || hEMA9_M3  ==INVALID_HANDLE ||
      hEMA15_M3  ==INVALID_HANDLE ||
      hEMA200_M15==INVALID_HANDLE || hEMA9_M15 ==INVALID_HANDLE ||
      hEMA15_M15 ==INVALID_HANDLE)
   {
      Print("INIT FAILED — invalid indicator handle. Check M3/M15 data availability.");
      return INIT_FAILED;
   }

   // Verify M3 data is available
   double testBuf[3]; ArraySetAsSeries(testBuf, true);
   if(CopyBuffer(hEMA9_M3, 0, 0, 3, testBuf) < 3)
   {
      Print("WARNING: M3 data not yet available — waiting for warmup.");
      // Don't fail; data will be ready after a few ticks
   }

   // ATR median history buffer
   ArrayResize(atrHistory, ATR_Med_Bars);
   ArrayInitialize(atrHistory, 0.0);

   initialBalance  = acc.Balance();
   dayStartBalance = initialBalance;
   todayTrades = 0; lastBar = 0; lastDay = 0;
   totalWins = 0; totalLoss = 0; totalProfit = 0; totalLossAmt = 0;

   Print("MTF EMA Scalper v1.0 | ", _Symbol,
         " | Balance:$", DoubleToString(initialBalance, 2),
         " | RR 1:", RRRatio,
         " | Risk:", RiskPct, "%/trade");
   return INIT_SUCCEEDED;
}


void OnDeinit(const int reason)
{
   IndicatorRelease(hEMA200_M1); IndicatorRelease(hEMA9_M1);
   IndicatorRelease(hEMA15_M1); IndicatorRelease(hRSI_M1);
   IndicatorRelease(hATR_M1);
   IndicatorRelease(hEMA200_M3); IndicatorRelease(hEMA9_M3);
   IndicatorRelease(hEMA15_M3);
   IndicatorRelease(hEMA200_M15); IndicatorRelease(hEMA9_M15);
   IndicatorRelease(hEMA15_M15);

   double wr = (totalWins+totalLoss > 0) ?
               (double)totalWins / (totalWins+totalLoss) * 100 : 0;
   Print("=== MTF FINAL STATS === W:", totalWins, " L:", totalLoss,
         " WR:", DoubleToString(wr, 1), "%",
         " Profit:$", DoubleToString(totalProfit, 2));
}


void OnTick()
{
   // Process only on new M1 bar close
   datetime barTime = iTime(_Symbol, PERIOD_M1, 0);
   if(barTime == lastBar) { UpdateHUD(); return; }
   lastBar = barTime;

   // Daily reset
   MqlDateTime dt; TimeCurrent(dt);
   datetime today = StringToTime(IntegerToString(dt.year) + "." +
                                 IntegerToString(dt.mon)  + "." +
                                 IntegerToString(dt.day));
   if(today != lastDay)
   {
      todayTrades    = 0;
      dayStartBalance = acc.Balance();
      lastDay        = today;
   }

   // Guards (priority order)
   if(IsMaxDD())              { Comment("MAX DRAWDOWN — EA STOPPED"); return; }
   if(IsDailyDDHit())         { Comment("Daily DD limit hit — resting | DD:" +
                                 DoubleToString(GetDailyDD(),1)+"%"); return; }
   if(todayTrades >= MaxTradesDay){ Comment("Daily limit: "+IntegerToString(todayTrades)); return; }
   if(!InSession())           { UpdateHUD(); return; }
   if(UseSpreadFilter && !SpreadOK()) { Comment("Spread too wide"); return; }
   if(HasOpenTrade())         { UpdateHUD(); return; }

   // ── Read M1 indicators (bar[1] = last closed bar) ─────────────────────
   double ema200_m1[3], ema9_m1[3], ema15_m1[3], rsi_m1[3], atr_m1[3];
   ArraySetAsSeries(ema200_m1,true); ArraySetAsSeries(ema9_m1,true);
   ArraySetAsSeries(ema15_m1,true);  ArraySetAsSeries(rsi_m1,true);
   ArraySetAsSeries(atr_m1,true);

   if(CopyBuffer(hEMA200_M1, 0, 0, 3, ema200_m1) < 3) return;
   if(CopyBuffer(hEMA9_M1,   0, 0, 3, ema9_m1)   < 3) return;
   if(CopyBuffer(hEMA15_M1,  0, 0, 3, ema15_m1)  < 3) return;
   if(CopyBuffer(hRSI_M1,    0, 0, 3, rsi_m1)    < 3) return;
   if(CopyBuffer(hATR_M1,    0, 0, 3, atr_m1)    < 3) return;

   // ── Read M3 indicators ─────────────────────────────────────────────────
   double ema200_m3[3], ema9_m3[3], ema15_m3[3];
   ArraySetAsSeries(ema200_m3,true); ArraySetAsSeries(ema9_m3,true);
   ArraySetAsSeries(ema15_m3,true);

   if(CopyBuffer(hEMA200_M3, 0, 0, 3, ema200_m3) < 3) return;
   if(CopyBuffer(hEMA9_M3,   0, 0, 3, ema9_m3)   < 3) return;
   if(CopyBuffer(hEMA15_M3,  0, 0, 3, ema15_m3)  < 3) return;

   // ── Read M15 indicators ────────────────────────────────────────────────
   double ema200_m15[3], ema9_m15[3], ema15_m15[3];
   ArraySetAsSeries(ema200_m15,true); ArraySetAsSeries(ema9_m15,true);
   ArraySetAsSeries(ema15_m15,true);

   if(CopyBuffer(hEMA200_M15, 0, 0, 3, ema200_m15) < 3) return;
   if(CopyBuffer(hEMA9_M15,   0, 0, 3, ema9_m15)   < 3) return;
   if(CopyBuffer(hEMA15_M15,  0, 0, 3, ema15_m15)  < 3) return;

   // ── Read recent M1 price bars for candle quality + swing SL ───────────
   int needed = SL_Lookback + 3;
   MqlRates barsM1[];
   ArraySetAsSeries(barsM1, true);
   if(CopyRates(_Symbol, PERIOD_M1, 0, needed, barsM1) < needed) return;

   double cl1 = barsM1[1].close;   // last confirmed closed bar

   // ── Step 1: 3-TF Alignment ─────────────────────────────────────────────
   bool bull_m1   = cl1 > ema200_m1[1];
   bool bull_m3   = cl1 > ema200_m3[1];
   bool bull_m15  = cl1 > ema200_m15[1];
   bool ema9_gt_m3  = ema9_m3[1]  > ema15_m3[1];
   bool ema9_gt_m15 = ema9_m15[1] > ema15_m15[1];

   bool bullAlign = bull_m1 && bull_m3 && bull_m15 && ema9_gt_m3 && ema9_gt_m15;
   bool bearAlign = !bull_m1 && !bull_m3 && !bull_m15 && !ema9_gt_m3 && !ema9_gt_m15;

   // ── Step 2: M1 EMA Crossover ───────────────────────────────────────────
   // bar[1] = last closed, bar[2] = bar before that (ArraySetAsSeries=true)
   bool crossUp   = (ema9_m1[1] > ema15_m1[1]) && (ema9_m1[2] <= ema15_m1[2]);
   bool crossDown = (ema9_m1[1] < ema15_m1[1]) && (ema9_m1[2] >= ema15_m1[2]);

   int signal = 0;
   if(crossUp   && bullAlign) signal =  1;
   if(crossDown && bearAlign) signal = -1;
   if(signal == 0) { UpdateHUD(); return; }

   // ── Step 3: Optional filters ───────────────────────────────────────────
   if(UseRSIFilter)
   {
      double r = rsi_m1[1];
      if(signal ==  1 && (r < RSI_Buy_Lo  || r > RSI_Buy_Hi))  { UpdateHUD(); return; }
      if(signal == -1 && (r < RSI_Sell_Lo || r > RSI_Sell_Hi)) { UpdateHUD(); return; }
   }

   if(UseATRVolFilter && !ATRAboveMedian(atr_m1[1])) { UpdateHUD(); return; }

   if(UseBodyFilter && !CandleBodyOK(barsM1[1]))      { UpdateHUD(); return; }

   if(UseEMASepFilter && !EMASepExpanding(ema9_m3, ema15_m3)) { UpdateHUD(); return; }

   // ── Step 4: Open trade ─────────────────────────────────────────────────
   if(signal ==  1) OpenBuy(barsM1,  atr_m1[1]);
   if(signal == -1) OpenSell(barsM1, atr_m1[1]);

   UpdateHUD();
}


//── Indicator helpers ────────────────────────────────────────────────────────

bool ATRAboveMedian(double currentATR)
{
   // Shift history and insert current value
   for(int i = ATR_Med_Bars - 1; i > 0; i--)
      atrHistory[i] = atrHistory[i - 1];
   atrHistory[0] = currentATR;

   // Calculate median
   double sorted[];
   ArrayCopy(sorted, atrHistory);
   ArraySort(sorted);
   double median;
   int n = ATR_Med_Bars;
   if(n % 2 == 0)
      median = (sorted[n/2 - 1] + sorted[n/2]) / 2.0;
   else
      median = sorted[n / 2];

   return (currentATR > median && median > 0);
}

bool CandleBodyOK(MqlRates &bar)
{
   double body  = MathAbs(bar.close - bar.open);
   double range = bar.high - bar.low;
   if(range <= 0) return false;
   return (body / range >= MinBodyRatio);
}

bool EMASepExpanding(double &ema9[], double &ema15[])
{
   // sep[1] > sep[2]  (ArraySetAsSeries=true: [1]=last closed, [2]=bar before)
   double sep1 = MathAbs(ema9[1] - ema15[1]);
   double sep2 = MathAbs(ema9[2] - ema15[2]);
   return (sep1 > sep2);
}


//── Trade execution ──────────────────────────────────────────────────────────

void OpenBuy(MqlRates &bars[], double atrVal)
{
   // Swing low = lowest Low of bars[1..SL_Lookback]
   double swingLow = bars[1].low;
   for(int i = 2; i <= SL_Lookback && i < ArraySize(bars); i++)
      swingLow = MathMin(swingLow, bars[i].low);

   sym.Refresh();
   double ask    = sym.Ask();
   double slDist = (ask - swingLow) + atrVal * SL_ATR_Buffer;
   if(slDist <= sym.Point()) return;

   double sl   = NormalizeDouble(ask - slDist, sym.Digits());
   double tp   = NormalizeDouble(ask + slDist * RRRatio, sym.Digits());
   double lots = CalcLots(slDist);
   if(lots <= 0) return;

   if(trade.Buy(lots, _Symbol, ask, sl, tp, TradeComment))
   {
      todayTrades++;
      Print("MTF BUY | lots=", lots, " ask=", ask,
            " sl=", sl, " tp=", tp,
            " SL dist=", DoubleToString(slDist, sym.Digits()),
            " risk=$", DoubleToString(acc.Equity() * RiskPct / 100, 2));
   }
   else
      Print("MTF BUY FAILED: ", trade.ResultRetcodeDescription());
}

void OpenSell(MqlRates &bars[], double atrVal)
{
   // Swing high = highest High of bars[1..SL_Lookback]
   double swingHigh = bars[1].high;
   for(int i = 2; i <= SL_Lookback && i < ArraySize(bars); i++)
      swingHigh = MathMax(swingHigh, bars[i].high);

   sym.Refresh();
   double bid    = sym.Bid();
   double slDist = (swingHigh - bid) + atrVal * SL_ATR_Buffer;
   if(slDist <= sym.Point()) return;

   double sl   = NormalizeDouble(bid + slDist, sym.Digits());
   double tp   = NormalizeDouble(bid - slDist * RRRatio, sym.Digits());
   double lots = CalcLots(slDist);
   if(lots <= 0) return;

   if(trade.Sell(lots, _Symbol, bid, sl, tp, TradeComment))
   {
      todayTrades++;
      Print("MTF SELL | lots=", lots, " bid=", bid,
            " sl=", sl, " tp=", tp,
            " SL dist=", DoubleToString(slDist, sym.Digits()),
            " risk=$", DoubleToString(acc.Equity() * RiskPct / 100, 2));
   }
   else
      Print("MTF SELL FAILED: ", trade.ResultRetcodeDescription());
}

double CalcLots(double slDist)
{
   if(slDist <= 0) return 0;
   sym.Refresh();
   double tv = sym.TickValue();
   double ts = sym.TickSize();
   if(tv <= 0 || ts <= 0) return sym.LotsMin();

   double riskAmt = acc.Equity() * RiskPct / 100.0;
   double lots    = riskAmt / (slDist / ts * tv);
   lots = MathFloor(lots / sym.LotsStep()) * sym.LotsStep();
   lots = MathMax(lots, sym.LotsMin());
   lots = MathMin(lots, sym.LotsMax());
   return NormalizeDouble(lots, 2);
}


//── Guard functions ──────────────────────────────────────────────────────────

bool HasOpenTrade()
{
   for(int i = 0; i < PositionsTotal(); i++)
      if(pos.SelectByIndex(i) && pos.Magic() == MagicNumber && pos.Symbol() == _Symbol)
         return true;
   return false;
}

bool IsMaxDD()
{
   double bal = acc.Balance();
   if(initialBalance <= 0) return false;
   return ((initialBalance - bal) / initialBalance * 100.0 >= MaxDDPct);
}

double GetDailyDD()
{
   if(dayStartBalance <= 0) return 0;
   return (dayStartBalance - acc.Balance()) / dayStartBalance * 100.0;
}

bool IsDailyDDHit()
{
   return GetDailyDD() >= DailyDDLimit;
}

bool InSession()
{
   MqlDateTime dt; TimeCurrent(dt); int h = dt.hour;
   if(LondonOn && h >= London_Start && h < London_End) return true;
   if(NYOn     && h >= NY_Start     && h < NY_End)     return true;
   return false;
}

bool SpreadOK()
{
   sym.Refresh();
   double spreadPts = (sym.Ask() - sym.Bid()) / sym.Point();
   return (spreadPts <= MaxSpreadPoints);
}


//── Trade result tracking ────────────────────────────────────────────────────

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &req,
                        const MqlTradeResult  &res)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   HistorySelect(TimeCurrent() - 86400, TimeCurrent());
   ulong ticket = trans.deal;
   if(!HistoryDealSelect(ticket)) return;
   if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != MagicNumber) return;
   if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;

   double pnl = HistoryDealGetDouble(ticket, DEAL_PROFIT)
              + HistoryDealGetDouble(ticket, DEAL_COMMISSION)
              + HistoryDealGetDouble(ticket, DEAL_SWAP);
   if(pnl > 0) { totalWins++;   totalProfit   += pnl; }
   else        { totalLoss++;   totalLossAmt  += MathAbs(pnl); }
}


//── On-chart dashboard ───────────────────────────────────────────────────────

void UpdateHUD()
{
   double bal = acc.Balance();
   double eq  = acc.Equity();
   double dd  = (initialBalance > 0) ? (initialBalance - bal) / initialBalance * 100 : 0;
   double ddd = GetDailyDD();
   double wr  = (totalWins + totalLoss > 0) ?
                (double)totalWins / (totalWins + totalLoss) * 100 : 0;
   double netPnl = totalProfit - totalLossAmt;

   // Current UTC time
   MqlDateTime dt; TimeGMT(dt);
   string utcTime = StringFormat("%02d:%02d UTC", dt.hour, dt.min);

   // Session label
   string sessLabel;
   int h = dt.hour;
   if(LondonOn && h >= London_Start && h < London_End)
      sessLabel = "LONDON (ACTIVE)";
   else if(NYOn && h >= NY_Start && h < NY_End)
      sessLabel = "NEW YORK (ACTIVE)";
   else if(h < London_Start)
      sessLabel = StringFormat("London in %dh%02dm", London_Start - h - 1, 60 - dt.min);
   else if(h < NY_Start)
      sessLabel = StringFormat("NY in %dh%02dm", NY_Start - h - 1, 60 - dt.min);
   else
      sessLabel = "OUT OF SESSION";

   // Alignment check (last closed bar = bar[1])
   double e200m1[2], e9m1[2], e15m1[2];
   double e200m3[2], e9m3[2], e15m3[2];
   double e200m15[2], e9m15[2], e15m15[2];
   ArraySetAsSeries(e200m1,true); ArraySetAsSeries(e9m1,true); ArraySetAsSeries(e15m1,true);
   ArraySetAsSeries(e200m3,true); ArraySetAsSeries(e9m3,true); ArraySetAsSeries(e15m3,true);
   ArraySetAsSeries(e200m15,true); ArraySetAsSeries(e9m15,true); ArraySetAsSeries(e15m15,true);

   string alignStr = "---";
   double closeM1 = iClose(_Symbol, PERIOD_M1, 1);
   if(CopyBuffer(hEMA200_M1,0,0,2,e200m1)>=2 &&
      CopyBuffer(hEMA9_M1,  0,0,2,e9m1)  >=2 &&
      CopyBuffer(hEMA15_M1, 0,0,2,e15m1) >=2 &&
      CopyBuffer(hEMA200_M3,0,0,2,e200m3)>=2 &&
      CopyBuffer(hEMA9_M3,  0,0,2,e9m3)  >=2 &&
      CopyBuffer(hEMA15_M3, 0,0,2,e15m3) >=2 &&
      CopyBuffer(hEMA200_M15,0,0,2,e200m15)>=2 &&
      CopyBuffer(hEMA9_M15, 0,0,2,e9m15) >=2 &&
      CopyBuffer(hEMA15_M15,0,0,2,e15m15)>=2)
   {
      bool bullM1  = closeM1    > e200m1[1];
      bool bullM3  = closeM1    > e200m3[1];
      bool bullM15 = closeM1    > e200m15[1];
      bool emaM3   = e9m3[1]   > e15m3[1];
      bool emaM15  = e9m15[1]  > e15m15[1];

      bool bearM1  = closeM1    < e200m1[1];
      bool bearM3  = closeM1    < e200m3[1];
      bool bearM15 = closeM1    < e200m15[1];
      bool emaM3b  = e9m3[1]   < e15m3[1];
      bool emaM15b = e9m15[1]  < e15m15[1];

      if(bullM1 && bullM3 && bullM15 && emaM3 && emaM15)
         alignStr = "BULLISH  M1+ M3+ M15+";
      else if(bearM1 && bearM3 && bearM15 && emaM3b && emaM15b)
         alignStr = "BEARISH  M1- M3- M15-";
      else
      {
         string m1s  = bullM1  ? "M1+"  : "M1-";
         string m3s  = bullM3  ? "M3+"  : "M3-";
         string m15s = bullM15 ? "M15+" : "M15-";
         alignStr = "MIXED    " + m1s + " " + m3s + " " + m15s;
      }
   }

   // Spread
   sym.Refresh();
   double spreadPts = (sym.Ask() - sym.Bid()) / sym.Point();

   string s = "";
   s += "============================\n";
   s += " MTF EMA Scalper  |  " + utcTime + "\n";
   s += "============================\n";
   s += "Symbol  : " + _Symbol + "\n";
   s += "Balance : $" + DoubleToString(bal, 2) + "\n";
   s += "Equity  : $" + DoubleToString(eq, 2) + "\n";
   s += "Net P&L : $" + DoubleToString(netPnl, 2) + "\n";
   s += "----------------------------\n";
   s += "Total DD: " + DoubleToString(dd,  1) + "% / " + DoubleToString(MaxDDPct, 0) + "%\n";
   s += "Daily DD: " + DoubleToString(ddd, 1) + "% / " + DoubleToString(DailyDDLimit, 1) + "%\n";
   s += "----------------------------\n";
   s += "Session : " + sessLabel + "\n";
   s += "Align   : " + alignStr + "\n";
   s += "Spread  : " + DoubleToString(spreadPts, 1) + " pts\n";
   s += "----------------------------\n";
   s += "Trades  : " + IntegerToString(todayTrades) + "/" + IntegerToString(MaxTradesDay) + " today\n";
   s += "W / L   : " + IntegerToString(totalWins) + " / " + IntegerToString(totalLoss);
   if(totalWins + totalLoss > 0)
      s += "  (" + DoubleToString(wr, 1) + "% WR)";
   s += "\n";
   s += "----------------------------\n";
   s += "Risk    : " + DoubleToString(RiskPct, 1) + "% = $" +
        DoubleToString(eq * RiskPct / 100, 2) + " / trade\n";
   s += "RR      : 1:" + DoubleToString(RRRatio, 1) + "\n";
   Comment(s);
}
//+------------------------------------------------------------------+
