// Asks ONE question to the goldscalp NotebookLM notebook.
// Called by goldscalp_batch.ps1 — fresh Chrome per question.
// Usage: node scripts/goldscalp_one.mjs <Q_NUM> "<QUESTION_TEXT>"

import { spawn } from "node:child_process";
import { appendFileSync } from "node:fs";

const SERVER =
  "C:/Users/Junait/AppData/Local/npm-cache/_npx/0d29dd9f4e472da9/node_modules/notebooklm-mcp/dist/index.js";
const NOTEBOOK_URL =
  "https://notebooklm.google.com/notebook/a8beab3a-f26b-44ae-a9dc-31167864935d";
const OUT = "C:/Users/Junait/mt5 bot/docs/goldscalp_research.md";
const TOTAL = 12;

const qNum = process.argv[2];
const question = process.argv[3];

if (!qNum || !question) {
  process.stderr.write("Usage: node goldscalp_one.mjs <Q_NUM> <QUESTION>\n");
  process.exit(1);
}

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
      () => { if (pending.has(id)) { pending.delete(id); reject(new Error("timeout " + id)); } },
      240000
    );
  });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  await rpc(1, "initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "goldscalp-one", version: "1.0" },
  });
  send({ jsonrpc: "2.0", method: "notifications/initialized" });
  await sleep(500);

  process.stderr.write(`\n===== Q${qNum}/${TOTAL} =====\n`);
  process.stderr.write(`${question.slice(0, 100)}...\n`);

  let answer = "(no answer)";
  try {
    const res = await rpc(10, "tools/call", {
      name: "ask_question",
      arguments: { question, notebook_url: NOTEBOOK_URL },
    });
    const txt = res.result?.content?.map((c) => c.text).join("\n") ?? "";
    try {
      const parsed = JSON.parse(txt);
      answer = parsed?.data?.answer ?? txt;
    } catch {
      answer = txt;
    }
  } catch (e) {
    answer = "ERROR: " + e.message;
  }

  appendFileSync(OUT, `\n\n## Q${qNum}. ${question}\n\n${answer}\n`);
  process.stderr.write(`Q${qNum} saved (${answer.length} chars)\n`);
  child.kill();
  process.exit(0);
})().catch((e) => {
  process.stderr.write("FATAL: " + e.message + "\n");
  child.kill();
  process.exit(1);
});
