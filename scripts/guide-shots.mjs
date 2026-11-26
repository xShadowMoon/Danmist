// 功能页的截图（2026-11-26）：开一个演示服务，用无头 Edge 把每个功能那一块拍下来，深色、浅色各一张，存到 static/guide/。
// 界面改了就重新跑一次：  py -3 server.py --demo --port 8440 --no-alert --no-update-check   然后   node scripts/guide-shots.mjs http://127.0.0.1:8440
// 每张卡片拍什么写在下面 SHOTS 里（id 要和 static/news.json 的 cards 对上）。
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, mkdirSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const base = (process.argv[2] || 'http://127.0.0.1:8440').replace(/\/$/, '');
const only = process.argv[3] ? new Set(process.argv[3].split(',')) : null;
const out = join(dirname(fileURLToPath(import.meta.url)), '..', 'static', 'guide');
mkdirSync(out, { recursive: true });
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);

// [id, 页面, 准备动作（在页面里跑的 JS）, 拍哪个元素（几个就拍把它们都框进去的那块）, 等几毫秒, 最宽拍多少（从左边量）]
const openSet = p => `openSettings(); document.querySelector('#stabs [data-st="${p}"]').click();`;
const SHOTS = [
  ['login', '/', openSet('acct'), '[data-sp="acct"]'],
  ['switch', '/', `$('xroombtn').click();`, ['#xroombtn', '#xroommenu']],
  ['dm', '/', '', '#p-dm', 5000],
  ['card', '/', `[...document.querySelectorAll('#dmlist .dm .n')].pop()?.click();`, '#card', 5000],
  ['sc', '/', '', '#p-sc', 5000],
  ['gift', '/', '', '#p-gift', 5000],
  ['req', '/', '', '#p-req', 5000],
  ['stats', '/', '', ['#stats', '#p-dm'], 5000, 700],
  ['tts', '/', openSet('tts'), '[data-sp="tts"]'],
  ['alert', '/', openSet('alert'), '[data-sp="alert"]'],
  ['obs', '/obs-setup', '', 'body', 2500, 900],
  ['hist', '/', `openHist();`, '#hist', 2500],
  ['layout', '/', `setLay(true);`, '#laydlg'],
  ['look', '/', openSet('view'), '[data-sp="view"]'],
  ['tags', '/', openSet('dm') + `setTimeout(() => $('tagbox').scrollIntoView(), 300);`, '#tagbox'],
  ['room', '/', openSet('room'), '[data-sp="room"]'],
  ['backup', '/', openSet('more'), ['#mascotbox', '#bakbox']],
  ['preflight', '/', `$('preflightbtn').click();`, '#wb-preflight', 3000],
  ['links', '/', openSet('link'), '[data-sp="link"]'],
];

const dir = mkdtempSync(join(tmpdir(), 'edgeshot-guide-'));
const port = 9300 + Math.floor(Math.random() * 80);
const edge = spawn(EDGE, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${dir}`, '--no-first-run', '--disable-sync', '--disable-extensions',
  '--disable-features=msImplicitSignin', '--no-default-browser-check', '--hide-scrollbars', '--window-size=1400,900', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const meta = {};
try {
  let tabs;
  for (let k = 0; k < 60; k++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); break; } catch { await sleep(250); } }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 0; const pend = {};
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend[m.id]) { pend[m.id](m); delete pend[m.id]; } };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async expr => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); return r.result?.result?.value; };
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1400, height: 900, deviceScaleFactor: 1.5, mobile: false });
  for (const theme of ['dark', 'light']) {
    await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: theme }] });  // OBS 设置页跟着系统深浅色走
    await send('Page.navigate', { url: base + '/' }); await sleep(2500);
    // 不弹公告、引导；深色 / 浅色；主题色用默认的（网页上会按用户的主题色转色相）
    await ev(`(async () => { const j = await (await fetch('/static/news.json')).json().catch(() => ({}));
      for (const k of ['xw-tour', 'xw-obs-tour', 'xw-pwa-asked']) localStorage.setItem(k, '1');
      localStorage.setItem('xw-news-seen', (j.news && j.news[0] && j.news[0].v) || '9');
      localStorage.setItem('xw-cfg', JSON.stringify({ v: 5, theme: '${theme}' })); })()`);
    for (const [name, page, setup, sel, wait, maxW] of SHOTS) {
      if (only && !only.has(name)) continue;
      await send('Page.navigate', { url: base + page + (page.includes('?') ? '&' : '?') + 'demo=1' }); await sleep(wait || 1800);
      if (page !== '/') await ev(`document.documentElement.dataset.theme = '${theme}'`);
      if (setup) { await ev(`(() => { ${setup} })()`); await sleep(900); }
      const sels = Array.isArray(sel) ? sel : [sel];
      const box = await ev(`(() => { const rs = ${JSON.stringify(sels)}.map(s => document.querySelector(s)?.getBoundingClientRect()).filter(r => r && r.width && r.height);
        if (!rs.length) return null; const x = Math.min(...rs.map(r => r.left)), y = Math.min(...rs.map(r => r.top));
        return { x: Math.max(0, x), y: Math.max(0, y), w: Math.min(innerWidth, Math.max(...rs.map(r => r.right))) - Math.max(0, x), h: Math.min(innerHeight, Math.max(...rs.map(r => r.bottom))) - Math.max(0, y) }; })()`);
      if (!box) { console.log('没找到', name, sel); continue; }
      if (maxW) box.w = Math.min(box.w, maxW);
      const h = Math.min(box.h, Math.round(box.w * 0.75));  // 太高的只拍上面一截（卡片里是 4:3）
      const s = await send('Page.captureScreenshot', { format: 'webp', quality: 82, clip: { x: box.x, y: box.y, width: box.w, height: h, scale: 1 } });
      writeFileSync(join(out, `${name}-${theme}.webp`), Buffer.from(s.result.data, 'base64'));
      console.log('ok', name, theme, Math.round(box.w), 'x', h);
    }
    meta[theme] = await ev(`getComputedStyle(document.documentElement).getPropertyValue('--mist-d').trim()`);
  }
  if (!only) writeFileSync(join(out, 'meta.json'), JSON.stringify({ accent: meta }) + '\n');
  ws.close();
} finally {
  edge.kill(); await sleep(800); try { rmSync(dir, { recursive: true, force: true }); } catch {}
  process.exit(0);
}
