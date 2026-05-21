//+------------------------------------------------------------------+
//| Strategy 2 — M5 Medium Frequency Scalp                          |
//| XAUUSD · Sessions 07:00-17:00 UTC · Risk 0.5%                   |
//| Layers: H1 EMA200 → M5 EMA9/21 cross → RSI14 zone → MACD hist   |
//+------------------------------------------------------------------+
#property copyright "FxVault"
#property version   "1.00"
#include <Trade\Trade.mqh>

input double RiskPct      = 0.5;
input int    SL_Pips      = 18;
input int    TP1_Pips     = 20;
input int    TP2_Pips     = 40;
input int    BE_Pips      = 8;
input int    Max_Spread   = 25;
input int    SessionStart = 7;
input int    SessionEnd   = 17;
input int    TimeExit_Min = 45;
input long   MagicNumber  = 20260200;

CTrade trade;
int h1ema200, m5ema9, m5ema21, m5rsi14, m5macd;
int m5macd_signal;

datetime lastM5Bar = 0;
datetime lastH1Bar = 0;
int      h1BiasDir = 0;

ulong    openTicket = 0;
double   openPrice  = 0;
datetime openTime   = 0;
double   initLot    = 0;
bool     tp1Hit     = false;
bool     beSet      = false;
double pip;

int OnInit()
{
   pip = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(20);

   h1ema200  = iMA(_Symbol, PERIOD_H1, 200, 0, MODE_EMA, PRICE_CLOSE);
   m5ema9    = iMA(_Symbol, PERIOD_M5,   9, 0, MODE_EMA, PRICE_CLOSE);
   m5ema21   = iMA(_Symbol, PERIOD_M5,  21, 0, MODE_EMA, PRICE_CLOSE);
   m5rsi14   = iRSI(_Symbol, PERIOD_M5, 14, PRICE_CLOSE);
   m5macd    = iMACD(_Symbol, PERIOD_M5, 12, 26, 9, PRICE_CLOSE);

   if(h1ema200 == INVALID_HANDLE) return INIT_FAILED;
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

void RefreshH1Bias()
{
   datetime bar = iTime(_Symbol, PERIOD_H1, 0);
   if(bar == lastH1Bar) return;
   lastH1Bar = bar;
   double ema[2];
   CopyBuffer(h1ema200, 0, 0, 2, ema);
   double price = iClose(_Symbol, PERIOD_H1, 1);
   double dist  = MathAbs(price - ema[1]) / pip;
   if(dist < 20) { h1BiasDir = 0; return; }
   h1BiasDir = (price > ema[1]) ? 1 : -1;
}

bool CheckM5Cross(int &dir)
{
   double e9[3], e21[3];
   CopyBuffer(m5ema9,  0, 0, 3, e9);
   CopyBuffer(m5ema21, 0, 0, 3, e21);
   bool bull = (e9[1] <= e21[1] && e9[0] > e21[0]);
   bool bear = (e9[1] >= e21[1] && e9[0] < e21[0]);
   if(bull) { dir = 1; return true; }
   if(bear) { dir = -1; return true; }
   return false;
}

bool CheckRSI(int dir)
{
   double rsi[1];
   CopyBuffer(m5rsi14, 0, 0, 1, rsi);
   if(dir == 1)  return (rsi[0] >= 40 && rsi[0] <= 65);
   if(dir == -1) return (rsi[0] >= 35 && rsi[0] <= 60);
   return false;
}

bool CheckMACD(int dir)
{
   double hist[2];
   CopyBuffer(m5macd, 2, 0, 2, hist);  // buffer 2 = histogram
   if(dir == 1)  return (hist[0] > 0 || hist[0] > hist[1]);
   if(dir == -1) return (hist[0] < 0 || hist[0] < hist[1]);
   return false;
}

void ManageOpenTrade()
{
   if(openTicket == 0) return;
   if(!PositionSelectByTicket(openTicket)) { openTicket = 0; return; }

   int    type     = (int)PositionGetInteger(POSITION_TYPE);
   double bid      = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask      = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double cur      = (type == POSITION_TYPE_BUY) ? bid : ask;
   double pnl_pips = (type == POSITION_TYPE_BUY) ? (cur - openPrice) / pip
                                                  : (openPrice - cur) / pip;

   if(!beSet && pnl_pips >= BE_Pips)
   {
      double new_sl = (type == POSITION_TYPE_BUY)
                      ? openPrice + 2 * pip
                      : openPrice - 2 * pip;
      trade.PositionModify(openTicket, NormalizeDouble(new_sl, _Digits),
                           PositionGetDouble(POSITION_TP));
      beSet = true;
   }

   if(!tp1Hit && pnl_pips >= TP1_Pips)
   {
      double vol   = PositionGetDouble(POSITION_VOLUME);
      double close_v = NormalizeDouble(initLot * 0.5, 2);
      close_v = MathMax(close_v, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN));
      if(close_v <= vol)
      {
         trade.PositionClosePartial(openTicket, close_v);
         tp1Hit = true;
      }
   }

   if((int)(TimeCurrent() - openTime) / 60 >= TimeExit_Min)
   {
      trade.PositionClose(openTicket);
      openTicket = 0;
   }
}

void SeekSignal()
{
   if(openTicket != 0) return;
   if(h1BiasDir == 0) return;
   if(!InSession()) return;

   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) -
                    SymbolInfoDouble(_Symbol, SYMBOL_BID)) / pip;
   if(spread > Max_Spread) return;

   datetime m5bar = iTime(_Symbol, PERIOD_M5, 0);
   if(m5bar == lastM5Bar) return;
   lastM5Bar = m5bar;

   int crossDir = 0;
   if(!CheckM5Cross(crossDir)) return;
   if(crossDir != h1BiasDir) return;
   if(!CheckRSI(crossDir)) return;
   if(!CheckMACD(crossDir)) return;

   double lot  = CalcLot(SL_Pips);
   double sl_d = SL_Pips * pip;
   double tp_d = TP2_Pips * pip;

   if(crossDir == 1)
   {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(trade.Buy(lot, _Symbol, ask,
                   NormalizeDouble(ask - sl_d, _Digits),
                   NormalizeDouble(ask + tp_d, _Digits), "S2_BUY"))
      {
         openTicket = trade.ResultOrder();
         openPrice = ask; openTime = TimeCurrent();
         initLot = lot; tp1Hit = false; beSet = false;
      }
   }
   else
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(trade.Sell(lot, _Symbol, bid,
                    NormalizeDouble(bid + sl_d, _Digits),
                    NormalizeDouble(bid - tp_d, _Digits), "S2_SELL"))
      {
         openTicket = trade.ResultOrder();
         openPrice = bid; openTime = TimeCurrent();
         initLot = lot; tp1Hit = false; beSet = false;
      }
   }
}

void OnTick()
{
   RefreshH1Bias();
   ManageOpenTrade();
   SeekSignal();
}
