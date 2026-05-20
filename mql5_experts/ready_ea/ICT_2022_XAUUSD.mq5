//+------------------------------------------------------------------+
//| ICT_2022_EA.mq5 — ICT 2022 Mentorship Model Expert Advisor       |
//| Based on: ICT Methodology Complete Reference (May 2026)          |
//|                                                                  |
//| Strategy pipeline (per bar close on M5):                        |
//|   HTF Bias (D1/H4) → Kill Zone → Liquidity Sweep → MSS on M5   |
//|   → Entry on FVG/OB inside OTE (0.618–0.786) → 1% risk          |
//|   → TP at 1:2 min (target 1:3) · 6% daily DD circuit breaker    |
//|                                                                  |
//| Recommended: run one instance per symbol on M5 chart             |
//| Backtest: bar-close mode, real (variable) spread, 2022–2025      |
//| Min balance: $1000 (see lot-size math in research doc)           |
//+------------------------------------------------------------------+
#property copyright "MT5 Bot — ICT"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//═══════════════════════════════════════════════════════════════════
// INPUT PARAMETERS
//═══════════════════════════════════════════════════════════════════

input group "── Kill Zones (UTC times) ──"
input bool   InpUseLondon      = true;   // London KZ 07:00–10:00 UTC
input bool   InpUseNY          = true;   // NY Open KZ 12:00–15:00 UTC
input bool   InpUseAsian       = false;  // Asian KZ 01:00–05:00 UTC
input bool   InpUseSilverBull  = false;  // Silver Bullet windows
input int    InpBrokerGMT      = 2;      // Broker GMT offset (Exness: 2 winter / 3 summer)

input group "── Bias & Structure ──"
input int    InpSwingLen       = 5;      // Swing lookback each side (bars)
input int    InpLiqLookback    = 50;     // M5 bars for liquidity level scan
input int    InpBiasDays       = 5;      // D1 bars for dealing-range EQ

input group "── Entry Parameters ──"
input double InpOTE_High       = 0.618;  // OTE shallow fib (closer to EQ)
input double InpOTE_Low        = 0.786;  // OTE deep fib (0.786 sweet spot)
input bool   InpRequireOTE     = true;   // FVG/OB must be inside OTE band
input double InpMinFVGPips     = 3.0;    // Min FVG height in pips (noise filter)
input bool   InpUseOBEntry     = true;   // Allow Order Block entries (not FVG only)
input double InpSLBufferPips   = 3.0;    // Extra pips beyond swept liquidity for SL

input group "── Risk Management ──"
input double InpRiskPct        = 1.0;    // Risk per trade (% of account balance)
input double InpMaxDailyDD     = 6.0;    // Daily loss circuit breaker (%)
input double InpMaxDailyProfit = 6.0;    // Daily profit lock — halt trading (%)
input int    InpMaxTradesDay   = 2;      // Max trades opened per day
input int    InpMaxConcurrent  = 3;      // Max simultaneous open positions

input group "── Trade Management ──"
input double InpTP1_RR         = 1.5;    // R-multiple for partial close + BE trigger
input double InpTP2_RR         = 3.0;    // R-multiple for full exit (final target)
input double InpPartialPct     = 50.0;   // % of position to close at TP1
input bool   InpUseTrail       = true;   // Trail SL to last M5 structural swing
input int    InpTrailBars      = 3;      // Bars each side for trail-swing detection

input group "── EA Settings ──"
input int    InpMagic          = 20260601;
input string InpComment        = "ICT2022";
input bool   InpLogging        = true;

//═══════════════════════════════════════════════════════════════════
// STRUCTS
//═══════════════════════════════════════════════════════════════════

struct SFairValueGap {
   double   top;         // lower of the two gap boundaries
   double   bottom;
   double   ce;          // consequent encroachment — 50% midpoint
   bool     isBullish;
   datetime barTime;
   bool     mitigated;
};

struct SOrderBlock {
   double   top;
   double   bottom;
   bool     isBullish;
   datetime barTime;
   bool     mitigated;
};

struct SLiquidityLevel {
   double   price;
   bool     isBSL;      // true = buy-side (stops above highs), false = sell-side
   bool     swept;
   datetime time;
};

struct STradeTracker {
   ulong  ticket;
   bool   tp1Done;
   bool   beDone;
};

//═══════════════════════════════════════════════════════════════════
// GLOBALS
//═══════════════════════════════════════════════════════════════════

CTrade    trade;
datetime  g_lastM5Bar  = 0;
double    g_pip;

// Detected levels (rebuilt every bar)
SFairValueGap    g_fvgs[];
SOrderBlock      g_obs[];
SLiquidityLevel  g_liq[];
int g_fvgCount = 0, g_obCount = 0, g_liqCount = 0;

// Per-trade management
STradeTracker g_activeTrades[];
int           g_activeCount = 0;

// Daily state
struct SDailyState {
   datetime dayStart;
   double   startBalance;
   int      bias;           // +1 bull, −1 bear, 0 neutral
   int      tradesOpened;
   bool     circuitBroken;
};
SDailyState g_day;

//═══════════════════════════════════════════════════════════════════
// INIT / DEINIT
//═══════════════════════════════════════════════════════════════════

int OnInit() {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(50);
   trade.SetTypeFilling(ORDER_FILLING_FOK);

   // Pip value: 5-digit forex = 0.0001, Gold = 0.1, BTCUSD = 1.0
   if (_Digits == 5 || _Digits == 3)      g_pip = _Point * 10;
   else if (_Digits == 4 || _Digits == 2) g_pip = _Point * 10;
   else                                   g_pip = _Point * 10;
   // Gold override
   if (StringFind(_Symbol, "XAU") >= 0 || StringFind(_Symbol, "GOLD") >= 0)
      g_pip = 0.1;

   ResetDay();
   Print("ICT 2022 EA | Symbol: ", _Symbol, " | Risk: ", InpRiskPct,
         "% | Magic: ", InpMagic, " | Pip: ", g_pip);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   ArrayFree(g_fvgs);
   ArrayFree(g_obs);
   ArrayFree(g_liq);
   ArrayFree(g_activeTrades);
}

//═══════════════════════════════════════════════════════════════════
// MAIN TICK — bar-close evaluation only
//═══════════════════════════════════════════════════════════════════

void OnTick() {
   datetime barTime = iTime(_Symbol, PERIOD_M5, 0);
   if (barTime == g_lastM5Bar) return;
   g_lastM5Bar = barTime;

   CheckDayReset();
   ManageOpenTrades();

   if (g_day.circuitBroken)                        return;
   if (g_day.tradesOpened >= InpMaxTradesDay)       return;
   if (CountMyPositions() >= InpMaxConcurrent)      return;
   if (!IsInKillZone())                             return;

   g_day.bias = CalcDailyBias();
   if (g_day.bias == 0)                             return;

   DetectLiquidityLevels();
   DetectFVGs();
   if (InpUseOBEntry) DetectOrderBlocks();

   CheckEntrySetup();
}

//═══════════════════════════════════════════════════════════════════
// DAY RESET & CIRCUIT BREAKER
//═══════════════════════════════════════════════════════════════════

void ResetDay() {
   g_day.dayStart      = TimeCurrent();
   g_day.startBalance  = AccountInfoDouble(ACCOUNT_BALANCE);
   g_day.bias          = 0;
   g_day.tradesOpened  = 0;
   g_day.circuitBroken = false;
   g_fvgCount = g_obCount = g_liqCount = 0;
   ArrayResize(g_fvgs, 0);
   ArrayResize(g_obs,  0);
   ArrayResize(g_liq,  0);
   // Note: keep g_activeTrades — open positions persist across days
}

void CheckDayReset() {
   MqlDateTime now, last;
   TimeToStruct(TimeCurrent(), now);
   TimeToStruct(g_day.dayStart, last);
   if (now.day != last.day || now.mon != last.mon) {
      ResetDay();
      if (InpLogging) Print("New day reset | Balance: ", g_day.startBalance);
   }

   if (!g_day.circuitBroken) {
      double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
      double ddPct   = (g_day.startBalance - equity) / g_day.startBalance * 100.0;
      double gainPct = (equity - g_day.startBalance) / g_day.startBalance * 100.0;
      if (ddPct >= InpMaxDailyDD || gainPct >= InpMaxDailyProfit) {
         g_day.circuitBroken = true;
         CloseAllMyPositions();
         Print("⛔ Circuit breaker | DD=", DoubleToString(ddPct, 1),
               "% Gain=", DoubleToString(gainPct, 1), "%");
      }
   }
}

//═══════════════════════════════════════════════════════════════════
// KILL ZONE CHECK (UTC)
//═══════════════════════════════════════════════════════════════════

bool IsInKillZone() {
   // Convert broker time to UTC
   datetime utc = TimeCurrent() - (datetime)(InpBrokerGMT * 3600);
   MqlDateTime dt;
   TimeToStruct(utc, dt);
   int m = dt.hour * 60 + dt.min;

   // Asian KZ: 01:00–05:00 UTC (60–299 min)
   if (InpUseAsian && m >= 60 && m < 300)    return true;

   // London KZ: 07:00–10:00 UTC (420–599)
   if (InpUseLondon && m >= 420 && m < 600)  return true;

   // London Close KZ: 15:00–17:00 UTC (900–1019) — also London session
   if (InpUseLondon && m >= 900 && m < 1020) return true;

   // NY Open KZ: 12:00–15:00 UTC (720–899)
   if (InpUseNY && m >= 720 && m < 900)      return true;

   // Silver Bullet London: 08:00–09:00 UTC (480–539)
   if (InpUseSilverBull && m >= 480 && m < 540) return true;

   // Silver Bullet NY AM: 15:00–16:00 UTC (900–959) — highest probability
   if (InpUseSilverBull && m >= 900 && m < 960) return true;

   // Silver Bullet NY PM: 19:00–20:00 UTC (1140–1199)
   if (InpUseSilverBull && m >= 1140 && m < 1200) return true;

   return false;
}

//═══════════════════════════════════════════════════════════════════
// DAILY BIAS SCORING (D1 + H4)
// Score >= +3 = bullish, <= -3 = bearish, else neutral (no trade)
//═══════════════════════════════════════════════════════════════════

int CalcDailyBias() {
   MqlRates d1[], h4[];
   ArraySetAsSeries(d1, true);
   ArraySetAsSeries(h4, true);

   if (CopyRates(_Symbol, PERIOD_D1, 0, 20, d1) < InpBiasDays + 3) return 0;
   if (CopyRates(_Symbol, PERIOD_H4, 0, 50, h4) < 25)              return 0;

   int score = 0;

   // 1. D1 close vs EQ of last N-day range  (+2 bull / -2 bear)
   double rh = -DBL_MAX, rl = DBL_MAX;
   for (int i = 1; i <= InpBiasDays; i++) {
      if (d1[i].high > rh) rh = d1[i].high;
      if (d1[i].low  < rl) rl = d1[i].low;
   }
   double eq = (rh + rl) * 0.5;
   if (d1[1].close > eq)      score += 2;
   else if (d1[1].close < eq) score -= 2;

   // 2. D1 structure: HH+HL vs LH+LL  (+2 / -2), or partial (+1 / -1)
   bool hh = d1[1].high > d1[2].high && d1[2].high > d1[3].high;
   bool hl = d1[1].low  > d1[2].low  && d1[2].low  > d1[3].low;
   bool lh = d1[1].high < d1[2].high && d1[2].high < d1[3].high;
   bool ll = d1[1].low  < d1[2].low  && d1[2].low  < d1[3].low;

   if (hh && hl)      score += 2;
   else if (lh && ll) score -= 2;
   else if (hh || hl) score += 1;
   else if (lh || ll) score -= 1;

   // 3. Recent D1 liquidity sweep  (+1 bull / -1 bear)
   //    SSL swept: wick below prior swing low, close back above it
   double nearLow  = MathMin(d1[2].low,  d1[3].low);
   double nearHigh = MathMax(d1[2].high, d1[3].high);
   if (d1[1].low < nearLow  && d1[1].close > nearLow)  score += 1;
   if (d1[1].high > nearHigh && d1[1].close < nearHigh) score -= 1;

   // 4. H4 premium/discount zone  (+1 discount / -1 premium)
   double h4h = -DBL_MAX, h4l = DBL_MAX;
   for (int i = 1; i <= 20; i++) {
      if (h4[i].high > h4h) h4h = h4[i].high;
      if (h4[i].low  < h4l) h4l = h4[i].low;
   }
   double h4eq = (h4h + h4l) * 0.5;
   double bid  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if (bid < h4eq)      score += 1;
   else if (bid > h4eq) score -= 1;

   if (InpLogging)
      Print("Bias score: ", score, " (", score >= 3 ? "BULL" : score <= -3 ? "BEAR" : "NEUTRAL", ")");

   if (score >= 3)  return  1;
   if (score <= -3) return -1;
   return 0;
}

//═══════════════════════════════════════════════════════════════════
// LIQUIDITY LEVEL DETECTION & SWEEP CHECK
//═══════════════════════════════════════════════════════════════════

void DetectLiquidityLevels() {
   MqlRates m5[];
   ArraySetAsSeries(m5, true);
   int n = CopyRates(_Symbol, PERIOD_M5, 0, InpLiqLookback + InpSwingLen + 2, m5);
   if (n < InpLiqLookback) return;

   g_liqCount = 0;
   ArrayResize(g_liq, 0);
   int L = InpSwingLen;

   for (int i = L; i < n - L; i++) {
      bool hi = true, lo = true;
      for (int j = i - L; j <= i + L; j++) {
         if (j == i) continue;
         if (m5[j].high >= m5[i].high) hi = false;
         if (m5[j].low  <= m5[i].low)  lo = false;
      }
      if (hi) { AddLiqLevel(m5[i].high, true,  m5[i].time); }
      if (lo) { AddLiqLevel(m5[i].low,  false, m5[i].time); }
   }

   // Mark levels swept by last completed bar (m5[1])
   for (int i = 0; i < g_liqCount; i++) {
      if (g_liq[i].isBSL) {
         // BSL swept: wick above level AND close back below
         if (m5[1].high > g_liq[i].price && m5[1].close < g_liq[i].price)
            g_liq[i].swept = true;
      } else {
         // SSL swept: wick below level AND close back above
         if (m5[1].low < g_liq[i].price && m5[1].close > g_liq[i].price)
            g_liq[i].swept = true;
      }
   }
}

void AddLiqLevel(double price, bool isBSL, datetime t) {
   ArrayResize(g_liq, g_liqCount + 1);
   g_liq[g_liqCount].price  = price;
   g_liq[g_liqCount].isBSL  = isBSL;
   g_liq[g_liqCount].swept  = false;
   g_liq[g_liqCount].time   = t;
   g_liqCount++;
}

// Returns true if a liquidity sweep matching the current bias occurred;
// outputs the swept extreme price (used as SL anchor)
bool FindLiquiditySweep(double &sweepLevel) {
   for (int i = 0; i < g_liqCount; i++) {
      if (!g_liq[i].swept) continue;
      // Bullish setup: SSL (sell-side / stops below lows) swept
      if (g_day.bias == 1 && !g_liq[i].isBSL) {
         sweepLevel = g_liq[i].price;
         return true;
      }
      // Bearish setup: BSL (buy-side / stops above highs) swept
      if (g_day.bias == -1 && g_liq[i].isBSL) {
         sweepLevel = g_liq[i].price;
         return true;
      }
   }
   return false;
}

//═══════════════════════════════════════════════════════════════════
// FAIR VALUE GAP DETECTION (M5)
// Bullish FVG (center bar i): high[i+1] < low[i-1], close[i] > open[i]
// FVG zone: top = low[i-1], bottom = high[i+1]
// Array is AS SERIES: index 0 = newest, i+1 = older than i
//═══════════════════════════════════════════════════════════════════

void DetectFVGs() {
   MqlRates m5[];
   ArraySetAsSeries(m5, true);
   int n = CopyRates(_Symbol, PERIOD_M5, 0, 100, m5);
   if (n < 5) return;

   g_fvgCount = 0;
   ArrayResize(g_fvgs, 0);
   double minH = InpMinFVGPips * g_pip;

   for (int i = 2; i < MathMin(n - 2, 60); i++) {
      double leftH  = m5[i+1].high;   // older bar
      double leftL  = m5[i+1].low;
      double rightL = m5[i-1].low;    // newer bar
      double rightH = m5[i-1].high;

      // Bullish FVG: gap above older high, below newer low
      if (leftH < rightL && m5[i].close > m5[i].open) {
         double top = rightL, bot = leftH;
         if (top - bot >= minH) {
            bool mit = false;
            for (int j = i - 1; j >= 1; j--) {
               if (m5[j].low <= bot) { mit = true; break; }
            }
            if (!mit) AddFVG(top, bot, true, m5[i].time);
         }
      }

      // Bearish FVG: gap below older low, above newer high
      if (leftL > rightH && m5[i].close < m5[i].open) {
         double top = leftL, bot = rightH;
         if (top - bot >= minH) {
            bool mit = false;
            for (int j = i - 1; j >= 1; j--) {
               if (m5[j].high >= top) { mit = true; break; }
            }
            if (!mit) AddFVG(top, bot, false, m5[i].time);
         }
      }
   }
}

void AddFVG(double top, double bot, bool bull, datetime t) {
   ArrayResize(g_fvgs, g_fvgCount + 1);
   g_fvgs[g_fvgCount].top       = top;
   g_fvgs[g_fvgCount].bottom    = bot;
   g_fvgs[g_fvgCount].ce        = (top + bot) * 0.5;
   g_fvgs[g_fvgCount].isBullish = bull;
   g_fvgs[g_fvgCount].barTime   = t;
   g_fvgs[g_fvgCount].mitigated = false;
   g_fvgCount++;
}

//═══════════════════════════════════════════════════════════════════
// ORDER BLOCK DETECTION (M5)
// Bullish OB: last bearish candle BEFORE a strong bullish displacement + BOS
//═══════════════════════════════════════════════════════════════════

void DetectOrderBlocks() {
   MqlRates m5[];
   ArraySetAsSeries(m5, true);
   int n = CopyRates(_Symbol, PERIOD_M5, 0, 100, m5);
   if (n < 6) return;

   g_obCount = 0;
   ArrayResize(g_obs, 0);

   for (int i = 3; i < MathMin(n - 3, 60); i++) {
      double range = m5[i-1].high - m5[i-1].low;
      if (range <= 0) continue;
      double bodyFrac = MathAbs(m5[i-1].close - m5[i-1].open) / range;

      // Bullish OB: current candle is bearish, followed by strong bullish displacement
      if (m5[i].close < m5[i].open &&
          m5[i-1].close > m5[i-1].open && bodyFrac > 0.55 &&
          m5[i-1].high > m5[i+1].high) // structure break
      {
         bool mit = false;
         for (int j = i - 1; j >= 1; j--) {
            if (m5[j].low <= m5[i].low) { mit = true; break; }
         }
         if (!mit) AddOB(m5[i].high, m5[i].low, true, m5[i].time);
      }

      // Bearish OB: current candle is bullish, followed by strong bearish displacement
      if (m5[i].close > m5[i].open &&
          m5[i-1].close < m5[i-1].open && bodyFrac > 0.55 &&
          m5[i-1].low < m5[i+1].low) // structure break
      {
         bool mit = false;
         for (int j = i - 1; j >= 1; j--) {
            if (m5[j].high >= m5[i].high) { mit = true; break; }
         }
         if (!mit) AddOB(m5[i].high, m5[i].low, false, m5[i].time);
      }
   }
}

void AddOB(double top, double bot, bool bull, datetime t) {
   ArrayResize(g_obs, g_obCount + 1);
   g_obs[g_obCount].top       = top;
   g_obs[g_obCount].bottom    = bot;
   g_obs[g_obCount].isBullish = bull;
   g_obs[g_obCount].barTime   = t;
   g_obs[g_obCount].mitigated = false;
   g_obCount++;
}

//═══════════════════════════════════════════════════════════════════
// MSS DETECTION (Market Structure Shift)
// = CHoCH + displacement candle (large body ratio) + FVG
// Evaluated on bar[1] (last completed M5 bar)
//═══════════════════════════════════════════════════════════════════

bool CheckMSS() {
   MqlRates m5[];
   ArraySetAsSeries(m5, true);
   if (CopyRates(_Symbol, PERIOD_M5, 0, 25, m5) < 15) return false;

   double range  = m5[1].high - m5[1].low;
   if (range <= 0) return false;

   // Bullish MSS: large bullish displacement candle + breaks recent swing high
   if (g_day.bias == 1) {
      double bodyFrac = (m5[1].close - m5[1].open) / range;
      if (m5[1].close > m5[1].open && bodyFrac > 0.50) {
         // FVG at center=bar[2]: high[m5[3]] < low[m5[1]]
         if (m5[3].high < m5[1].low) {
            // Structure break: closed above recent swing high
            double recentHi = -DBL_MAX;
            for (int i = 3; i < 18; i++) {
               if (m5[i].high > recentHi) recentHi = m5[i].high;
            }
            if (m5[1].close > recentHi) return true;
         }
      }
   }

   // Bearish MSS: large bearish displacement candle + breaks recent swing low
   if (g_day.bias == -1) {
      double bodyFrac = (m5[1].open - m5[1].close) / range;
      if (m5[1].close < m5[1].open && bodyFrac > 0.50) {
         // Bearish FVG at center=bar[2]: low[m5[3]] > high[m5[1]]
         if (m5[3].low > m5[1].high) {
            double recentLo = DBL_MAX;
            for (int i = 3; i < 18; i++) {
               if (m5[i].low < recentLo) recentLo = m5[i].low;
            }
            if (m5[1].close < recentLo) return true;
         }
      }
   }

   return false;
}

//═══════════════════════════════════════════════════════════════════
// OTE ZONE CHECK (M15 dealing range)
// Long : fib low→high; OTE = 0.618–0.786 retracement (deep discount)
//        price must be BELOW EQ (0.5) AND in [low+0.214r, low+0.382r]
// Short: fib high→low; OTE = 0.618–0.786 retracement (deep premium)
//        price must be ABOVE EQ (0.5) AND in [low+0.618r, low+0.786r]
//═══════════════════════════════════════════════════════════════════

bool IsInOTE(double checkPrice, bool forLong) {
   if (!InpRequireOTE) return true;

   MqlRates m15[];
   ArraySetAsSeries(m15, true);
   if (CopyRates(_Symbol, PERIOD_M15, 0, 50, m15) < 20) return false;

   double sh = -DBL_MAX, sl = DBL_MAX;
   for (int i = 1; i < 30; i++) {
      if (m15[i].high > sh) sh = m15[i].high;
      if (m15[i].low  < sl) sl = m15[i].low;
   }
   double rng = sh - sl;
   if (rng <= 0) return false;

   double eq = sl + rng * 0.5;

   if (forLong) {
      if (checkPrice >= eq) return false;                    // must be in discount
      double oteBot = sl + rng * (1.0 - InpOTE_Low);        // ~0.214
      double oteTop = sl + rng * (1.0 - InpOTE_High);       // ~0.382
      return (checkPrice >= oteBot && checkPrice <= oteTop);
   } else {
      if (checkPrice <= eq) return false;                    // must be in premium
      double oteBot = sl + rng * InpOTE_High;               // ~0.618
      double oteTop = sl + rng * InpOTE_Low;                // ~0.786
      return (checkPrice >= oteBot && checkPrice <= oteTop);
   }
}

//═══════════════════════════════════════════════════════════════════
// MAIN SETUP: Sweep → MSS → FVG/OB in OTE → Enter
//═══════════════════════════════════════════════════════════════════

void CheckEntrySetup() {
   // Step 1: Liquidity sweep
   double sweepLevel = 0;
   if (!FindLiquiditySweep(sweepLevel)) return;

   // Step 2: MSS confirmation
   if (!CheckMSS()) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // Spread guard
   double spread = ask - bid;
   double maxSprd = (StringFind(_Symbol, "XAU") >= 0 || StringFind(_Symbol, "BTC") >= 0)
                    ? 100 * _Point : 30 * _Point;
   if (spread > maxSprd) {
      if (InpLogging) Print("Spread too high: ", spread / _Point, " pts — skipping");
      return;
   }

   double entry = 0, sl = 0, tp1 = 0, tp2 = 0;
   bool found = false;

   if (g_day.bias == 1) {
      // Bullish: price must be retracing into a bullish FVG or OB
      for (int i = 0; i < g_fvgCount && !found; i++) {
         SFairValueGap &f = g_fvgs[i];
         if (!f.isBullish || f.mitigated) continue;
         if (ask >= f.bottom && ask <= f.top) {
            if (!IsInOTE(f.ce, true)) continue;
            entry = ask;
            sl    = sweepLevel - InpSLBufferPips * g_pip;
            found = (entry - sl > 0);
         }
      }
      for (int i = 0; i < g_obCount && !found; i++) {
         SOrderBlock &o = g_obs[i];
         if (!o.isBullish || o.mitigated) continue;
         if (ask >= o.bottom && ask <= o.top) {
            if (!IsInOTE((o.top + o.bottom) * 0.5, true)) continue;
            entry = ask;
            sl    = sweepLevel - InpSLBufferPips * g_pip;
            found = (entry - sl > 0);
         }
      }
      if (found) {
         double slDist = entry - sl;
         tp1 = entry + slDist * InpTP1_RR;
         tp2 = entry + slDist * InpTP2_RR;
         ExecuteEntry(true, entry, sl, tp2);
      }

   } else if (g_day.bias == -1) {
      // Bearish: price must be retracing into a bearish FVG or OB
      for (int i = 0; i < g_fvgCount && !found; i++) {
         SFairValueGap &f = g_fvgs[i];
         if (f.isBullish || f.mitigated) continue;
         if (bid <= f.top && bid >= f.bottom) {
            if (!IsInOTE(f.ce, false)) continue;
            entry = bid;
            sl    = sweepLevel + InpSLBufferPips * g_pip;
            found = (sl - entry > 0);
         }
      }
      for (int i = 0; i < g_obCount && !found; i++) {
         SOrderBlock &o = g_obs[i];
         if (o.isBullish || o.mitigated) continue;
         if (bid <= o.top && bid >= o.bottom) {
            if (!IsInOTE((o.top + o.bottom) * 0.5, false)) continue;
            entry = bid;
            sl    = sweepLevel + InpSLBufferPips * g_pip;
            found = (sl - entry > 0);
         }
      }
      if (found) {
         double slDist = sl - entry;
         tp1 = entry - slDist * InpTP1_RR;
         tp2 = entry - slDist * InpTP2_RR;
         ExecuteEntry(false, entry, sl, tp2);
      }
   }
}

//═══════════════════════════════════════════════════════════════════
// EXECUTE ENTRY
//═══════════════════════════════════════════════════════════════════

void ExecuteEntry(bool isBuy, double entry, double sl, double tp) {
   double slDist = MathAbs(entry - sl);
   double tpDist = MathAbs(tp - entry);

   // Minimum 1:2 RR guard
   if (slDist <= 0 || tpDist / slDist < 1.9) {
      if (InpLogging) Print("Entry rejected — RR too low: ", tpDist / slDist);
      return;
   }

   double lots = CalcLots(slDist);
   if (lots <= 0) {
      if (InpLogging) Print("Entry rejected — lot size = 0 (balance too low for SL dist)");
      return;
   }

   bool ok = isBuy
             ? trade.Buy(lots,  _Symbol, 0, sl, tp, InpComment)
             : trade.Sell(lots, _Symbol, 0, sl, tp, InpComment);

   if (ok) {
      ulong ticket = trade.ResultOrder();
      g_day.tradesOpened++;
      // Register for management
      ArrayResize(g_activeTrades, g_activeCount + 1);
      g_activeTrades[g_activeCount].ticket  = ticket;
      g_activeTrades[g_activeCount].tp1Done = false;
      g_activeTrades[g_activeCount].beDone  = false;
      g_activeCount++;
      Print("✅ TRADE OPEN | ", isBuy ? "BUY" : "SELL",
            " | Lots: ", lots,
            " | Entry: ", entry,
            " | SL: ", sl,
            " | TP: ", tp,
            " | Ticket: ", ticket);
   } else {
      if (InpLogging)
         Print("❌ Trade failed: ", trade.ResultRetcodeDescription(),
               " (", trade.ResultRetcode(), ")");
   }
}

//═══════════════════════════════════════════════════════════════════
// LOT SIZING — 1% risk per trade
// lots = riskUSD / (slDistance / tickSize × tickValue)
//═══════════════════════════════════════════════════════════════════

double CalcLots(double slDist) {
   double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskUSD  = balance * InpRiskPct / 100.0;
   double tickVal  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if (tickSize <= 0 || tickVal <= 0) return 0;

   double lots     = riskUSD / (slDist / tickSize * tickVal);
   double step     = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double lotMin   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double lotMax   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);

   lots = MathFloor(lots / step) * step;
   return MathMax(lotMin, MathMin(lots, lotMax));
}

//═══════════════════════════════════════════════════════════════════
// TRADE MANAGEMENT — break-even, partial close, structural trail
//═══════════════════════════════════════════════════════════════════

void ManageOpenTrades() {
   // Clean closed tickets from tracker
   CleanTradeTracker();

   for (int t = 0; t < g_activeCount; t++) {
      ulong ticket = g_activeTrades[t].ticket;
      if (!PositionSelectByTicket(ticket)) continue;

      double openPx  = PositionGetDouble(POSITION_PRICE_OPEN);
      double curSL   = PositionGetDouble(POSITION_SL);
      double curTP   = PositionGetDouble(POSITION_TP);
      double curPx   = PositionGetDouble(POSITION_PRICE_CURRENT);
      double vol     = PositionGetDouble(POSITION_VOLUME);
      bool   isBuy   = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);

      double slDist  = MathAbs(openPx - curSL);
      if (slDist <= 0) continue;

      double profitR = isBuy ? (curPx - openPx) / slDist
                             : (openPx - curPx) / slDist;

      // Break-even: move SL to open + 1 point
      if (!g_activeTrades[t].beDone && profitR >= InpTP1_RR) {
         double newSL = isBuy ? openPx + _Point : openPx - _Point;
         bool   valid = isBuy ? (newSL > curSL) : (newSL < curSL);
         if (valid && trade.PositionModify(ticket, newSL, curTP)) {
            g_activeTrades[t].beDone = true;
            if (InpLogging) Print("BE set | Ticket: ", ticket, " | New SL: ", newSL);
         }
      }

      // Partial close at TP1
      if (!g_activeTrades[t].tp1Done && profitR >= InpTP1_RR) {
         double step    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
         double lotMin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
         double closeV  = MathFloor(vol * InpPartialPct / 100.0 / step) * step;
         closeV = MathMax(lotMin, closeV);
         if (closeV < vol && trade.PositionClosePartial(ticket, closeV)) {
            g_activeTrades[t].tp1Done = true;
            if (InpLogging)
               Print("Partial close ", closeV, " lots at R", DoubleToString(profitR, 2),
                     " | Ticket: ", ticket);
         }
      }

      // Structural trail after BE is set
      if (InpUseTrail && g_activeTrades[t].beDone) {
         double trailSL = GetStructuralSL(isBuy);
         if (trailSL > 0) {
            bool better = isBuy ? (trailSL > curSL && trailSL < curPx - _Point)
                                : (trailSL < curSL && trailSL > curPx + _Point);
            if (better) trade.PositionModify(ticket, trailSL, curTP);
         }
      }
   }
}

double GetStructuralSL(bool isBuy) {
   MqlRates m5[];
   ArraySetAsSeries(m5, true);
   if (CopyRates(_Symbol, PERIOD_M5, 0, 20, m5) < 10) return 0;

   int L = InpTrailBars;
   for (int i = L; i < 15; i++) {
      bool ok = true;
      for (int j = i - L; j <= i + L; j++) {
         if (j == i) continue;
         if (isBuy  && m5[j].low  <= m5[i].low)  { ok = false; break; }
         if (!isBuy && m5[j].high >= m5[i].high)  { ok = false; break; }
      }
      if (ok) {
         return isBuy ? m5[i].low  - InpSLBufferPips * g_pip
                      : m5[i].high + InpSLBufferPips * g_pip;
      }
   }
   return 0;
}

void CleanTradeTracker() {
   for (int i = g_activeCount - 1; i >= 0; i--) {
      if (!PositionSelectByTicket(g_activeTrades[i].ticket)) {
         // Position closed — remove from tracker
         for (int j = i; j < g_activeCount - 1; j++)
            g_activeTrades[j] = g_activeTrades[j + 1];
         g_activeCount--;
         ArrayResize(g_activeTrades, g_activeCount);
      }
   }
}

//═══════════════════════════════════════════════════════════════════
// UTILITIES
//═══════════════════════════════════════════════════════════════════

int CountMyPositions() {
   int c = 0;
   for (int i = 0; i < PositionsTotal(); i++) {
      if (PositionSelectByTicket(PositionGetTicket(i)))
         if (PositionGetInteger(POSITION_MAGIC) == InpMagic) c++;
   }
   return c;
}

void CloseAllMyPositions() {
   for (int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong tk = PositionGetTicket(i);
      if (PositionSelectByTicket(tk))
         if (PositionGetInteger(POSITION_MAGIC) == InpMagic)
            trade.PositionClose(tk);
   }
}
