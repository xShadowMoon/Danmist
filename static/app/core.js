// 雾幕主页面 · 基础：全局状态、设置、深浅色和配色、小工具、线条图标、面板放大、设置搜索、表情放大
// 这几个文件按顺序加载，共用同一套全局变量。加载时只能直接用前面文件里的东西，用后面文件的函数要放进回调里
const $ = id => document.getElementById(id);
const S = { room: {}, flow: { gift: 0, sc: 0, guard: 0 }, dm: [], enters: [], gifts: [], scs: [], guards: [], users: [], session_start: 0 };
let giftTab = 'all', userTab = 'top', dmQuery = '';
let pipWin = null;  // 弹幕小窗（画中画窗口）开着时是它的 window

/* ---------- 设置 ---------- */
const DEF_TPL = { dm: '{name}说：{text}', sc: '{name}的{price}元醒目留言：{text}', gift: '{name}送了{num}个{gift}',
  guard: '{name}开通了大航海', enter: '欢迎{name}进入直播间', follow: '谢谢{name}的关注' };
// 送礼榜、上舰、高能榜原来也是单独模块，跟「礼物 & 上舰」「直播间的人」里的标签页重复，去掉了
const PANELS = { dm: '弹幕', sc: 'SC', gift: '礼物', enter: '进房', users: '观众', req: '点歌',
  follow: '新关注', note: '便签', clock: '时间' };
const PANEL_TIPS = { dm: '点名字看这个人的记录', sc: '醒目留言，带倒计时', gift: '礼物、上舰、送礼榜',
  enter: '刚进来的人', users: '在线的人、本场来过的人', req: '歌单，和弹幕里的点歌、提问', rank: '本场送礼最多的人',
  guards: '本场开通舰长、提督、总督的人', top: 'B 站的高能用户榜', follow: '本场新关注', note: '随手记，只存在这个浏览器', clock: '时间和开播时长' };
const EXTRA = ['follow', 'note', 'clock'];  // 后来加的模块，默认不显示，在「布局」里添加
const TILES = { watched: '看过人数', users: '本场来过', dur: '本场时长' };  // 在线人数挪到「观众」面板的标签上了；收益挪到「礼物」面板标题旁（2026-11-13）
const DEF_LAYOUT = {
  cols: [{ w: 1.5, items: [{ id: 'dm', h: 1 }] }, { w: 1, items: [{ id: 'sc', h: 1.1 }, { id: 'gift', h: 1 }] }, { w: 0.9, items: [{ id: 'req', h: 1 }, { id: 'enter', h: .8 }, { id: 'users', h: 1 }] }],
  hidden: [], tiles: { money: true, watched: true, online: true, users: true, dur: true },
};
const clone = o => JSON.parse(JSON.stringify(o));
const DEF = {
  v: 6, theme: 'auto', pal: '', frames: true, enterMerge: true, songGroup: '',
  // 进房并入弹幕的样子：位置 flow（弹幕区底部常驻小栏，默认）/ top / bottom（有人进来才弹出），停几秒，显示哪些，带不带头像
  enterTip: { pos: 'flow', sec: 3.5, enter: true, follow: true, share: true, like: true, guardOnly: false, avatar: true }, compact: false,
  snd: { on: false, dm: false, sc: true, gift: true, guard: true, enterGuard: false, follow: false, giftMin: 10, scMin: 0, vol: 0.6 }, giftAnim: true, bigGift: { on: true, min: 10, guard: true }, dmSize: 15.5, giftMin: 0, snow: false,
  dmFilter: 'all', dmMedalMin: 10, hlWords: '主播 点歌',
  dm: { gap: 0, name: 12, bg: 'none', font: '', color: '', avatar: true, medal: true, simple: false, time: true, bold: false, inline: false, guardBg: true, note: true, hoverPause: true, anim: 'in', animMs: 600 },
  sc: { size: 14.5, read: 'dim', avatar: true, bar: true, unreadTop: false, autoRead: false, min: 0 },
  accent: '', bgAlpha: 85, fs: { sc: 100, gift: 100, enter: 100, users: 100, req: 100 }, topHide: [], topPin: ['obsbtn', 'ttsbtn', 'histbtn', 'librarybtn'],
  layout: clone(DEF_LAYOUT),
  tts: { on: false, voice: '', aiScope: 'thanks', volume: 1, rate: 1.15, pitch: 1,
    dm: true, sc: true, gift: true, giftMin: 1, guard: true, enter: false, enterGuardOnly: true, follow: false,
    readName: true, readEmoticon: false, readPrice: true, zeroDelay: false, maxLen: 40, block: '', muted: [],
    skipBot: true, skipAnchor: true, tpl: { ...DEF_TPL } },
};
const merge = (base, over) => {
  if (Array.isArray(base) || typeof base !== 'object' || base === null) return over === undefined ? base : over;
  const out = { ...base };
  for (const k of Object.keys(base)) if (over && k in over) out[k] = merge(base[k], over[k]);
  return out;
};
// 默认值留一份副本（2026-11-21）：没存过设置时 cfg 就是 DEF 本身，一改 cfg 默认值也跟着变，「改过的」就认不出来了
const DEF0 = JSON.parse(JSON.stringify(DEF));
let cfg = DEF;
try {
  const saved = JSON.parse(localStorage.getItem('xw-cfg') || '{}');
  cfg = merge(DEF, saved);
  // 第 2 版起飘雪动画默认关（占电脑），以前存过「开」的也先关上，想要可以再开
  if (!(saved.v >= 2)) { cfg.snow = false; cfg.v = 2; }
  // 第 3 版（2026-11-18）：进房提示默认改成弹幕区底部的小栏，以前存过别的位置也先换过来，想要可以再改回
  if (!(saved.v >= 3)) { cfg.enterMerge = true; cfg.enterTip.pos = 'flow'; cfg.v = 3; }
  // 第 4 版（2026-11-18）：大礼物特效门槛默认从 100 元降到 10 元（告白花束 19.9 元在 B 站也有大特效）
  if (!(saved.v >= 4)) { if (cfg.bigGift.min === 100) cfg.bigGift.min = 10; cfg.v = 4; }
  // 第 5 版（2026-11-18）：提示音改成分开设置、默认全关（用户要求）；以前的「提示音」开关不再用
  if (!(saved.v >= 5)) { cfg.snd.on = false; cfg.v = 5; }
  // 第 6 版（2026-11-28）：弹幕「简洁」默认改成不开（用户要求）；0.9.15 默认开着的，先关上，想要可以再开
  if (!(saved.v >= 6)) { cfg.dm.simple = false; cfg.v = 6; }
  // 2026-11-12 上舰默认说法改成「xx开通了大航海」；自己改过说法的不动，只换掉还是旧默认的
  if (cfg.tts.tpl.guard === '感谢{name}开通{level}') cfg.tts.tpl.guard = DEF_TPL.guard;
  // 2026-11-19 SC 只留一个「字号」（整张卡一起缩放）：以前单独调过 SC 文字大小的，折算进去
  if (cfg.sc.size !== DEF.sc.size) { cfg.fs.sc = Math.min(160, Math.max(80, Math.round(cfg.fs.sc * cfg.sc.size / DEF.sc.size / 5) * 5)); cfg.sc.size = DEF.sc.size; }
} catch {}
// 网址带 ?replay=1：重新弹一次新手引导和「装到桌面」提示（给自己看效果用，2026-11-18），然后把参数从地址栏去掉
if (new URLSearchParams(location.search).has('replay')) {
  try { localStorage.removeItem('xw-tour'); localStorage.removeItem('xw-pwa-asked'); } catch {}
  const u = new URL(location.href); u.searchParams.delete('replay'); history.replaceState(null, '', u.pathname + u.search + u.hash);
}
// 网址带 ?pop=1：只显示弹幕的小窗口（浏览器不支持「浮在最上面」时用）。小窗里不朗读、不响、不存设置，免得跟主窗口重复
const POP = new URLSearchParams(location.search).has('pop');
if (POP) { document.body.classList.add('pop'); cfg = clone(cfg); cfg.tts.on = false; cfg.snd.on = false; }
// 普通链接 / 普通视角用一套固定的简单布局：原来的布局先收在 stashLayout 里，存设置时存的还是它
let stashLayout = null;
const saveCfg = () => { if (POP) return; try { localStorage.setItem('xw-cfg', JSON.stringify(stashLayout ? { ...cfg, layout: stashLayout } : cfg)); } catch {} };
const getK = k => k.split('.').reduce((o, p) => o?.[p], cfg);
const setK = (k, v) => { const ps = k.split('.'), last = ps.pop(); ps.reduce((o, p) => o[p], cfg)[last] = v; };

function applyCfg() {
  document.documentElement.style.setProperty('--dm-size', cfg.dmSize + 'px');
  if (typeof setTipPos === 'function') setTipPos();  // 进房细栏的位置跟着设置走（render.js 里）
  // 弹幕栏的自定义样式
  const D = cfg.dm, R = document.documentElement.style, B = document.body.classList;
  R.setProperty('--dm-gap', D.gap + 'px');
  R.setProperty('--dm-name', D.name + 'px');
  const FONTS = { round: '"YouYuan", "幼圆", "HarmonyOS Sans SC", sans-serif', hei: '"SimHei", "黑体", "Microsoft YaHei", sans-serif', kai: '"KaiTi", "楷体", "STKaiti", serif', song: '"SimSun", "宋体", "Songti SC", serif' };
  FONTS[D.font] ? R.setProperty('--dm-font', FONTS[D.font]) : R.removeProperty('--dm-font');
  $('dmlist').style.color = D.color || '';
  for (const k of ['bubble', 'stripe', 'line']) B.toggle('dm-' + k, D.bg === k);
  B.toggle('dm-simple', !!D.simple);  // 简洁（2026-11-26）：名字前只留身份和自己直播间的粉丝牌
  B.toggle('dm-noav', !D.avatar); B.toggle('dm-notime', !D.time); B.toggle('dm-nomedal', !D.medal);
  B.toggle('dm-bold', !!D.bold); B.toggle('dm-inline', !!D.inline);
  // 主题色、背景图、各面板字号
  const A = /^#[0-9a-f]{6}$/i.test(cfg.accent) ? cfg.accent : '';
  for (const [k, v] of [['--mist-d', A], ['--mist', A], ['--chip', A && `color-mix(in srgb, ${A} 16%, var(--card))`], ['--frost', A && `color-mix(in srgb, ${A} 35%, var(--card))`]]) v ? R.setProperty(k, v) : R.removeProperty(k);
  let bg = ''; try { bg = localStorage.getItem('xw-bg') || ''; } catch {}
  B.toggle('hasbg', !!bg); document.body.style.backgroundImage = bg ? `url("${bg}")` : '';
  if (typeof drawAccentSwatches === 'function') drawAccentSwatches(bg);  // songs.js 里的；刚打开时它还没读进来，最后那次 applyCfg 会补上
  R.setProperty('--pa', cfg.bgAlpha + '%');
  for (const [id, z] of Object.entries(cfg.fs)) document.querySelectorAll(`#p-${id} .list`).forEach(el => el.style.zoom = z === 100 ? '' : z / 100);
  B.toggle('dm-gbg', !!D.guardBg); B.toggle('dm-nonote', !D.note);
  // 弹幕进场动画、SC 栏
  R.setProperty('--dm-anim', D.anim); R.setProperty('--dm-ms', D.animMs + 'ms');
  const C = cfg.sc;
  R.setProperty('--sc-size', C.size + 'px'); R.setProperty('--sc-read-op', C.read === 'dim' ? '.5' : '1');
  B.toggle('sc-fold', C.read === 'fold'); B.toggle('sc-hide', C.read === 'hide');
  B.toggle('sc-noav', !C.avatar); B.toggle('sc-nobar', !C.bar);
  try { if (stick) toBottom(); } catch {}
  const b = $('ttsbtn');
  b.innerHTML = `${icon('volume')}<span class="lbl"> 朗读：${cfg.tts.on ? '开' : '关'}</span>`;
  b.classList.toggle('on', cfg.tts.on);
  document.body.classList.toggle('compact', !!cfg.compact);
  document.body.classList.toggle('noframe', cfg.frames === false);
  $('compactbtn').classList.toggle('on', !!cfg.compact);
  applyTopHide();
  renderLayoutBar();
  if (!cfg.tts.on) ttsClear();
  updateTtsBar();
  renderMuted();
  applyTheme();
  snowOn(cfg.snow);
  syncPop();
}
// 设置里的拖条（2026-11-21 改版，参考 PR）：数字是蓝色的，按住左右拖就能改，点一下直接打字；旁边一条细拖条
function rangeSet(r, raw) {
  const min = Number(r.min), max = Number(r.max), step = Number(r.step) || 1;
  let v = Number(raw); if (!Number.isFinite(v)) return;
  v = Number(Math.min(max, Math.max(min, Math.round((v - min) / step) * step + min)).toFixed(3));
  r.value = v; r.dispatchEvent(new Event('input', { bubbles: true }));
}
document.querySelectorAll('input[type=range][data-k]').forEach(r => {
  const pct = !!r.dataset.pct, show = v => pct ? Math.round(Number(v) * 100) : Number(v);
  const sb = document.createElement('b');
  sb.className = 'scrub'; sb.tabIndex = 0; sb.title = '按住左右拖，或点一下直接打字';
  sb._txt = () => { sb.innerHTML = `${show(r.value)}<small>${r.dataset.u || ''}</small>`; };
  r.before(sb); sb._txt();
  r.addEventListener('input', sb._txt);
  let x0 = null, v0 = 0, moved = false;
  sb.addEventListener('pointerdown', e => { x0 = e.clientX; v0 = Number(r.value); moved = false; sb.setPointerCapture(e.pointerId); e.preventDefault(); });
  sb.addEventListener('pointermove', e => {
    if (x0 == null) return;
    const dx = e.clientX - x0;
    if (Math.abs(dx) > 3) moved = true;
    if (moved) rangeSet(r, v0 + Math.round(dx / 4) * (Number(r.step) || 1));
  });
  const edit = () => {
    const n = document.createElement('input');
    n.type = 'number'; n.className = 'nv'; n.min = show(r.min); n.max = show(r.max); n.step = show(r.step); n.value = show(r.value);
    sb.replaceWith(n); n.focus(); n.select();
    let done = false;
    const finish = ok => { if (done) return; done = true; if (ok && n.value !== '') rangeSet(r, pct ? Number(n.value) / 100 : n.value); n.replaceWith(sb); sb._txt(); };
    n.onblur = () => finish(true);
    n.onkeydown = e => { if (e.key === 'Enter') finish(true); if (e.key === 'Escape') finish(false); };
  };
  sb.addEventListener('pointerup', () => { const was = moved; x0 = null; if (!was) edit(); });
  sb.addEventListener('keydown', e => { if (e.key === 'Enter') edit(); if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); rangeSet(r, Number(r.value) + (e.key === 'ArrowLeft' ? -1 : 1) * (Number(r.step) || 1)); } });
});
function fillSettings() {
  document.querySelectorAll('[data-k]').forEach(el => {
    const v = getK(el.dataset.k);
    if (el.type === 'checkbox') el.checked = !!v; else if (el.type === 'color') el.value = v || (el.dataset.k === 'accent' ? '#4a8cc4' : matchMedia('(prefers-color-scheme: dark)').matches ? '#e2ebf4' : '#23364a'); else el.value = v ?? '';
  });
  document.querySelectorAll('[data-v]').forEach(el => el.textContent = getK(el.dataset.v));
  document.querySelectorAll('#settings .scrub').forEach(b => b._txt?.());
  syncSegs(); markChg();
}
/* ---------- 2026-11-21 设置改版：两三个选项用一排连着的按钮（.seg），后面藏着原来的下拉框 / 勾选框，点按钮就是改它 ---------- */
function syncSegs() {
  document.querySelectorAll('.seg[data-segk]').forEach(sg => {
    const v = String(getK(sg.dataset.segk) ?? '');
    sg.querySelectorAll('[data-val]').forEach(b => b.classList.toggle('on', b.dataset.val === v));
  });
}
document.addEventListener('click', e => {
  const b = e.target.closest('.seg[data-segk] [data-val]');
  if (!b) return;
  const k = b.closest('.seg').dataset.segk, el = b.closest('.ctl, .opt')?.querySelector(`[data-k="${k}"]`);
  if (!el) return;
  if (el.type === 'checkbox') el.checked = b.dataset.val === 'true'; else el.value = b.dataset.val;
  el.dispatchEvent(new Event('change', { bubbles: true }));
  syncSegs(); markChg();
});
// 改过的项（跟默认不一样）名字加粗、右边出 ↺；左边分类有改过的带小红点（参考 PR / DaVinci）
const getDef = k => k.split('.').reduce((o, p) => o?.[p], DEF0);
const sameV = (a, b) => JSON.stringify(a ?? '') === JSON.stringify(b ?? '');
function markChg() {
  const box = $('settings');
  box.querySelectorAll('.r').forEach(r => { const el = r.querySelector('[data-k]'); r.classList.toggle('chg', !!el && !sameV(getK(el.dataset.k), getDef(el.dataset.k))); });
  box.querySelectorAll('.chip').forEach(c => { const el = c.querySelector('[data-k]'); c.classList.toggle('chg', !!el && !sameV(!!getK(el.dataset.k), !!getDef(el.dataset.k))); });
  // 左边分类的小红点去掉了（2026-11-21 用户：红点一直不消失，看着像有没处理的事）；改过的项在页面里照样加粗、带 ↺
  box.querySelectorAll('#stabs .dot').forEach(b => b.classList.remove('dot'));
}
// 恢复一项：把控件改回默认，再让它自己的事件跑一遍（该重画的都会重画）
function resetK(el) {
  const k = el.dataset.k, d = getDef(k);
  if (el.type === 'color') { setK(k, clone(d ?? '')); saveCfg(); applyCfg(); fillSettings(); return; }
  if (el.type === 'checkbox') el.checked = !!d; else el.value = d ?? '';
  el.dispatchEvent(new Event(el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input', { bubbles: true }));
}
$('settings').addEventListener('click', e => {
  const rs = e.target.closest('.r .rs');
  if (rs) { const el = rs.closest('.r').querySelector('[data-k]'); if (el) { resetK(el); fillSettings(); } return; }
  if (e.target.closest('#pagereset')) {
    const pg = $('settings').querySelector('.spage.on');
    pg?.querySelectorAll('[data-k]').forEach(resetK);
    if (pg?.dataset.sp === 'tts') { cfg.tts.tpl = { ...DEF_TPL }; saveCfg(); }
    fillSettings(); note('这一页恢复默认了', true);
  }
});
let chgT = 0;
['change', 'input'].forEach(t => $('settings').addEventListener(t, () => { clearTimeout(chgT); chgT = setTimeout(markChg, 80); }));
document.querySelectorAll('[data-k]').forEach(el => {
  el.addEventListener(el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input', () => {
    let v = el.type === 'checkbox' ? el.checked : el.value;
    if (el.type === 'number' || el.type === 'range') v = Number(v) || 0;
    setK(el.dataset.k, v);
    document.querySelectorAll(`[data-v="${el.dataset.k}"]`).forEach(x => x.textContent = v);
    saveCfg(); applyCfg();
    if (el.dataset.k === 'giftMin') renderGifts();
    if (el.dataset.k === 'enterMerge') renderLayout();
    if (el.dataset.k.startsWith('enterTip.') || el.dataset.k === 'enterMerge') previewEnter();
    if (el.dataset.k === 'hlWords' || el.dataset.k === 'dmMedalMin') renderDm();
    if (el.dataset.k.startsWith('sc.')) renderSc();
    if (el.dataset.k === 'tts.on' && v) ttsUnlockHint();
  });
});
// 进场动画预览：改了样式或时长就播一遍示例弹幕
function playAnim() {
  const d = { t: Date.now() / 1000 | 0, uid: 0, name: (window.BRAND?.short || '主播') + '的猫', face: '', text: (window.BRAND?.short || '主播') + '晚上好～', medal: window.BRAND?.medal || '粉丝团', medal_level: 15, guard: 3, emoticon: '' };
  $('animprevlist').innerHTML = dmHtml(d);
}
$('animprev').onclick = playAnim;
document.querySelectorAll('[data-k="dm.anim"], [data-k="dm.animMs"]').forEach(el => el.addEventListener(el.tagName === 'SELECT' ? 'change' : 'input', () => setTimeout(playAnim, 0)));
$('stabs').addEventListener('click', e => { if (e.target.closest('[data-st=dm]')) setTimeout(() => { playAnim(); previewEnter(); }, 200); });
$('dmcolorreset').onclick = () => { cfg.dm.color = ''; saveCfg(); applyCfg(); fillSettings(); };
$('dmreset').onclick = () => { cfg.dm = clone(DEF.dm); cfg.sc = clone(DEF.sc); cfg.dmSize = DEF.dmSize; saveCfg(); applyCfg(); fillSettings(); };
// page：打开哪一页（各栏齿轮传自己的名字，比如 dm、sc）；不传就停在上次那页
const openSettings = page => { fillSettings(); fillVoices(); if (typeof page === 'string') $('stabs').querySelector(`[data-st="${page}"]`)?.click(); $('settings').classList.add('open'); $('mask').classList.add('show', 'clear'); };  // 调设置时不压暗页面，改了马上看得到
const closeAll = () => { ['settings', 'card', 'hist', 'obsbox', 'laydlg', 'guide'].forEach(id => $(id).classList.remove('open')); $('layoutbtn').classList.remove('on'); $('mask').classList.remove('show', 'clear'); if ($('obsframe').src) $('obsframe').removeAttribute('src'); };
$('setbtn').onclick = () => openSettings();
$('stabs').onclick = e => {
  const b = e.target.closest('[data-st]');
  if (!b) return;
  $('stabs').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.spage').forEach(x => x.classList.toggle('on', x.dataset.sp === b.dataset.st));
  $('settings').querySelector('.body').scrollTop = 0;
};
$('setclose').onclick = closeAll;
$('mask').onclick = closeAll;
addEventListener('keydown', e => { if (e.key === 'Escape') { closeAll(); if (document.body.classList.contains('editing')) setEditing(false); } });
$('ttsbtn').onclick = () => { cfg.tts.on = !cfg.tts.on; saveCfg(); applyCfg(); if (cfg.tts.on) { ttsUnlockHint(); say('朗读已打开', 2, true); } };
$('tplreset').onclick = () => { cfg.tts.tpl = { ...DEF_TPL }; saveCfg(); fillSettings(); };

/* ---------- 深色 / 浅色 ---------- */
const darkMQ = matchMedia('(prefers-color-scheme: dark)');
const APPWIN = new URLSearchParams(location.search).get('app') === '1';  // 桌面版的软件窗口里打开的（desktop.py 加的 ?app=1）
// 配色方案：名字、两个色点（浅色主色、深色主色）；OBS 设置页也有同样几套
// 品牌（2026-11-26，小雾版和开源版合成一份）：后台在网页里放了 window.BRAND = { name 软件名, short 怎么称呼主播, host 主播专属链接地址, pack 有没有私有包 }
const BRAND_NAME = () => window.BRAND?.name || '雾幕', ANCHOR = () => window.BRAND?.short || '主播';
// 小雾版以前把「紫金」配色叫 hanaki，存过的设置照样认
if (cfg.pal === 'hanaki') cfg.pal = 'lilac';
const PALS = { '': ['雾蓝', '#7fb3dd', '#4a8cc4'], sakura: ['樱粉', '#f3c7d8', '#cc5d87'], mint: ['薄荷', '#b3e1cf', '#2b9670'], night: ['雪夜', '#c6c8ef', '#5a5fc4'], lilac: ['紫金', '#d3ccf3', '#f0b429'] };
for (const [k, n] of Object.entries(window.EXT?.palLabel || {})) if (PALS[k]) PALS[k][0] = n;  // 包里可以给配色改名
$('pals').innerHTML = Object.entries(PALS).map(([k, [n, a, b]]) => `<button data-pal="${k}" style="--a:${a};--b:${b}" title="${n}"><i></i>${n}</button>`).join('');
$('pals').onclick = e => { const b = e.target.closest('[data-pal]'); if (!b) return; cfg.pal = b.dataset.pal; cfg.accent = ''; saveCfg(); applyCfg(); fillSettings(); };
const effTheme = () => cfg.theme === 'auto' ? (darkMQ.matches ? 'dark' : 'light') : cfg.theme;
function applyTheme() {
  const t = effTheme();
  document.documentElement.dataset.theme = t;
  PALS[cfg.pal] ? document.documentElement.dataset.pal = cfg.pal : delete document.documentElement.dataset.pal;
  $('pals').querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.pal === (PALS[cfg.pal] ? cfg.pal : '')));
  $('themebtn').innerHTML = icon(t === 'dark' ? 'sun' : 'moon') + `<span class="lbl"> ${t === 'dark' ? '浅色' : '深色'}</span>`;
  $('themebtn').title = t === 'dark' ? '换成浅色' : '换成深色';
}
darkMQ.addEventListener?.('change', () => { if (cfg.theme === 'auto') applyTheme(); });
$('themebtn').onclick = () => { cfg.theme = effTheme() === 'dark' ? 'light' : 'dark'; saveCfg(); applyTheme(); };
// 顶栏按钮（2026-11-26 改）：勾上的带字放在外面（默认 OBS、朗读、历史、曲库），没勾的都在「更多」里；外面放不下的也收进「更多」
const TOP_BTNS = [['librarybtn', '曲库'], ['preflightbtn', '自检'], ['histbtn', '历史'], ['obsbtn', 'OBS'], ['layoutbtn', '布局'], ['compactbtn', '紧凑'],
  ['themebtn', '深浅色'], ['ttsbtn', '朗读'], ['copylink', '复制链接'], ['viewbtn', '普通视角'], ['newsbtn', '公告']];
const topPinned = () => Array.isArray(cfg.topPin) ? cfg.topPin : ['obsbtn', 'ttsbtn', 'histbtn', 'librarybtn'];
function applyTopHide() {
  const pin = topPinned();
  const box = $('topbtns');
  if (box && !box.dataset.done) {
    box.dataset.done = 1;
    box.onchange = e => { const id = e.target.dataset.tb; if (!id) return; cfg.topPin = e.target.checked ? [...new Set([...topPinned(), id])] : topPinned().filter(x => x !== id); saveCfg(); applyTopHide(); };
  }
  if (box) box.innerHTML = TOP_BTNS.map(([id, n]) => `<label class="chip"><input type="checkbox" data-tb="${id}"${pin.includes(id) ? ' checked' : ''}><span>${n}</span></label>`).join('');
  window.fitTop?.();
}
function toggleCompact() { cfg.compact = !cfg.compact; saveCfg(); applyCfg(); renderLayoutBar(); }
$('compactbtn').onclick = toggleCompact;

/* ---------- 小工具 ---------- */
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const hhmm = t => { const d = new Date(t * 1000); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
const yuan = n => '¥' + (Math.round(n * 100) / 100).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
const num = n => n == null || n === '' ? '-' : Number(n).toLocaleString('zh-CN');
const fmtMd = t => { const d = new Date(t * 1000); return `${d.getMonth() + 1}/${d.getDate()} ${hhmm(t)}`; };
const dur = sec => { sec = Math.max(0, Math.floor(sec)); return `${Math.floor(sec / 3600)}:${String(Math.floor(sec % 3600 / 60)).padStart(2, '0')}`; };
const GN = { 1: '总督', 2: '提督', 3: '舰长' };
// 粉丝牌颜色：按 B 站官方的等级分段（21 级以上是渐变）
// B 站新版粉丝牌：每 10 级一个颜色；第三个是舰长 / 提督 / 总督牌子的亮边（2026-11-12 从 B 站接口实测，1–20 级的亮边是照着同色调亮的）
const MEDAL_COLORS = [[51, '#EC4F6E', '#F18087'], [41, '#A773F1', '#D47AFF'], [31, '#4C7DFF', '#58A1F8'], [21, '#3FB4F6', '#5FC7F4'],
  [11, '#C770A4', '#DD92C0'], [1, '#5762A7', '#7F89CC']];
function medalHtml(name, lv, guard, dim) {  // dim：牌子是灰的（没点亮），跟 B 站一样显示成灰色（2026-11-18）
  const c = MEDAL_COLORS.find(x => lv >= x[0]) || MEDAL_COLORS[MEDAL_COLORS.length - 1];
  if (dim) return `<span class="medal dim" title="粉丝牌没点亮"><b>${esc(name)}</b><i>${lv}</i></span>`;
  return `<span class="medal" style="--m:${c[1]}${guard ? ';--mb:' + c[2] : ''}"><b>${esc(name)}</b><i>${lv}</i></span>`;
}
const GS = { 1: '总', 2: '提', 3: '舰' };
// 身份标签（2026-11-26 用户要的）：自带的名字、简称、颜色能在 设置 → 弹幕 → 身份标签 里改；自己的标签在观众卡片里给人加上
const TAG_DEF = { g1: ['总督', '总'], g2: ['提督', '提'], g3: ['舰长', '舰'], admin: ['房管', '房'], bot: ['机器人', '机器人'], anchor: ['主播', '主播'] };
const tagName = k => S.tags?.builtin?.[k]?.name || TAG_DEF[k][0];
const tagShort = k => S.tags?.builtin?.[k]?.short || S.tags?.builtin?.[k]?.name || TAG_DEF[k][1];
function applyTags() {
  for (const n of [1, 2, 3]) { GN[n] = tagName('g' + n); GS[n] = tagShort('g' + n); }
  const B = S.tags?.builtin || {};
  const css = Object.entries(B).filter(([, v]) => v.color).map(([k, v]) => `.tag.${k}{background:${v.color}!important}`).join('')
    + (S.tags?.custom || []).filter(t => t.color).map(t => `.tag.ct-${t.id}{background:${t.color}}`).join('');
  let el = document.getElementById('tagcss');
  if (!el) { el = document.createElement('style'); el.id = 'tagcss'; document.head.append(el); }
  el.textContent = css;
}
const userTags = uid => (S.tags?.users?.[uid] || []).map(id => (S.tags.custom || []).find(t => t.id === id)).filter(Boolean);
const customTagsHtml = uid => userTags(uid).map(t => `<span class="tag ct ct-${t.id}" title="${esc(t.name)}">${esc(t.name)}</span>`).join('');
// 荣耀等级（B 站的财富等级，2026-11-19）：小圆角块 + 等级，颜色按段分，跟 B 站差不多
const WEALTH_TIERS = [[50, '#ff6a3d'], [40, '#e85bd0'], [30, '#8d6cf0'], [20, '#3f8cf4'], [10, '#27b0a0'], [1, '#8fa2b5']];
// 有 B 站官方的等级勋章图（1–80 级每级一张）就用官方的，没拿到再用自己画的小块
let WEALTH_ICON = {};
// 2026-11-25：服务刚启动的几秒里还没拿到图标，那时打开的页面以前就一直是色块；没拿到就隔几秒再问
function loadWealth(tries = 0) {
  const again = () => { if (tries < 40) setTimeout(() => loadWealth(tries + 1), 3000); };
  fetch('api/wealth_icons').then(r => r.json()).then(j => { WEALTH_ICON = j || {}; if (!Object.keys(WEALTH_ICON).length) return again(); if (typeof renderDm === 'function') renderDm(); }).catch(again);
}
loadWealth();
// 舰长头像框（2026-11-25）：没放自己的框图时用 B 站官方的框，官方框底下自带「舰长」字，就不再叠锚徽章
fetch('api/art').then(r => r.json()).then(a => document.body.classList.toggle('biliframe', !a.includes('frame3-s.png'))).catch(() => {});
function wealthHtml(lv) {
  const u = WEALTH_ICON[lv];
  if (u) return `<img class="wealthimg" src="img?u=${encodeURIComponent(u)}&s=big" alt="荣耀 ${lv}" title="荣耀等级 ${lv}">`;
  const c = (WEALTH_TIERS.find(x => lv >= x[0]) || WEALTH_TIERS[WEALTH_TIERS.length - 1])[1];
  return `<span class="wealth" style="--w:${c}" title="荣耀等级 ${lv}">${icon('gem')}${lv}</span>`;
}  // 身份标签只写一个字，跟 B 站一样
const COLORS = ['#7fb3dd', '#9cc4e4', '#f2a7bf', '#a7c8a1', '#c3a6e0', '#e8b77a', '#88b9c9'];
function avatar(face, name, guard, size) {
  const g = guard ? ' g' + guard : '';
  const st = size ? `width:${size}px;height:${size}px;` : '';
  const ch = esc([...String(name || '?')][0]);
  const c = COLORS[[...String(name)].reduce((a, x) => a + x.charCodeAt(0), 0) % COLORS.length];
  const av = face ? `<img class="av${g}" style="${st}" src="img?u=${encodeURIComponent(face)}" loading="lazy" data-ch="${ch}" onerror="avFail(this)">`
    : `<span class="av${g}" style="${st}background:${c}">${ch}</span>`;
  // 舰长头像框（2026-11-19 改醒目）：头像和框之间一圈白边隔开，框外有等级色光晕，右下角一个锚徽章，一眼看出是舰长 / 提督 / 总督
  return guard >= 1 && guard <= 3 ? `<span class="avw g${guard}">${av}<img class="avf" src="art/frame${guard}-s.png?v=3" alt="" onerror="this.remove()"><img class="avb" src="art/guard${guard}.png?v=3" alt="" onerror="this.remove()"></span>` : av;
}
fillIcons();

/* ---------- 双击面板标题：这个面板临时铺满窗口，再双击或按 Esc 还原 ---------- */
document.addEventListener('dblclick', e => {
  const head = e.target.closest('.panel > header');
  if (!head || e.target.closest('button, input, select, textarea, a, .tab')) return;
  const p = head.parentElement, on = !p.classList.contains('max');
  document.querySelectorAll('.panel.max').forEach(x => x.classList.remove('max'));
  p.classList.toggle('max', on);
  document.body.classList.toggle('has-max', on);
  if (p.id === 'p-dm' && stick) toBottom();
});
addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.querySelector('.panel.max')) {
    document.querySelectorAll('.panel.max').forEach(x => x.classList.remove('max'));
    document.body.classList.remove('has-max');
  }
});

/* ---------- 设置搜索：输入关键词，四页里所有对得上的选项一起列出来，别的先藏起来 ---------- */
$('setsearch').addEventListener('input', () => {
  const q = $('setsearch').value.trim().toLowerCase(), box = $('settings');
  gearSearch(q);
  box.classList.toggle('searching', !!q);
  for (const el of box.querySelectorAll('.spage .opt, .spage .chip, .spage .field, .spage .chips > .btn')) {
    const text = (el.textContent + ' ' + (el.title || '') + ' ' + (el.querySelector('[title]')?.title || '')).toLowerCase();
    el.classList.toggle('s-miss', !!q && !text.includes(q));
  }
  // 整组都没对上的小标题、折叠块也藏起来
  for (const el of box.querySelectorAll('.spage fieldset')) {
    if (!q) { el.classList.remove('s-miss'); continue; }
    el.classList.toggle('s-miss', !el.querySelector('legend')?.textContent.toLowerCase().includes(q) && !el.querySelector('.opt:not(.s-miss), .chip:not(.s-miss), .field:not(.s-miss), .chips > .btn:not(.s-miss)'));
  }
  for (const pg of box.querySelectorAll('.spage')) pg.classList.toggle('s-miss', !!q && !pg.querySelector('fieldset:not(.s-miss)'));  // 一项都没搜到的那页，标题也不显示
  for (const el of box.querySelectorAll('.spage h3, .spage details, .spage .chips')) {
    if (!q) { el.classList.remove('s-miss'); continue; }
    if (el.tagName === 'H3') {
      let n = el.nextElementSibling, hit = false;
      while (n && n.tagName !== 'H3') { if (n.matches('.opt, .chips, .field, details, textarea, div') && !n.classList.contains('s-miss') && n.querySelector(':not(.s-miss)')) hit = true; n = n.nextElementSibling; }
      el.classList.toggle('s-miss', !hit && !el.textContent.toLowerCase().includes(q));
    } else {
      el.classList.toggle('s-miss', !el.querySelector('.opt:not(.s-miss), .chip:not(.s-miss), .field:not(.s-miss), .chips > .btn:not(.s-miss)'));
      if (el.tagName === 'DETAILS' && !el.classList.contains('s-miss')) el.open = true;
    }
  }
});

// 各栏齿轮里的设置 2026-11-21 改版后都在设置窗口里各一页了，搜设置直接搜得到
function gearSearch() {}

/* ---------- 表情包大图：点一下放大看 ---------- */
document.addEventListener('click', e => {
  const img = e.target.closest('.dm .txt img:not(.emo), .hdm img:not(.emo)');
  if (!img) return;
  e.stopPropagation();
  const box = document.createElement('div');
  box.className = 'zoom';
  box.innerHTML = `<img src="${img.src}" alt="${esc(img.alt)}"><span>${esc(img.alt || '')}</span>`;
  box.onclick = () => box.remove();
  document.body.append(box);
}, true);
addEventListener('keydown', e => { if (e.key === 'Escape') document.querySelector('.zoom')?.remove(); });

function avFail(img) {
  const s = document.createElement('span');
  s.className = img.className; s.style.cssText = img.style.cssText; s.style.background = COLORS[0]; s.textContent = img.dataset.ch;
  img.replaceWith(s);
}
// SC 颜色跟 B 站一模一样（2026-11-21 从 B 站 SC 数据里拿的）：[上半浅色, 下半深色, 金额颜色]；上半名字深色字，下半留言白字
function scColor(p) {
  if (p >= 2000) return ['#ffd8d8', '#ab1a32', '#c86a7a']; if (p >= 1000) return ['#ffe7e4', '#e54d4d', '#ee8b8b'];
  if (p >= 500) return ['#ffead2', '#e09443', '#e8af79']; if (p >= 100) return ['#fff1c5', '#e2b52b', '#eccf75'];
  if (p >= 50) return ['#dbfffd', '#427d9e', '#7da4bd']; return ['#edf5ff', '#2a60b2', '#7497cd'];
}
// 500 元以上 B 站右上角有一张装饰图：后台转发 B 站给的那张；以前的 SC 没存，就按金额用已知的
const SC_ICON = [[2000, 'https://i0.hdslb.com/bfs/live/0d9cbbdbad7d3371266cd5b568065415415316ae.png'], [500, 'https://i0.hdslb.com/bfs/live/e12e931ed8d9e5189ab6d1a3a1da35af4f8a55af.png']];
const scTier = p => p >= 2000 ? 2000 : p >= 1000 ? 1000 : p >= 500 ? 500 : 0;
const scIcon = s => s.icon || S.sc_icons?.[scTier(s.price)] || (s.price >= 1000 && s.price < 2000 ? '' : (SC_ICON.find(x => s.price >= x[0]) || [])[1] || '');  // S.sc_icons：后台见过的各档装饰图（11-21）
const userOf = uid => S.users.find(u => u.uid === uid);
const noteOf = uid => S.notes?.[String(uid)]?.note || '';  // 观众备注（只有管理身份拿得到）
const isMuted = uid => cfg.tts.muted.some(m => m.uid === uid);
// live = 本场面板里的（带倒计时和已读按钮）；历史详情里不带
const scHtml = (s, live) => {
  const [c1, c2, c3] = scColor(s.price), ic = scIcon(s);
  const read = live && scRead.has(String(s.id));
  const expiredDim = live && cfg.sc.autoRead && s.end && s.end <= Date.now() / 1000;
  const active = live && s.end && s.end > Date.now() / 1000;
  const total = s.end ? Math.max(1, s.end - s.t) : 1;
  return `<div class="sc${read ? ' read' : ''}${expiredDim ? ' expired-dim' : ''}" style="--scp:${c3};--scd:${c2}" data-uid="${s.uid}" data-k="sc${s.id}"${active ? ` data-end="${s.end}" data-total="${total}"` : ''}><div class="h${ic ? ' hasic' : ''}" style="background:${c1}${ic ? ` url('img?u=${encodeURIComponent(ic)}') right bottom/auto 100% no-repeat` : ''}">${avatar(s.face, s.name, s.guard)}<span class="n">${esc(s.name)}</span>${active ? `<span class="left">${scLeft(s.end)}</span>` : `<span class="tm">${hhmm(s.t)}</span>`}<span class="p">¥${s.price}</span>${read ? '<span class="rdtag">已读</span>' : ''}<button class="rd" data-saysc="${s.id}" title="朗读这条">▶</button>${live ? `<button class="rd" data-read="${s.id}" title="${read ? '标成未读' : '标成已读'}">${read ? '↺' : '✓'}</button>` : ''}</div>${active ? `<div class="bar"><i style="transform:scaleX(${Math.max(0, (s.end - Date.now() / 1000) / total)})"></i></div>` : ''}<div class="m" style="background:${c2}">${esc(s.text)}</div></div>`;
};
const scLeft = end => { const sec = Math.max(0, Math.round(end - Date.now() / 1000)); return `置顶 ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`; };
// SC 已读记在自己浏览器里
let scRead = new Set();
try { scRead = new Set(JSON.parse(localStorage.getItem('xw-scread') || '[]')); } catch {}
// 管理身份的已读状态由后台记着（S.sc_read），几台设备看到的一样
const scSynced = () => !!S.admin && Array.isArray(S.sc_read);
const saveScRead = () => { try { localStorage.setItem('xw-scread', JSON.stringify([...scRead].slice(-500))); } catch {} };
// 上舰一条（2026-11-18 重做）：跟礼物一样两行（名字 / 开通了什么），右边放舰长 / 提督 / 总督的锚徽章，底色按等级淡淡地染
const guardRow = (g, i, all, withDay) => `<div class="guardrow l${g.level}" data-uid="${g.uid}" data-k="g${g.uid}-${g.t}" data-t="${g.t}">${avatar(g.face || userOf(g.uid)?.face || '', g.name, g.level)}<div class="body"><div class="n"><span class="nm">${esc(g.name)}</span>${g.source === '下播' ? '<span class="tag off" title="下播期间开通的">下播</span>' : ''}</div><div class="g" title="${hhmm(g.t)} ${esc(g.op || '开通')}${esc(g.level_name)}">${g.op ? `${esc(g.op)}了 ` : ''}<b class="lv">${esc(g.level_name)}</b> ${g.num}${esc(g.unit)} ${g.yuan == null ? '' : ` · <span class="y">${yuan(g.yuan)}</span>`}${withDay || g.source === '下播' ? ` · ${fmtMd(g.t)}` : ''}</div>${g.days > 0 ? `<div class="gd"${g.days_est ? ' title="这条是按 B 站现在的陪伴天数往回推的"' : ''}>这是 TA 陪伴你的第 <b>${g.days}</b> 天</div>` : ''}</div><img class="gbadge" src="/art/guard${g.level}.png?v=3" alt="" onerror="this.remove()"></div>`;
const rankRow = (u, i) => `<div class="row" data-uid="${u.uid}" data-k="r${u.uid}"><span class="rank r${i + 1}">${i + 1}</span>${avatar(u.face, u.name, u.guard, 26)}<span class="n">${esc(u.name)}</span>${u.guard ? `<span class="tag g${u.guard}" title="${GN[u.guard]}">${GS[u.guard]}</span>` : ''}<span class="r money">${yuan(u.spend)}</span></div>`;

