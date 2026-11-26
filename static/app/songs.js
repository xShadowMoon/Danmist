// 雾幕主页面 · 连接状态、歌单和点歌、答谢条、发弹幕、账号登录、主题色和方案、浮动小窗（歌词 / 直播画面）、改标题
// 这几个文件按顺序加载，共用同一套全局变量。加载时只能直接用前面文件里的东西，用后面文件的函数要放进回调里
/* ---------- 连接 ---------- */
const timers = {};
const soon = (fn, key) => { if (!timers[key]) timers[key] = setTimeout(() => { timers[key] = 0; fn(); }, 300); };
function upsertUser(uid, name, face, patch) {
  if (!uid) return;
  let u = userOf(uid);
  const now = Math.floor(Date.now() / 1000);
  if (!u) { u = { uid, name, face, first: now, dm: 0, enter: 0, spend: 0, guard: 0, medal: '', last: 0 }; S.users.push(u); }
  u.name = name || u.name; if (face) u.face = face; u.last = now;
  if (patch.dm) u.dm += patch.dm; if (patch.enter) u.enter += patch.enter;
  if (patch.guard) u.guard = patch.guard; if (patch.medal) u.medal = patch.medal;
}
function putUser(u) {
  if (!u) return;
  const i = S.users.findIndex(x => x.uid === u.uid);
  if (i >= 0) S.users[i] = u; else S.users.push(u);
}
/* ---------- 点歌 & 提问 ---------- */
let reqTab = 'list';
// 歌单：提前写好的歌，唱完打勾；不跟着每场清零
/* ---------- 弹幕点歌直接放（2026-11-25）：歌单最上面一块「放歌」，正在放 + 排着的，每首标是谁点的 ---------- */
const MSTATE = { wait: '等你同意', deny: '' };
let mplayer = null;
function musicHtml() {
  const m = S.music;
  if (!m || (!m.on && !(m.list || []).some(x => ['play', 'ok', 'wait'].includes(x.state)))) return '';
  const L = m.list || [], now = L.find(x => x.state === 'play'), queue = L.filter(x => x.state === 'ok' || x.state === 'wait');
  const deny = S.admin ? L.filter(x => x.state === 'deny').slice(-3).reverse() : [];
  const who = x => `<span class="mwho">${esc(x.name)}</span>`;
  const row = (x, i) => `<div class="req mrow${x.state === 'deny' ? ' over' : ''}" data-k="m${x.id}${x.state}">${x.cover ? `<img class="mcov" src="${esc(x.cover)}" alt="" loading="lazy">` : `<span class="sn">${i}</span>`}<div class="b"><div class="s">${esc(x.title)}${x.artist ? `<small class="mart"> · ${esc(x.artist)}</small>` : ''}</div><div class="w">${who(x)}${x.state === 'wait' ? ' · <b class="mwait">等你同意</b>' : ''}${x.why ? ' · ' + esc(x.why) : ''}</div></div>`
    + (S.admin ? `${x.state === 'wait' || (x.state === 'deny' && x.sid) ? `<button class="btn sm" data-mq="music_ok" data-id="${x.id}" title="同意，排进去">✓</button>` : ''}${x.state === 'ok' && i > 1 ? `<button class="btn sm" data-mq="music_top" data-id="${x.id}" title="下一首就放">↑</button>` : ''}<button class="btn sm" data-mq="music_del" data-id="${x.id}" title="不放了">✕</button>` : '') + `</div>`;
  const pct = now && now.dur ? Math.max(0, Math.min(100, (Date.now() / 1000 + (m.skew || 0) - now.start) / now.dur * 100)) : 0;
  return `<div class="mq"><div class="mqh">${icon('music')}<b>放歌</b><small>${m.on ? (m.mode === 'app' ? '电脑上的网易云' : '网页放') : '已暂停'}</small><span class="sp"></span>${S.admin ? `<label class="chip mhere" title="这个页面也出声（不用 OBS 放歌源时开）"><input type="checkbox" id="mhere"${cfg.musicHere ? ' checked' : ''}><span>${icon('volume')}</span></label>${now ? `<button class="btn sm" data-mq="music_next" title="切歌">${icon('skip')}</button>` : ''}` : ''}</div>`
    + (now ? `<div class="req mrow mnow" data-k="m${now.id}play">${now.cover ? `<img class="mcov" src="${esc(now.cover)}" alt="">` : `<span class="sn">♪</span>`}<div class="b"><div class="s">${esc(now.title)}${now.artist ? `<small class="mart"> · ${esc(now.artist)}</small>` : ''}</div><div class="w">${who(now)} 点的</div><div class="mbar"><i style="transform:scaleX(${pct / 100})"></i></div></div></div>` : `<div class="mempty">${m.on ? '弹幕发「点歌 歌名」就会排进来' : '没在放'}</div>`)
    + queue.map((x, i) => row(x, i + 1)).join('') + deny.map(x => row(x, '')).join('') + '</div>';
}
function musicTick() {
  const m = S.music, now = m?.list?.find(x => x.state === 'play'), bar = document.querySelector('.mnow .mbar i');
  if (now && bar && now.dur) bar.style.transform = `scaleX(${Math.max(0, Math.min(1, (Date.now() / 1000 + (m.skew || 0) - now.start) / now.dur))})`;
}
setInterval(musicTick, 1000);
function musicSync() {
  if (!S.music) return;
  if (!mplayer && typeof MusicPlayer === 'function') { mplayer = new MusicPlayer(); if (typeof sinkTo === 'function') sinkTo(mplayer.audio); mplayer.blocked = () => note('浏览器不让自动出声：点一下页面再开「这页出声」', false); }
  if (mplayer) { mplayer.on = !!cfg.musicHere && !!S.admin; mplayer.update(S.music); }
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-mq]'); if (!b) return;
  e.stopPropagation();
  window._ws?.send(JSON.stringify(b.dataset.id ? { cmd: b.dataset.mq, id: b.dataset.id } : { cmd: b.dataset.mq }));
}, true);
document.addEventListener('change', e => {
  if (e.target.id !== 'mhere') return;
  cfg.musicHere = e.target.checked; saveCfg(); musicSync();
});
// 设置 → 点歌 → 弹幕点歌直接放
const MSRC = { '163': '网易云', qq: 'QQ 音乐' };
let mqr = { src: '', key: '', t: 0 };
function drawMusicSet() {
  const R = S.music_rules, box = $('msetbox');
  if (!box) return;
  box.hidden = !R;
  if (!R) return;
  box.querySelectorAll('[data-mr]').forEach(el => {
    if (document.activeElement === el) return;
    const v = R[el.dataset.mr];
    if (el.type === 'checkbox') el.checked = !!v; else el.value = String(v ?? '');
  });
  box.querySelectorAll('[data-mseg]').forEach(sg => sg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.val === String(R[sg.dataset.mseg]))));
  const lg = R.login || {}, src = R.src;
  $('mlogin').innerHTML = lg[src] ? `<span class="mlg">${esc(lg[src])}</span><button class="btn sm" data-mlogout="${src}">退出</button>`
    : `<button class="btn sm" data-mlogin="${src}">${icon('phone')} 扫码登录${MSRC[src]}</button><button class="btn sm" data-mcookie="${src}" title="扫码登不上时用：在电脑浏览器登录${MSRC[src]}网页版，按 F12 → 应用/存储 → Cookie，复制${src === '163' ? ' MUSIC_U' : ' uin 和 qqmusic_key'}粘进来">粘贴登录信息</button>`
      + `<small class="mtip">${R.mode === 'app' && src === '163' ? '「电脑上的网易云」用客户端自己的登录，这里可以不登' : '不登录只能放免费的歌'}</small>`;
  $('mobsurl').value = location.origin + location.pathname.replace(/[^/]*$/, '') + 'obs-music';
}
function sendRules(patch) { window._ws?.send(JSON.stringify({ cmd: 'music_rules', ...patch })); }
document.addEventListener('change', e => {
  const el = e.target.closest('#msetbox [data-mr]'); if (!el) return;
  const k = el.dataset.mr;
  sendRules({ [k]: el.type === 'checkbox' ? el.checked : k === 'skip' ? el.value : Math.max(0, Math.min(k === 'max' ? 20 : 100, parseInt(el.value, 10) || 0)) });
});
document.addEventListener('click', e => {
  const sb = e.target.closest('#msetbox [data-mseg] button');
  if (sb) { sendRules({ [sb.parentElement.dataset.mseg]: sb.dataset.val }); return; }
  const li = e.target.closest('[data-mlogin]');
  if (li) { mqr = { src: li.dataset.mlogin, key: '', t: 0 }; window._ws?.send(JSON.stringify({ cmd: 'music_qr', src: mqr.src })); return; }
  const mc = e.target.closest('[data-mcookie]');
  if (mc) {
    const v = prompt(mc.dataset.mcookie === '163' ? '粘贴网易云的 Cookie（整段，或者只粘 MUSIC_U 的值）' : '粘贴 QQ 音乐的 Cookie（要有 uin 和 qqmusic_key）');
    if (v && v.trim()) { mqr = { src: mc.dataset.mcookie, key: '', t: 0 }; window._ws?.send(JSON.stringify({ cmd: 'music_cookie', src: mc.dataset.mcookie, cookie: v.trim() })); }
    return;
  }
  const lo = e.target.closest('[data-mlogout]');
  if (lo) { window._ws?.send(JSON.stringify({ cmd: 'music_logout', src: lo.dataset.mlogout })); return; }
  if (e.target.id === 'mobscopy') navigator.clipboard?.writeText($('mobsurl').value).then(() => note('已复制，OBS → 来源 ＋ → 浏览器 → 粘贴', true)).catch(() => $('mobsurl').select());
});
function musicLoginResult(d) {
  const box = $('mqrbox');
  clearTimeout(mqr.t);
  if (d.cmd === 'music_qr' && d.ok) {
    mqr.key = d.key;
    box.innerHTML = `<div class="mqr">${d.svg || `<img src="${d.png}" alt="">`}<div>${esc(d.msg)}</div></div>`;
    box.hidden = false;
  } else if (d.cmd === 'music_poll' && box.querySelector('.mqr > div')) box.querySelector('.mqr > div').textContent = d.msg;
  if (!d.ok || ['ok', 'expired', 'fail', 'out'].includes(d.state)) {
    if (d.state === 'ok' || d.state === 'out') box.hidden = true;
    else { box.innerHTML = `<div class="mqr"><div>${esc(d.msg)}</div><button class="btn sm" data-mlogin="${esc(d.src || mqr.src)}">换一张</button></div>`; box.hidden = false; }
    note(d.msg, d.ok && d.state !== 'fail' && d.state !== 'expired');
    return;
  }
  mqr.t = setTimeout(() => window._ws?.send(JSON.stringify({ cmd: 'music_poll', src: mqr.src, key: mqr.key })), 2000);
}
/* ---------- 其他平台（2026-11-25）：斗鱼、虎牙的直播间，弹幕收进来标上平台 ---------- */
const PLAT_LABEL = { douyu: '斗鱼', huya: '虎牙', douyin: '抖音' };
function platTag(p) { return PLAT_LABEL[p] ? `<span class="tag plat p-${p}" title="${PLAT_LABEL[p]}直播间">${PLAT_LABEL[p]}</span>` : ''; }
function drawPlats() {
  const box = $('platbox'), P = S.platforms;
  if (!box) return;
  box.hidden = !P;
  if (!P) return;
  // 抖音（2026-11-26）：在这台电脑上开一个看不见的浏览器窗口读直播间网页；只有 Windows + Edge / Chrome 才有
  const dy = $('platsel').querySelector('option[value="douyin"]');
  if (P.douyin && !dy) $('platsel').insertAdjacentHTML('beforeend', '<option value="douyin">抖音</option>');
  if (!P.douyin && dy) dy.remove();
  $('platlist').innerHTML = (P.rooms || []).map((r, i) => `<div class="lkrow"><div>${platTag(r.plat)} <b>${esc(r.room)}</b><small${r.warn ? ' class="plwarn"' : ''}>${esc(r.state || '')}</small></div>${r.plat === 'douyin' ? `<button class="btn sm" data-plshow="${i}" title="把抖音那个浏览器窗口拿出来：登录（不登录名字会打码）、过验证">显示窗口</button><button class="btn sm" data-plhide="${i}">藏起来</button>` : ''}<label class="chip"><input type="checkbox" data-plon="${i}"${r.on ? ' checked' : ''}><span>收</span></label><button class="btn sm" data-pldel="${i}">删掉</button></div>`).join('')
    || '<div class="empty" style="padding:8px">还没加。同时在别的平台开播时，把那边的房间号加进来</div>';
}
function sendPlats(rooms) { window._ws?.send(JSON.stringify({ cmd: 'plat_set', rooms: rooms.map(r => ({ plat: r.plat, room: r.room, on: r.on })) })); }
$('platadd')?.addEventListener('click', () => {
  const room = $('platroom').value.trim(); if (!room) return;
  sendPlats([...(S.platforms?.rooms || []), { plat: $('platsel').value, room, on: true }]); $('platroom').value = '';
});
$('platlist')?.addEventListener('change', e => { const i = e.target.dataset.plon; if (i == null) return; const R = [...(S.platforms?.rooms || [])]; R[i] = { ...R[i], on: e.target.checked }; sendPlats(R); });
$('platlist')?.addEventListener('click', e => { const s = e.target.closest('[data-plshow],[data-plhide]'); if (s) { const r = (S.platforms?.rooms || [])[Number(s.dataset.plshow ?? s.dataset.plhide)]; if (r) window._ws?.send(JSON.stringify({ cmd: 'plat_show', plat: r.plat, room: r.room, show: s.dataset.plshow != null })); return; } });
$('platlist')?.addEventListener('click', e => { const b = e.target.closest('[data-pldel]'); if (!b) return; sendPlats((S.platforms?.rooms || []).filter((_, i) => i !== Number(b.dataset.pldel))); });
function renderSongs() {
  const all = S.songs || [], left = all.filter(x => !x.done).length;
  const lyr = new Set(S.admin ? (S.library || []).filter(r => r.lyrics).map(r => r.name.toLowerCase()) : []);
  followLyrics();
  const grouped = cfg.songGroup === 'artist' || cfg.songGroup === 'tag';
  const row = (x, i) => `<div class="req${x.done ? ' done' : ''}${x.now ? ' now' : ''}" data-k="s${x.id}${x.now ? 'n' : ''}"${!x.done && !x.now ? ` data-pend="${x.id}"` : ''}><span class="sn${S.admin && !grouped && !x.done && !x.now ? ' grip" title="按住拖动排序' : ''}">${x.done ? '✓' : x.now ? '♪' : i + 1}</span><div class="b"><div class="s">${esc(x.name)}</div>${x.now ? '<small class="nowtag">正在唱</small>' : x.done ? '<small class="donetag">已唱</small>' : ''}</div>${!x.done && lyr.has(x.name.toLowerCase()) ? `<button class="btn sm" data-lyr="${esc(x.name)}" title="歌词提词小窗">${icon('lyrics')}</button>` : ''}${S.admin && !x.done ? `<button class="btn sm${x.now ? ' on' : ''}" data-sq="song_now" data-id="${x.id}" title="${x.now ? '取消「正在唱」' : '标成正在唱（OBS 歌单会高亮）'}">♪</button>` : ''}${S.admin ? `<button class="btn sm" data-sq="song_done" data-done="${!x.done}" data-id="${x.id}" title="${x.done ? '改回没唱' : '唱完了'}">${x.done ? '↩' : '✓'}</button><button class="btn sm" data-sq="song_del" data-id="${x.id}" title="删掉">✕</button>` : ''}</div>`;
  const pend = all.filter(x => !x.done && !x.now);
  let body;
  if (grouped && pend.length) {
    // 分组：正在唱的在最上面，没唱的按歌手 / 第一个标签分组（点组名收起、展开），唱完的在最下面；分组时不能拖动排序
    const keyOf = x => (cfg.songGroup === 'artist' ? x.artist : (x.tags || [])[0]) || '其他';
    const groups = new Map();
    pend.forEach((x, i) => { const k = keyOf(x); if (!groups.has(k)) groups.set(k, []); groups.get(k).push([x, i]); });
    const names = [...groups.keys()].sort((p, q) => (p === '其他') - (q === '其他'));
    body = all.filter(x => x.now).map(row).join('')
      + names.map(k => `<div class="sgrp${songFold.has(k) ? ' fold' : ''}" data-sgrp="${esc(k)}" data-k="grp${esc(k)}${songFold.has(k) ? 'f' : ''}"><b>${esc(k)}</b><small>${groups.get(k).length}</small></div>`
        + (songFold.has(k) ? '' : groups.get(k).map(([x, i]) => row(x, i + 1)).join(''))).join('')
      + all.filter(x => x.done).map(row).join('');
  } else {
    const sorted = [...all.filter(x => x.now), ...pend, ...all.filter(x => x.done)];  // 正在唱的排最上面
    body = sorted.map(row).join('');
  }
  const mq = musicHtml();
  setList($('reqlist'), mq + (all.length ? body
    + (S.admin ? `<div style="text-align:center;padding:8px;display:flex;gap:6px;justify-content:center">${all.some(x => x.done) ? '<button class="btn sm" data-sq="song_clear" data-id="done">清掉唱完的</button>' : ''}<button class="btn sm" data-sq="song_clear" data-id="all">清空</button></div>` : '')
    : mq ? '' : `<div class="empty xw">暂无${S.admin ? '<br><small>可以一次粘贴多行</small>' : ''}</div>`));
}
// 歌单拖动排序：按住序号拖到想要的位置（只在没唱的歌之间挪；唱完的自动变灰沉到最下面）
$('reqlist').addEventListener('pointerdown', e => {
  const grip = e.target.closest('.grip'), row = grip?.closest('[data-pend]');
  if (!row || e.button > 0) return;
  e.preventDefault();
  const list = $('reqlist'), id = row.dataset.pend;
  let before = null;  // 挪到哪一首前面；'' = 最后
  const clear = () => list.querySelectorAll('.dropb, .dropa').forEach(x => x.classList.remove('dropb', 'dropa'));
  const move = ev => {
    row.classList.add('dragging'); document.body.classList.add('fdrag');
    const rows = [...list.querySelectorAll('[data-pend]')].filter(x => x !== row);
    clear();
    const hit = rows.find(x => { const r = x.getBoundingClientRect(); return ev.clientY < r.top + r.height / 2; });
    if (hit) { hit.classList.add('dropb'); before = hit.dataset.pend; }
    else if (rows.length) { rows[rows.length - 1].classList.add('dropa'); before = ''; }
    // 靠近上下边时自己滚
    const lr = list.getBoundingClientRect();
    if (ev.clientY < lr.top + 30) list.scrollTop -= 12; else if (ev.clientY > lr.bottom - 30) list.scrollTop += 12;
  };
  const up = () => {
    removeEventListener('pointermove', move); removeEventListener('pointerup', up); removeEventListener('pointercancel', up);
    row.classList.remove('dragging'); document.body.classList.remove('fdrag'); clear();
    if (before === null) return;
    const order = [...list.querySelectorAll('[data-pend]')].map(x => x.dataset.pend), i = order.indexOf(id);
    if ((before === '' && i === order.length - 1) || order[i + 1] === before) return;  // 没挪地方
    window.sendWorkbench?.({ cmd: 'song_move', id, before });
  };
  addEventListener('pointermove', move); addEventListener('pointerup', up); addEventListener('pointercancel', up);
});
// 歌单分组：收起来的组记在这里（刷新页面就都展开）
const songFold = new Set();
$('reqlist').addEventListener('click', e => {
  const g = e.target.closest('[data-sgrp]');
  if (!g) return;
  const k = g.dataset.sgrp;
  songFold.has(k) ? songFold.delete(k) : songFold.add(k);
  renderSongs();
});
$('songgroup').onchange = e => { cfg.songGroup = e.target.value; saveCfg(); renderReqs(); };
// SC 只看多少元以上
$('scmin').onchange = e => { cfg.sc.min = Number(e.target.value) || 0; saveCfg(); renderSc(); };
// 复制普通链接：发给别人看的网址（不带管理身份）
$('copylink').onclick = async () => {
  const url = (S.public_url || location.origin + location.pathname).replace(/[?#].*$/, '');
  try { await navigator.clipboard.writeText(url); note('已复制普通链接：' + url, true); }
  catch { note('没复制上，手动复制：' + url, false); }
};
/* ---------- 链接：普通链接、管理链接（有效期、作废、换新）。管理链接的明文只在新建那一下给一次 ---------- */
const sendLink = o => window._ws?.readyState === 1 && window._ws.send(JSON.stringify(o));
const dayStr = t => { const d = new Date(t * 1000); return `${d.getMonth() + 1}月${d.getDate()}日`; };
function drawLinks() {
  if (!S.admin) return;
  $('lk-public').value = (S.public_url || S.lan?.url || location.origin + location.pathname).replace(/[?#].*$/, '');
  // 手机打开（2026-11-25）：有外网地址的（比如隧道）不需要这一块
  $('lk-lanbox').hidden = !!S.public_url;
  $('lk-lan').checked = !!S.lan?.on;
  $('lk-lanrow').hidden = $('lk-lantip').hidden = !S.lan?.url;
  $('lk-lanurl').value = S.lan?.url ? S.lan.url + '/' : '';
  const c = S.connections;
  $('lk-online').textContent = c ? `${c.public} 人${c.obs ? ` · OBS ${c.obs}` : ''}` : '-';
  $('copylink').title = `复制普通链接：发给别人看的那个网址${c ? `（现在 ${c.public} 人在看）` : ''}`;
  const now = Date.now() / 1000, L = (S.admin_links || []).filter(x => x.active);
  $('lk-list').innerHTML = L.length ? L.map(x => `<div class="lkrow"><div><b>${esc(x.name || (x.host ? '主播专属' : '管理链接'))}</b>${x.host ? '<span class="tag">主播专属</span>' : ''}${x.current ? '<span class="tag">这台</span>' : ''}${x.host ? `<small>打开 ${x.opens || 0} 次${(x.open_log || []).length ? ' · 最近 ' + (x.open_log || []).slice(-3).reverse().map(t => bjTime(t)).join('、') : ''}</small>${x.host ? openSrcHtml(x) : ''}` : ''}<small>${x.expires_at ? `${dayStr(x.expires_at)} 到期` : '长期'}${x.last_used_at ? ` · ${now - x.last_used_at < 3600 ? '刚用过' : dayStr(x.last_used_at) + ' 用过'}` : ' · 没用过'}</small></div><button class="btn sm" data-lkdel="${x.id}" title="作废：用这个链接的人马上进不来">作废</button></div>`).join('')
    : '<div class="empty" style="padding:10px">没有管理链接<br><small>在这台电脑上直接打开不需要链接</small></div>';
}
// 打开记录用：北京时间、国家代码转中文（2026-11-19）
// 时间按看网页这台设备的时区显示（2026-11-19 用户要求，原来固定北京时间）
const bjTime = t => new Date(t * 1000).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
// 主播专属链接的打开记录：一直有入口；有来源的列 IP / 地区 / 设备，加这功能之前的那几次只有时间
function openSrcHtml(x) {
  const src = x.open_src || [], have = new Set(src.map(o => o.t));
  const rows = [...src, ...(x.open_log || []).filter(t => !have.has(t)).map(t => ({ t, old: true }))].sort((a, b) => b.t - a.t);
  const del = o => `<button class="lkdel" data-lkopen="${x.id}" data-t="${o.t}" title="删掉这条（比如是自己测试时打开的）">${icon('close')}</button>`;
  const body = rows.length ? rows.map(o => o.old ? `<div><span>${bjTime(o.t)}</span><span class="old">这次没记来源（加记录功能之前）</span>${del(o)}</div>`
    : `<div><span>${bjTime(o.t)}</span><span>${esc(ccName(o.cc) + (o.region ? ' ' + o.region : '') + (o.city ? ' ' + o.city : '')) || '-'}</span><span class="ip">${esc(o.ip || '')}</span>${del(o)}<span>${esc(o.dev || '')}</span></div>`).join('')
    : '<div><span class="old">还没有记录</span></div>';
  return `<details class="lksrc"><summary>打开记录（${rows.length}）</summary>${body}</details>`;
}
const CC = { CN: '中国', HK: '中国香港', TW: '中国台湾', MO: '中国澳门', US: '美国', JP: '日本', KR: '韩国', SG: '新加坡', MY: '马来西亚', GB: '英国', CA: '加拿大', AU: '澳大利亚', DE: '德国', FR: '法国', NZ: '新西兰', TH: '泰国', VN: '越南', PH: '菲律宾', ID: '印度尼西亚', RU: '俄罗斯', IN: '印度', NL: '荷兰', IT: '意大利', ES: '西班牙', XX: '未知', T1: 'Tor' };
const ccName = cc => cc ? (CC[cc] || cc) : '';
document.addEventListener('click', e => {
  const b = e.target.closest('[data-lkopen]');
  if (!b) return;
  e.preventDefault();
  sendLink({ cmd: 'admin_link_open_del', id: b.dataset.lkopen, t: Number(b.dataset.t) });
});
function linkResult(d) {
  if (!d.ok) { note(d.msg, false); return; }
  if (d.links) { S.admin_links = d.links; drawLinks(); }
  if (d.url) {  // 新建 / 换新：明文只有这一次，先复制到剪贴板，再放进一个不会自己关的小窗
    $('lkboxurl').value = d.url; $('lkbox').hidden = false;
    $('lkboxqr').innerHTML = d.qr || ''; $('lkboxqr').hidden = !d.qr;  // 手机扫这个码直接打开
    navigator.clipboard?.writeText(d.url).then(() => note('新的管理链接已复制', true)).catch(() => {});
  }
}
$('stabs').addEventListener('click', e => { if (e.target.closest('[data-st="link"]')) sendLink({ cmd: 'admin_link_list' }); });
$('lk-copy').onclick = () => $('copylink').click();
$('lk-lan').onchange = e => window._ws?.send(JSON.stringify({ cmd: 'lan_set', on: e.target.checked }));
$('lk-lancopy').onclick = () => navigator.clipboard?.writeText($('lk-lanurl').value).then(() => note('已复制', true)).catch(() => $('lk-lanurl').select());
$('lk-new').onclick = () => { sendLink({ cmd: 'admin_link_create', name: $('lk-name').value.trim(), days: Number($('lk-days').value), host: $('lk-host').checked }); $('lk-name').value = ''; $('lk-host').checked = false; };
$('lk-list').onclick = e => {
  const b = e.target.closest('[data-lkdel]'); if (!b) return;
  if (b.dataset.arm !== '1') { b.dataset.arm = '1'; b.textContent = '再点一次'; setTimeout(() => { b.dataset.arm = ''; b.textContent = '作废'; }, 3000); return; }
  sendLink({ cmd: 'admin_link_revoke', id: b.dataset.lkdel });
};
let rotateArm = 0;
$('lk-rotate').onclick = () => {
  if (Date.now() - rotateArm > 3000) { rotateArm = Date.now(); $('lk-rotate').textContent = '再点一次：全部作废'; setTimeout(() => { $('lk-rotate').textContent = '全部作废，换新的'; }, 3000); return; }
  rotateArm = 0; sendLink({ cmd: 'admin_link_rotate', name: $('lk-name').value.trim(), days: Number($('lk-days').value) });
};
$('lkboxclose').onclick = () => { $('lkbox').hidden = true; $('lkboxurl').value = ''; $('lkboxqr').innerHTML = ''; };
$('lkboxcopy').onclick = () => navigator.clipboard?.writeText($('lkboxurl').value).then(() => note('已复制', true)).catch(() => { $('lkboxurl').select(); });
/* ---------- 禁言名单（观众栏的「禁言」页签）：现查现看，点两下解除。查名单 5 秒内只能查一次 ---------- */
let mutes = null, muteMsg = '', muteAt = 0, muteT = 0;
function askMutes() {
  if (!S.admin || userTab !== 'mute') return;
  clearTimeout(muteT);
  const wait = 5300 - (Date.now() - muteAt);
  if (wait > 0) { muteT = setTimeout(askMutes, wait); return; }
  muteAt = Date.now();
  window._ws?.send(JSON.stringify({ cmd: 'mute_list', acct: sayAcct() }));
}
function renderMutes() {
  const el = $('userlist');
  if (muteMsg) { setList(el, `<div class="empty">${esc(muteMsg)}<br><button class="btn sm" data-mutes>再查一次</button></div>`); return; }
  if (!mutes) { setList(el, '<div class="empty">正在查…</div>'); return; }
  setList(el, mutes.items.length ? mutes.items.map(m => `<div class="row" data-k="mu${esc(m.id)}"><span class="n">${esc(m.name)}</span><span class="r" style="margin-left:auto">${esc(m.until_text || '')}</span><button class="btn sm" data-unmute="${esc(m.id)}" title="解除禁言">解除</button></div>`).join('')
    + (mutes.truncated ? `<div class="empty" style="padding:8px"><small>一共 ${mutes.total} 人，只列了前 ${mutes.items.length} 个</small></div>` : '')
    : '<div class="empty">现在没有人被禁言</div>');
}
function muteResult(d) {
  if (d.cmd === 'mute_list') {
    if (d.ok) { mutes = d.mutes; muteMsg = ''; } else { muteMsg = d.msg || '没查到'; }
    if (userTab === 'mute') renderUsers();
  } else note(d.msg, d.ok);
}
$('userlist').addEventListener('click', e => {
  if (e.target.closest('[data-mutes]')) { muteMsg = ''; mutes = null; renderUsers(); askMutes(); return; }
  const b = e.target.closest('[data-unmute]'); if (!b) return;
  e.stopPropagation();
  if (b.dataset.arm !== '1') { b.dataset.arm = '1'; b.textContent = '再点一次'; setTimeout(() => { b.dataset.arm = ''; b.textContent = '解除'; }, 3000); return; }
  window._ws?.send(JSON.stringify({ cmd: 'unmute', id: b.dataset.unmute, acct: sayAcct() }));
});
function drawReqHead() {
  const all = S.reqs || [], todo = k => all.filter(r => r.kind === k && !r.done && !r.over).length, songs = S.songs || [];
  $('reqn').textContent = reqTab === 'list' ? (songs.length ? `${songs.filter(x => x.done).length}/${songs.length}` : '') : (todo(reqTab) || '');
  $('songadd').style.display = reqTab === 'list' ? '' : 'none';
  $('songgroup').style.display = reqTab === 'list' ? '' : 'none';
  $('songgroup').value = cfg.songGroup || '';
  $('scmin').value = String(cfg.sc.min || 0);
  $('reqrules').style.display = reqTab === 'song' && S.admin ? '' : 'none';
  const R = S.req_rules || {};
  for (const [id, k] of [['rr-max', 'max'], ['rr-medal', 'medal']]) if (document.activeElement !== $(id)) $(id).value = R[k] || 0;
}
$('reqrules').addEventListener('change', () => {
  const n = (id, hi) => Math.max(0, Math.min(hi, parseInt($(id).value, 10) || 0));
  window._ws?.send(JSON.stringify({ cmd: 'req_rules', max: n('rr-max', 50), medal: n('rr-medal', 40) }));
});
$('songinput').addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.isComposing || !e.target.value.trim()) return;
  window.queueSongInput?.(e.target.value);
});
// 歌单联想：输几个字，列出以前加过 / 唱过的歌（唱过几次、上次哪天），点一下就加进歌单
function drawSug() {
  const box = $('songsug'), q = $('songinput').value.trim().toLowerCase();
  const inList = new Set((S.songs || []).filter(x => !x.done).map(x => x.name));
  const hits = q ? (S.songbook || []).filter(b => b[0].toLowerCase().includes(q) && !inList.has(b[0])).sort((a, b) => (b[2] - a[2]) || (b[1] - a[1])).slice(0, 6) : [];
  box.innerHTML = hits.map(b => `<button data-sug="${esc(b[0])}"><b>${esc(b[0])}</b><small>${b[1] ? `唱过 ${b[1]} 次 · 上次 ${fmtDay(b[2]).replace(/ 周.$/, '')}` : '还没唱过'}</small></button>`).join('');
  box.classList.toggle('show', hits.length > 0);
}
$('songinput').addEventListener('input', drawSug);
$('songinput').addEventListener('focus', drawSug);
$('songinput').addEventListener('blur', () => setTimeout(() => $('songsug').classList.remove('show'), 200));
$('songsug').addEventListener('mousedown', e => {
  const b = e.target.closest('[data-sug]');
  if (!b) return;
  e.preventDefault();
  window.queueSongInput?.(b.dataset.sug);
});
$('songinput').addEventListener('paste', e => {  // 粘贴一整段歌单：一行一首
  const text = (e.clipboardData || window.clipboardData).getData('text');
  if (!/[\r\n]/.test(text)) return;
  e.preventDefault(); window.queueSongInput?.(text);
});
document.addEventListener('click', e => {
  const b = e.target.closest('[data-sq]');
  if (!b) return;
  e.stopPropagation();
  window.sendWorkbench?.({ cmd: b.dataset.sq, id: b.dataset.id || '', text: b.dataset.text || '', req_id: b.dataset.reqId || '', ...(b.dataset.done ? {done: b.dataset.done === 'true'} : {}) });
}, true);
function renderReqs() {
  drawReqHead();
  if (reqTab === 'list') return renderSongs();
  const all = S.reqs || [], list = all.filter(r => r.kind === reqTab);
  // 没处理的在上面（先来的排前面），勾掉的沉到下面
  const sorted = [...list.filter(r => !r.done && !r.over), ...list.filter(r => !r.done && r.over), ...list.filter(r => r.done).reverse()];
  setList($('reqlist'), sorted.length ? sorted.map(r => `<div class="req${r.done ? ' done' : ''}${r.over ? ' over' : ''}" title="${r.over ? esc(r.over) + '（还是可以手动加进歌单）' : ''}" data-uid="${r.uid}" data-k="q${r.id}">${avatar(r.face, r.name, r.guard, 24)}<div class="b"><div class="s">${esc(r.kind === 'song' ? r.song : r.text)}${r.over ? ` <small class="overtag">${esc(r.over)}</small>` : ''}</div><div class="w">${r.fans?.length ? `<b style="color:var(--money-ink)">${r.fans.length + 1} 人点</b> · ${esc([r.name, ...r.fans.map(f => f.name)].slice(0, 3).join('、'))}${r.fans.length > 2 ? ' 等' : ''}` : esc(r.name)} · ${hhmm(r.t)}${r.kind === 'song' && !r.fans?.length ? ' · ' + esc(r.text) : ''}</div></div>${S.admin ? `${r.kind === 'song' ? `<button class="btn sm" data-sq="song_add" data-req-id="${r.id}" data-text="${esc(r.song)}" title="关联请求并加进歌单">${r.queued_id ? '已排' : '＋'}</button>` : ''}<button class="btn sm" data-rq="req_done" data-id="${r.id}" title="${r.done ? '改回没处理' : reqTab === 'song' ? '唱完了' : '回答了'}">${r.done ? '↺' : '✓'}</button><button class="btn sm" data-rq="req_del" data-id="${r.id}" title="删掉">✕</button>` : ''}</div>`).join('')
    + (S.admin && list.some(r => r.done) ? `<div style="text-align:center;padding:8px"><button class="btn sm" data-rq="req_clear">清掉已经勾掉的</button></div>` : '')
    : `<div class="empty xw">${reqTab === 'song' ? '暂无<br><small>弹幕发「点歌 歌名」</small>' : '还没有人提问～'}</div>`);
}
document.querySelectorAll('[data-r]').forEach(t => t.onclick = () => {
  reqTab = t.dataset.r; document.querySelectorAll('[data-r]').forEach(x => x.classList.toggle('on', x === t)); renderReqs();
});
document.addEventListener('click', e => {
  const b = e.target.closest('[data-rq]');
  if (!b) return;
  e.stopPropagation();
  window._ws?.send(JSON.stringify({ cmd: b.dataset.rq, id: b.dataset.id || '', kind: reqTab }));
}, true);

/* ---------- 超管警告 / 切断（2026-11-19）：顶上红条，一直挂着，点 ✕ 才关；响一声（不管提示音开没开） ---------- */
function showWarn(w) {
  const box = $('warnbar');
  box.innerHTML = `<span>${icon('ban')}</span><b>${w.kind === 'cut' ? '直播被 B 站切断了' : 'B 站超管警告'}</b><span class="t">${esc(w.msg || '')}</span><small>${hhmm(w.t)}</small><button class="btn sm" title="知道了">✕</button>`;
  box.hidden = false;
  box.querySelector('button').onclick = () => { box.hidden = true; };
  try { ding([880, 659.25, 880, 659.25], 0.8); } catch {}
}
/* ---------- 发弹幕（管理身份）：交给机器人的弹幕助手去发 ---------- */
let noteT;
function note(text, ok = true) {
  let n = $('note');
  if (!n) { n = document.createElement('div'); n.id = 'note'; document.body.append(n); }
  n.textContent = text; n.className = 'show' + (ok ? '' : ' bad');
  clearTimeout(noteT); noteT = setTimeout(() => n.className = '', 4000);
}
// 回复某条弹幕（2026-11-21）：发送框左边出来「回复 谁 ✕」。用自己的号发：B 站上是真的回复（带回复标记）；
// 默认账号（机器人那边发）做不了真的回复，就在前面加「@名字」
let replyTo = null;
function setReply(r) { replyTo = r; drawReply(); $('sayinput').focus(); }
function drawReply() {
  let chip = $('replychip');
  if (!chip) { chip = document.createElement('span'); chip.id = 'replychip'; $('sayinput').before(chip); }
  chip.hidden = !replyTo;
  $('sayinput').placeholder = replyTo ? (sayAcct() ? `回复 ${replyTo.name}` : `@${replyTo.name}（换成自己的号发才是真的回复）`) : '发弹幕';
  if (!replyTo) return;
  chip.title = replyTo.text ? '回复：' + replyTo.text : '';
  chip.innerHTML = `${icon('reply')}<b>${esc(replyTo.name)}</b><button type="button" title="不回复了">✕</button>`;
  chip.querySelector('button').onclick = () => { replyTo = null; drawReply(); };
}
function sendSay() {
  const text = $('sayinput').value.trim();
  if (!text) return;
  if (window._ws?.readyState !== 1) { note('已断开，稍后再发', false); return; }
  const msg = { cmd: 'say', text, acct: sayAcct() };
  if (replyTo) {
    if (msg.acct) { msg.reply_uid = replyTo.uid; if (replyTo.dmid) msg.reply_dmid = replyTo.dmid; }
    else if (!text.startsWith('@' + replyTo.name)) msg.text = `@${replyTo.name} ${text}`.slice(0, 40);
  }
  window._ws.send(JSON.stringify(msg));
  replyTo = null; drawReply();
}
$('saybtn').onclick = sendSay;
$('sayinput').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) sendSay(); });

/* ---------- 用自己的 B 站号发（每个浏览器各登各的；浏览器里只存一串口令，登录信息在电脑上） ---------- */
let acct = null;  // { token, uname, uid, use }，use = true 表示用自己的号发
try { acct = JSON.parse(localStorage.getItem('xw-acct') || 'null'); } catch {}
const saveAcct = () => { try { acct ? localStorage.setItem('xw-acct', JSON.stringify(acct)) : localStorage.removeItem('xw-acct'); } catch {} };
const sayAcct = () => acct?.use ? acct.token : '';
function drawSayAs() {
  const me = acct?.use, r = S.room || {};
  const name = me ? acct.uname || '我的号' : r.bot_name || '默认账号', face = me ? acct.face : r.bot_face;
  const k = name + '|' + (face || ''), b = $('sayas');
  if (b.dataset.k === k) return;
  b.dataset.k = k; b.title = '换账号';
  b.innerHTML = `${avatar(face, name, 0, 20)}<span class="sn">${esc(name)}</span>`;
}
let qrKey = '', qrTimer = 0;
function acctDialog(state = {}) {
  clearInterval(qrTimer);
  const box = $('card');
  box.innerHTML = `<div class="head"><span class="av" style="background:#7fb3dd">${icon('key')}</span><div><div class="nm">发弹幕的账号</div><div class="sub">仅此浏览器</div></div></div>
    <div class="hist" style="padding:14px 18px">
      ${acct ? `<div class="opt"><span>已登录：<b>${esc(acct.uname)}</b>（UID ${acct.uid}）</span></div>
        <label class="opt"><input type="radio" name="sayas" value="me"${acct.use ? ' checked' : ''}><span>我的号</span></label>
        <label class="opt"><input type="radio" name="sayas" value="bot"${acct.use ? '' : ' checked'}><span>用 ${esc(S.room?.bot_name || '默认账号')}</span></label>`
      : state.svg ? `<div style="text-align:center"><div style="width:220px;margin:0 auto;background:#fff;border-radius:12px;padding:6px">${state.svg}</div>
        <div id="qrstate" style="margin-top:8px;color:var(--ink2)">${esc(state.msg || '用 B 站 App 扫码')}</div></div>`
      : `<p style="margin:0 0 10px">现在用 ${esc(S.room?.bot_name || '默认账号')} 发。</p>`}
      ${!acct && S.room?.login_ok === false ? '<p class="disc" style="color:var(--ink2)">现在连直播间没登录，观众名字会打码。扫码登录后，也会用这个号连直播间。</p>' : ''}
      ${acct ? '' : '<p class="disc">登录后用你的账号发弹幕。B 站可能限制或封禁用第三方工具的账号，风险自负，作者不承担责任。</p>'}
      
    </div>
    <div class="acts">${acct ? '<button class="btn danger" id="acctout">退出登录</button>' : `<button class="btn" id="acctqr">${state.svg ? '换一张二维码' : icon('phone') + ' 扫码登录'}</button>`}
      <button class="btn" id="acctclose" style="margin-left:auto">关闭</button></div>`;
  $('acctclose').onclick = () => { clearInterval(qrTimer); box.classList.remove('open'); $('mask').classList.remove('show'); };
  if (acct) {
    box.querySelectorAll('[name=sayas]').forEach(r => r.onchange = () => { acct.use = r.value === 'me'; saveAcct(); drawSayAs(); });
    let arm = 0;
    $('acctout').onclick = () => {
      if (Date.now() - arm > 3000) { arm = Date.now(); $('acctout').textContent = '再点一次'; return; }
      window._ws?.send(JSON.stringify({ cmd: 'acct_logout', acct: acct.token }));
      acct = null; saveAcct(); drawSayAs(); acctDialog();
    };
  } else {
    $('acctqr').onclick = () => window._ws?.send(JSON.stringify({ cmd: 'acct_qr' }));
    if (state.svg) qrTimer = setInterval(() => window._ws?.send(JSON.stringify({ cmd: 'acct_poll', key: qrKey })), 2000);
  }
  box.classList.add('open'); $('mask').classList.add('show');
}
function acctResult(d) {
  if (d.cmd === 'acct_qr') {
    if (!d.ok) { note(d.msg, false); return; }
    qrKey = d.key; acctDialog({ svg: d.svg });
  } else if (d.cmd === 'acct_poll') {
    if (d.state === 'done') {
      clearInterval(qrTimer);
      acct = { token: d.token, uname: d.uname, face: d.face, uid: d.uid, use: true }; saveAcct(); drawSayAs(); acctDialog();
      note(`已登录 ${d.uname}`);
    } else if (d.state === 'expired') { clearInterval(qrTimer); const s = $('qrstate'); if (s) s.textContent = d.msg; }
    else { const s = $('qrstate'); if (s) s.textContent = d.msg; }
  } else if (d.cmd === 'acct_info') {
    if (acct && !d.ok) { acct = null; saveAcct(); drawSayAs(); note('登录失效，重新扫码', false); }
    else if (acct && d.ok) { acct.uname = d.msg || acct.uname; acct.face = d.face || ''; saveAcct(); drawSayAs(); }
  }
}
$('sayas').onclick = () => acctDialog();
drawSayAs();

/* ---------- 自定义：主题色、背景图、方案、导出导入 ---------- */
$('accentreset').onclick = () => { cfg.accent = ''; saveCfg(); applyCfg(); fillSettings(); };
const setAccent = hex => { cfg.accent = hex; saveCfg(); applyCfg(); fillSettings(); };
// 吸管（Chrome / Edge 才有）：在屏幕上任意点一下，吸那里的颜色
if (window.EyeDropper) {
  $('accentpick').hidden = false;
  $('accentpick').onclick = () => new EyeDropper().open().then(r => setAccent(r.sRGBHex.slice(0, 7).toLowerCase())).catch(() => {});
}
// 从背景图里取几个主要的颜色：缩成小图数一遍，按色相分 12 组，挑最显眼的 5 组；太灰、太黑、太白的不要
let accBg = null;
function drawAccentSwatches(bg) {
  const box = $('accsw');
  const mark = () => box.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.acc === cfg.accent));
  if (bg === accBg) return mark();
  accBg = bg; box.innerHTML = '';
  if (!bg) return;
  const im = new Image();
  im.onload = () => {
    if (accBg !== bg) return;
    const N = 48, c = document.createElement('canvas'); c.width = c.height = N;
    const g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(im, 0, 0, N, N);
    let px; try { px = g.getImageData(0, 0, N, N).data; } catch { return; }
    const bins = Array.from({ length: 12 }, () => [0, 0, 0, 0]);
    for (let k = 0; k < px.length; k += 4) {
      const r = px[k] / 255, gg = px[k + 1] / 255, b = px[k + 2] / 255, mx = Math.max(r, gg, b), mn = Math.min(r, gg, b), l = (mx + mn) / 2, d = mx - mn;
      if (d < .12 || l < .18 || l > .88) continue;
      const sat = d / (1 - Math.abs(2 * l - 1)), h = (mx === r ? ((gg - b) / d + 6) % 6 : mx === gg ? (b - r) / d + 2 : (r - gg) / d + 4) * 60;
      const bin = bins[Math.floor(h / 30) % 12], w = sat * sat;
      bin[0] += r * w; bin[1] += gg * w; bin[2] += b * w; bin[3] += w;
    }
    const hex = bins.filter(x => x[3] > 2).sort((a, b) => b[3] - a[3]).slice(0, 5)
      .map(x => '#' + [0, 1, 2].map(j => Math.round(Math.min(.82, Math.max(.2, x[j] / x[3])) * 255).toString(16).padStart(2, '0')).join(''));
    box.innerHTML = hex.length ? '<span>背景图</span>' + hex.map(h => `<button data-acc="${h}" style="background:${h}" title="${h}"></button>`).join('') : '';
    mark();
  };
  im.src = bg;
}
$('accsw').onclick = e => { const b = e.target.closest('[data-acc]'); if (b) setAccent(b.dataset.acc); };
$('bgpick').onclick = () => $('bgfile').click();
$('bgfile').onchange = e => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  const im = new Image();
  im.onload = () => {
    // 缩到最宽 1920 再存进浏览器，原图太大存不下
    const k = Math.min(1, 1920 / im.naturalWidth), c = document.createElement('canvas');
    c.width = Math.round(im.naturalWidth * k); c.height = Math.round(im.naturalHeight * k);
    c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
    try { localStorage.setItem('xw-bg', c.toDataURL('image/jpeg', .82)); applyCfg(); } catch { note('图太大，存不下', false); }
    URL.revokeObjectURL(im.src);
  };
  im.onerror = () => note('这张图打不开', false);
  im.src = URL.createObjectURL(f);
};
$('bgclear').onclick = () => { try { localStorage.removeItem('xw-bg'); } catch {} applyCfg(); };
const loadPsets = () => { try { return JSON.parse(localStorage.getItem('xw-presets') || '{}'); } catch { return {}; } };
const savePsets = o => { try { localStorage.setItem('xw-presets', JSON.stringify(o)); } catch {} };
function useCfg(c) { cfg = merge(DEF, c); cfg.v = DEF.v; fixLayout(cfg.layout); saveCfg(); applyCfg(); fillSettings(); renderLayout(); renderDm(); renderGifts(); }
const sendProfile = o => window._ws?.readyState === 1 && window._ws.send(JSON.stringify(o));
function profileResult(d) {
  if (!d.ok) { note(d.msg, false); return; }
  if (d.profiles) { S.profiles = d.profiles; drawPsets(); }
  if (d.cmd === 'profile_get' && d.profile) { useCfg(d.profile.content); note('已换成「' + d.profile.name + '」'); }
  if (d.cmd === 'profile_save') note('已存到后台，别的设备也能用');
}
function drawPsets() {
  const o = loadPsets(), names = Object.keys(o), cloud = S.admin && S.profiles;
  // 后台的方案（所有设备通用）在前；本机以前存的在后，可以传到后台
  $('psets').innerHTML = (cloud ? S.profiles.map(p => `<span class="pset cloud" title="存在后台，所有设备通用"><button data-cuse="${esc(p.name)}">${icon('cloud')}${esc(p.name)}</button><button data-cdel="${esc(p.name)}" title="删掉">✕</button></span>`).join('') : '')
    + names.map(n => `<span class="pset"><button data-puse="${esc(n)}" title="只存在这个浏览器，点一下换成这套">${esc(n)}</button>${cloud ? `<button data-pup="${esc(n)}" title="传到后台，别的设备也能用">${icon('upload')}</button>` : ''}<button data-pdel="${esc(n)}" title="删掉">✕</button></span>`).join('');
  $('psets').querySelectorAll('[data-cuse]').forEach(b => b.onclick = () => sendProfile({ cmd: 'profile_get', name: b.dataset.cuse }));
  $('psets').querySelectorAll('[data-cdel]').forEach(b => b.onclick = () => sendProfile({ cmd: 'profile_delete', name: b.dataset.cdel }));
  $('psets').querySelectorAll('[data-pup]').forEach(b => b.onclick = () => sendProfile({ cmd: 'profile_save', name: b.dataset.pup, content: o[b.dataset.pup] }));
  $('psets').querySelectorAll('[data-puse]').forEach(b => b.onclick = () => { useCfg(o[b.dataset.puse]); note('已换成「' + b.dataset.puse + '」'); });
  $('psets').querySelectorAll('[data-pdel]').forEach(b => b.onclick = () => { delete o[b.dataset.pdel]; savePsets(o); drawPsets(); });
}
$('psetsave').onclick = () => {
  const n = $('psetname').value.trim();
  if (!n) { $('psetname').focus(); return; }
  $('psetname').value = '';
  if (S.admin && S.profiles) { sendProfile({ cmd: 'profile_save', name: n, content: clone(cfg) }); return; }  // 连着后台：直接存到后台
  const o = loadPsets(); o[n] = clone(cfg); savePsets(o); drawPsets(); note('已保存「' + n + '」');
};
drawPsets();
$('cfgexport').onclick = () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify({ app: 'xiaowu-danmuji', cfg, presets: loadPsets() }, null, 1)], { type: 'application/json' }));
  a.download = BRAND_NAME() + '设置.json'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
};
$('cfgimport').onclick = () => $('cfgfile').click();
$('cfgfile').onchange = async e => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  try {
    const j = JSON.parse(await f.text());
    if (!j || typeof j.cfg !== 'object') throw 0;
    if (j.presets && typeof j.presets === 'object') savePsets({ ...loadPsets(), ...j.presets });
    useCfg(j.cfg); drawPsets(); note('已导入');
  } catch { note(`这不是${BRAND_NAME()}的设置文件`, false); }
};

/* ---------- 浮动小窗：拖标题挪位置，右下角拖大小，位置记在这台电脑上 ---------- */
function fwin(w) {
  const key = 'xw-win-' + w.id;
  const save = () => { const r = w.getBoundingClientRect(); try { localStorage.setItem(key, JSON.stringify({ x: r.left, y: r.top, w: r.width, h: r.height })); } catch {} };
  w.place = () => {
    let p = null; try { p = JSON.parse(localStorage.getItem(key) || 'null'); } catch {}
    if (p && p.x < innerWidth - 60 && p.y < innerHeight - 40) Object.assign(w.style, { left: p.x + 'px', top: Math.max(0, p.y) + 'px', width: p.w + 'px', height: p.h + 'px', right: 'auto', bottom: 'auto' });
  };
  w.querySelector('header').addEventListener('pointerdown', e => {
    if (e.button || e.target.closest('button, a, input')) return;
    const r = w.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
    const mv = ev => Object.assign(w.style, { left: Math.max(0, Math.min(innerWidth - 60, ev.clientX - dx)) + 'px', top: Math.max(0, Math.min(innerHeight - 40, ev.clientY - dy)) + 'px', right: 'auto', bottom: 'auto' });
    const up = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', up); document.body.classList.remove('fdrag'); save(); };
    document.body.classList.add('fdrag'); addEventListener('pointermove', mv); addEventListener('pointerup', up);
  });
  let t = 0;
  new ResizeObserver(() => { if (!w.hidden) { clearTimeout(t); t = setTimeout(save, 400); } }).observe(w);
  return w;
}
// 歌词提词：曲库里填了歌词 / 谱子链接的歌，歌单那一行有「词」按钮；开着的时候，换了「正在唱」会自动跟过去
let lyrSong = '', lyrNow = '';
fwin($('lyr'));
function drawLyrics() {
  if ($('lyr').hidden) return;
  const r = (S.library || []).find(x => x.name.toLowerCase() === lyrSong.toLowerCase()), L = (r?.lyrics || '').trim();
  $('lyrname').textContent = lyrSong || '歌词';
  $('lyr').style.setProperty('--lyr-size', (cfg.lyrSize || 20) + 'px');
  // 网址：图片直接显示，别的变成「打开谱子」链接
  $('lyrbody').innerHTML = L ? esc(L).replace(/https?:\/\/[^\s<"']+/g, u => /\.(png|jpe?g|webp|gif)(\?|$)/i.test(u) ? `<img src="${u}" alt="">` : `<a href="${u}" target="_blank" rel="noopener">打开谱子</a>`)
    : `<div class="empty">这首还没填歌词<br><small>曲库 → 编辑 → 歌词 / 谱子</small></div>`;
  $('lyrbody').scrollTop = 0;
}
function openLyrics(name) { lyrSong = name; if ($('lyr').hidden) { $('lyr').hidden = false; $('lyr').place(); } drawLyrics(); }
function followLyrics() {
  const now = (S.songs || []).find(x => x.now)?.name || '';
  if (now !== lyrNow) { lyrNow = now; if (now && !$('lyr').hidden) openLyrics(now); }
}
document.addEventListener('click', e => { const b = e.target.closest('[data-lyr]'); if (b) { e.stopPropagation(); openLyrics(b.dataset.lyr); } }, true);
$('lyrclose').onclick = () => { $('lyr').hidden = true; };
$('lyrsm').onclick = () => { cfg.lyrSize = Math.max(12, (cfg.lyrSize || 20) - 2); saveCfg(); drawLyrics(); };
$('lyrbig').onclick = () => { cfg.lyrSize = Math.min(48, (cfg.lyrSize || 20) + 2); saveCfg(); drawLyrics(); };
// 直播画面：B 站官方的嵌入播放器，静音；关掉就把播放器卸掉，不再占网速和 CPU
fwin($('mon'));
const monUrl = () => `https://www.bilibili.com/blackboard/live/live-activity-player.html?cid=${S.room.room_real || S.room_id}&mute=1&enterTheRoom=0&recommend=0&send=0&gift=0`;
function closeMon() { $('mon').hidden = true; $('monframe').src = 'about:blank'; $('monbtn').classList.remove('on'); }
$('monbtn').onclick = () => {
  if (!$('mon').hidden) return closeMon();
  $('mon').hidden = false; $('mon').place(); $('monframe').src = monUrl(); $('monbtn').classList.add('on');
};
$('monclose').onclick = closeMon;
$('monreload').onclick = () => { $('monframe').src = 'about:blank'; setTimeout(() => { $('monframe').src = monUrl(); }, 50); };

/* ---------- 改直播间标题 / 分区（只有主播本人登录了自己的号才出现） ---------- */
let areaList = null;
const isAnchor = () => !!(S.admin && acct && acct.uid && acct.uid === S.room.uid);
// 直播间公告（2026-11-21）：标题旁「公告」按钮，读现在的公告，改了点保存（要主播本人的号）
function newsOpen() {
  let p = $('tnews');
  if (!p) {
    p = document.createElement('div'); p.id = 'tnews';
    p.innerHTML = `<div class="tnh">${icon('notice')}<b>直播间公告</b><small id="tnewsn"></small></div><textarea id="tnewstext" maxlength="60" placeholder="读取中…"></textarea><div class="tnf"><span id="tnewsat"></span><button type="button" class="btn sm" id="tnewsclose">关闭</button><button type="button" class="btn sm accent" id="tnewssave">保存</button></div>`;
    document.body.appendChild(p);
    const cnt = () => { $('tnewsn').textContent = `${$('tnewstext').value.length}/60`; };
    $('tnewstext').addEventListener('input', cnt);
    $('tnewsclose').onclick = () => { p.hidden = true; };
    $('tnewssave').onclick = () => {
      if (!acct?.token) { note(`先在发送框左边扫码登录${ANCHOR()}的号`, false); return; }
      $('tnewssave').disabled = true;
      window._ws?.send(JSON.stringify({ cmd: 'news_set', acct: acct.token, text: $('tnewstext').value.trim() }));
    };
    document.addEventListener('click', e => { if (!p.hidden && !e.target.closest('#tnews, #tnewsbtn')) p.hidden = true; });
  }
  const r = $('tnewsbtn').getBoundingClientRect();
  Object.assign(p.style, { left: Math.max(8, Math.min(r.left, innerWidth - 336)) + 'px', top: r.bottom + 8 + 'px' });
  p.hidden = false;
  $('tnewstext').value = ''; $('tnewstext').placeholder = '读取中…'; $('tnewsat').textContent = ''; $('tnewssave').disabled = true;
  window._ws?.send(JSON.stringify({ cmd: 'news_get' }));
}
function newsResult(d) {
  const p = $('tnews');
  if (d.cmd === 'news_get') {
    if (!p || p.hidden) return;
    if (!d.ok) { $('tnewstext').placeholder = d.msg || '没读到公告'; return; }
    $('tnewstext').value = d.text || ''; $('tnewstext').placeholder = '写点什么（最多 60 个字）';
    $('tnewsat').textContent = d.ctime ? '上次改：' + String(d.ctime).slice(5, 16) : '';
    $('tnewssave').disabled = false; $('tnewstext').dispatchEvent(new Event('input'));
    return;
  }
  if ($('tnewssave')) $('tnewssave').disabled = false;
  note(d.msg || (d.ok ? '公告改好了' : '没改成'), d.ok);
  if (d.ok && p) p.hidden = true;
}
$('tnewsbtn').onclick = e => { e.preventDefault(); e.stopPropagation(); const p = $('tnews'); if (p && !p.hidden) p.hidden = true; else newsOpen(); };
function drawRoomBtns() {
  const rid = S.room.room_real || S.room_id, anchor = isAnchor();
  $('roomlink').style.display = $('monbtn').style.display = rid ? '' : 'none';
  if (rid) $('roomlink').href = 'https://live.bilibili.com/' + rid;
  // 主播本人登录了自己的号：标题那里直接是输入框 + 分区 + 确认；别人只看得到标题
  $('title').hidden = anchor; $('tedit').hidden = !anchor;
  if (!anchor) return;
  if (!areaList && !drawRoomBtns.asked) { drawRoomBtns.asked = true; window._ws?.send(JSON.stringify({ cmd: 'areas' })); }
  const ti = $('tinput'), ta = $('tarea');
  if (document.activeElement !== ti && !ti.dataset.dirty) ti.value = S.room.title || '';
  if (!ta.dataset.dirty && document.activeElement !== ta) {
    const cur = S.room.area_id, key = (areaList ? 'L' : 'N') + cur;
    if (ta.dataset.key !== key) {  // 分区表没变、当前分区没变就不重画
      ta.dataset.key = key;
      ta.innerHTML = areaList ? areaList.map(p => `<optgroup label="${esc(p.name)}">${p.list.map(x => `<option value="${x.id}"${x.id === cur ? ' selected' : ''}>${esc(x.name)}</option>`).join('')}</optgroup>`).join('')
        : `<option value="${cur || 0}">${esc(S.room.area || '分区')}</option>`;
    }
  }
  drawTSave(); lpDraw();
}
function drawTSave() {
  const changed = $('tinput').value.trim() !== (S.room.title || '') || (areaList && Number($('tarea').value) !== S.room.area_id);
  $('tsave').classList.toggle('on', !!changed); $('tsave').disabled = !changed;
}
$('tinput').addEventListener('input', () => { $('tinput').dataset.dirty = '1'; drawTSave(); });
$('tarea').addEventListener('change', () => { $('tarea').dataset.dirty = '1'; drawTSave(); });
$('tedit').addEventListener('submit', e => {
  e.preventDefault();
  if ($('tsave').disabled || !acct) return;
  window._ws?.send(JSON.stringify({ cmd: 'room_edit', acct: acct.token, title: $('tinput').value, area_id: areaList ? Number($('tarea').value) : 0 }));
});
$('tinput').addEventListener('keydown', e => { if (e.key === 'Escape') { delete $('tinput').dataset.dirty; $('tinput').blur(); drawRoomBtns(); e.stopPropagation(); } });
/* ---------- 常用标题 + 分区（2026-11-18）：存几组（歌回、杂谈…），点一下直接换上；存在电脑上，各设备同一份 ---------- */
const tpreAreaName = id => { for (const p of areaList || []) for (const x of p.list) if (x.id === id) return x.name; return ''; };
function drawTpre() {
  const L = S.title_presets || [];
  $('tpremenu').innerHTML = (L.length ? L.map((p, i) => `<div class="tprow" data-tpi="${i}" title="换成：${esc(p.title || S.room.title || '')} · ${esc(p.area || '')}"><b>${esc(p.name || p.area || '常用')}</b><span>${esc(p.title)}</span><small>${esc(p.area)}</small><button type="button" class="tpdel" data-tpdel="${i}" title="删掉这个">${icon('close')}</button></div>`).join('')
    : '<div class="tpempty">还没有常用标题<br><small>先在左边填好标题、选好分区，再存</small></div>')
    + `<form class="tpadd"><input id="tpname" maxlength="12" placeholder="名字，如 歌回"><button class="btn sm" title="把左边现在填的标题和分区存成一个常用">${icon('save')} 存现在的</button></form>`;
}
function sendTpre(L) { window._ws?.send(JSON.stringify({ cmd: 'tpre_set', list: L })); }
$('tprebtn').onclick = e => {
  e.stopPropagation();
  const m = $('tpremenu');
  if (!m.hidden) { m.hidden = true; return; }
  drawTpre(); m.hidden = false;
  const r = $('tprebtn').getBoundingClientRect();
  m.style.top = r.bottom + 6 + 'px'; m.style.left = Math.max(8, Math.min(innerWidth - m.offsetWidth - 8, r.right - m.offsetWidth)) + 'px';
};
document.addEventListener('click', e => { const m = $('tpremenu'); if (!m.hidden && !m.contains(e.target)) m.hidden = true; });
$('tpremenu').addEventListener('click', e => {
  e.stopPropagation();
  const del = e.target.closest('[data-tpdel]');
  if (del) { const L = (S.title_presets || []).slice(); L.splice(+del.dataset.tpdel, 1); sendTpre(L); return; }
  const row = e.target.closest('[data-tpi]');
  if (!row || !acct) return;
  const p = (S.title_presets || [])[+row.dataset.tpi];
  if (!p) return;
  window._ws?.send(JSON.stringify({ cmd: 'room_edit', acct: acct.token, title: p.title || S.room.title || '', area_id: p.area_id || 0 }));
  $('tpremenu').hidden = true;
});
$('tpremenu').addEventListener('submit', e => {
  e.preventDefault();
  const L = (S.title_presets || []).slice();
  if (L.length >= 12) return note('常用标题最多 12 个，先删掉一个', false);
  const area_id = areaList ? Number($('tarea').value) : (S.room.area_id || 0), title = $('tinput').value.trim();
  if (!title && !area_id) return note('先填标题或选分区', false);
  L.push({ name: $('tpname').value.trim(), title, area_id, area: tpreAreaName(area_id) || (area_id === S.room.area_id ? S.room.area || '' : '') });
  sendTpre(L);
});
/* ---------- 一键开播 / 下播（2026-11-18）----------
   点「开播」：后台用主播本人的号让 B 站开播，拿回推流地址和推流码；勾了「让 OBS 自动推流」就通过 OBS 自带的 WebSocket
   （OBS → 工具 → WebSocket 服务器设置，开在主播自己电脑上）把推流码填进 OBS 并开始推流；没勾或连不上就显示推流码让她自己贴。
   下播：先让 OBS 停推流，再让 B 站下播（只停 OBS 不会结束 B 站的直播）。OBS 地址和密码只存在这台电脑的浏览器里。 */
const LP_KEY = 'xw-obsws';
try { if (localStorage.getItem('xw-golive') === '1') document.body.classList.add('golive'); } catch {}
let lp = { url: 'ws://127.0.0.1:4455', pw: '', auto: true };
try { Object.assign(lp, JSON.parse(localStorage.getItem(LP_KEY) || '{}')); } catch {}
const lpSave = () => { try { localStorage.setItem(LP_KEY, JSON.stringify(lp)); } catch {} };
let lpBusy = false, lpConfirm = 0, lpLast = null;
async function sha256b64(text) {
  const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return btoa(String.fromCharCode(...new Uint8Array(h)));
}
// 连一次 OBS，按顺序发几个请求，发完就断开；返回每个请求的结果
function obsCall(url, pw, requests) {
  return new Promise((resolve, reject) => {
    let ws;
    try { ws = new WebSocket(url || 'ws://127.0.0.1:4455', 'obswebsocket.json'); } catch (e) { reject(new Error('OBS 地址不对')); return; }
    const out = [], timer = setTimeout(() => { try { ws.close(); } catch {} reject(new Error('连 OBS 超时：OBS 开着吗？WebSocket 服务器开了吗？')); }, 8000);
    let i = 0;
    const next = () => {
      if (i >= requests.length) { clearTimeout(timer); ws.close(); resolve(out); return; }
      const [requestType, requestData] = requests[i];
      ws.send(JSON.stringify({ op: 6, d: { requestType, requestId: 'r' + i, requestData: requestData || {} } }));
    };
    ws.onerror = () => { clearTimeout(timer); reject(new Error('连不上 OBS：确认 OBS 开着，工具 → WebSocket 服务器设置 里勾了「开启」')); };
    ws.onclose = e => { if (e.code === 4009) { clearTimeout(timer); reject(new Error('OBS 密码不对')); } };
    ws.onmessage = async ev => {
      let m; try { m = JSON.parse(ev.data); } catch { return; }
      if (m.op === 0) {  // Hello：要密码的话按 OBS 的规则算一下
        const d = { rpcVersion: 1 }, a = m.d && m.d.authentication;
        if (a) d.authentication = await sha256b64(await sha256b64((pw || '') + a.salt) + a.challenge);
        ws.send(JSON.stringify({ op: 1, d }));
      } else if (m.op === 2) next();
      else if (m.op === 7) { out.push(m.d.requestStatus || {}); i++; next(); }
    };
  });
}
const obsOk = (st, also = []) => st && (st.result || also.includes(st.code));
function lpDraw() {
  const live = S.room.live === 1, area = areaList ? tpreAreaName(Number($('tarea').value)) : (S.room.area || '');
  $('golive').classList.toggle('on', live);
  $('golive').querySelector('span').textContent = live ? '下播' : '开播';
  if ($('livepanel').hidden) return;
  $('lptitle').textContent = live ? '一键下播' : '一键开播';
  $('lpinfo').innerHTML = live ? `现在在播：${esc(S.room.title || '')}`
    : `用左边的标题和分区开播<br><b>${esc($('tinput').value.trim() || S.room.title || '')}</b> · ${esc(area || '没选分区')}`;
  $('lpauto').checked = !!lp.auto; $('lpobs').hidden = !lp.auto;
  if (document.activeElement !== $('lpurl')) $('lpurl').value = lp.url || ''; if (document.activeElement !== $('lppw')) $('lppw').value = lp.pw || '';
  const go = $('lpgo');
  go.disabled = lpBusy;
  go.classList.toggle('stop', live);
  go.textContent = lpBusy ? '稍等…' : live ? (lpConfirm > Date.now() ? '再点一下确定下播' : '■ 下播') : '▶ 开播';
}
function lpMsg(html, ok = true) { $('lpmsg').innerHTML = html; $('lpmsg').className = 'lpmsg' + (ok ? '' : ' bad'); }
function lpShowKey(addr, code) {
  const box = $('lpkey');
  box.hidden = false;
  box.innerHTML = `<div>推流地址 <code>${esc(addr)}</code><button type="button" class="btn sm" data-lpcopy="a">复制</button></div>`
    + `<div>推流码 <code>••••••${esc(code.slice(-4))}</code><button type="button" class="btn sm" data-lpcopy="c">复制</button></div>`
    + '<small>OBS → 设置 → 直播：服务选「自定义」，填上这两个，再点「开始直播」</small>';
  box.onclick = e => { const b = e.target.closest('[data-lpcopy]'); if (b) navigator.clipboard?.writeText(b.dataset.lpcopy === 'a' ? addr : code).then(() => note('复制好了')); };
}
$('golive').onclick = e => {
  e.stopPropagation();
  const p = $('livepanel');
  if (!p.hidden) { p.hidden = true; return; }
  p.hidden = false; lpConfirm = 0; lpMsg(''); $('lpkey').hidden = true; lpDraw();
  const r = $('golive').getBoundingClientRect();
  p.style.top = r.bottom + 6 + 'px'; p.style.left = Math.max(8, Math.min(innerWidth - p.offsetWidth - 8, r.right - p.offsetWidth)) + 'px';
};
$('lpclose').onclick = () => { $('livepanel').hidden = true; };
$('livepanel').addEventListener('click', e => e.stopPropagation());
document.addEventListener('click', () => { if (!lpBusy) $('livepanel').hidden = true; });
$('lpauto').onchange = () => { lp.auto = $('lpauto').checked; lpSave(); lpDraw(); };
$('lpurl').onchange = () => { lp.url = $('lpurl').value.trim(); lpSave(); };
$('lppw').onchange = () => { lp.pw = $('lppw').value; lpSave(); };
$('lptest').onclick = async () => {
  lp.url = $('lpurl').value.trim(); lp.pw = $('lppw').value; lpSave();
  lpMsg('正在连 OBS…');
  try {
    const [v, s] = await obsCall(lp.url, lp.pw, [['GetVersion'], ['GetStreamStatus']]);
    lpMsg(obsOk(v) ? `连上了 OBS ✓${s && s.result ? '' : ''}` : 'OBS 回话了，但没认出来', obsOk(v));
  } catch (err) { lpMsg(esc(err.message), false); }
};
// 一键开播
function lpStartResult(d) {
  if (!d.ok) {
    lpBusy = false; lpDraw();
    lpMsg(esc(d.msg) + (d.face_qr ? `<div class="lpqr">${d.face_qr}</div>` : ''), false);
    return;
  }
  lpLast = { addr: d.addr, code: d.code };
  if (!lp.auto) { lpBusy = false; lpDraw(); lpMsg('B 站已经开播 ✓ 把下面的推流码填进 OBS 再开始直播'); lpShowKey(d.addr, d.code); return; }
  lpMsg('B 站已经开播 ✓ 正在让 OBS 开始推流…');
  obsCall(lp.url, lp.pw, [['SetStreamServiceSettings', { streamServiceType: 'rtmp_custom', streamServiceSettings: { server: d.addr, key: d.code } }], ['StartStream']])
    .then(([set, start]) => {
      if (!obsOk(set)) throw new Error('OBS 没接受推流码（' + (set.comment || set.code || '') + '）');
      if (!obsOk(start, [500])) throw new Error('OBS 没开始推流（' + (start.comment || start.code || '') + '）');
      lpMsg('开播了 ✓ OBS 已经在推流');
    })
    .catch(err => { lpMsg('B 站已经开播，但 ' + esc(err.message) + '<br>可以手动把推流码填进 OBS：', false); lpShowKey(d.addr, d.code); })
    .finally(() => { lpBusy = false; lpDraw(); });
}
function lpStopResult(d) { lpBusy = false; lpDraw(); lpMsg(esc(d.msg), d.ok); if (d.ok) setTimeout(() => { if (!lpBusy) $('livepanel').hidden = true; }, 2500); }
$('lpgo').onclick = async () => {
  if (lpBusy || !acct) return;
  const live = S.room.live === 1;
  if (!live) {
    const area_id = areaList ? Number($('tarea').value) : (S.room.area_id || 0);
    lpBusy = true; lpDraw(); lpMsg('正在让 B 站开播…'); $('lpkey').hidden = true;
    window._ws?.send(JSON.stringify({ cmd: 'live_start', acct: acct.token, area_id, title: $('tinput').value.trim() }));
    return;
  }
  if (lpConfirm < Date.now()) { lpConfirm = Date.now() + 4000; lpDraw(); setTimeout(lpDraw, 4100); return; }
  lpConfirm = 0; lpBusy = true; lpDraw();
  if (lp.auto) {
    lpMsg('正在让 OBS 停止推流…');
    try { const [st] = await obsCall(lp.url, lp.pw, [['StopStream']]); if (!obsOk(st, [501])) lpMsg('OBS 没停下来（' + esc(st.comment || st.code || '') + '），先让 B 站下播…', false); }
    catch (err) { lpMsg(esc(err.message) + '，先让 B 站下播，记得自己停 OBS', false); }
  }
  window._ws?.send(JSON.stringify({ cmd: 'live_stop', acct: acct.token }));
};
function roomResult(d) {
  if (d.cmd === 'areas') { if (d.ok) { areaList = d.areas; drawRoomBtns(); } return; }
  if (d.cmd === 'live_start') return lpStartResult(d);
  if (d.cmd === 'live_stop') return lpStopResult(d);
  note(d.msg, d.ok);
  if (d.ok) { delete $('tinput').dataset.dirty; delete $('tarea').dataset.dirty; $('tinput').blur(); }
}
