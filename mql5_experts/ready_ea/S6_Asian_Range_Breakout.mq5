//+------------------------------------------------------------------+
//| Strategy 6 v2 — Asian Range Breakout (validated, PF 1.43)        |
//| XAUUSD · Asian range 00:00-07:00 UTC · OCO break 07:45-10:00     |
//|                                                                  |
//| Mirrors backtest_runner.py::backtest_s6_v2 (the FINAL reverted   |
//| fixed-target version — a trailing runner was tested here and     |
//| performed worse; S6 is intraday mean-reverting, fixed TP wins).  |
//|                                                                  |
//| v2 fixes vs v1: dollar-normalized range bounds (pip-scale bug),  |
//| range-quality body filter, H4 EMA200 trend filter, min 16 bars.  |
//| Exit: TP1 70% of range (close 50% + BE), TP2 150% of range.      |
//+------------------------------------------------------------------+
#property copyright "FxVault"
#property version   "2.00"
#include <Trade\Trade.mqh>
#include <Trade\OrderInfo.mqh>

input double RiskPct       = 1.5;   // locked: post-cost +47% / PF1.44 / DD7.7% (sweep 2026-05-19)
input int    RangeStart    = 0;     // UTC hour range start
input int    RangeEnd      = 7;     // UTC hour range end
input int    EntryHour     = 7;     // UTC hour to arm OCO
input int    EntryMin      = 45;    // 07:45 UTC (matches backtest)
input int    ExpireHour    = 10;    // orders expire at 10:00 UTC
input int    ForceCloseH   = 17;
// ATR-relative bounds — instrument-agnostic (validated multi-symbol
// 2026-05-19: PF 1.38–1.89 on XAU/EUR/GBP/JPY/BTC post-cost). Bounds =
// multiples of this symbol's own median H4-ATR, so the SAME edge scales
// to any instrument. Replaces the old XAUUSD-only $ bounds.
input double RMin_ATR      = 0.50;  // min Asian range  = 0.50 × H4-ATR
input double RMax_ATR      = 4.00;  // max Asian range  = 4.00 × H4-ATR
input double CMax_ATR      = 1.50;  // max single candle = 1.50 × H4-ATR
input double Buf_ATR       = 0.10;  // SL buffer beyond range = 0.10 × H4-ATR
input int    AtrRefBars    = 250;   // H4 bars to average for the ATR ref
input double BodyMaxFrac   = 0.60;  // reject if largest candle body > 60% range
input int    MinRangeBars  = 16;    // require >= 16 M15 bars in window
input int    Max_Spread    = 30;
input long   MagicNumber   = 20260602;

CTrade trade;
COrderInfo orderInfo;

double pip;
int    h4ema200;
int    h4atr;
double rangeHigh = 0, rangeLow = 0, rangeSize = 0;  // rangeSize in pips
double gBufPips  = 0;                                // ATR-derived SL buffer (pips)
bool   rangeReady   = false;
bool   ordersPlaced = false;
bool   tp1Hit       = false;
bool   beSet        = false;
ulong  buyTicket    = 0, sellTicket = 0;
ulong  openTicket   = 0;
double openPrice    = 0;
double initLot      = 0;
datetime lastDay    = 0;

int OnInit()
{
   pip = _Point * 10;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   h4ema200 = iMA(_Symbol, PERIOD_H4, 200, 0, MODE_EMA, PRICE_CLOSE);
   h4atr    = iATR(_Symbol, PERIOD_H4, 14);
   if(h4ema200 == INVALID_HANDLE || h4atr == INVALID_HANDLE) return INIT_FAILED;
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) {}

void DailyReset()
{
   MqlDateTime tm; TimeGMT(tm);
   datetime d = StringToTime(StringFormat("%04d.%02d.%02d", tm.year, tm.mon, tm.day));
   if(d == lastDay) return;
   lastDay      = d;
   rangeReady   = false;
   ordersPlaced = false;
   tp1Hit       = false;
   beSet        = false;
   openTicket   = 0;
   buyTicket    = 0;
   sellTicket   = 0;
   rangeHigh    = 0;
   rangeLow     = 0;
}

// Stable per-symbol volatility scale = mean of the last AtrRefBars H4
// ATR(14) values (price units). Live, non-lookahead equivalent of the
// backtest's atr_series(h4,14).median() global scale.
double H4AtrRef()
{
   double a[]; ArraySetAsSeries(a, true);
   int n = CopyBuffer(h4atr, 0, 0, AtrRefBars, a);
   if(n <= 0) return 0.0;
   double s = 0.0; int c = 0;
   for(int i = 0; i < n; i++)
      if(a[i] > 0) { s += a[i]; c++; }
   return c > 0 ? s / c : 0.0;
}

void CalcRange()
{
   if(rangeReady) return;
   MqlDateTime tm; TimeGMT(tm);
   if(tm.hour < RangeEnd) return;  // range window not finished yet

   // ATR-relative bounds (pips) — instrument-agnostic
   double atrRef = H4AtrRef();                 // price units
   if(atrRef <= 0) return;
   double rmin_p = RMin_ATR * atrRef / pip;
   double rmax_p = RMax_ATR * atrRef / pip;
   double cmax_p = CMax_ATR * atrRef / pip;
   double buf_p  = Buf_ATR  * atrRef / pip;    // pips (used by PlaceOCO)
   gBufPips = buf_p;                            // share with PlaceOCO

   MqlDateTime st; st = tm;
   st.hour = RangeStart; st.min = 0; st.sec = 0;
   datetime range_start_t = StructToTime(st);
   st.hour = RangeEnd;
   // CopyRates is inclusive on the end time; subtract 1s so the RangeEnd
   // (07:00) bar — which belongs to the entry window, not the Asian
   // range — is excluded. Window = 00:00..06:45 (28 M15 bars), exactly
   // matching backtest_s6_v2's pre-07:00 window.
   datetime range_end_t   = StructToTime(st) - 1;
   // NOTE: this broker's server time == UTC (verified). If you move to a
   // broker whose server != UTC, the Asian window must be offset to keep
   // it aligned with the backtest's UTC hours.

   MqlRates bars[];
   int n = CopyRates(_Symbol, PERIOD_M15, range_start_t, range_end_t, bars);
   if(n < MinRangeBars) return;                       // v2: min 16 bars

   double highest = -1, lowest = 1e12, max_body = 0;
   for(int i = 0; i < n; i++)
   {
      double hl_p = (bars[i].high - bars[i].low) / pip;
      if(hl_p > cmax_p) return;                       // candle too big (ATR-rel)
      double body = MathAbs(bars[i].close - bars[i].open);
      if(body > max_body) max_body = body;
      if(bars[i].high > highest) highest = bars[i].high;
      if(bars[i].low  < lowest)  lowest  = bars[i].low;
   }

   double size_p = (highest - lowest) / pip;          // range size in pips
   if(size_p < rmin_p || size_p > rmax_p) return;     // ATR-relative bounds
   // v2 quality filter: no single candle body > 60% of total range
   if(max_body > BodyMaxFrac * (highest - lowest)) return;

   rangeHigh  = highest;
   rangeLow   = lowest;
   rangeSize  = size_p;                               // pips, for SL/TP math
   rangeReady = true;
}

double CalcLot(double sl_pips)
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

// v2 H4 EMA200 trend filter: returns allowed direction(s)
// 1 = BUY only, -1 = SELL only, 0 = both (not clearly trending)
int H4Filter()
{
   double ema[]; ArraySetAsSeries(ema, true);   // ema[1] = last closed H4 bar
   if(CopyBuffer(h4ema200, 0, 0, 2, ema) < 2) return 0;
   double price = iClose(_Symbol, PERIOD_H4, 1);
   double dist  = MathAbs(price - ema[1]) / pip;
   if(dist <= 30) return 0;                  // not clearly trending → both
   return (price > ema[1]) ? 1 : -1;         // strong trend → that side only
}

void PlaceOCO()
{
   if(ordersPlaced || !rangeReady) return;

   double sl_pips = rangeSize + gBufPips;        // ATR-derived buffer (pips)
   double tp2_pip = rangeSize * 1.50;
   double lot     = CalcLot(sl_pips);
   int    allow   = H4Filter();
   double buf_px  = gBufPips * pip;              // buffer in price units

   double buy_entry  = NormalizeDouble(rangeHigh + 2 * pip, _Digits);
   double buy_sl     = NormalizeDouble(rangeLow  - buf_px, _Digits);
   double buy_tp     = NormalizeDouble(buy_entry + tp2_pip * pip, _Digits);

   double sell_entry = NormalizeDouble(rangeLow  - 2 * pip, _Digits);
   double sell_sl    = NormalizeDouble(rangeHigh + buf_px, _Digits);
   double sell_tp    = NormalizeDouble(sell_entry - tp2_pip * pip, _Digits);

   MqlDateTime exp_tm; TimeGMT(exp_tm);
   exp_tm.hour = ExpireHour; exp_tm.min = 0; exp_tm.sec = 0;
   datetime expiry = StructToTime(exp_tm);

   if(allow >= 0)   // BUY allowed (1) or both (0)
   {
      trade.BuyStop(lot, buy_entry, _Symbol, buy_sl, buy_tp,
                    ORDER_TIME_SPECIFIED, expiry, "S6v2_BUY");
      buyTicket = trade.ResultOrder();
   }
   if(allow <= 0)   // SELL allowed (-1) or both (0)
   {
      trade.SellStop(lot, sell_entry, _Symbol, sell_sl, sell_tp,
                     ORDER_TIME_SPECIFIED, expiry, "S6v2_SELL");
      sellTicket = trade.ResultOrder();
   }
   ordersPlaced = true;
}

void CancelOpposite(ulong keep_ticket)
{
   ulong cancel = (keep_ticket == buyTicket) ? sellTicket : buyTicket;
   if(cancel != 0 && OrderSelect(cancel))
      trade.OrderDelete(cancel);
}

void ManageBreakout()
{
   if(openTicket != 0)
   {
      if(!PositionSelectByTicket(openTicket)) { openTicket = 0; return; }

      int    type     = (int)PositionGetInteger(POSITION_TYPE);
      double bid      = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask      = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double cur      = (type == POSITION_TYPE_BUY) ? bid : ask;
      double pnl_pips = (type == POSITION_TYPE_BUY) ? (cur - openPrice) / pip
                                                    : (openPrice - cur) / pip;
      double tp1_pips = rangeSize * 0.70;

      // TP1: close 50%, then lock BE+ on the remaining half
      if(!tp1Hit && pnl_pips >= tp1_pips)
      {
         double vol     = PositionGetDouble(POSITION_VOLUME);
         double close_v = NormalizeDouble(initLot * 0.5, 2);
         close_v = MathMax(close_v, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN));
         if(close_v < vol) { trade.PositionClosePartial(openTicket, close_v); tp1Hit = true; }
      }
      if(tp1Hit && !beSet)
      {
         // Lock 10% of the Asian range as profit on the remaining 50%
         // (range-proportional, symbol-agnostic — matches validated
         // backtest fix; the old fixed +1-pip lock killed the runner).
         double lock_px = (rangeSize * 0.10) * pip;
         double new_sl  = (type == POSITION_TYPE_BUY)
                          ? openPrice + lock_px : openPrice - lock_px;
         trade.PositionModify(openTicket, NormalizeDouble(new_sl, _Digits),
                              PositionGetDouble(POSITION_TP));
         beSet = true;
      }
      return;
   }

   // detect which OCO leg filled, adopt it, cancel the other
   if(!ordersPlaced) return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionGetInteger(POSITION_MAGIC) == MagicNumber)
      {
         openTicket = ticket;
         openPrice  = PositionGetDouble(POSITION_PRICE_OPEN);
         initLot    = PositionGetDouble(POSITION_VOLUME);
         tp1Hit     = false;
         beSet      = false;
         CancelOpposite(ticket);
         break;
      }
   }
}

void ForceClose()
{
   if(openTicket != 0 && PositionSelectByTicket(openTicket))
      { trade.PositionClose(openTicket); openTicket = 0; }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(OrderGetInteger(ORDER_MAGIC) == MagicNumber)
         trade.OrderDelete(ticket);
   }
}

void OnTick()
{
   DailyReset();
   CalcRange();

   MqlDateTime tm; TimeGMT(tm);

   if(tm.hour >= ForceCloseH) { ForceClose(); return; }

   if(tm.hour == EntryHour && tm.min >= EntryMin && !ordersPlaced)
      PlaceOCO();

   ManageBreakout();
}
