// 雾幕主页面 · 工作模式菜单、弹幕小窗、按钮、飘雪，最后开始连接
// 这几个文件按顺序加载，共用同一套全局变量。加载时只能直接用前面文件里的东西，用后面文件的函数要放进回调里
/* ---------- 工作模式菜单（画在顶栏；真正切换交给 workbench.js 里隐藏的 #workmode） ---------- */
const WM_ICON = {
  custom: '<svg viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>',
  sing: '<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M9 21h6"/></svg>',
  chat: '<svg viewBox="0 0 24 24"><path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-4.5 3.5V17H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/><path d="M8 10h8M8 13h5"/></svg>',
  moderate: '<svg viewBox="0 0 24 24"><path d="M12 3 5 6v5c0 4.6 3 8.4 7 10 4-1.6 7-5.4 7-10V6z"/><path d="m9 12 2 2 4-4"/></svg>',
};
const WM_NAME = { custom: '我的布局', sing: '唱歌', chat: '聊天', moderate: '房管' };
function drawWorkMode() {
  const v = $('workmode').value || 'custom';
  $('workmodeico').innerHTML = WM_ICON[v];
  $('workmodelbl').textContent = ' ' + WM_NAME[v];
  $('workmodebtn').classList.toggle('on', v !== 'custom');
  $('workmenu').innerHTML = ['custom', 'sing', 'chat', 'moderate'].map((k, i) => `${i === 1 ? '<hr>' : ''}<button role="menuitemradio" aria-checked="${k === v}" data-wm="${k}"${k === v ? ' class="on"' : ''}><span class="wi">${WM_ICON[k]}</span>${WM_NAME[k]}<svg class="ck" viewBox="0 0 16 16"><path d="m3.5 8.5 3 3 6-7"/></svg></button>`).join('');
}
const wmOpen = on => { $('workmenu').hidden = !on; $('workmodebtn').setAttribute('aria-expanded', on); };
$('workmodebtn').onclick = e => { e.stopPropagation(); drawWorkMode(); wmOpen($('workmenu').hidden); };
$('workmenu').onclick = e => {
  const b = e.target.closest('[data-wm]');
  if (!b) return;
  wmOpen(false);
  if ($('workmode').value === b.dataset.wm) return;
  $('workmode').value = b.dataset.wm;
  $('workmode').dispatchEvent(new Event('change'));
};
$('workmode').addEventListener('change', drawWorkMode);
document.addEventListener('click', e => { if (!e.target.closest('.wmode')) wmOpen(false); });
addEventListener('keydown', e => { if (e.key === 'Escape') wmOpen(false); });
setTimeout(drawWorkMode, 0);  // workbench.js 读完上次的模式之后再画
/* ---------- 弹幕小窗：浮在所有窗口最上面（Chrome / Edge 的画中画窗口），打游戏时放在角落 ---------- */
// 按钮在弹幕面板的标题栏里，面板搬进小窗后按 id 在主页面找不到它，先记下来
const popBtn = document.getElementById('dmpop');
function syncPop() {
  if (!pipWin) return;
  const d = pipWin.document;
  d.documentElement.dataset.theme = document.documentElement.dataset.theme;
  d.documentElement.style.cssText = document.documentElement.style.cssText;
  d.body.className = document.body.className + ' pip';
}
async function openPop() {
  if (pipWin) { popBack(); return; }
  const fallback = () => window.open(location.pathname + '?pop=1', 'xwpop', 'width=420,height=680');  // 不支持画中画的浏览器：开一个只有弹幕的普通小窗
  if (!window.documentPictureInPicture) { fallback(); return; }
  try { pipWin = await documentPictureInPicture.requestWindow({ width: 400, height: 620 }); } catch { pipWin = null; fallback(); return; }
  const d = pipWin.document, p = $('p-dm');
  d.title = '💬 弹幕';
  document.querySelectorAll('style, link[rel=stylesheet]').forEach(s => { const c = s.cloneNode(true); if (s.href) c.href = s.href; d.head.appendChild(c); });
  p.style.flex = '';
  d.body.appendChild(p);
  syncPop(); renderLayout(); stick = true; toBottom();
  popBtn.classList.add('on'); popBtn.title = '收回主窗口';
  pipPanel = p;
  pipWin.addEventListener('pagehide', popBack);
}
// 收回主窗口：弹幕面板这时还在小窗的页面里，要先把它搬回来（按 id 在主页面找不到它）。
// 小窗已经被关掉、或者引用丢了，点「收回来」也一样能恢复
let pipPanel = null;
function popBack() {
  const w = pipWin, p = pipPanel || $('p-dm');
  pipWin = null; pipPanel = null;
  if (p && p.ownerDocument !== document) $('pool').appendChild(document.adoptNode(p));
  popBtn.classList.remove('on'); popBtn.title = '弹幕小窗：浮在最上面';
  renderLayout(); stick = true; toBottom();
  try { if (w && !w.closed) w.close(); } catch {}
}
setInterval(() => { if (pipWin && pipWin.closed) popBack(); }, 2000);
popBtn.onclick = e => { e.stopPropagation(); openPop(); };
document.addEventListener('click', e => { if (e.target.closest('[data-popback]')) popBack(); });

/* ---------- 按钮 ---------- */
document.querySelectorAll('[data-g]').forEach(t => t.onclick = () => {
  giftTab = t.dataset.g; document.querySelectorAll('[data-g]').forEach(x => x.classList.toggle('on', x === t)); renderGifts();
});
document.querySelectorAll('[data-u]').forEach(t => t.onclick = () => {
  userTab = t.dataset.u; document.querySelectorAll('[data-u]').forEach(x => x.classList.toggle('on', x === t)); renderUsers();
  if (userTab === 'mute') { mutes = null; muteMsg = ''; renderUsers(); askMutes(); }
});
/* ---------- 飘雪：用 CSS 动画让显卡去挪雪花，不用每帧重画，几乎不占 CPU；设置里能关 ---------- */
let snowShown = false;
function snowOn(on) {
  if (on === snowShown) return;
  snowShown = on;
  const box = $('snow');
  box.innerHTML = on ? Array.from({ length: 18 }, () => {
    const size = (Math.random() * 3 + 2).toFixed(1), dur = (Math.random() * 10 + 12).toFixed(1);
    return `<i style="left:${(Math.random() * 100).toFixed(1)}%;width:${size}px;height:${size}px;animation-duration:${dur}s;animation-delay:-${(Math.random() * dur).toFixed(1)}s;--dx:${Math.round(Math.random() * 80 - 40)}px"></i>`;
  }).join('') : '';
}

cfg.layout = fixLayout(cfg.layout);
renderLayout();
applyCfg();
ttsUnlockHint();
showCachedView();
connect();

/* ---------- 装到桌面（2026-11-18）：Chrome / Edge 会给一个安装提示，点按钮弹出；已经装了或浏览器不支持就说怎么装 ---------- */
let pwaPrompt = null;
const pwaInstalled = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone;
addEventListener('beforeinstallprompt', e => { e.preventDefault(); pwaPrompt = e; });
addEventListener('appinstalled', () => { pwaPrompt = null; note(`装好了，桌面和开始菜单里有「${BRAND_NAME()}」`); });
$('pwabtn').onclick = async () => {
  if (pwaInstalled()) return note('现在就是桌面应用的窗口');
  if (!pwaPrompt) return note(/Edg\//.test(navigator.userAgent) ? '点地址栏右边的「安装」小图标（或右上角 ⋯ → 应用 → 将此站点作为应用安装）' : '点地址栏右边的「安装」小图标（或右上角 ⋮ → 投放、保存和分享 → 将页面安装为应用）', false);
  pwaPrompt.prompt();
  try { await pwaPrompt.userChoice; } catch {}
  pwaPrompt = null;
};
if (pwaInstalled()) document.body.classList.add('pwa');
// 第一次打开就提示一次（2026-11-18 用户要求）：只给管理链接 / 主播专属链接，普通观众链接不弹；装过了、浏览器不支持（没有安装提示）也不弹。
// 等更新公告、新手引导这些都关了再出来，点「安装」或「以后再说」都不再弹（设置 → 显示 →「装到桌面」随时能装）
let pwaAsked = true; try { pwaAsked = !!localStorage.getItem('xw-pwa-asked'); } catch {}
const pwaDone = () => { $('pwatip').hidden = true; pwaAsked = true; try { localStorage.setItem('xw-pwa-asked', '1'); } catch {} };
if (!pwaAsked && !POP && !pwaInstalled()) setTimeout(() => {
  const t0 = Date.now();
  const tw = setInterval(() => {
    if (pwaAsked) return clearInterval(tw);
    // 浏览器的安装提示事件有时不来（Chrome 有冷却期、已经装过、不是 Chrome/Edge）：最多等 6 秒，之后照样弹卡片，点「安装」改成教怎么手动装
    if ((!pwaPrompt && Date.now() - t0 < 6000) || !S.admin || document.body.classList.contains('viewer')) return;
    if (!$('tour').hidden || document.querySelector('#guide.open, #settings.open, #card.open, #hist.open, #laydlg.open, #mask.show, dialog[open]')) return;
    clearInterval(tw); $('pwatip').hidden = false;
  }, 1000);
}, 4000);
$('pwalater').onclick = pwaDone;
$('pwayes').onclick = () => {
  if (pwaPrompt) { pwaDone(); $('pwabtn').click(); return; }
  // 没有安装提示：卡片里直接写怎么装，点「知道了」再关
  const edge = /Edg\//.test(navigator.userAgent);
  $('pwatip').querySelector('.pt').innerHTML = '<b>这样装到桌面</b><small>点地址栏最右边的「安装」小图标；没有的话：' + (edge ? '浏览器右上角 ⋯ → 应用 → 将此站点作为应用安装' : '浏览器右上角 ⋮ → 投放、保存和分享 → 将页面安装为应用') + '。已经装过的，那里会显示「在应用中打开」</small>';
  $('pwalater').hidden = true; $('pwayes').textContent = '知道了'; $('pwayes').onclick = pwaDone;
};

/* ---------- 新手引导：第一次打开时圈出最常用的三个按钮，可以跳过；设置 → 显示 → 引导 能再看 ---------- */
const TOUR = [
  ['#setbtn', '设置都在这里，顶上能搜索'],
  ['#layoutbtn', '布局：加减模块；按住面板标题能挪，缝隙能拖宽窄'],
  ['#newsbtn', '功能一览：每个功能在哪，点一下带你过去'],
];
/* ---------- 每个模块自己的教学（2026-11-19）：标题栏的「?」，一步步圈出真按钮，每步一句话 ----------
   [选择器, 一句话, 先做的事（比如切到某个页签）] —— 找不到的那步自动跳过 */
const tab = sel => () => document.querySelector(sel)?.click();
// 教学里圈列表里的东西：只圈现在看得见的（2026-11-19 修：以前圈第一条弹幕，直播时早滚出去了，圈圈跑到看不见的地方）
const inView = e => { const l = e.closest('.list, #dmlist'); if (!l) return true; const a = e.getBoundingClientRect(), b = l.getBoundingClientRect(); return a.height > 0 && a.top >= b.top - 1 && a.bottom <= b.bottom + 1; };
const lastName = () => [...document.querySelectorAll('#dmlist .dm .n')].reverse().find(inView) || null;  // 最新、看得见的那条弹幕的名字
const tq = s => typeof s === 'function' ? s() : ([...document.querySelectorAll(s)].find(e => e.getClientRects().length && inView(e)) || document.querySelector(s));
const MTOUR = {
  dm: [['#dmfilter', '只看哪些弹幕'], ['#dmsearch', '搜这一场的弹幕'], ['#dmpop', '弹幕单独开个小窗'],
    [lastName, '点名字：看记录、写备注、禁言'], ['#sayinput', '在这里发弹幕'], ['#sayas', '换成自己的号发'], ['#p-dm .pgear', '字号、颜色、进房提示在这里调']],
  sc: [['#sclist .sc', 'SC 会置顶，倒计时到了自动收起'], ['#sclist [data-saysc]', '▶ 再读一遍'], ['#sclist [data-read]', '✓ 标成已读'],
    ['#scmin', '只看多少元以上'], ['#screadall', '全部标已读']],
  gift: [['#p-gift [data-g="all"]', '礼物和上舰都在这', tab('#p-gift [data-g="all"]')], ['#giftlist .gthx', '✓ 标成已感谢'],
    ['#p-gift [data-g="guard"]', '只看上舰'], ['#p-gift [data-g="rank"]', '送礼榜：本场 / 本周 / 本月'],
    ['#p-gift .pgear', '大特效、动图在这里设置', tab('#p-gift [data-g="all"]')]],
  req: [['#songinput', '打歌名，回车加进歌单', tab('#p-req [data-r="list"]')], ['#reqlist [data-sq="song_now"]', '♪ 标成正在唱'],
    ['#reqlist [data-sq="song_done"]', '✓ 唱完了'], ['#songnext', '唱完点这里，自动换下一首'], ['#songlibrary', '曲库：歌手、标签、歌词'],
    ['#p-req [data-r="song"]', '观众发「点歌 歌名」会出现在这', tab('#p-req [data-r="song"]')], ['#reqlist [data-sq="song_add"]', '＋ 加进歌单'],
    ['#reqrules', '每人能点几首、要几级粉丝牌'], ['#p-req [data-r="list"]', '回到歌单', tab('#p-req [data-r="list"]')]],
  users: [['#p-users [data-u="top"]', '现在在线的人', tab('#p-users [data-u="top"]')], ['#p-users [data-u="all"]', '这场来过的人'],
    ['#p-users [data-u="guard"]', '舰长和到期时间'], ['#p-users [data-u="mute"]', '禁言名单，能解除'], ['#p-users [data-u="top"]', '点名字看这个人', tab('#p-users [data-u="top"]')]],
};
let TOUR_STEPS = TOUR, tourKey = '', tourFollow = 0;
// 先把每一步走一遍，看看哪些在页面上真的有（有的要先切页签），只留下有的 —— 这样「第几步 / 共几步」是准的（2026-11-19 修）
function tourPlan(steps) {
  const ok = steps.filter(st => { try { st[2]?.(); } catch {} return tq(st[0])?.getClientRects().length; });
  return ok;
}
function tourStart(steps, key) {
  closeAll(); tourKey = key || '';
  setTimeout(() => { TOUR_STEPS = tourPlan(steps); tourStep(0); }, 150);
}
function moduleTour(id) { if (MTOUR[id]) tourStart(MTOUR[id], id); }
let tourI = -1;
// 把说明框放在圈出来的东西旁边，不盖住它：下面放得下放下面，不然放上面，再不行放左右
function tourPlace(el) {
  const box = $('tour'), r = el.getBoundingClientRect(), bw = box.offsetWidth, bh = box.offsetHeight, gap = 16;
  let top, left = r.left + r.width / 2 - bw / 2;
  if (r.bottom + gap + bh < innerHeight - 8) top = r.bottom + gap;
  else if (r.top - gap - bh > 8) top = r.top - gap - bh;
  else { top = Math.max(8, Math.min(innerHeight - bh - 8, r.top)); left = r.right + gap + bw < innerWidth - 8 ? r.right + gap : r.left - gap - bw; }
  box.style.top = Math.max(8, top) + 'px';
  box.style.left = Math.max(8, Math.min(innerWidth - bw - 8, left)) + 'px';
}
function spotTo(el) {  // 只挪圈圈，不重放动画
  const r = el.getBoundingClientRect(), pad = 6;
  Object.assign($('spot').style, { left: r.left - pad + 'px', top: r.top - pad + 'px', width: r.width + pad * 2 + 'px', height: r.height + pad * 2 + 'px' });
}
function tourStep(i) {
  if (i >= TOUR_STEPS.length) return tourEnd();
  const st = TOUR_STEPS[i];
  try { st[2]?.(); } catch {}
  let el = tq(st[0]);
  if (!el?.getClientRects().length) return tourStep(i + 1);  // 这一步的东西刚好没了，跳过
  tourI = i;
  const box = $('tour');
  spotlight(el, '', true);
  $('tourtxt').textContent = st[1]; $('tourn').textContent = `${i + 1} / ${TOUR_STEPS.length}`;
  $('tournext').textContent = i === TOUR_STEPS.length - 1 ? '知道了' : '下一步';
  box.hidden = false; document.body.classList.add('touring');
  tourPlace(el);
  // 弹幕、礼物一直在刷新，按钮会挪位置：每 0.25 秒看一次，圈圈和说明框跟着走；
  // 圈住的那个还在、还看得见就一直圈它（不跟着新弹幕跳来跳去），没了或滚出去了才重新找
  clearInterval(tourFollow);
  tourFollow = setInterval(() => {
    if (!el.isConnected || !el.getClientRects().length || !inView(el)) { const e = tq(st[0]); if (!e?.getClientRects().length) return; el = e; }
    spotTo(el); tourPlace(el);
  }, 250);
}
function tourEnd() {
  clearInterval(tourFollow);
  tourI = -1; $('tour').hidden = true; $('spot').classList.remove('show'); document.body.classList.remove('touring');
  if (!tourKey) { try { localStorage.setItem('xw-tour', '1'); } catch {} }
  TOUR_STEPS = TOUR; tourKey = '';
}
$('tournext').onclick = e => { e.stopPropagation(); tourStep(tourI + 1); };
$('tourskip').onclick = e => { e.stopPropagation(); tourEnd(); };
$('touropen').onclick = () => tourStart(TOUR, '');
document.addEventListener('click', e => { const b = e.target.closest('.phelp'); if (b) { e.stopPropagation(); moduleTour(b.dataset.help); } });
addEventListener('keydown', e => { if (e.key === 'Escape' && tourI >= 0) tourEnd(); });
let tourSeen = false; try { tourSeen = !!localStorage.getItem('xw-tour'); } catch {}
// 等更新公告之类的窗口都关了再出来，不跟它们叠在一起
if (!tourSeen && !POP) setTimeout(() => { const tw = setInterval(() => { if (document.querySelector('#guide.open, #settings.open, #card.open, #hist.open, #laydlg.open, #mask.show, dialog[open]')) return; clearInterval(tw); if (!document.body.classList.contains('viewer')) tourStart(TOUR, ''); }, 1000); }, 2500);  // 更新公告是 1.5 秒时弹的，引导排在它后面

/* ---------- 复制弹幕 / SC 的文字：鼠标移到那一条上，右边出来一个小按钮，点一下就复制（手机上长按文字本来就能复制） ----------
   全页只有这一个按钮，移到哪条就挂到哪条上，不给每条弹幕都多加一个按钮 */
const cpBtn = document.createElement('button');
cpBtn.className = 'cpbtn'; cpBtn.title = '复制这条的文字'; cpBtn.innerHTML = icon('copy');
// 回复按钮（2026-11-21）：跟复制按钮一样全页只有一个，挂在鼠标所在的那条弹幕上（只给管理身份，看别的直播间时没有）
const rpBtn = document.createElement('button');
rpBtn.className = 'cpbtn rpbtn'; rpBtn.title = '回复这条弹幕'; rpBtn.innerHTML = icon('reply');
document.addEventListener('mouseover', e => {
  const row = e.target.closest?.('#dmlist .dm, #sclist .sc, #hdmlist .it');
  if (row && cpBtn.parentElement !== row) row.appendChild(cpBtn);
  const dm = e.target.closest?.('#dmlist .dm:not(.dmsys)');
  if (dm && S.admin && !S.side && rpBtn.parentElement !== dm && dm.dataset.uid) dm.appendChild(rpBtn);
});
rpBtn.addEventListener('click', e => {
  e.stopPropagation();
  const row = rpBtn.parentElement; if (!row) return;
  const uid = Number(row.dataset.uid), name = row.querySelector('.n')?.textContent || '';
  setReply({ uid, name, dmid: row.dataset.dmid || '', text: rowText(row) });
});
// 文字里的小表情按 [妙] 这种写法复制，表情包大图复制它的名字
const rowText = row => {
  const el = (row.querySelector('.txt, .m') || row.querySelector('span:last-of-type')).cloneNode(true);
  el.querySelectorAll('img').forEach(im => im.replaceWith(im.alt || im.title || ''));
  el.querySelectorAll('.rep, .cpbtn, .rpbtn').forEach(x => x.remove());
  return el.textContent.trim();
};
cpBtn.addEventListener('click', async e => {
  e.stopPropagation();
  const row = cpBtn.parentElement; if (!row) return;
  const text = rowText(row);
  try { await navigator.clipboard.writeText(text); note('已复制：' + (text.length > 24 ? text.slice(0, 24) + '…' : text), true); }
  catch { note('没复制上', false); }
});

/* ---------- 切换直播间（2026-11-20）：整页切过去，弹幕、礼物、SC、上舰、观众、数字、标题都换成那个直播间的；
   网址带 ?room=房间号，后台给那个房间单独开一套（只在内存里），主播的记录、统计、OBS 都不受影响 ---------- */
// 2026-11-26：也能切到斗鱼 / 虎牙 / 抖音的直播间，网址里是 room=douyu:9999 这样；B 站还是只写房间号
const SIDE_ROOM = (v => /^\d{1,12}$/.test(v) || /^(douyu|huya|douyin):\d{1,20}$/.test(v) ? v : '')(new URLSearchParams(location.search).get('room') || '');
const xrKey = x => x.plat ? `${x.plat}:${x.room}` : String(x.room);
const XR_PLATS = [['', 'B 站'], ['douyu', '斗鱼'], ['huya', '虎牙'], ['douyin', '抖音']];
// 2026-11-21 名单放到后台：管理链接里增删、开关「普通链接也能切」，普通链接只能切名单里的（最多 10 个）
// 名字都用 B 站用户名（2026-11-20 用户要求）；管理身份切过去一次就会换成那边最新的用户名
const XR_MAX = 10;
const mainName = () => S.room?.anchor_name || ANCHOR();
const xrList = () => (S.xrooms?.rooms || []).map(x => ({ room: x.room, plat: x.plat || '', name: x.name || String(x.room) }));
const xrSend = (open, rooms) => {
  if (!S.admin || window._ws?.readyState !== 1) { note('连接还没好，等一下再试', false); return; }
  window._ws.send(JSON.stringify({ cmd: 'xrooms_set', open: !!open, rooms: rooms.slice(0, XR_MAX).map(x => ({ room: Number(x.room), name: String(x.name || '').slice(0, 40), ...(x.plat ? { plat: x.plat } : {}) })) }));
};
// 普通链接：开关开着、名单里有直播间才出现切换按钮
function xrShow() {
  const w = document.querySelector('.xrwrap');
  if (w) w.hidden = !(S.admin || (S.xrooms?.open && S.xrooms.rooms?.length));
}
function xroomGo(room) {
  room = room && room !== '0' ? String(room) : '';
  const u = new URL(location.href);
  if (room) u.searchParams.set('room', room); else u.searchParams.delete('room');
  location.href = u.toString();
}
// 收到快照后：是别的直播间就在顶上挂一条提示，藏掉只对主播有用的按钮
function sideApply() {
  const sd = S.side;
  xrShow();
  document.body.classList.toggle('side', !!sd);
  $('xroomlbl').textContent = sd ? (sd.uname || sd.room) : mainName();
  $('sidebar').hidden = !sd;
  if (!sd) return;
  // 管理身份：名单里这个直播间的名字换成 B 站现在的用户名
  const a = xrList(), i = a.findIndex(x => xrKey(x) === String(sd.room) || xrKey(x) === SIDE_ROOM);
  if (S.admin && i >= 0 && sd.uname && !sd.plat && a[i].name !== sd.uname) { a[i].name = sd.uname; xrSend(S.xrooms.open, a); }
  $('sidebar').innerHTML = `${icon('tv')}<span>正在看 ${sd.plat ? platTag(sd.plat) + ' ' : ''}<b>${esc(sd.uname || '')}</b> 的直播间 ${esc(String(sd.room).replace(/^\w+:/, ''))}（只是看，朗读和提示音先停着，回到 ${mainName()} 自动恢复）</span><button class="btn sm" id="sideback">回到 ${mainName()}</button>`;
  $('sideback').onclick = () => xroomGo(0);
  document.title = `${sd.uname || sd.room} 的直播间 · ${BRAND_NAME()}`;
}
function xroomMenu() {
  const m = $('xroommenu'), a = xrList(), adm = !!S.admin && !S.host;
  // 2026-11-26 用户：做大一点，在这里就能选平台。每个房间前面标平台；新加的先选平台再填房间号
  const plats = XR_PLATS.filter(([k]) => k !== 'douyin' || S.platforms?.douyin);
  m.innerHTML = `<div class="xrhead">切换直播间</div><button data-xr="0"${!SIDE_ROOM ? ' class="on"' : ''}>${icon('mic')}<span class="xrn">${esc(mainName())}</span><span class="tag plat p-bili">B 站</span><small>${S.room?.room_real || ''}</small></button>`
    + a.map(x => `<div class="xrrow"><button data-xr="${esc(xrKey(x))}"${SIDE_ROOM === xrKey(x) || String(S.side?.room) === xrKey(x) ? ' class="on"' : ''}>${icon('tv')}<span class="xrn">${esc(x.name)}</span>${x.plat ? platTag(x.plat) : '<span class="tag plat p-bili">B 站</span>'}<small>${x.room}</small></button>${adm ? `<button class="xrdel" data-xrdel="${esc(xrKey(x))}" title="从名单里删掉">${icon('close')}</button>` : ''}</div>`).join('')
    + (S.admin ? `<div class="xrnew"><select id="xrplat" title="哪个平台">${plats.map(([k, n]) => `<option value="${k}">${n}</option>`).join('')}</select><input id="xrinput" inputmode="numeric" placeholder="房间号" maxlength="20"><button class="btn sm" id="xrgo" title="只是自己看一下，不加进名单">看</button>${adm ? `<button class="btn sm" id="xradd" title="加进名单，普通链接也能切过去"${a.length >= XR_MAX ? ' disabled' : ''}>加到名单</button>` : ''}</div>`
      + `<div class="xrtip">抖音填 live.douyin.com/ 后面的数字；斗鱼、虎牙填房间号</div>` : '')
    + (adm ? `<label class="xropen"><span>普通链接也能切<small>名单 ${a.length}/${XR_MAX}</small></span><span class="switch"><input type="checkbox" id="xropen"${S.xrooms?.open ? ' checked' : ''}><i></i></span></label>` : '');
  m.hidden = false;
  const r = $('xroombtn').getBoundingClientRect();  // 标题栏会裁掉超出的部分，菜单用 fixed 定位贴在按钮下面
  Object.assign(m.style, { position: 'fixed', left: Math.min(r.left, innerWidth - m.offsetWidth - 8) + 'px', top: r.bottom + 6 + 'px', right: 'auto' });
  const op = $('xropen');
  if (op) op.onchange = () => xrSend(op.checked, xrList());
}
$('xroombtn').onclick = e => { e.stopPropagation(); if ($('xroommenu').hidden) xroomMenu(); else $('xroommenu').hidden = true; };
$('xroommenu').addEventListener('click', e => {
  e.stopPropagation();
  const d = e.target.closest('[data-xrdel]');
  if (d) return xrSend(S.xrooms?.open, xrList().filter(x => xrKey(x) !== d.dataset.xrdel));
  const b = e.target.closest('[data-xr]');
  if (b) return xroomGo(b.dataset.xr);
  const v = ($('xrinput')?.value || '').replace(/\D/g, ''), pl = $('xrplat')?.value || '', k = v ? (pl ? `${pl}:${v}` : v) : '';
  if (e.target.closest('#xrgo') && k) xroomGo(k);
  if (e.target.closest('#xradd') && k) {
    const a = xrList();
    if (a.some(x => xrKey(x) === k)) { note('名单里已经有了', false); return; }
    if (a.length >= XR_MAX) { note(`名单最多 ${XR_MAX} 个`, false); return; }
    xrSend(S.xrooms?.open, [...a, { room: Number(v), name: pl ? `${XR_PLATS.find(p => p[0] === pl)[1]} ${v}` : '', plat: pl }]);
  }
});
$('xroommenu').addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'xrinput') { const v = e.target.value.replace(/\D/g, ''), pl = $('xrplat')?.value || ''; if (v) xroomGo(pl ? `${pl}:${v}` : v); } });
document.addEventListener('click', e => { if (!$('xroommenu').hidden && !e.target.closest('.xrwrap')) $('xroommenu').hidden = true; });

/* ---------- 半屏（2026-11-20）：顶栏一行放不下时，从后往前把按钮收进「⋯」菜单；设置、工作模式一直留在外面 ---------- */
(() => {
  const ORDER = ['newsbtn', 'histbtn', 'obsbtn', 'preflightbtn', 'librarybtn', 'copylink', 'viewbtn', 'compactbtn', 'themebtn', 'layoutbtn', 'ttsbtn'];
  const top = document.querySelector('.top'), wrap = $('morewrap'), menu = $('moremenu'), brand = document.querySelector('.brand');
  // 每个按钮原来的位置放一个看不见的记号，收回来时放回记号后面，顺序不会乱
  const mark = new Map(ORDER.map(id => $(id)).filter(Boolean).map(el => { const c = document.createComment(el.id); el.before(c); return [el, c]; }));
  const wrapped = () => top.offsetHeight > brand.offsetHeight + 12;
  function fitTop() {
    for (const [el, c] of mark) if (el.parentNode === menu) c.after(el);
    menu.hidden = true; wrap.hidden = true; top.classList.remove('icons');
    if (innerWidth <= 640) {  // 手机（2026-11-21）：按钮挤成两行太占地方，不常用的直接收进「⋯」
      top.classList.add('icons');
      for (const id of ORDER) { const el = $(id); if (el && !['themebtn', 'viewbtn'].includes(id) && el.getClientRects().length) menu.appendChild(el); }
      wrap.hidden = !menu.children.length;
      return;
    }
    if (!wrapped()) return;
    top.classList.add('icons');  // 先去掉文字
    if (!wrapped()) return;
    wrap.hidden = false;
    for (const id of ORDER) {
      const el = $(id);
      if (!el || !el.getClientRects().length) continue;
      menu.appendChild(el);
      if (!wrapped()) break;
    }
  }
  let t = 0;
  addEventListener('resize', () => { clearTimeout(t); t = setTimeout(fitTop, 120); });
  new ResizeObserver(() => { clearTimeout(t); t = setTimeout(fitTop, 120); }).observe(top);  // 按钮显示 / 隐藏、标题变长也会重排
  $('morebtn').onclick = e => { e.stopPropagation(); menu.hidden = !menu.hidden; };
  menu.addEventListener('click', () => setTimeout(() => { menu.hidden = true; }, 0));
  document.addEventListener('click', e => { if (!menu.hidden && !e.target.closest('#morewrap')) menu.hidden = true; });
  setTimeout(fitTop, 300);
  window.fitTop = fitTop;
  // 面板标题栏放不下：加 .tight，页签换到第二行
    const over = e => e && e.getClientRects().length && e.scrollWidth > e.clientWidth + 1;
  const fitHead = h => { if (!h) return; h.classList.remove('tight'); if (over(h) || [...h.querySelectorAll('.tabs, .ttl')].some(over)) h.classList.add('tight'); };
  const ro = new ResizeObserver(es => { for (const e of es) fitHead(e.target.querySelector(':scope > header')); });
  const watch = () => document.querySelectorAll('.panel > header').forEach(h => { if (!h._fit) { h._fit = 1; ro.observe(h.parentElement); } fitHead(h); });
  setTimeout(watch, 400); addEventListener('resize', () => setTimeout(watch, 150));
  window.fitHeads = watch;
})();

/* ---------- 每个模块自己的设置（2026-11-18）：标题栏右边一个齿轮，点开就是这一栏的设置；总设置只留整体的 ---------- */
// 设置项从总设置里原样搬过来（事件都还在），所以存法、默认值都不变
const MSET = {
  // 2026-11-19 分组：弹幕、SC、礼物的设置在 index.html 里各是一页（带小标题），整页搬进齿轮
  dm: { title: '弹幕设置', pick: [() => [...($q('[data-sp="dm"]')?.children || [])]] },
  sc: { title: 'SC 设置', pick: [() => [...($q('[data-sp="sc"]')?.children || [])]] },
  gift: { title: '礼物设置', pick: [() => [...($q('[data-sp="gift"]')?.children || [])]] },
  enter: { title: '进房设置', pick: [() => $q('[data-k="fs.enter"]')?.closest('.opt')] },
  users: { title: '观众设置', pick: [() => $q('[data-k="fs.users"]')?.closest('.opt')] },
  req: { title: '点歌设置', pick: [() => $q('[data-k="fs.req"]')?.closest('.opt')] },
};
function $q(sel) { return document.querySelector(sel); }
// 2026-11-21 改版：齿轮不再弹小窗，直接打开设置窗口里这一栏的那一页
for (const [id, m] of Object.entries(MSET)) {
  const head = $('p-' + id)?.querySelector(':scope > header');
  if (!head) continue;
  if (MTOUR[id]) { const h = document.createElement('button'); h.className = 'phelp'; h.title = '这个模块怎么用'; h.innerHTML = icon('help'); h.dataset.help = id; head.appendChild(h); }
  const b = document.createElement('button');
  b.className = 'pgear'; b.title = m.title; b.innerHTML = icon('gear'); b.dataset.mset = id;
  b.onclick = e => { e.stopPropagation(); openSettings(id); };
  head.appendChild(b);  // 齿轮一律放在标题栏最右边（2026-11-18 用户要求位置统一）
}

// 主播专属链接的样子（2026-11-18）：左上角图标和浏览器标签页图标换成主播的头像
function setHostLook() {
  const logo = document.querySelector('.brand .logo');
  if (logo && !logo.querySelector('img')) logo.innerHTML = '<img src="/art/icon-256.png" alt="">';
  const fav = document.querySelector('link[rel="icon"]');
  if (fav) fav.href = "/art/icon-32.png";
}

/* ---------- 手机：一次只看一栏，底下一排按钮切换（2026-11-21） ---------- */
const MOB = matchMedia('(max-width: 700px)');
let mobTab = ''; try { mobTab = localStorage.getItem('xw-mtab') || ''; } catch {}
function mobTabs() {
  const bar = $('mtabs');
  if (!bar) return;
  const panels = [...$('main').querySelectorAll('.panel[data-id]')].filter(p => p.style.display !== 'none');
  if (!panels.length) { bar.innerHTML = ''; return; }
  if (!panels.some(p => p.dataset.id === mobTab)) mobTab = panels[0].dataset.id;
  bar.innerHTML = panels.map(p => `<button type="button" data-mt="${p.dataset.id}"${p.dataset.id === mobTab ? ' class="on"' : ''}>${icon('p-' + p.dataset.id)}<span>${esc(PANELS[p.dataset.id] || p.dataset.id)}</span></button>`).join('');
  panels.forEach(p => p.classList.toggle('mon', p.dataset.id === mobTab));
}
$('mtabs').addEventListener('click', e => {
  const b = e.target.closest('[data-mt]');
  if (!b) return;
  mobTab = b.dataset.mt;
  try { localStorage.setItem('xw-mtab', mobTab); } catch {}
  b.querySelector('i.new')?.remove();
  mobTabs();
  if (mobTab === 'dm' && typeof stick !== 'undefined' && stick) toBottom();
});
// 别的栏有新东西：底下按钮上亮个小红点（只在手机上）
function mobPing(id) {
  if (!MOB.matches || id === mobTab) return;
  const b = $('mtabs').querySelector(`[data-mt="${id}"]`);
  if (b && !b.querySelector('i.new')) b.insertAdjacentHTML('beforeend', '<i class="new"></i>');
}
{
  const _rl = renderLayout;
  renderLayout = function () { _rl.apply(this, arguments); mobTabs(); };
  mobTabs();
  MOB.addEventListener?.('change', () => { mobTabs(); if (typeof stick !== 'undefined' && stick) toBottom(); });
}
