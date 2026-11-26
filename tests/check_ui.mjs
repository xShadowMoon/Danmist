// 网页自动检查（2026-11-26，体检 A3）：用无头 Edge 打开演示服务，查两件以前总出问题的事
//   1. 每个页面打开有没有脚本报错 / 加载失败（可选的美术图 404 不算）
//   2. 弹幕跟随：满 300 条照样跟；滚轮往上停住、滚回底部接着跟；PageUp 停住；鼠标停着 2 秒恢复；鼠标停着时用键盘往上翻不会被拽回去
// 用法：node tests/check_ui.mjs http://127.0.0.1:端口     （tests/run_ui.py 会自己开演示服务再调它）
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8390';
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find(p => existsSync(p));
if (!EDGE) { console.log('SKIP 没有 Edge / Chrome'); process.exit(0); }
const dir = mkdtempSync(join(tmpdir(), 'edgeshot-ui-'));
const port = 9300 + Math.floor(Math.random() * 400);
const edge = spawn(EDGE, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${dir}`, '--no-first-run', '--window-size=1400,900', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fails = [];
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) fails.push(what); };
// 可选的图：主播自己没放就 404，页面会自己藏起来，不算错
const OPTIONAL = /\/(static\/art\/|art\/)(xw-|banner|guard\d|frame|mist-|diary-)|favicon\.ico/;

try {
  let tabs;
  for (let k = 0; k < 60; k++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); break; } catch { await sleep(250); } }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 0; const pend = {}; let probs = [];
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pend[m.id]) { pend[m.id](m); delete pend[m.id]; return; }
    // 只算我们自己页面的报错（浏览器自己往页面里塞的脚本报错不算）
    if (m.method === 'Runtime.exceptionThrown') { const d = m.params.exceptionDetails; if (!d.url || d.url.startsWith(base)) probs.push('脚本报错 ' + (d.exception?.description || d.text).split('\n')[0] + (d.url ? ' @' + d.url.replace(base, '') + ':' + d.lineNumber : '')); }
    if (process.env.UI_DEBUG && (m.method === 'Page.frameNavigated' && !m.params.frame.parentId || m.method === 'Runtime.executionContextsCleared')) console.log('  …' + m.method + ' ' + (m.params.frame?.url || ''));
    if (m.method === 'Page.javascriptDialogOpening') { probs.push('弹了对话框：' + m.params.message); send('Page.handleJavaScriptDialog', { accept: false }); }
    if (m.method === 'Network.responseReceived' && m.params.response.status >= 400 && !OPTIONAL.test(m.params.response.url)) probs.push(`HTTP ${m.params.response.status} ${m.params.response.url.replace(base, '')}`);
  };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  // 每一步最多等 3 分钟，卡住就算没过（以前一卡就整个挂住）
  const ev = async expr => {
    const r = await Promise.race([send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }), sleep(180000).then(() => ({ timeout: true }))]);
    if (r.timeout) { console.log('FAIL 卡住超过 3 分钟：' + expr.slice(0, 80)); fails.push('卡住：' + expr.slice(0, 60)); throw new Error('页面里一步卡住超过 3 分钟：' + expr.slice(0, 60)); }
    return r.result?.result?.value;
  };
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');

  // ---------- 1. 每个页面 ----------
  await send('Page.navigate', { url: base + '/' }); await sleep(2500);
  await ev(`(async () => { const j = await (await fetch('/static/news.json')).json().catch(() => ({})); for (const k of ['xw-tour','xw-obs-tour','xw-pwa-asked']) localStorage.setItem(k, '1'); localStorage.setItem('xw-news-seen', (j.news && j.news[0] && j.news[0].v) || '9'); })()`);
  for (const p of process.env.UI_SKIP_PAGES ? [] : ['/', '/host', '/obs', '/obs?style=luna&demo=1', '/obs?style=bubble&demo=1', '/obs-setup', '/obs-songs?demo=1', '/obs-songs?style=vinyl&demo=1', '/obs-music']) {
    probs = [];
    await send('Page.navigate', { url: base + p }); await sleep(3500);
    ok(!probs.length, `页面 ${p}${probs.length ? '：' + [...new Set(probs)].join('；') : ''}`);
  }

  // ---------- 2. 弹幕跟随 ----------
  const step = t => process.env.UI_DEBUG && console.log('  …' + t);
  await send('Page.navigate', { url: base + '/' }); await sleep(4000);
  const state = () => ev(`({ stick, gap: Math.round(dmList.scrollHeight - dmList.scrollTop - dmList.clientHeight), bar: $('newbar').style.display })`);
  const more = (n, gap = 40) => ev(`(async () => { for (let k = 0; k < ${n}; k++) { addDm({ uid: 7, name: '测试', text: '第 ' + k + ' 条，长一点好占地方', t: Date.now() / 1000, i: 100000 + Math.random() * 1e9 | 0 }); await new Promise(r => setTimeout(r, k % 3 ? 16 : ${gap})); } await new Promise(r => setTimeout(r, 1200)); })()`);
  await more(5);  // 先热一下（刚打开时第一批偶尔很慢）
  step('加 420 条'); await ev(`stick = true, toBottom(), hideNewbar()`);
  const rows0 = await ev(`dmList.querySelectorAll(':scope > .dm').length`);
  await more(Math.max(60, 340 - rows0)); step('加完');  // 只加到超过 300 条再多一点（电脑忙的时候也不会太久）
  let s = await state();
  const rows1 = await ev(`dmList.querySelectorAll(':scope > .dm').length`);
  ok(rows1 >= 300 && s.stick && s.gap < 40 && s.bar !== 'block', `满 300 条（现在 ${rows1} 条）以后照样跟随（stick=${s.stick} 离底 ${s.gap}）`);
  const box = await ev(`(() => { const r = dmList.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y });
  await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: box.x, y: box.y, deltaX: 0, deltaY: -400 }); await sleep(700);
  await more(20);
  s = await state();
  ok(!s.stick && s.gap > 200, `滚轮往上翻后停住，不被新弹幕拽回去（离底 ${s.gap}）`);
  await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: box.x, y: box.y, deltaX: 0, deltaY: 100000 }); await sleep(1200);
  await more(20);
  s = await state();
  ok(s.stick && s.gap < 40, `滚回最底下接着跟（离底 ${s.gap}）`);
  await ev(`dmList.tabIndex = 0, dmList.focus()`);
  await send('Input.dispatchKeyEvent', { type: 'rawKeyDown', windowsVirtualKeyCode: 33, key: 'PageUp', code: 'PageUp' });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: 33, key: 'PageUp', code: 'PageUp' });
  await sleep(800); await more(20);
  s = await state();
  ok(!s.stick && s.gap > 200, `PageUp 往上翻后停住（离底 ${s.gap}）`);
  // 鼠标停在列表上：先停，静止 2 秒恢复
  await ev(`stick = true, hoverHeld = false, toBottom(), hideNewbar()`); await sleep(500);
  const hover = await ev(`(async () => {
    dmList.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
    for (let n = 0; n < 10; n++) addDm({ uid: 8, name: 'h', text: '悬停 ' + n, t: Date.now() / 1000, i: 900000 + n });
    await new Promise(r => setTimeout(r, 400));
    const paused = !stick && hoverHeld;
    await new Promise(r => setTimeout(r, 2800));
    return { paused, resumed: stick && !hoverHeld && dmList.scrollHeight - dmList.scrollTop - dmList.clientHeight < 40 };
  })()`);
  ok(hover.paused && hover.resumed, `鼠标在弹幕上动时停住，静止 2 秒后接着跟（${JSON.stringify(hover)}）`);
  // 鼠标停着时用键盘往上翻：不能 2 秒后被拽回最底下（2026-11-26 修的）
  const yank = await ev(`(async () => {
    stick = true; toBottom(); await new Promise(r => setTimeout(r, 300));
    dmList.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'PageUp' }));
    dmList.scrollTop -= 600;
    await new Promise(r => setTimeout(r, 3200));
    return { stick, gap: Math.round(dmList.scrollHeight - dmList.scrollTop - dmList.clientHeight) };
  })()`);
  ok(!yank.stick && yank.gap > 200, `鼠标停着时键盘往上翻，不会被拽回最底下（离底 ${yank.gap}）`);
  ws.close();
} catch (e) {
  console.log('FAIL ' + e.message);
  if (!fails.length) fails.push(e.message);
} finally {
  edge.kill(); await sleep(800);
  try { rmSync(dir, { recursive: true, force: true }); } catch {}
  console.log(fails.length ? `\n${fails.length} 项没过` : '\n全部通过');
  process.exit(fails.length ? 1 : 0);
}
