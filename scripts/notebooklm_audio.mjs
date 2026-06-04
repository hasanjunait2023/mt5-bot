// NotebookLM Audio Overview — generate the "podcast" overview for a notebook,
// poll until ready, download the mp3. Requires the FULL tool profile.
//
// USAGE: node scripts/notebooklm_audio.mjs --notebook-url <url> --dest-dir <dir>
// stdout (last line): {"status":"ready|timeout|error","file":"...|null"}

import { spawn } from "node:child_process";

const SERVER =
  "C:/Users/Junait/AppData/Local/npm-cache/_npx/0d29dd9f4e472da9/node_modules/notebooklm-mcp/dist/index.js";

function arg(name, def = null) {
  const i = process.argv.indexOf(name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : def;
}
const NOTEBOOK_URL = arg("--notebook-url");
const DEST = arg("--dest-dir");
if (!NOTEBOOK_URL || !DEST) {
  console.error("Usage: node notebooklm_audio.mjs --notebook-url <url> --dest-dir <dir>");
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
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error("timeout id " + id)); } }, 60000);
  });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const callText = (res) => res.result?.content?.map((c) => c.text).join("\n") ?? "";

(async () => {
  await rpc(1, "initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "nlm-audio", version: "1.0" } });
  send({ jsonrpc: "2.0", method: "notifications/initialized" });
  await sleep(400);
  let id = 10;
  const nb = { notebook_url: NOTEBOOK_URL };
  try {
    await rpc(id++, "tools/call", { name: "generate_audio", arguments: nb });
  } catch (e) {
    process.stdout.write(JSON.stringify({ status: "error", file: null, error: e.message }) + "\n");
    child.kill(); process.exit(1);
  }
  // Poll up to ~12 min.
  let ready = false;
  for (let i = 0; i < 24; i++) {
    await sleep(30000);
    try {
      const res = await rpc(id++, "tools/call", { name: "get_audio_status", arguments: nb });
      const txt = callText(res);
      process.stderr.write(`audio status: ${txt.slice(0, 120)}\n`);
      if (/ready|complete|"status"\s*:\s*"ready"/i.test(txt)) { ready = true; break; }
    } catch (e) { process.stderr.write("status poll err: " + e.message + "\n"); }
  }
  if (!ready) {
    process.stdout.write(JSON.stringify({ status: "timeout", file: null }) + "\n");
    child.kill(); process.exit(0);
  }
  let file = null;
  try {
    const res = await rpc(id++, "tools/call", { name: "download_audio", arguments: { ...nb, destination_dir: DEST } });
    const txt = callText(res);
    const m = txt.match(/([A-Za-z]:[\\/][^\s"]+\.(?:mp3|wav|m4a))/) || txt.match(/(\/[^\s"]+\.(?:mp3|wav|m4a))/);
    file = m ? m[1] : null;
  } catch (e) { process.stderr.write("download err: " + e.message + "\n"); }
  process.stdout.write(JSON.stringify({ status: "ready", file }) + "\n");
  child.kill(); process.exit(0);
})().catch((e) => { process.stderr.write("FATAL: " + e.message + "\n"); child.kill(); process.exit(1); });
