//+------------------------------------------------------------------+
//| Strategy 18 — Heikin Ashi Trend Rider  (Notion #2 TOP WINNER)    |
//| XAUUSD · D1 · Risk 1.0%                                          |
//|                                                                  |
//| Notion backtest (Yahoo, XAUUSD D1, 2y): WR 71.4% · +93.55% ·     |
//|   PF 4.96 · maxDD 7.97% · 14 trades. Highest-return strategy.    |
//|                                                                  |
//| Entry (BUY): EMA50>EMA200 AND last 3 HA candles all bull AND      |
//|   last 5 HA have 3-4 bull (fresh, not over-extended) AND          |
//|   Close > EMA50.  SELL = mirror.                                  |
//| Exit : fixed  SL = entry -/+ ATR*1.5 ,  TP = entry +/- ATR*3.5    |
//|        (1:2.3 RR). No partials/trailing — backtest used fixed     |
//|        SL/TP, so live == tested.                                  |
//|                                                                  |
//| Decisions on CLOSED D1 bars only (shift>=1). Source spec: Notion  |
//| page 364bbf27-1afa-8114-a526-f82fec90e2bf.                        |
//+------------------------------------------------------------------+
#property copyright "FxVault"
#property version   "1.00"
#include <Trade\Trade.mqh>

input double RiskPct     = 1.0;
input int    EMAFastP    = 50;
input int    EMASlowP    = 200;
input int    ATRPeriod   = 14;
input double SL_ATR_Mult  = 1.5;
input double TP_ATR_Mult  = 3.5;
input int    Max_Spread  = 60;     // points; Gold spread guard
input long   MagicNumber = 20261800;

CTrade trade;
int    emaFast, emaSlow, atrH;
double pip;
datetime lastD1Bar = 0;
ulong  openTicket  = 0;

int OnInit()
{
   pip     = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   emaFast = iMA(_Symbol, PERIOD_D1, EMAFastP, 0, MODE_EMA, PRICE_CLOSE);
   emaSlow = iMA(_Symbol, PERIOD_D1, EMASlowP, 0, MODE_EMA, PRICE_CLOSE);
   atrH    = iATR(_Symbol, PERIOD_D1, ATRPeriod);
   if(emaFast == INVALID_HANDLE || emaSlow == INVALID_HANDLE ||
      atrH    == INVALID_HANDLE) return INIT_FAILED;
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

// Heikin-Ashi over the last N D1 bars. haBull[s]/haBear[s] indexed by
// shift (1 = last CLOSED daily bar). HA_Open recursion needs oldest→
// newest, so we build forward then expose by shift.
#define HA_N 120
bool haBull[HA_N];
bool haBear[HA_N];
bool haValid = false;

void BuildHA()
{
   MqlRates r[]; ArraySetAsSeries(r, true);          // r[0] = forming bar
   int got = CopyRates(_Symbol, PERIOD_D1, 0, HA_N, r);
   haValid = false;
   if(got < 30) return;

   double haO[HA_N], haC[HA_N];
   int o = got - 1;                                  // oldest
   haC[o] = (r[o].open + r[o].high + r[o].low + r[o].close) / 4.0;
   haO[o] = (r[o].open + r[o].close) / 2.0;
   for(int i = got - 2; i >= 0; i--)
   {
      haC[i] = (r[i].open + r[i].high + r[i].low + r[i].close) / 4.0;
      haO[i] = (haO[i + 1] + haC[i + 1]) / 2.0;
   }
   for(int s = 0; s < got; s++)
   {
      haBull[s] = haC[s] > haO[s];
      haBear[s] = haC[s] < haO[s];
   }
   haValid = true;
}

bool Last3(bool bull)            // shifts 1,2,3 all same colour
{
   if(bull) return haBull[1] && haBull[2] && haBull[3];
   return       haBear[1] && haBear[2] && haBear[3];
}
int Count5(bool bull)            // bull/bear count over shifts 1..5
{
   int c = 0;
   for(int s = 1; s <= 5; s++) c += (bull ? haBull[s] : haBear[s]) ? 1 : 0;
   return c;
}

void OnTick()
{
   // act once per new CLOSED D1 bar
   datetime b = iTime(_Symbol, PERIOD_D1, 0);
   if(b == lastD1Bar) return;
   lastD1Bar = b;

   if(HavePosition()) return;

   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) -
                    SymbolInfoDouble(_Symbol, SYMBOL_BID)) / _Point;
   if(spread > Max_Spread) return;

   BuildHA();
   if(!haValid) return;

   double ef[], es[], at[];
   ArraySetAsSeries(ef, true); ArraySetAsSeries(es, true);
   ArraySetAsSeries(at, true);
   if(CopyBuffer(emaFast, 0, 0, 3, ef) < 3) return;
   if(CopyBuffer(emaSlow, 0, 0, 3, es) < 3) return;
   if(CopyBuffer(atrH,    0, 0, 3, at) < 3) return;

   double close1 = iClose(_Symbol, PERIOD_D1, 1);    // last closed D1 close
   double ema50  = ef[1];
   double ema200 = es[1];
   double atr    = at[1];
   if(atr <= 0) return;

   int  c5b = Count5(true);
   int  c5s = Count5(false);
   bool buy  = Last3(true)  && (c5b >= 3 && c5b <= 4) &&
               ema50 > ema200 && close1 > ema50;
   bool sell = Last3(false) && (c5s >= 3 && c5s <= 4) &&
               ema50 < ema200 && close1 < ema50;
   if(!buy && !sell) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl_dist = atr * SL_ATR_Mult;
   double tp_dist = atr * TP_ATR_Mult;
   double lot = CalcLot(sl_dist);

   if(buy)
   {
      double sl = NormalizeDouble(ask - sl_dist, _Digits);
      double tp = NormalizeDouble(ask + tp_dist, _Digits);
      if(trade.Buy(lot, _Symbol, ask, sl, tp, "S18_BUY"))
         openTicket = trade.ResultOrder();
   }
   else
   {
      double sl = NormalizeDouble(bid + sl_dist, _Digits);
      double tp = NormalizeDouble(bid - tp_dist, _Digits);
      if(trade.Sell(lot, _Symbol, bid, sl, tp, "S18_SELL"))
         openTicket = trade.ResultOrder();
   }
}
