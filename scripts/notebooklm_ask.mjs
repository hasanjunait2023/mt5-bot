// NotebookLM bridge — drives the notebooklm-mcp stdio server directly.
//
// WHY: the notebooklm MCP tools do NOT surface inside the Claude Code harness
// (server connects but tools never register in ToolSearch). The server itself
// works fine over stdio JSON-RPC, and Google auth is already persisted, so we
// talk to it directly.
//
// USAGE:
//   node scripts/notebooklm_ask.mjs "<question>" [notebookUrl] [sessionId]
//
// Prints the answer JSON to stdout. Reuse the printed session_id for sharper
// follow-up questions in the same notebook.

import { spawn } from "node:child_process";

const SERVER =
  "C:/Users/Junait/AppData/Local/npm-cache/_npx/0d29dd9f4e472da9/node_modules/notebooklm-mcp/dist/index.js";

const question = process.argv[2];
const notebookUrl =
  process.argv[3] ||
  "https://notebooklm.google.com/notebook/4898da73-2ca1-486d-83e3-071343953ae1";
const sessionId = process.argv[4] || null;

if (!question) {
  console.error('Usage: node scripts/notebooklm_ask.mjs "<question>" [notebookUrl] [sessionId]');
  process.exit(2);
}

const child = spawn(process.execPath, [SERVER], {
  env: { ...process.env, NOTEBOOKLM_PROFILE: "standard" },
  stdio: ["pipe", "pipe", "pipe"],
});

let buf = "";
child.stdout.on("data", (d) => {
  buf += d.toString();
  let i;
  while ((i = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, i).trim();
    buf = buf.slice(i + 1);
    if (!line.startsWith("{")) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { continue; }
    if (msg.id === 2) {
      const txt = msg.result?.content?.map((c) => c.text).join("\n") ?? JSON.stringify(msg, null, 2);
      console.log(txt);
      child.kill();
      process.exit(0);
    }
  }
});
child.stderr.on("data", (d) => process.stderr.write(d.toString())); // progress logs

const send = (o) => child.stdin.write(JSON.stringify(o) + "\n");
const args = { question, notebook_url: notebookUrl };
if (sessionId) args.session_id = sessionId;

send({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "nlm-bridge", version: "1.0" } } });
setTimeout(() => send({ jsonrpc: "2.0", method: "notifications/initialized" }), 500);
setTimeout(() => send({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "ask_question", arguments: args } }), 1200);

setTimeout(() => { console.error("TIMEOUT: no answer in 170s"); child.kill(); process.exit(1); }, 170000);
