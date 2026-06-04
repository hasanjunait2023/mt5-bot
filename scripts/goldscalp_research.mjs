// Deep research script for "Forex Gold Scalping and Trend Reversal" notebook
// Asks 12 targeted questions to extract all profitable scalping strategies
// Output: goldscalp_research.md

import { spawn } from "node:child_process";
import { appendFileSync, writeFileSync } from "node:fs";

const SERVER =
  "C:/Users/Junait/AppData/Local/npm-cache/_npx/0d29dd9f4e472da9/node_modules/notebooklm-mcp/dist/index.js";
const NOTEBOOK_URL =
  "https://notebooklm.google.com/notebook/a8beab3a-f26b-44ae-a9dc-31167864935d";
const OUT = "C:/Users/Junait/mt5 bot/docs/goldscalp_research.md";

const QUESTIONS = [
  // Q1 - Inventory of sources
  "List ALL the sources, videos, PDFs, and documents uploaded to this notebook. Give the name/title of each source and a one-sentence description of what it covers. This helps me understand what strategies are available.",

  // Q2 - Top 10 strategies overview
  "From ALL sources in this notebook, identify and list the top 10 best scalping strategies that work on 1-minute (M1) and 3-minute (M3) charts. For each strategy give: (1) its name, (2) which timeframe it uses (M1/M3/both), (3) which instrument it works on (forex pairs, gold/XAUUSD, etc.), and (4) a one-sentence description of the core idea.",

  // Q3 - Strategy 1-3 detailed entry rules
  "For the top 3 strategies you identified: give the COMPLETE mechanical entry rules for each. Include: (a) exact indicator settings if any, (b) precise entry trigger and order type (market/limit/stop), (c) exact stop-loss placement rule, (d) exact take-profit rule, (e) risk-reward ratio, (f) session/time filter if any. Format as numbered steps a programmer can code.",

  // Q4 - Strategy 4-6 detailed entry rules
  "For strategies 4, 5, and 6 you identified: give the COMPLETE mechanical entry rules for each. Include: (a) exact indicator settings, (b) precise entry trigger and order type, (c) exact stop-loss placement, (d) exact take-profit rule, (e) risk-reward ratio, (f) session/time filter. Format as numbered steps.",

  // Q5 - Strategy 7-10 detailed entry rules
  "For strategies 7, 8, 9, and 10 you identified: give the COMPLETE mechanical entry rules for each. Include: (a) exact indicator settings, (b) precise entry trigger and order type, (c) exact stop-loss placement, (d) exact take-profit rule, (e) risk-reward ratio, (f) session/time filter. Format as numbered steps.",

  // Q6 - Gold/XAUUSD specific strategies
  "Focus ONLY on strategies for GOLD (XAUUSD). What are the exact rules for scalping gold on M1 and M3? What makes gold different from forex pairs in these strategies? Are there specific volatility filters, spread filters, or time-of-day rules for gold scalping? Give all specifics.",

  // Q7 - Trend reversal setups
  "Describe ALL the trend reversal strategies in this notebook in detail. For each: (a) how do you identify the reversal point, (b) what confirms the reversal (indicators, price action, volume), (c) exact entry rule, (d) stop loss, (e) take profit, (f) which timeframe and instrument. Include any specific candlestick patterns, divergence rules, or zone-based reversal concepts.",

  // Q8 - Indicators and settings
  "List EVERY indicator mentioned across all strategies in this notebook. For each indicator give: (1) exact name, (2) exact parameter settings (period, source, type, etc.), (3) how to read the signal (what counts as a buy vs sell signal), (4) which strategy it belongs to. Include EMA, RSI, MACD, Bollinger Bands, ATR, or any custom indicators.",

  // Q9 - Entry filters and confluence
  "What are the confluence filters used across all strategies? Which conditions must ALL be true before entering a trade? Examples: higher timeframe trend alignment, specific session (London/NY/Asia), news avoidance, spread filter, ATR volatility filter, volume filter. List every filter mentioned across all strategies.",

  // Q10 - Risk management
  "What are the EXACT risk management rules taught across all strategies? Cover: (1) risk per trade as % of account, (2) position sizing formula, (3) maximum daily loss/drawdown limit, (4) maximum trades per day, (5) partial profit taking rules, (6) when to move stop to break-even, (7) trailing stop rules, (8) when to exit early. Give numbers, not general concepts.",

  // Q11 - Best pairs and sessions
  "Which currency pairs and instruments perform BEST with each strategy? When is the best time of day (GMT) to trade each strategy? Are there specific pairs to avoid? What is the minimum recommended account size and typical broker spread tolerance for each strategy?",

  // Q12 - Backtesting evidence and win rates
  "What backtesting results, win rates, profit factors, or historical performance data is mentioned in the notebook for any of these strategies? Give specific numbers: win rate %, average R, profit factor, max drawdown, number of trades tested. If no backtest data exists, what do the sources say about expected performance?",
];

writeFileSync(
  OUT,
  `# Forex Gold Scalping & Trend Reversal — Deep Research Dump\n\nSource: NotebookLM ${NOTEBOOK_URL}\nGenerated: ${new Date().toISOString()}\n\n> AI-generated from user-uploaded sources. Verify before relying on specifics.\n\n`
);

const child = spawn(process.execPath, [SERVER], {
  env: { ...process.env, NOTEBOOKLM_PROFILE: "standard" },
  stdio: ["pipe", "pipe", "pipe"],
});
child.stderr.on("data", (d) => process.stderr.write(d.toString()));

let buf = "";
const pending = new Map();
child.stdout.on("data", (d) => {
  buf += d.toString();
  let i;
  while ((i = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, i).trim();
    buf = buf.slice(i + 1);
    if (!line.startsWith("{")) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { continue; }
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  }
});

const send = (o) => child.stdin.write(JSON.stringify(o) + "\n");
const rpc = (id, method, params) =>
  new Promise((resolve, reject) => {
    pending.set(id, resolve);
    send({ jsonrpc: "2.0", id, method, params });
    setTimeout(
      () => { if (pending.has(id)) { pending.delete(id); reject(new Error("timeout id " + id)); } },
      200000
    );
  });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  await rpc(1, "initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "goldscalp-research", version: "1.0" },
  });
  send({ jsonrpc: "2.0", method: "notifications/initialized" });
  await sleep(500);

  let sessionId = null;
  let id = 10;

  for (let q = 0; q < QUESTIONS.length; q++) {
    const question = QUESTIONS[q];
    const args = { question, notebook_url: NOTEBOOK_URL };
    if (sessionId) args.session_id = sessionId;

    process.stderr.write(`\n\n===== Q${q + 1}/${QUESTIONS.length} =====\n`);
    process.stderr.write(`${question.slice(0, 80)}...\n`);

    let answer = "(no answer)";
    try {
      const res = await rpc(id++, "tools/call", {
        name: "ask_question",
        arguments: args,
      });
      const txt = res.result?.content?.map((c) => c.text).join("\n") ?? "";
      try {
        const parsed = JSON.parse(txt);
        answer = parsed?.data?.answer ?? txt;
        if (parsed?.data?.session_id) sessionId = parsed.data.session_id;
      } catch {
        answer = txt;
      }
    } catch (e) {
      answer = "ERROR: " + e.message;
    }

    appendFileSync(OUT, `\n\n## Q${q + 1}. ${question}\n\n${answer}\n`);
    process.stderr.write(`  → saved Q${q + 1}\n`);
    await sleep(2000);
  }

  appendFileSync(
    OUT,
    `\n\n---\n_DONE — ${QUESTIONS.length} questions, session ${sessionId}_\n`
  );
  process.stderr.write("\n=== ALL DONE ===\n");
  child.kill();
  process.exit(0);
})().catch((e) => {
  process.stderr.write("FATAL: " + e.message + "\n");
  child.kill();
  process.exit(1);
});
