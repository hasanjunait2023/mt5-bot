import { spawn } from "node:child_process";
import { appendFileSync } from "node:fs";

const SERVER = "C:/Users/Junait/AppData/Local/npm-cache/_npx/0d29dd9f4e472da9/node_modules/notebooklm-mcp/dist/index.js";
const NOTEBOOK_URL = "https://notebooklm.google.com/notebook/4898da73-2ca1-486d-83e3-071343953ae1";
const OUT = "C:/Users/Junait/mt5 bot/urbanforex_iconic_research.md";
const Q1 = "EXACT mechanical entry rules for the Set 1 / Set 2 anticipation trade. For BOTH Type 1 (line break) and Type 2 (ranging below line): (a) the precise entry trigger and order type (limit/market/stop), (b) exact stop-loss placement, (c) exactly how to set the take-profit / target, and (d) the typical risk-reward. Give it as a numbered step-by-step a trader can follow blindly.";

const child = spawn(process.execPath, [SERVER], { env: { ...process.env, NOTEBOOKLM_PROFILE: "standard" }, stdio: ["pipe", "pipe", "pipe"] });
child.stderr.on("data", (d) => process.stderr.write(d.toString()));

let buf = "";
const pending = new Map();
child.stdout.on("data", (d) => {
  buf += d.toString();
  let i;
  while ((i = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
    if (!line.startsWith("{")) continue;
    let m; try { m = JSON.parse(line); } catch { continue; }
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  }
});
const send = (o) => child.stdin.write(JSON.stringify(o) + "\n");
const rpc = (id, method, params) => new Promise((res, rej) => { pending.set(id, res); send({ jsonrpc: "2.0", id, method, params }); setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error("rpc timeout " + id)); } }, 200000); });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  await rpc(1, "initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "reask", version: "1.0" } });
  send({ jsonrpc: "2.0", method: "notifications/initialized" }); await sleep(500);
  let sessionId = null, answer = null, id = 10;
  for (let attempt = 1; attempt <= 4 && !answer; attempt++) {
    process.stderr.write(`\n=== Q1 attempt ${attempt} ===\n`);
    const args = { question: Q1, notebook_url: NOTEBOOK_URL };
    if (sessionId) args.session_id = sessionId;
    try {
      const r = await rpc(id++, "tools/call", { name: "ask_question", arguments: args });
      const txt = r.result?.content?.map((c) => c.text).join("\n") ?? "";
      let parsed; try { parsed = JSON.parse(txt); } catch { parsed = null; }
      if (parsed?.data?.session_id) sessionId = parsed.data.session_id;
      if (parsed?.success && parsed?.data?.answer) { answer = parsed.data.answer; }
      else { process.stderr.write("attempt failed: " + (parsed?.error || txt).slice(0, 120) + "\n"); await sleep(4000); }
    } catch (e) { process.stderr.write("err: " + e.message + "\n"); await sleep(4000); }
  }
  if (answer) {
    appendFileSync(OUT, `\n\n## Q1 (RE-ASK). Set 1 / Set 2 exact entry / SL / TP / RR rules\n\n${answer}\n`);
    process.stderr.write("\n=== Q1 CAPTURED ===\n");
  } else {
    process.stderr.write("\n=== Q1 STILL FAILED after retries ===\n");
  }
  child.kill(); process.exit(answer ? 0 : 1);
})().catch((e) => { process.stderr.write("FATAL " + e.message + "\n"); child.kill(); process.exit(1); });
