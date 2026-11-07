// Print a page (the brief, the listing audit) to PDF with headless Chrome over the DevTools protocol.
// Usage: node tools/pdf.mjs <page.html> <out.pdf> [pages]
// Optional 3rd argument: the exact page count to require (the brief passes 2).
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const src = resolve(process.argv[2] || "site/brief/index.html");
const out = resolve(process.argv[3] || "site/brief/tulsa-pantry-gap-brief.pdf");
const want = process.argv[4] ? Number(process.argv[4]) : null;
const port = 9334;
const prof = mkdtempSync(join(tmpdir(), "tpg-pdf-"));
const chrome = spawn("google-chrome-stable", ["--headless=new", "--disable-gpu", `--remote-debugging-port=${port}`,
  `--user-data-dir=${prof}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0;
const pending = new Map();
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });

let code = 0;
try {
  for (let i = 0; i < 50 && !ws; i++) {
    try {
      const page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((x) => x.type === "page");
      ws = new WebSocket(page.webSocketDebuggerUrl);
      await new Promise((r) => ws.addEventListener("open", r));
      ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } });
    } catch { ws = undefined; await sleep(200); }
  }
  if (!ws) throw new Error("chrome did not start");
  await send("Page.enable");
  await send("Page.navigate", { url: pathToFileURL(src).href });
  await sleep(1500);
  await send("Runtime.evaluate", { expression: "document.fonts.ready", awaitPromise: true });
  const r = await send("Page.printToPDF", { printBackground: true, preferCSSPageSize: true, marginTop: 0, marginBottom: 0,
    marginLeft: 0, marginRight: 0 });
  const buf = Buffer.from(r.result.data, "base64");
  writeFileSync(out, buf);
  const pages = (buf.toString("latin1").match(/\/Type\s*\/Page[^s]/g) || []).length;
  console.log(`wrote ${out} (${Math.round(buf.length / 1024)} kB, ${pages} pages)`);
  if (want && pages !== want) { console.error(`FAIL expected ${want} pages`); code = 1; }
} catch (err) { console.error(err); code = 1; }
chrome.kill();
await sleep(300);
rmSync(prof, { recursive: true, force: true });
process.exit(code);
