// NotebookLM deep-research: asks a sequence of questions in ONE persistent
// session (reusing session_id so follow-ups stay context-aware) and writes
// every Q&A to an output markdown file incrementally.
//
// Drives notebooklm-mcp stdio directly (harness doesn't expose its tools).
// USAGE: node scripts/notebooklm_research.mjs

import { spawn } from "node:child_process";
import { appendFileSync, writeFileSync } from "node:fs";

const SERVER =
  "C:/Users/Junait/AppData/Local/npm-cache/_npx/0d29dd9f4e472da9/node_modules/notebooklm-mcp/dist/index.js";
const NOTEBOOK_URL =
  "https://notebooklm.google.com/notebook/4898da73-2ca1-486d-83e3-071343953ae1";
const OUT = "C:/Users/Junait/mt5 bot/urbanforex_iconic_research.md";

const QUESTIONS = [
  "EXACT mechanical entry rules for the Set 1 / Set 2 anticipation trade. For BOTH Type 1 (line break) and Type 2 (ranging below line): (a) the precise entry trigger and order type (limit/market/stop), (b) exact stop-loss placement, (c) exactly how to set the take-profit / target, and (d) the typical risk-reward. Give it as a numbered step-by-step a trader can follow blindly.",
  "Which exact timeframes does Navin use in this program? Specify the timeframe for trend/bias, for spotting the setup, and for entry timing. Explain the full multi-timeframe workflow and what the '60-minute anticipation trade' means.",
  "Explain EXACTLY how to read volume in this method: which volume indicator/tool, on which timeframe, what quantitatively counts as a 'High Volume Pop' versus a 'Low Volume Pullback', and how to compare one volume bar against others. How is dead/low volume confirmed?",
  "Define precisely what a 'money spot' (range/congestion) is and the exact criteria to identify and confirm one has formed. Then explain 'Test 1' and 'Test 2' in detail — what they are, how to spot them, and how Test 2 (with volume) confirms the entry.",
  "Explain the correlation method step by step: which tool/indicator is used, what the correlation numbers mean, the exact thresholds for a valid correlation, how to read the daily correlation, and how to identify the strongest 'leader' pair in a currency group for entry.",
  "Give the COMPLETE A-class / B-class / C-class trade classification checklist, and the full step-by-step decision process (a checklist) a trader runs from opening the chart all the way to placing the entry. List every condition that must be true.",
  "What are the exact trading session times and the news rules? When is it allowed to trade and when must you stay out? How exactly do you use the economic calendar as 'Purpose' — which news impact levels (red/orange/etc.) qualify, and how to handle a trade around a news release?",
  "Explain in detail three concepts: (1) the 'Eclipse' trade setup and its rules, (2) 'Trend Pullback Failure' — its precise definition and how to trade it, and (3) the 'why ranges and highs and lows' concept — how to mark and use previous day/session highs and lows and ranges.",
  "What are the exact risk-management and trade-management rules taught: risk per trade (% of account), position sizing, partial profit taking, moving stop to break-even, trailing the stop, and the exact conditions for exiting a trade early. Summarize the full money-management system.",
];

writeFileSync(OUT, `# Urban Forex — Iconic Trader Program: Deep Research Dump\n\nSource: NotebookLM notebook ${NOTEBOOK_URL}\nGenerated: ${new Date().toISOString()}\n\n> NotebookLM/Gemini output — AI-generated from user-uploaded sources, verify before relying.\n\n`);

const child = spawn(process.execPath, [SERVER], {
  env: { ...process.env, NOTEBOOKLM_PROFILE: "standard" },
  stdio: ["pipe", "pipe", "pipe"],
});
child.stderr.on("data", (d) => process.stderr.write(d.toString()));

let buf = "";
const pending = new Map(); // id -> resolve
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
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error("timeout id " + id)); } }, 200000);
  });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  await rpc(1, "initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "nlm-research", version: "1.0" } });
  send({ jsonrpc: "2.0", method: "notifications/initialized" });
  await sleep(500);

  let sessionId = null;
  let id = 10;
  for (let q = 0; q < QUESTIONS.length; q++) {
    const question = QUESTIONS[q];
    const args = { question, notebook_url: NOTEBOOK_URL };
    if (sessionId) args.session_id = sessionId;
    process.stderr.write(`\n\n===== Q${q + 1}/${QUESTIONS.length} =====\n`);
    let answer = "(no answer)";
    try {
      const res = await rpc(id++, "tools/call", { name: "ask_question", arguments: args });
      const txt = res.result?.content?.map((c) => c.text).join("\n") ?? "";
      try {
        const parsed = JSON.parse(txt);
        answer = parsed?.data?.answer ?? txt;
        if (parsed?.data?.session_id) sessionId = parsed.data.session_id;
      } catch { answer = txt; }
    } catch (e) {
      answer = "ERROR: " + e.message;
    }
    appendFileSync(OUT, `\n\n## Q${q + 1}. ${question}\n\n${answer}\n`);
    await sleep(1500);
  }
  appendFileSync(OUT, `\n\n---\n_DONE — ${QUESTIONS.length} questions, session ${sessionId}_\n`);
  process.stderr.write("\n=== ALL DONE ===\n");
  child.kill();
  process.exit(0);
})().catch((e) => { process.stderr.write("FATAL: " + e.message + "\n"); child.kill(); process.exit(1); });
