// NotebookLM Q&A — ask a list of questions against ONE notebook in a single
// persistent session, write each Q&A to a markdown file, and emit a JSON result
// on stdout. Parametrized version of notebooklm_research.mjs for the Strategy
// Factory (Option C: the user supplies the notebook URL).
//
// USAGE:
//   node scripts/notebooklm_qa.mjs --notebook-url <url> --questions <q.json> --out <md> [--session <id>]
//   (questions file = JSON array of strings)
//
// stdout (last line): {"session_id":"...","out":"...","answers":[{"q":..,"a":..}]}

import { spawn } from "node:child_process";
import { appendFileSync, writeFileSync, readFileSync } from "node:fs";

const SERVER =
  "C:/Users/Junait/AppData/Local/npm-cache/_npx/0d29dd9f4e472da9/node_modules/notebooklm-mcp/dist/index.js";

function arg(name, def = null) {
  const i = process.argv.indexOf(name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : def;
}

const NOTEBOOK_URL = arg("--notebook-url");
const Q_FILE = arg("--questions");
const OUT = arg("--out");
let sessionId = arg("--session", null);

if (!NOTEBOOK_URL || !Q_FILE || !OUT) {
  console.error("Usage: node notebooklm_qa.mjs --notebook-url <url> --questions <q.json> --out <md> [--session <id>]");
  process.exit(2);
}

const QUESTIONS = JSON.parse(readFileSync(Q_FILE, "utf8"));
if (!Array.isArray(QUESTIONS) || QUESTIONS.length === 0) {
  console.error("questions file must be a non-empty JSON array");
  process.exit(2);
}

const child = spawn(process.execPath, [SERVER], {
  env: { ...process.env, NOTEBOOKLM_PROFILE: "full" },
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
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  }
});

const send = (o) => child.stdin.write(JSON.stringify(o) + "\n");
const rpc = (id, method, params) =>
  new Promise((resolve, reject) => {
    pending.set(id, resolve);
    send({ jsonrpc: "2.0", id, method, params });
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error("timeout id " + id)); } }, 220000);
  });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  await rpc(1, "initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "nlm-qa", version: "1.0" } });
  send({ jsonrpc: "2.0", method: "notifications/initialized" });
  await sleep(400);

  if (OUT) writeFileSync(OUT, `# NotebookLM Q&A\n\nNotebook: ${NOTEBOOK_URL}\nGenerated: ${new Date().toISOString()}\n`, { flag: "a" });

  const answers = [];
  let id = 10;
  for (let q = 0; q < QUESTIONS.length; q++) {
    const question = QUESTIONS[q];
    const args = { question, notebook_url: NOTEBOOK_URL };
    if (sessionId) args.session_id = sessionId;
    process.stderr.write(`\n===== Q${q + 1}/${QUESTIONS.length} =====\n`);
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
    answers.push({ q: question, a: answer });
    appendFileSync(OUT, `\n\n## Q${q + 1}. ${question}\n\n${answer}\n`);
    await sleep(1200);
  }
  process.stdout.write("\n" + JSON.stringify({ session_id: sessionId, out: OUT, answers }) + "\n");
  child.kill();
  process.exit(0);
})().catch((e) => { process.stderr.write("FATAL: " + e.message + "\n"); child.kill(); process.exit(1); });
