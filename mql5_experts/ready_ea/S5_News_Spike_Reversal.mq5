//+------------------------------------------------------------------+
//| Strategy 5 — News Spike Reversal                                 |
//| XAUUSD · Detects M1 spike > SpikeThreshold pips                 |
//| Enters reversal after RSI reversion signal                       |
//| Note: In backtester, real news calendar not available.           |
//| Bot detects large M1 spikes automatically as news proxy.         |
//+------------------------------------------------------------------+
#property copyright "FxVault"
#property version   "1.00"
#include <Trade\Trade.mqh>

input double RiskPct        = 1.0;
input int    SpikeThresh    = 80;   // pips — M1 candle to classify as news spike
input int    SL_Pips        = 30;   // pips beyond spike extreme
input int    Retrace50_Pips = 50;   // TP1 pips (50% retrace proxy)
input int    Retrace70_Pips = 70;   // TP2 pips (70% retrace proxy)
input int    BE_Pips        = 30;
input int    Max_Spread     = 25;
input int    SessionStart   = 7;
input int    SessionEnd     = 22;   // wider window for news events
input int    HoldMaxMin     = 240;  // 4-hour force exit
input int    FailContinuePips = 100; // cancel reversal if price continues >100 pips
input long   MagicNumber    = 20260500;

CTrade trade;
int m1rsi14;

double pip;
datetime lastM1Bar   = 0;
bool     inReversion = false;
double   spikeHigh   = 0, spikeLow = 0;
int      spikeDir    = 0;   // 1=bull spike -1=bear spike
datetime spikeTime   = 0;

ulong    openTicket  = 0;
double   openPrice   = 0;
datetime openTime    = 0;
double   initLot     = 0;
bool     tp1Hit      = false;
bool     beSet       = false;

int OnInit()
{
   pip     = _Point * 10;
   m1rsi14 = iRSI(_Symbol, PERIOD_M1, 14, PRICE_CLOSE);
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   if(m1rsi14 == INVALID_HANDLE) return INIT_FAILED;
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) {}

bool InSession()
{
   MqlDateTime tm; TimeGMT(tm);
   return (tm.hour >= SessionStart && tm.hour < SessionEnd);
}

double CalcLot(int sl_pips)
{
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_usd = equity * RiskPct / 100.0;
   double tick_val = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_sz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double lot_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double min_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double sl_price = sl_pips * pip;
   if(sl_price <= 0 || tick_sz <= 0) return min_lot;
   double raw = risk_usd / (sl_price / tick_sz * tick_val);
   return MathMax(min_lot, MathMin(max_lot, MathFloor(raw / lot_step) * lot_step));
}

void DetectSpike()
{
   if(inReversion) return;
   datetime bar = iTime(_Symbol, PERIOD_M1, 1);  // last closed M1
   if(bar == lastM1Bar) return;
   lastM1Bar = bar;

   double h = iHigh(_Symbol,  PERIOD_M1, 1);
   double l = iLow(_Symbol,   PERIOD_M1, 1);
   double o = iOpen(_Symbol,  PERIOD_M1, 1);
   double c = iClose(_Symbol, PERIOD_M1, 1);
   double range_pips = (h - l) / pip;

   if(range_pips < SpikeThresh) return;

   spikeHigh = h;
   spikeLow  = l;
   spikeTime = bar;
   spikeDir  = (c > o) ? 1 : -1;   // bull or bear spike
   inReversion = true;
}

// Broker minimum valid stop distance (price units): max of stops-level and
// spread, plus a small buffer. SL/TP closer than this => "invalid stops".
double MinStopDist()
{
   long   lvl    = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double spread = SymbolInfoDouble(_Symbol, SYMBOL_ASK) -
                   SymbolInfoDouble(_Symbol, SYMBOL_BID);
   return MathMax(lvl * _Point, spread) + 5 * pip;   // 5-pip safety buffer
}

void SeekReversal()
{
   if(!inReversion || openTicket != 0) return;
   if(spikeDir == 0) return;

   // check spike failure: if price continues >100 pips beyond spike extreme
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(spikeDir == 1 && bid > spikeHigh + FailContinuePips * pip) { inReversion = false; return; }
   if(spikeDir == -1 && bid < spikeLow - FailContinuePips * pip) { inReversion = false; return; }

   // window: 5–30 min after spike
   int elapsed = (int)(TimeCurrent() - spikeTime) / 60;
   if(elapsed < 5 || elapsed > 30) { if(elapsed > 30) inReversion = false; return; }

   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) -
                    SymbolInfoDouble(_Symbol, SYMBOL_BID)) / pip;
   if(spread > Max_Spread) return;

   double rsi[]; ArraySetAsSeries(rsi, true);
   if(CopyBuffer(m1rsi14, 0, 0, 2, rsi) < 2) return;   // rsi[1] = last CLOSED M1 bar
   double minD = MinStopDist();

   // reversal: bear spike → BUY (RSI<35); bull spike → SELL (RSI>65)
   if(spikeDir == -1 && rsi[1] < 35)
   {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double sl  = spikeLow - SL_Pips * pip;        // SL beyond spike extreme
      double tp  = ask + Retrace70_Pips * pip;
      // entry must sit a valid distance ABOVE the SL; if not, no room → skip
      if(ask - sl < minD) return;
      if(tp - ask < minD) tp = ask + minD;          // respect broker stop level
      int    slp = (int)MathRound((ask - sl) / pip);// size off ACTUAL SL distance
      double lot = CalcLot(slp);
      if(trade.Buy(lot, _Symbol, ask,
                   NormalizeDouble(sl, _Digits),
                   NormalizeDouble(tp, _Digits), "S5_BUY_REV"))
      {
         openTicket=trade.ResultOrder(); openPrice=ask;
         openTime=TimeCurrent(); initLot=lot; tp1Hit=false; beSet=false;
      }
      else inReversion = false;                     // don't spam failed orders
   }
   else if(spikeDir == 1 && rsi[1] > 65)
   {
      double bid2 = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double sl   = spikeHigh + SL_Pips * pip;
      double tp   = bid2 - Retrace70_Pips * pip;
      if(sl - bid2 < minD) return;
      if(bid2 - tp < minD) tp = bid2 - minD;
      int    slp  = (int)MathRound((sl - bid2) / pip);
      double lot  = CalcLot(slp);
      if(trade.Sell(lot, _Symbol, bid2,
                    NormalizeDouble(sl, _Digits),
                    NormalizeDouble(tp, _Digits), "S5_SELL_REV"))
      {
         openTicket=trade.ResultOrder(); openPrice=bid2;
         openTime=TimeCurrent(); initLot=lot; tp1Hit=false; beSet=false;
      }
      else inReversion = false;
   }
}

void ManageOpenTrade()
{
   if(openTicket == 0) return;
   if(!PositionSelectByTicket(openTicket)) { openTicket = 0; inReversion = false; return; }

   int    type     = (int)PositionGetInteger(POSITION_TYPE);
   double bid      = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask      = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double cur      = (type == POSITION_TYPE_BUY) ? bid : ask;
   double pnl_pips = (type == POSITION_TYPE_BUY) ? (cur - openPrice) / pip
                                                  : (openPrice - cur) / pip;

   if(!beSet && pnl_pips >= BE_Pips)
   {
      double new_sl = (type == POSITION_TYPE_BUY)
                      ? openPrice + 2*pip : openPrice - 2*pip;
      trade.PositionModify(openTicket, NormalizeDouble(new_sl, _Digits),
                           PositionGetDouble(POSITION_TP));
      beSet = true;
   }

   if(!tp1Hit && pnl_pips >= Retrace50_Pips)
   {
      double vol     = PositionGetDouble(POSITION_VOLUME);
      double close_v = NormalizeDouble(initLot * 0.5, 2);
      close_v = MathMax(close_v, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN));
      if(close_v <= vol) { trade.PositionClosePartial(openTicket, close_v); tp1Hit = true; }
   }

   // 4-hour force exit
   if((int)(TimeCurrent() - openTime) / 60 >= HoldMaxMin)
   {
      trade.PositionClose(openTicket);
      openTicket = 0; inReversion = false;
   }
}

void OnTick()
{
   if(!InSession()) return;
   ManageOpenTrade();
   DetectSpike();
   SeekReversal();
}
