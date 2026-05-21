//+------------------------------------------------------------------+
//| Strategy 4 — Multi-Pair Parallel Engine (single-pair instance)  |
//| Attach to each pair chart separately.                            |
//| Pair configs auto-loaded from symbol name.                       |
//| Logic: S3 M1 HFT adapted per pair SL/TP/ATR/spread/session      |
//+------------------------------------------------------------------+
#property copyright "FxVault"
#property version   "1.00"
#include <Trade\Trade.mqh>

input double RiskPct     = 0.3;
input long   MagicNumber = 20260400;
// Override 0 = auto-detect from symbol
input int    Override_SL       = 0;
input int    Override_TP1      = 0;
input int    Override_TP2      = 0;
input double Override_ATR_Min  = 0;
input double Override_ATR_Max  = 0;
input int    Override_Spread   = 0;
input int    Session1_Start    = -1;
input int    Session1_End      = -1;
input int    Session2_Start    = -1;
input int    Session2_End      = -1;

CTrade trade;
int h1ema200, m5ema5, m5ema13, m1ema5, m1ema13, m1rsi7, m1atr;

// per-pair auto config
int    g_sl, g_tp1, g_tp2, g_spread;
double g_atr_min, g_atr_max;
int    g_sess[2][2];   // [session_idx][start/end]
int    g_sess_count;

datetime lastM1Bar = 0, lastH1Bar = 0;
int      h1BiasDir = 0;
ulong    openTicket = 0;
double   openPrice = 0;
datetime openTime  = 0;
double   initLot   = 0;
bool     tp1Hit    = false, beSet = false;
double   pip;

void LoadPairConfig()
{
   string sym = _Symbol;
   if(sym == "XAUUSD")  { g_sl=7;  g_tp1=10; g_tp2=15; g_atr_min=0.50; g_atr_max=3.00; g_spread=20; g_sess[0][0]=8;  g_sess[0][1]=17; g_sess_count=1; }
   else if(sym == "XAGUSD") { g_sl=8; g_tp1=12; g_tp2=18; g_atr_min=0.03; g_atr_max=0.20; g_spread=25; g_sess[0][0]=8; g_sess[0][1]=17; g_sess_count=1; }
   else if(sym == "USDJPY") { g_sl=8; g_tp1=12; g_tp2=18; g_atr_min=0.10; g_atr_max=0.50; g_spread=2;  g_sess[0][0]=0; g_sess[0][1]=4; g_sess[1][0]=13; g_sess[1][1]=17; g_sess_count=2; }
   else if(sym == "GBPUSD") { g_sl=10; g_tp1=15; g_tp2=22; g_atr_min=0.0008; g_atr_max=0.003; g_spread=3; g_sess[0][0]=8; g_sess[0][1]=17; g_sess_count=1; }
   else if(sym == "EURUSD") { g_sl=7;  g_tp1=11; g_tp2=16; g_atr_min=0.0005; g_atr_max=0.0025; g_spread=1; g_sess[0][0]=7; g_sess[0][1]=17; g_sess_count=1; }
   else { g_sl=10; g_tp1=15; g_tp2=20; g_atr_min=0.0001; g_atr_max=1.0; g_spread=20; g_sess[0][0]=7; g_sess[0][1]=17; g_sess_count=1; }

   // allow overrides
   if(Override_SL > 0)      g_sl      = Override_SL;
   if(Override_TP1 > 0)     g_tp1     = Override_TP1;
   if(Override_TP2 > 0)     g_tp2     = Override_TP2;
   if(Override_ATR_Min > 0) g_atr_min = Override_ATR_Min;
   if(Override_ATR_Max > 0) g_atr_max = Override_ATR_Max;
   if(Override_Spread > 0)  g_spread  = Override_Spread;
   if(Session1_Start >= 0)  { g_sess[0][0]=Session1_Start; g_sess[0][1]=Session1_End; g_sess_count=1; }
   if(Session2_Start >= 0)  { g_sess[1][0]=Session2_Start; g_sess[1][1]=Session2_End; g_sess_count=2; }
}

int OnInit()
{
   pip = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   LoadPairConfig();

   h1ema200 = iMA(_Symbol, PERIOD_H1, 200, 0, MODE_EMA, PRICE_CLOSE);
   m5ema5   = iMA(_Symbol, PERIOD_M5,   5, 0, MODE_EMA, PRICE_CLOSE);
   m5ema13  = iMA(_Symbol, PERIOD_M5,  13, 0, MODE_EMA, PRICE_CLOSE);
   m1ema5   = iMA(_Symbol, PERIOD_M1,   5, 0, MODE_EMA, PRICE_CLOSE);
   m1ema13  = iMA(_Symbol, PERIOD_M1,  13, 0, MODE_EMA, PRICE_CLOSE);
   m1rsi7   = iRSI(_Symbol, PERIOD_M1,  7, PRICE_CLOSE);
   m1atr    = iATR(_Symbol, PERIOD_M1, 14);

   if(h1ema200 == INVALID_HANDLE) return INIT_FAILED;
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) {}

bool InSession()
{
   MqlDateTime tm; TimeGMT(tm);
   for(int i = 0; i < g_sess_count; i++)
      if(tm.hour >= g_sess[i][0] && tm.hour < g_sess[i][1]) return true;
   return false;
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
   double ema[2]; CopyBuffer(h1ema200, 0, 0, 2, ema);
   double price = iClose(_Symbol, PERIOD_H1, 1);
   double dist  = MathAbs(price - ema[1]) / pip;
   if(dist < 20) { h1BiasDir = 0; return; }
   h1BiasDir = (price > ema[1]) ? 1 : -1;
}

bool CheckM5Trend(int dir)
{
   double e5[1], e13[1];
   CopyBuffer(m5ema5,  0, 0, 1, e5);
   CopyBuffer(m5ema13, 0, 0, 1, e13);
   return (dir == 1) ? e5[0] > e13[0] : e5[0] < e13[0];
}

bool CheckM1Cross(int dir)
{
   double e5[3], e13[3], rsi[1], atr[1];
   CopyBuffer(m1ema5,  0, 0, 3, e5);
   CopyBuffer(m1ema13, 0, 0, 3, e13);
   CopyBuffer(m1rsi7,  0, 0, 1, rsi);
   CopyBuffer(m1atr,   0, 0, 1, atr);
   bool cross = (dir == 1) ? (e5[1] <= e13[1] && e5[0] > e13[0])
                            : (e5[1] >= e13[1] && e5[0] < e13[0]);
   if(!cross) return false;
   if(rsi[0] < 40 || rsi[0] > 60) return false;
   if(atr[0] < g_atr_min || atr[0] > g_atr_max) return false;
   return true;
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

   if(!beSet && pnl_pips >= 4)
   {
      double new_sl = (type == POSITION_TYPE_BUY) ? openPrice + 6*pip : openPrice - 6*pip;
      trade.PositionModify(openTicket, NormalizeDouble(new_sl, _Digits),
                           PositionGetDouble(POSITION_TP));
      beSet = true;
   }

   if(!tp1Hit && pnl_pips >= g_tp1)
   {
      double vol     = PositionGetDouble(POSITION_VOLUME);
      double close_v = NormalizeDouble(initLot * 0.6, 2);
      close_v = MathMax(close_v, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN));
      if(close_v <= vol) { trade.PositionClosePartial(openTicket, close_v); tp1Hit = true; }
   }

   if((int)(TimeCurrent() - openTime) / 60 >= 15)
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
   if(spread > g_spread) return;

   datetime m1bar = iTime(_Symbol, PERIOD_M1, 0);
   if(m1bar == lastM1Bar) return;
   lastM1Bar = m1bar;

   int dir = h1BiasDir;
   if(!CheckM5Trend(dir)) return;
   if(!CheckM1Cross(dir)) return;

   double lot  = CalcLot(g_sl);
   double sl_d = g_sl  * pip;
   double tp_d = g_tp2 * pip;

   if(dir == 1)
   {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(trade.Buy(lot, _Symbol, ask,
                   NormalizeDouble(ask - sl_d, _Digits),
                   NormalizeDouble(ask + tp_d, _Digits), "S4_BUY"))
      {
         openTicket=trade.ResultOrder(); openPrice=ask;
         openTime=TimeCurrent(); initLot=lot; tp1Hit=false; beSet=false;
      }
   }
   else
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(trade.Sell(lot, _Symbol, bid,
                    NormalizeDouble(bid + sl_d, _Digits),
                    NormalizeDouble(bid - tp_d, _Digits), "S4_SELL"))
      {
         openTicket=trade.ResultOrder(); openPrice=bid;
         openTime=TimeCurrent(); initLot=lot; tp1Hit=false; beSet=false;
      }
   }
}

void OnTick()
{
   RefreshH1Bias();
   ManageOpenTrade();
   SeekSignal();
}
