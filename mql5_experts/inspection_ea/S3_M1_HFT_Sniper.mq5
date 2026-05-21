//+------------------------------------------------------------------+
//| Strategy 3 — M1 HFT Sniper                                      |
//| XAUUSD · Sessions 07:00-17:00 UTC · Risk 0.3%                   |
//| Layers: H1 EMA200 → M5 EMA5/13 → M1 EMA5/13 + RSI7 + ATR14     |
//+------------------------------------------------------------------+
#property copyright "FxVault"
#property version   "1.00"
#include <Trade\Trade.mqh>

//── inputs ──────────────────────────────────────────────────────────
input double RiskPct      = 0.3;    // Risk % per trade
input int    SL_Pips      = 7;      // Stop loss (pips)
input int    TP1_Pips     = 10;     // TP1 (pips)
input int    TP2_Pips     = 15;     // TP2 (pips)
input int    BE_Pips      = 4;      // Break-even trigger (pips)
input int    BE_Lock_Pips = 6;      // SL moved to entry + this after BE
input double ATR_Min      = 0.50;
input double ATR_Max      = 3.00;
input int    Max_Spread   = 20;     // pips
input int    SessionStart = 7;      // UTC hour
input int    SessionEnd   = 17;
input int    TimeExit_Min = 15;
input int    BrokerGMT    = 3;      // broker GMT offset (3 = UTC+3)
input long   MagicNumber  = 20260300;

//── globals ──────────────────────────────────────────────────────────
CTrade trade;
int h1_ema200_handle, m5_ema5_handle, m5_ema13_handle;
int m1_ema5_handle,   m1_ema13_handle, m1_rsi7_handle, m1_atr_handle;

datetime lastM1Bar     = 0;
datetime lastH1Bias    = 0;
int      h1BiasDir     = 0;   // 1=BUY_ONLY -1=SELL_ONLY 0=NO_TRADE
bool     h1BiasDirty   = true;

ulong    openTicket    = 0;
double   openPrice     = 0;
datetime openTime      = 0;
double   initLot       = 0;
bool     tp1Hit        = false;
bool     beSet         = false;

double pip;

//+------------------------------------------------------------------+
int OnInit()
{
   pip = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);

   h1_ema200_handle  = iMA(_Symbol, PERIOD_H1,  200, 0, MODE_EMA, PRICE_CLOSE);
   m5_ema5_handle    = iMA(_Symbol, PERIOD_M5,    5, 0, MODE_EMA, PRICE_CLOSE);
   m5_ema13_handle   = iMA(_Symbol, PERIOD_M5,   13, 0, MODE_EMA, PRICE_CLOSE);
   m1_ema5_handle    = iMA(_Symbol, PERIOD_M1,    5, 0, MODE_EMA, PRICE_CLOSE);
   m1_ema13_handle   = iMA(_Symbol, PERIOD_M1,   13, 0, MODE_EMA, PRICE_CLOSE);
   m1_rsi7_handle    = iRSI(_Symbol, PERIOD_M1,   7, PRICE_CLOSE);
   m1_atr_handle     = iATR(_Symbol, PERIOD_M1,  14);

   if(h1_ema200_handle == INVALID_HANDLE || m1_ema5_handle == INVALID_HANDLE)
      return INIT_FAILED;
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {}

//+------------------------------------------------------------------+
bool InSession()
{
   MqlDateTime tm;
   TimeGMT(tm);
   int h = tm.hour;
   return (h >= SessionStart && h < SessionEnd);
}

double CalcLot(int sl_pips)
{
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_usd = equity * RiskPct / 100.0;
   double sl_price = sl_pips * pip;
   double tick_val = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_sz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double lot_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double min_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(sl_price <= 0 || tick_sz <= 0) return min_lot;
   double raw = risk_usd / (sl_price / tick_sz * tick_val);
   double lot = MathFloor(raw / lot_step) * lot_step;
   return MathMax(min_lot, MathMin(max_lot, lot));
}

void RefreshH1Bias()
{
   datetime now_d = TimeCurrent();
   MqlDateTime tm;
   TimeToStruct(now_d, tm);
   // refresh once per H1 bar
   datetime h1bar = iTime(_Symbol, PERIOD_H1, 0);
   if(h1bar == lastH1Bias) return;
   lastH1Bias = h1bar;

   double ema200[3];
   CopyBuffer(h1_ema200_handle, 0, 0, 3, ema200);
   double price = iClose(_Symbol, PERIOD_H1, 1);
   double dist  = MathAbs(price - ema200[1]) / pip;
   if(dist < 20) { h1BiasDir = 0; return; }
   h1BiasDir = (price > ema200[1]) ? 1 : -1;
}

bool CheckM5Trend(int dir)
{
   double e5[2], e13[2];
   CopyBuffer(m5_ema5_handle,  0, 0, 2, e5);
   CopyBuffer(m5_ema13_handle, 0, 0, 2, e13);
   if(dir == 1)  return e5[0] > e13[0];
   if(dir == -1) return e5[0] < e13[0];
   return false;
}

bool CheckM1Cross(int dir)
{
   double e5[3], e13[3];
   CopyBuffer(m1_ema5_handle,  0, 0, 3, e5);
   CopyBuffer(m1_ema13_handle, 0, 0, 3, e13);
   bool cross = false;
   if(dir == 1)  cross = (e5[1] <= e13[1] && e5[0] > e13[0]);
   if(dir == -1) cross = (e5[1] >= e13[1] && e5[0] < e13[0]);
   if(!cross) return false;

   double rsi[1], atr[1];
   CopyBuffer(m1_rsi7_handle, 0, 0, 1, rsi);
   CopyBuffer(m1_atr_handle,  0, 0, 1, atr);
   if(rsi[0] < 40 || rsi[0] > 60) return false;
   if(atr[0] < ATR_Min || atr[0] > ATR_Max) return false;
   return true;
}

bool SpreadOK()
{
   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) -
                    SymbolInfoDouble(_Symbol, SYMBOL_BID)) / pip;
   return spread <= Max_Spread;
}

void ManageOpenTrade()
{
   if(openTicket == 0) return;
   if(!PositionSelectByTicket(openTicket)) { openTicket = 0; return; }

   double bid   = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask   = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   int    type  = (int)PositionGetInteger(POSITION_TYPE);
   double cur   = (type == POSITION_TYPE_BUY) ? bid : ask;
   double pnl_pips = (type == POSITION_TYPE_BUY)
                     ? (cur - openPrice) / pip
                     : (openPrice - cur) / pip;

   // BE
   if(!beSet && pnl_pips >= BE_Pips)
   {
      double new_sl = (type == POSITION_TYPE_BUY)
                      ? openPrice + BE_Lock_Pips * pip
                      : openPrice - BE_Lock_Pips * pip;
      trade.PositionModify(openTicket, NormalizeDouble(new_sl, _Digits),
                           PositionGetDouble(POSITION_TP));
      beSet = true;
   }

   // TP1 partial
   if(!tp1Hit && pnl_pips >= TP1_Pips)
   {
      double vol      = PositionGetDouble(POSITION_VOLUME);
      double close_v  = NormalizeDouble(initLot * 0.6, 2);
      close_v = MathMax(close_v, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN));
      if(close_v <= vol)
      {
         trade.PositionClosePartial(openTicket, close_v);
         tp1Hit = true;
      }
   }

   // Time exit
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
   if(!SpreadOK()) return;

   datetime m1bar = iTime(_Symbol, PERIOD_M1, 0);
   if(m1bar == lastM1Bar) return;
   lastM1Bar = m1bar;

   int dir = h1BiasDir;
   if(!CheckM5Trend(dir)) return;
   if(!CheckM1Cross(dir)) return;

   double lot = CalcLot(SL_Pips);
   double sl_d  = SL_Pips * pip;
   double tp2_d = TP2_Pips * pip;

   if(dir == 1)
   {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(trade.Buy(lot, _Symbol, ask,
                   NormalizeDouble(ask - sl_d, _Digits),
                   NormalizeDouble(ask + tp2_d, _Digits), "S3_BUY"))
      {
         openTicket = trade.ResultOrder();
         openPrice  = ask;
         openTime   = TimeCurrent();
         initLot    = lot;
         tp1Hit     = false;
         beSet      = false;
      }
   }
   else
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(trade.Sell(lot, _Symbol, bid,
                    NormalizeDouble(bid + sl_d, _Digits),
                    NormalizeDouble(bid - tp2_d, _Digits), "S3_SELL"))
      {
         openTicket = trade.ResultOrder();
         openPrice  = bid;
         openTime   = TimeCurrent();
         initLot    = lot;
         tp1Hit     = false;
         beSet      = false;
      }
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   RefreshH1Bias();
   ManageOpenTrade();
   SeekSignal();
}
//+------------------------------------------------------------------+
