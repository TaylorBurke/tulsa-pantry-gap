// Headless smoke test for the site: loads the page in Chrome over the DevTools
// protocol at phone size, exercises every control, taps a tract and a pantry,
// switches dark mode, and fails on console errors or empty panels.
// Usage: node tools/smoke.mjs http://localhost:8765/ <screenshot-dir>
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const url = process.argv[2] || "http://localhost:8765/";
const out = process.argv[3] || ".";
const port = 9333;
const prof = mkdtempSync(join(tmpdir(), "tpg-smoke-"));
const chrome = spawn("google-chrome-stable", ["--headless=new", "--disable-gpu", `--remote-debugging-port=${port}`,
  `--user-data-dir=${prof}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0;
const pending = new Map(), errors = [];
async function connect() {
  for (let i = 0; i < 50; i++) {
    try {
      const t = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = t.find((x) => x.type === "page");
      ws = new WebSocket(page.webSocketDebuggerUrl);
      await new Promise((r) => ws.addEventListener("open", r));
      ws.addEventListener("message", (m) => {
        const d = JSON.parse(m.data);
        if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
        if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.text + " " + (d.params.exceptionDetails.exception?.description || ""));
        if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") errors.push(d.params.args.map((a) => a.value || a.description).join(" "));
        if (d.method === "Log.entryAdded" && d.params.entry.level === "error") errors.push(d.params.entry.text + " " + (d.params.entry.url || ""));
      });
      return;
    } catch { await sleep(200); }
  }
  throw new Error("chrome did not start");
}
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;
async function shot(name) {
  const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  writeFileSync(join(out, name), Buffer.from(r.result.data, "base64"));
}
const fails = [];
const check = (ok, msg) => { console.log((ok ? "PASS " : "FAIL ") + msg); if (!ok) fails.push(msg); };

try {
  await connect();
  await send("Runtime.enable"); await send("Log.enable"); await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await send("Emulation.setTouchEmulationEnabled", { enabled: true });
  await send("Page.navigate", { url });
  await sleep(3000);
  check(await ev("document.querySelectorAll('#map path.tract:not(.top)').length") === 208, "208 tract paths drawn");
  check(await ev("document.querySelectorAll('#map circle.pantry').length") > 80, "pantry markers drawn");
  check(await ev("document.querySelectorAll('#map path.route').length") >= 15, "bus routes drawn");
  check(await ev("document.querySelectorAll('#tract-table tbody tr').length") === 208, "table view has 208 rows");
  check(await ev("document.documentElement.scrollWidth <= 390"), "no horizontal scroll at 390px");
  check(await ev("document.querySelectorAll('.rank-label').length") === 10, "ten ranked tracts labelled");
  // every control
  for (const [ctl, v] of [["win", "weekday_day"], ["win", "weekday_evening"], ["layer", "noaccess"], ["layer", "need"], ["wait", "walk_up"], ["win", "saturday"], ["layer", "gap"], ["wait", "planned"]]) {
    await ev(`document.querySelector('.seg[data-ctl="${ctl}"] button[data-v="${v}"]').click()`);
    await sleep(150);
    const sub = await ev("document.getElementById('map-sub').textContent");
    check(sub && sub.length > 20, `control ${ctl}=${v} updates caption`);
  }
  const fillsDiffer = await ev(`(async()=>{const f=()=>[...document.querySelectorAll('#map path.tract')].map(p=>p.getAttribute('fill')).join();
    const b=document.querySelector('.seg[data-ctl="win"] button[data-v="weekday_day"]'); b.click(); await new Promise(r=>setTimeout(r,100)); const a=f();
    document.querySelector('.seg[data-ctl="win"] button[data-v="saturday"]').click(); await new Promise(r=>setTimeout(r,100)); return a!==f();})()`);
  check(fillsDiffer, "window toggle changes tract fills");
  check(await ev("[...document.querySelectorAll('[data-win-panel]')].filter(e=>!e.hidden).length") === 1, "one gap table visible");
  // tap the top-ranked tract and a pantry
  await ev(`(()=>{const id=window.PANTRY_GAP.ranking.saturday[0]; const p=[...document.querySelectorAll('#map path.tract')].find(x=>x.__data__.properties.GEOID===id); p.dispatchEvent(new MouseEvent('click',{bubbles:true})); })()`);
  await sleep(200);
  const info = await ev("document.getElementById('info').innerText");
  check(/Peoria/.test(info) && /In poverty/.test(info), "tract tap fills the info panel: " + info.split("\n")[0]);
  await shot("smoke-phone-tract.png");
  await ev(`(()=>{const c=[...document.querySelectorAll('#map circle.pantry.open')][0]; c.dispatchEvent(new MouseEvent('click',{bubbles:true}));})()`);
  await sleep(200);
  const pinfo = await ev("document.getElementById('info').innerText");
  check(/Open/.test(pinfo) || /Hours/.test(pinfo), "pantry tap fills the info panel: " + pinfo.split("\n")[0]);
  // table row click selects tract
  await ev(`document.querySelector('[data-win-panel="saturday"] tr[data-geoid]').click()`);
  await sleep(300);
  check(await ev("document.querySelectorAll('#map path.tract.sel:not(.top)').length") === 1, "gap-table row selects a tract");
  // dark mode
  await ev("document.getElementById('theme').click()");
  await sleep(300);
  check(await ev("document.documentElement.dataset.theme") === "dark", "theme toggle switches to dark");
  check(await ev("getComputedStyle(document.body).backgroundColor") === "rgb(13, 13, 13)", "dark page background applied");
  await ev("window.scrollTo(0, 0)");
  await shot("smoke-phone-dark.png");
  await ev(`document.getElementById('map-fig').scrollIntoView()`);
  await sleep(200);
  await shot("smoke-phone-dark-map.png");
  check(errors.length === 0, "no console errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} finally {
  chrome.kill();
}
process.exit(fails.length ? 1 : 0);
