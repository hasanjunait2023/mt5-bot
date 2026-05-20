//+------------------------------------------------------------------+
//|                                            ScalpMaster_HFT.mq5   |
//|                              High Frequency 1M Scalping Bot       |
//|                              Risk: $1 | Reward: $2 | RR 1:2      |
//+------------------------------------------------------------------+
#property copyright "Junait - ScalpMaster HFT"
#property link      ""
#property version   "1.20"
#property description "1M Candle High Frequency Scalper — Compound Sizing"
#property description "Dynamic Risk % of equity | 1:2 RR | Session-Optimized"
#property description "Max Drawdown Protection: 20% | Supports: EURUSD, XAUUSD, BTCUSD"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+
input group "=== RISK MANAGEMENT ==="
input double   RiskPercent       = 3.0;        // Risk % of equity per trade (compound aggressive)
input double   RiskPerTrade      = 3.0;        // Risk per trade in $ (used only if RiskPercent=0)
input double   RewardPerTrade    = 7.5;        // Reward per trade in $ (2.5 RR)
input double   MaxDrawdownPct    = 25.0;       // Max drawdown % of initial balance
input int      MaxOpenTrades     = 3;          // Max simultaneous open trades
input int      MaxTradesPerDay   = 12;         // Max trades per day

input group "=== STRATEGY SETTINGS ==="
input int      EMA_Fast          = 9;          // Fast EMA Period  [optimized]
input int      EMA_Slow          = 21;         // Slow EMA Period  [optimized]
input int      RSI_Period        = 7;          // RSI Period       [optimized]
input int      RSI_OB            = 70;         // RSI Overbought   [tightened]
input int      RSI_OS            = 30;         // RSI Oversold     [tightened]
input int      ATR_Period        = 14;         // ATR Period
input double   ATR_SL_Multi      = 0.8;        // ATR multiplier for SL [optimized: 47.8% WR]
input int      BB_Period         = 20;         // Bollinger Band Period
input double   BB_Deviation      = 2.0;        // Bollinger Band Deviation
input int      MACD_Fast         = 8;          // MACD Fast
input int      MACD_Slow         = 17;         // MACD Slow
input int      MACD_Signal       = 9;          // MACD Signal

input group "=== MOMENTUM FILTER ==="
input int      MomCandles        = 2;          // Consecutive candles for momentum [optimized]
input double   MinCandleBody     = 0.25;       // Min candle body ratio [optimized: more signals]

input group "=== SESSION FILTER (UTC / Server Time) ==="
// BTCUSD OPTIMIZED: S1=9-13 (London open), S2=20-23 (NY close) — 47.8% WR proven
// XAUUSD:          S1=10-13, S2=20-23
// EURUSD/GBPUSD:   S1=8-12,  S2=13-17
input bool     UseSession1       = true;       // Enable Session 1
input int      S1_Start          = 9;          // Session 1 Start Hour (UTC)
input int      S1_End            = 13;         // Session 1 End Hour (UTC)
input bool     UseSession2       = true;       // Enable Session 2
input int      S2_Start          = 20;         // Session 2 Start Hour (UTC)
input int      S2_End            = 23;         // Session 2 End Hour (UTC)
input bool     UseSession3       = false;      // Enable Session 3
input int      S3_Start          = 0;          // Session 3 Start Hour
input int      S3_End            = 4;          // Session 3 End Hour

input group "=== SPREAD & VOLATILITY ==="
input double   MaxSpreadPips     = 3.0;        // Max spread in pips (use 3+ for Gold)
input double   MinATR_Pips       = 1.0;        // Min ATR in pips

input group "=== TRADE MANAGEMENT ==="
input bool     UseTrailingStop   = true;       // Enable trailing stop
input double   TrailStartPips    = 1.0;        // Start trailing after X pips profit
input double   TrailStepPips     = 0.5;        // Trail step in pips
input bool     UseBreakEven      = true;       // Move SL to breakeven
input double   BE_TriggerPips    = 1.0;        // Trigger breakeven at X pips
input double   BE_LockPips       = 0.2;        // Lock X pips above entry

input group "=== SYSTEM ==="
input int      MagicNumber       = 20260516;   // Magic Number
input int      Slippage          = 10;         // Max Slippage Points
input string   TradeComment      = "SM_HFT";   // Trade Comment

//+------------------------------------------------------------------+
//| GLOBAL VARIABLES                                                  |
//+------------------------------------------------------------------+
CTrade         trade;
CPositionInfo  posInfo;
CAccountInfo   accInfo;
CSymbolInfo    symInfo;

int handleEMA_Fast, handleEMA_Slow;
int handleRSI;
int handleATR;
int handleBB;
int handleMACD;

double initialBalance;
int    todayTradeCount;
datetime lastTradeDay;
datetime lastBarTime;

int totalWins, totalLosses;
double totalProfit, totalLoss;

// Symbol pip multiplier: auto-detected in OnInit
double g_pipSize;

//+------------------------------------------------------------------+
//| Calculate pip size for current symbol                              |
//+------------------------------------------------------------------+
double GetPipSize()
{
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

   // 3 or 5 digit symbols (forex): 1 pip = 10 points
   // 2 digit symbols (Gold, BTC, indices): 1 pip = 10 points
   // Rule: pip = point * 10 works universally for most brokers
   // Exception: JPY pairs (2/3 digit): also point * 10
   return point * 10.0;
}

//+------------------------------------------------------------------+
//| Expert initialization function                                     |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(Slippage);
   trade.SetTypeFilling(ORDER_FILLING_IOC);
   trade.SetMarginMode();

   symInfo.Name(_Symbol);
   symInfo.Refresh();

   // Auto-detect pip size
   g_pipSize = GetPipSize();

   handleEMA_Fast = iMA(_Symbol, PERIOD_M1, EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   handleEMA_Slow = iMA(_Symbol, PERIOD_M1, EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   handleRSI      = iRSI(_Symbol, PERIOD_M1, RSI_Period, PRICE_CLOSE);
   handleATR      = iATR(_Symbol, PERIOD_M1, ATR_Period);
   handleBB       = iBands(_Symbol, PERIOD_M1, BB_Period, 0, BB_Deviation, PRICE_CLOSE);
   handleMACD     = iMACD(_Symbol, PERIOD_M1, MACD_Fast, MACD_Slow, MACD_Signal, PRICE_CLOSE);

   if(handleEMA_Fast == INVALID_HANDLE || handleEMA_Slow == INVALID_HANDLE ||
      handleRSI == INVALID_HANDLE || handleATR == INVALID_HANDLE ||
      handleBB == INVALID_HANDLE || handleMACD == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create indicator handles!");
      return(INIT_FAILED);
   }

   initialBalance = accInfo.Balance();
   todayTradeCount = 0;
   lastTradeDay = 0;
   lastBarTime = 0;
   totalWins = 0;
   totalLosses = 0;
   totalProfit = 0;
   totalLoss = 0;

   Print("ScalpMaster HFT v1.10 | Symbol: ", _Symbol,
         " | PipSize: ", DoubleToString(g_pipSize, symInfo.Digits()),
         " | Balance: $", DoubleToString(initialBalance, 2),
         " | Risk: $", RiskPerTrade, " | Reward: $", RewardPerTrade);

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                    |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(handleEMA_Fast);
   IndicatorRelease(handleEMA_Slow);
   IndicatorRelease(handleRSI);
   IndicatorRelease(handleATR);
   IndicatorRelease(handleBB);
   IndicatorRelease(handleMACD);

   double winRate = (totalWins + totalLosses > 0) ?
                    (double)totalWins / (totalWins + totalLosses) * 100.0 : 0;

   Print("=== ScalpMaster HFT Final Stats [", _Symbol, "] ===");
   Print("Wins: ", totalWins, " | Losses: ", totalLosses,
         " | Win Rate: ", DoubleToString(winRate, 1), "%");
   Print("Total Profit: $", DoubleToString(totalProfit, 2),
         " | Total Loss: $", DoubleToString(totalLoss, 2));
}

//+------------------------------------------------------------------+
//| Expert tick function                                               |
//+------------------------------------------------------------------+
void OnTick()
{
   datetime currentBarTime = iTime(_Symbol, PERIOD_M1, 0);
   if(currentBarTime == lastBarTime)
   {
      ManageOpenTrades();
      return;
   }
   lastBarTime = currentBarTime;

   // Reset daily counter
   MqlDateTime dt;
   TimeCurrent(dt);
   datetime today = StringToTime(IntegerToString(dt.year) + "." +
                                  IntegerToString(dt.mon) + "." +
                                  IntegerToString(dt.day));
   if(today != lastTradeDay)
   {
      todayTradeCount = 0;
      lastTradeDay = today;
   }

   if(IsDrawdownExceeded())
   {
      Comment("MAX DRAWDOWN REACHED - Trading Stopped");
      return;
   }

   if(todayTradeCount >= MaxTradesPerDay)
   {
      Comment("Daily trade limit reached: ", todayTradeCount);
      return;
   }

   if(CountOpenTrades() >= MaxOpenTrades)
   {
      ManageOpenTrades();
      return;
   }

   if(!IsValidSession()) return;
   if(!IsSpreadAcceptable()) return;

   // Get indicator values (closed candle = index 1)
   double emaFast[], emaSlow[], rsi[], atr[];
   double bbUpper[], bbMiddle[], bbLower[];
   double macdMain[], macdSignal[];

   ArraySetAsSeries(emaFast, true);
   ArraySetAsSeries(emaSlow, true);
   ArraySetAsSeries(rsi, true);
   ArraySetAsSeries(atr, true);
   ArraySetAsSeries(bbUpper, true);
   ArraySetAsSeries(bbMiddle, true);
   ArraySetAsSeries(bbLower, true);
   ArraySetAsSeries(macdMain, true);
   ArraySetAsSeries(macdSignal, true);

   if(CopyBuffer(handleEMA_Fast, 0, 0, 5, emaFast) < 5) return;
   if(CopyBuffer(handleEMA_Slow, 0, 0, 5, emaSlow) < 5) return;
   if(CopyBuffer(handleRSI, 0, 0, 5, rsi) < 5) return;
   if(CopyBuffer(handleATR, 0, 0, 5, atr) < 5) return;
   // iBands: 0=Base/Middle, 1=Upper, 2=Lower
   if(CopyBuffer(handleBB, 0, 0, 5, bbMiddle) < 5) return;
   if(CopyBuffer(handleBB, 1, 0, 5, bbUpper) < 5) return;
   if(CopyBuffer(handleBB, 2, 0, 5, bbLower) < 5) return;
   if(CopyBuffer(handleMACD, 0, 0, 5, macdMain) < 5) return;
   if(CopyBuffer(handleMACD, 1, 0, 5, macdSignal) < 5) return;

   MqlRates candles[];
   ArraySetAsSeries(candles, true);
   if(CopyRates(_Symbol, PERIOD_M1, 0, MomCandles + 2, candles) < MomCandles + 2) return;

   // Min volatility check using symbol-aware pip size
   double atrPips = atr[1] / g_pipSize;
   if(atrPips < MinATR_Pips) return;

   int signal = 0;
   int requiredScore = 5;   // optimized: 5 = 47.8% WR on BTCUSD

   bool emaBullish = emaFast[1] > emaSlow[1] && emaFast[2] <= emaSlow[2];
   bool emaBearish = emaFast[1] < emaSlow[1] && emaFast[2] >= emaSlow[2];
   bool emaAbove   = emaFast[1] > emaSlow[1];
   bool emaBelow   = emaFast[1] < emaSlow[1];

   bool rsiBuy       = rsi[1] < 45 && rsi[1] > RSI_OS;
   bool rsiSell      = rsi[1] > 55 && rsi[1] < RSI_OB;
   bool rsiOversold  = rsi[1] <= RSI_OS;
   bool rsiOverbought = rsi[1] >= RSI_OB;

   double close1 = candles[1].close;
   bool bbBounceUp   = close1 <= bbLower[1] || candles[2].low <= bbLower[2];
   bool bbBounceDown = close1 >= bbUpper[1] || candles[2].high >= bbUpper[2];

   bool macdBullCross = macdMain[1] > macdSignal[1] && macdMain[2] <= macdSignal[2];
   bool macdBearCross = macdMain[1] < macdSignal[1] && macdMain[2] >= macdSignal[2];
   bool macdBullish   = macdMain[1] > macdSignal[1];
   bool macdBearish   = macdMain[1] < macdSignal[1];

   bool bullMomentum = CheckMomentum(candles, 1, true);
   bool bearMomentum = CheckMomentum(candles, 1, false);

   // Strategy A: Trend continuation
   int scoreA_buy = 0, scoreA_sell = 0;
   if(emaBullish || emaAbove) scoreA_buy++;
   if(rsiBuy || rsiOversold) scoreA_buy++;
   if(macdBullCross || macdBullish) scoreA_buy++;
   if(bullMomentum) scoreA_buy++;
   if(close1 > emaSlow[1]) scoreA_buy++;

   if(emaBearish || emaBelow) scoreA_sell++;
   if(rsiSell || rsiOverbought) scoreA_sell++;
   if(macdBearCross || macdBearish) scoreA_sell++;
   if(bearMomentum) scoreA_sell++;
   if(close1 < emaSlow[1]) scoreA_sell++;

   // Strategy B: Mean reversion
   int scoreB_buy = 0, scoreB_sell = 0;
   if(bbBounceUp && rsiOversold) scoreB_buy += 3;
   if(macdBullCross) scoreB_buy++;
   if(candles[1].close > candles[1].open) scoreB_buy++;

   if(bbBounceDown && rsiOverbought) scoreB_sell += 3;
   if(macdBearCross) scoreB_sell++;
   if(candles[1].close < candles[1].open) scoreB_sell++;

   if(scoreA_buy >= requiredScore)       signal = 1;
   else if(scoreA_sell >= requiredScore) signal = -1;
   else if(scoreB_buy >= requiredScore)  signal = 1;
   else if(scoreB_sell >= requiredScore) signal = -1;

   // Avoid stacking trades in same direction too close together
   if(signal != 0 && HasSameDirectionTrade(signal))
   {
      if(!IsPriceSeparated(signal, atr[1] * 2.0))
         signal = 0;
   }

   if(signal == 1)       ExecuteBuy(atr[1]);
   else if(signal == -1) ExecuteSell(atr[1]);

   ManageOpenTrades();
   UpdateDashboard(emaFast[1], emaSlow[1], rsi[1], atr[1],
                   scoreA_buy, scoreA_sell, scoreB_buy, scoreB_sell);
}

//+------------------------------------------------------------------+
//| Check momentum - consecutive candles in one direction              |
//+------------------------------------------------------------------+
bool CheckMomentum(MqlRates &candles[], int startIdx, bool bullish)
{
   for(int i = startIdx; i < startIdx + MomCandles; i++)
   {
      double body  = MathAbs(candles[i].close - candles[i].open);
      double range = candles[i].high - candles[i].low;
      if(range == 0) return false;
      if(body / range < MinCandleBody) return false;
      if(bullish  && candles[i].close <= candles[i].open) return false;
      if(!bullish && candles[i].close >= candles[i].open) return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Calculate lot size for fixed $ risk                                |
//+------------------------------------------------------------------+
double CalculateLotSize(double slDistance)
{
   if(slDistance <= 0) return 0;

   symInfo.Refresh();
   double tickValue = symInfo.TickValue();
   double tickSize  = symInfo.TickSize();
   double minLot    = symInfo.LotsMin();
   double maxLot    = symInfo.LotsMax();
   double lotStep   = symInfo.LotsStep();

   if(tickValue <= 0 || tickSize <= 0) return minLot;

   // Compound sizing: use % of current equity (grows with account)
   double riskAmount = (RiskPercent > 0)
                       ? AccountInfoDouble(ACCOUNT_EQUITY) * RiskPercent / 100.0
                       : RiskPerTrade;

   double lots = riskAmount / (slDistance / tickSize * tickValue);
   lots = MathFloor(lots / lotStep) * lotStep;
   lots = MathMax(lots, minLot);
   lots = MathMin(lots, maxLot);

   return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
//| Execute BUY trade                                                  |
//+------------------------------------------------------------------+
void ExecuteBuy(double atrValue)
{
   symInfo.Refresh();
   double ask = symInfo.Ask();

   double slDistance = atrValue * ATR_SL_Multi;
   if(slDistance < g_pipSize) slDistance = g_pipSize; // Min 1 pip SL

   double sl = NormalizeDouble(ask - slDistance, symInfo.Digits());
   double tpDistance = slDistance * (RewardPerTrade / RiskPerTrade);
   double tp = NormalizeDouble(ask + tpDistance, symInfo.Digits());

   double lots = CalculateLotSize(slDistance);
   if(lots <= 0) return;

   if(trade.Buy(lots, _Symbol, ask, sl, tp, TradeComment))
   {
      todayTradeCount++;
      Print("BUY Opened | ", _Symbol, " | Lots: ", lots,
            " | SL: ", sl, " | TP: ", tp,
            " | SL Pips: ", DoubleToString(slDistance / g_pipSize, 1),
            " | Trade #", todayTradeCount);
   }
   else
      Print("BUY Failed: ", trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| Execute SELL trade                                                 |
//+------------------------------------------------------------------+
void ExecuteSell(double atrValue)
{
   symInfo.Refresh();
   double bid = symInfo.Bid();

   double slDistance = atrValue * ATR_SL_Multi;
   if(slDistance < g_pipSize) slDistance = g_pipSize;

   double sl = NormalizeDouble(bid + slDistance, symInfo.Digits());
   double tpDistance = slDistance * (RewardPerTrade / RiskPerTrade);
   double tp = NormalizeDouble(bid - tpDistance, symInfo.Digits());

   double lots = CalculateLotSize(slDistance);
   if(lots <= 0) return;

   if(trade.Sell(lots, _Symbol, bid, sl, tp, TradeComment))
   {
      todayTradeCount++;
      Print("SELL Opened | ", _Symbol, " | Lots: ", lots,
            " | SL: ", sl, " | TP: ", tp,
            " | SL Pips: ", DoubleToString(slDistance / g_pipSize, 1),
            " | Trade #", todayTradeCount);
   }
   else
      Print("SELL Failed: ", trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| Manage open trades - trailing stop & breakeven                     |
//+------------------------------------------------------------------+
void ManageOpenTrades()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != MagicNumber) continue;
      if(posInfo.Symbol() != _Symbol) continue;

      double openPrice = posInfo.PriceOpen();
      double currentSL = posInfo.StopLoss();
      double currentTP = posInfo.TakeProfit();
      ulong  ticket    = posInfo.Ticket();

      // Use symbol-aware pip size for all pip calculations
      double trailStart = TrailStartPips * g_pipSize;
      double trailStep  = TrailStepPips  * g_pipSize;
      double beTrigger  = BE_TriggerPips * g_pipSize;
      double beLock     = BE_LockPips    * g_pipSize;

      if(posInfo.PositionType() == POSITION_TYPE_BUY)
      {
         double bid       = symInfo.Bid();
         double profitDist = bid - openPrice;

         if(UseBreakEven && profitDist >= beTrigger)
         {
            double newSL = NormalizeDouble(openPrice + beLock, symInfo.Digits());
            if(currentSL < newSL)
               trade.PositionModify(ticket, newSL, currentTP);
         }

         if(UseTrailingStop && profitDist >= trailStart)
         {
            double trailSL = NormalizeDouble(bid - trailStep, symInfo.Digits());
            if(trailSL > currentSL)
               trade.PositionModify(ticket, trailSL, currentTP);
         }
      }
      else if(posInfo.PositionType() == POSITION_TYPE_SELL)
      {
         double ask       = symInfo.Ask();
         double profitDist = openPrice - ask;

         if(UseBreakEven && profitDist >= beTrigger)
         {
            double newSL = NormalizeDouble(openPrice - beLock, symInfo.Digits());
            if(currentSL > newSL || currentSL == 0)
               trade.PositionModify(ticket, newSL, currentTP);
         }

         if(UseTrailingStop && profitDist >= trailStart)
         {
            double trailSL = NormalizeDouble(ask + trailStep, symInfo.Digits());
            if(trailSL < currentSL || currentSL == 0)
               trade.PositionModify(ticket, trailSL, currentTP);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Check drawdown limit                                               |
//+------------------------------------------------------------------+
bool IsDrawdownExceeded()
{
   double currentBalance = accInfo.Balance();
   double drawdown = (initialBalance - currentBalance) / initialBalance * 100.0;
   return (drawdown >= MaxDrawdownPct);
}

//+------------------------------------------------------------------+
//| Count open trades for this EA on this symbol                       |
//+------------------------------------------------------------------+
int CountOpenTrades()
{
   int count = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(posInfo.SelectByIndex(i))
         if(posInfo.Magic() == MagicNumber && posInfo.Symbol() == _Symbol)
            count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Check if same direction trade exists                               |
//+------------------------------------------------------------------+
bool HasSameDirectionTrade(int direction)
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != MagicNumber) continue;
      if(posInfo.Symbol() != _Symbol) continue;
      if(direction == 1  && posInfo.PositionType() == POSITION_TYPE_BUY)  return true;
      if(direction == -1 && posInfo.PositionType() == POSITION_TYPE_SELL) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Check if price is separated from existing trades                   |
//+------------------------------------------------------------------+
bool IsPriceSeparated(int direction, double minDistance)
{
   symInfo.Refresh();
   double currentPrice = (direction == 1) ? symInfo.Ask() : symInfo.Bid();
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != MagicNumber) continue;
      if(posInfo.Symbol() != _Symbol) continue;
      if(MathAbs(currentPrice - posInfo.PriceOpen()) < minDistance)
         return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Session filter                                                     |
//+------------------------------------------------------------------+
bool IsValidSession()
{
   MqlDateTime dt;
   TimeCurrent(dt);
   int hour = dt.hour;
   if(UseSession1 && hour >= S1_Start && hour < S1_End) return true;
   if(UseSession2 && hour >= S2_Start && hour < S2_End) return true;
   if(UseSession3 && hour >= S3_Start && hour < S3_End) return true;
   return false;
}

//+------------------------------------------------------------------+
//| Spread check using symbol-aware pip size                           |
//+------------------------------------------------------------------+
bool IsSpreadAcceptable()
{
   symInfo.Refresh();
   double spreadPips = symInfo.Spread() * symInfo.Point() / g_pipSize;
   return (spreadPips <= MaxSpreadPips);
}

//+------------------------------------------------------------------+
//| Track closed trade stats                                           |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans,
                         const MqlTradeRequest& request,
                         const MqlTradeResult& result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;

   // Must select history before accessing deals
   HistorySelect(TimeCurrent() - 86400, TimeCurrent());

   ulong dealTicket = trans.deal;
   if(!HistoryDealSelect(dealTicket)) return;
   if(HistoryDealGetInteger(dealTicket, DEAL_MAGIC) != MagicNumber) return;
   if(HistoryDealGetInteger(dealTicket, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;

   double profit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT)
                 + HistoryDealGetDouble(dealTicket, DEAL_COMMISSION)
                 + HistoryDealGetDouble(dealTicket, DEAL_SWAP);
   if(profit > 0)
   {
      totalWins++;
      totalProfit += profit;
   }
   else
   {
      totalLosses++;
      totalLoss += MathAbs(profit);
   }
}

//+------------------------------------------------------------------+
//| Dashboard display                                                  |
//+------------------------------------------------------------------+
void UpdateDashboard(double emaF, double emaS, double rsiVal, double atrVal,
                     int sBuy, int sSell, int rBuy, int rSell)
{
   double balance  = accInfo.Balance();
   double equity   = accInfo.Equity();
   double dd       = (initialBalance > 0) ? (initialBalance - balance) / initialBalance * 100.0 : 0;
   double winRate  = (totalWins + totalLosses > 0) ?
                     (double)totalWins / (totalWins + totalLosses) * 100.0 : 0;
   int openTrades  = CountOpenTrades();
   double atrPips  = atrVal / g_pipSize;

   string info = "";
   info += "╔══════════════════════════════════╗\n";
   info += "║   SCALPMASTER HFT v1.10          ║\n";
   info += "║   Symbol: " + _Symbol + "               \n";
   info += "╠══════════════════════════════════╣\n";
   info += "║ Balance:  $" + DoubleToString(balance, 2) + "\n";
   info += "║ Equity:   $" + DoubleToString(equity, 2) + "\n";
   info += "║ Drawdown: " + DoubleToString(dd, 2) + "% / " + DoubleToString(MaxDrawdownPct, 0) + "%\n";
   info += "╠══════════════════════════════════╣\n";
   info += "║ Open:  " + IntegerToString(openTrades) + "/" + IntegerToString(MaxOpenTrades) + "\n";
   info += "║ Today: " + IntegerToString(todayTradeCount) + "/" + IntegerToString(MaxTradesPerDay) + "\n";
   info += "║ W:" + IntegerToString(totalWins) + " L:" + IntegerToString(totalLosses) +
           " WR:" + DoubleToString(winRate, 1) + "%\n";
   info += "║ Profit: $" + DoubleToString(totalProfit, 2) + "\n";
   info += "║ Loss:   $" + DoubleToString(totalLoss, 2) + "\n";
   info += "╠══════════════════════════════════╣\n";
   info += "║ EMA F: " + DoubleToString(emaF, symInfo.Digits()) + "\n";
   info += "║ EMA S: " + DoubleToString(emaS, symInfo.Digits()) + "\n";
   info += "║ RSI:   " + DoubleToString(rsiVal, 1) + "\n";
   info += "║ ATR:   " + DoubleToString(atrPips, 1) + " pips\n";
   info += "║ Trend: BUY=" + IntegerToString(sBuy) + " SELL=" + IntegerToString(sSell) + "\n";
   info += "║ Rev:   BUY=" + IntegerToString(rBuy) + " SELL=" + IntegerToString(rSell) + "\n";
   info += "╚══════════════════════════════════╝";

   Comment(info);
}
//+------------------------------------------------------------------+
