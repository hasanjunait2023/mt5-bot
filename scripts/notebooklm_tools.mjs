// SPIKE: enumerate the notebooklm-mcp server's tools + input schemas so we know
// the EXACT arg names and whether add_notebook can CREATE a notebook or only
// REGISTER an existing share-URL. Drives the stdio server directly like the
// other notebooklm_*.mjs bridges.
//
// USAGE: node scripts/notebooklm_tools.mjs

import { spawn } from "node:child_process";

const SERVER =
  "C:/Users/Junait/AppData/Local/npm-cache/_npx/0d29dd9f4e472da9/node_modules/notebooklm-mcp/dist/index.js";

const child = spawn(process.execPath, [SERVER], {
  env: { ...process.env, NOTEBOOKLM_PROFILE: process.env.NOTEBOOKLM_PROFILE || "standard" },
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
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error("timeout id " + id)); } }, 30000);
  });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  await rpc(1, "initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "nlm-tools", version: "1.0" } });
  send({ jsonrpc: "2.0", method: "notifications/initialized" });
  await sleep(400);
  const res = await rpc(2, "tools/list", {});
  const tools = res.result?.tools ?? [];
  for (const t of tools) {
    console.log(`\n### ${t.name}`);
    if (t.description) console.log(t.description.split("\n")[0]);
    const props = t.inputSchema?.properties ?? {};
    const required = t.inputSchema?.required ?? [];
    for (const [k, v] of Object.entries(props)) {
      console.log(`  - ${k}${required.includes(k) ? "*" : ""}: ${v.type || "?"}${v.description ? " — " + v.description.split("\n")[0] : ""}`);
    }
  }
  console.log(`\n=== ${tools.length} tools ===`);
  child.kill();
  process.exit(0);
})().catch((e) => { process.stderr.write("FATAL: " + e.message + "\n"); child.kill(); process.exit(1); });
