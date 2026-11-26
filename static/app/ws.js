// 雾幕主页面 · 和后台的连接：收消息、断线重连
// 这几个文件按顺序加载，共用同一套全局变量。加载时只能直接用前面文件里的东西，用后面文件的函数要放进回调里
function drawBanner() {
  const b = $('banner'), show = !!S.admin && S.room.login_ok === false;
  b.classList.toggle('show', show);
  if (show) setText(b, '⚠ 连直播间没登录，名字会打码：点发弹幕框左边的头像扫码登录');
}
// 断线自动重连：等待时间 2、4、8… 秒，最多 30 秒；超过 150 秒一条消息都没有，也当断线处理
let wsRetry = 0, wsTimer = 0, lastMsgAt = Date.now();
/* ---------- 普通链接 / 普通视角 ----------
   2026-11-21 用户：普通链接可以用大部分功能（自己的布局、朗读、提醒、观众、点歌…），但看不到主播的数据和历史：
   收益、价格、送礼榜、历史、下播期间、备注、曲库，以及发弹幕、禁言、改标题这些会动 B 站的操作（后台本来就不给）。
   管理身份点「普通视角」：用普通身份重新连一次后台，看到的就是别人真实拿到的；再点一下回到管理。 */
let preview = false; try { preview = sessionStorage.getItem('xw-preview') === '1'; } catch {}
function setViewer(on) {
  document.body.classList.toggle('viewer', on);
  if (stashLayout) { cfg.layout = stashLayout; stashLayout = null; }  // 以前普通链接用固定布局，现在用自己的
  if (on) {
    closeAll();
    if (giftTab === 'rank') { giftTab = 'all'; document.querySelectorAll('[data-g]').forEach(x => x.classList.toggle('on', x.dataset.g === 'all')); }  // 送礼榜不给普通链接
    if (!$('lyr').hidden) $('lyrclose').click();  // 歌词要曲库；「新的管理链接」小窗不关：明文只给一次
  }
  const b = $('viewbtn');
  b.hidden = !(S.admin || preview);
  b.classList.toggle('on', preview);
  b.innerHTML = preview ? `${icon('eye')}<span> 回到管理</span>` : `${icon('eye')}<span class="lbl"> 普通视角</span>`;
}
$('viewbtn').onclick = () => {
  preview = !preview;
  try { sessionStorage.setItem('xw-preview', preview ? '1' : ''); } catch {}
  note(preview ? '现在是普通视角：拿普通链接的人看到的就是这些' : '回到管理了', true);
  connect();
};
function connect() {
  clearTimeout(wsTimer);
  const old = window._ws;
  if (old && old.readyState < 2) { old.onclose = old.onmessage = null; old.close(); }
  const room = (v => /^\d{1,12}$/.test(v) || /^(douyu|huya|douyin):\d{1,20}$/.test(v) ? v : '')(new URLSearchParams(location.search).get('room') || '');  // 切到别的直播间（2026-11-20）；别的平台是 douyu:9999 这样（2026-11-26）
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + location.pathname.replace(/[^/]*$/, '') + 'ws' + ((q => q ? '?' + q : '')(new URLSearchParams({ ...(preview ? { view: 'public' } : {}), ...(room ? { room } : {}) }).toString())));  // 普通视角也能切直播间（2026-11-21）
  window._ws = ws;
  ws.onopen = () => { wsRetry = 0; lastMsgAt = Date.now(); wsOpen = true; drawConn(); $('netbar').classList.remove('on'); };
  ws.onclose = ev => {
    if (window._ws !== ws) return;
    if (ev.code === 4001) note('这个管理链接已经失效，现在是普通视角', false);
    wsOpen = false; $('conn').textContent = '重连中…'; $('conn').className = 'pill bad'; $('netbar').classList.add('on');
    wsTimer = setTimeout(connect, ev.code === 4008 ? 30000 : ev.code === 4001 ? 500 : Math.min(30000, 2000 * 2 ** wsRetry++));  // 人满了就隔 30 秒再试，不一直撞
  };
  ws.onmessage = ev => {
    lastMsgAt = Date.now();
    const msg = JSON.parse(ev.data), { type, data } = msg;
    if (window.workbenchMessage?.(type, data)) return;
    if (msg.uc) S.userCount = msg.uc;
    if (/^(gift|sc|guard|enter|room)$/.test(type)) soon(renderExtra, 'x');
    if (type === 'emots') { Object.assign(EMO, data); return; }
    if (type === 'ver') { checkVer(data); return; }
    if (type === 'songbook') { S.songbook = data; return; }
    if (type === 'snapshot') {
      checkVer(data.ver);
      Object.assign(EMO, data.emots || {});
      Object.assign(S, data);
      applyTags(); drawTagSet();  // 身份标签的名字和颜色（2026-11-26）
      drawRoomSet();  // 直播间：没设置就出卡片（2026-11-26）
      if (S.music) S.music.skew = (S.music.now || Date.now() / 1000) - Date.now() / 1000;
      window.syncWorkbench?.();
      S.userCount = data.user_count;
      S.dmTotal = data.dm_total ?? (data.users || []).reduce((a, u) => a + (u.dm || 0), 0);
      $('roomid').textContent = data.room_id ? '' : '演示';
      if (!S.admin) { S.notes = null; for (const k of ['sc_read', 'admin_links', 'connections', 'library', 'songbook', 'profiles', 'title_presets', 'lan', 'music_rules', 'desktop', 'platforms']) delete S[k]; }  // 切到普通视角时，把管理身份才有的东西从页面里清掉
      document.body.classList.toggle('nomoney', !S.admin);
      setViewer(!S.admin);
      document.body.classList.toggle('host', !!S.host);  // 主播专属链接：藏掉普通视角、链接管理、清零这些后台的东西
      if (S.host) setHostLook();  // 主播专属：左上角和浏览器标签页换成主播的头像
      applyMascot(S.mascot);  // 换过看板娘：图标都换成换的那张（2026-11-26）
      if (!S.side) refreshOffDot();
      sideApply();
      if (scSynced()) {
        const have = new Set(S.sc_read.map(String)), mine = S.scs.map(x => String(x.id)).filter(id => scRead.has(id) && !have.has(id)).slice(0, 40);
        mine.forEach((id, i) => setTimeout(() => window._ws?.readyState === 1 && window._ws.send(JSON.stringify({ cmd: 'sc_read', id, read: true })), 200 * (i + 1)));
        scRead = new Set([...have, ...mine]);
      }
      renderLayout(); drawBanner(); drawConn(); drawSayAs(); drawPsets(); drawLinks(); drawUpd();
      if (S.admin) acctCheckAll();  // 看看之前登录的号还在不在
      renderAll(); musicSync(); drawMusicSet(); drawPlats();
    } else if (type === 'dm') {
      S.dm.push(data); if (S.dm.length > 300) S.dm.shift();
      if (data.kind) { addDm(data); return; }  // 禁言提示：只显示，不算发言、不朗读
      S.dmTotal = (S.dmTotal || 0) + 1;
      upsertUser(data.uid, data.name, data.face, { dm: 1, guard: data.guard, medal: data.medal ? `${data.medal} ${data.medal_level}${data.medal_dim ? ' dim' : ''}` : '' });
      addDm(data); speakDm(data); sound('dm');
      renderStats(); if (userTab === 'all') soon(renderUsers, 'u');
    } else if (type === 'enter') {
      S.enters.push(data); if (S.enters.length > 200) S.enters.shift();
      upsertUser(data.uid, data.name, data.face, { enter: data.kind === 'enter' ? 1 : 0, guard: data.guard });
      addEnter(data); renderStats(); if (userTab === 'all') soon(renderUsers, 'u');
      speakEnter(data);  // 舰长进房的顶部答谢条用户不要了（2026-11-18）
      if (data.kind === 'follow') sound('follow'); else if (data.kind === 'enter' && data.guard) sound('enterGuard');
    } else if (type === 'enter_update') {
      const e = S.enters.slice().reverse().find(x => x.uid === data.uid && x.t === data.t);
      if (e) { if (!e.guard && data.guard && e.kind === 'enter') sound('enterGuard'); e.guard = data.guard; }
      upsertUser(data.uid, data.name, data.face, { guard: data.guard });
      soon(renderEnters, 'e');
    } else if (type === 'gift') {
      const i = S.gifts.findIndex(g => g.id === data.item.id);
      if (data.item.anim) { data.item._at = Date.now(); setTimeout(() => soon(renderGifts, 'g'), GIFT_ANIM_MS + 100); }  // 动图播完换回静态图
      if (i < 0 && cfg.bigGift.on && data.item.yuan >= (Number(cfg.bigGift.min) || 10)) bigGiftFx(data.item);
      if (i < 0 && data.item.yuan >= (Number(cfg.snd.giftMin) || 0)) sound('gift');  // 大额礼物：礼物栏里放大播一次
      if (i >= 0) S.gifts[i] = data.item; else S.gifts.push(data.item);
      if (i < 0 && data.item.source === '下播') refreshOffDot();
      if (data.flow) S.flow = data.flow; putUser(data.user);
      soon(renderGifts, 'g'); renderStats(); speakGiftLater(data.item);
      // 大额礼物的大提示卡用户不要了（2026-11-18）；上舰、大额 SC 的大提示还在
    } else if (type === 'sc') {
      window.mobPing?.('sc');
      S.scs.push(data.item); if (data.flow) S.flow = data.flow; putUser(data.user);
      renderSc(); renderStats(); if (giftTab === 'rank') soon(renderGifts, 'g'); speakSc(data.item); if (data.item.price >= (Number(cfg.snd.scMin) || 0)) sound('sc');
    } else if (type === 'guard') {
      S.guards.push(data.item); if (data.flow) S.flow = data.flow; putUser(data.user);
      if (data.item.source === '下播') refreshOffDot();
      soon(renderGifts, 'g'); renderStats(); speakGuard(data.item); sound('guard');
      if (cfg.bigGift.on && cfg.bigGift.guard !== false) bigGiftFx({ ...data.item, face: data.user?.face || '', _guard: true });  // 上舰大特效（2026-11-18，代替原来的大提示卡）
    } else if (type === 'room') {
      // 看过人数、点赞这些一直在变，高能榜真变了才重画，免得列表一直闪
      const topKey = JSON.stringify(data.top || []), changed = topKey !== S.topKey;
      S.room = data; S.topKey = topKey; renderStats(); drawSayAs(); if (userTab === 'top' && changed) renderUsers(); tick();
      drawBanner(); drawConn(); if (!S.side && $('xroomlbl')) $('xroomlbl').textContent = mainName();  // 主播名字查到了就换上（2026-11-26）
    } else if (type === 'req') {
      (S.reqs ??= []).push(data); renderReqs(); window.mobPing?.('req');
    } else if (type === 'songs') {
      S.songs = data; renderReqs();
    } else if (type === 'reqs') {
      S.reqs = data; renderReqs();
    } else if (type === 'req_rules') {
      S.req_rules = data; drawReqHead();
    } else if (type === 'music') {  // 放歌队列变了（2026-11-25）
      S.music = data; S.music.skew = (data.now || Date.now() / 1000) - Date.now() / 1000;
      if (reqTab === 'list') soon(renderReqs, 'mq');
      musicSync();
    } else if (type === 'platforms') {  // 其他平台的直播间和连接状态
      // 抖音要验证 / 页面改版收不到了：弹一句提醒（2026-11-26），同一个房间亮着黄字时只提醒一次
      const was = new Set((S.platforms?.rooms || []).filter(r => r.warn).map(r => r.plat + r.room));
      const bad = (data?.rooms || []).find(r => r.warn && !was.has(r.plat + r.room));
      S.platforms = data; drawPlats();
      if (bad) note(`${bad.label || bad.plat} ${bad.room}：${bad.state}（设置 → 直播间）`, false);
    } else if (type === 'music_rules') {
      S.music_rules = data; drawMusicSet();
    } else if (type === 'result') {
      if (String(data.cmd).startsWith('acct_')) { acctResult(data); drawRoomBtns(); return; }
      if (String(data.cmd).startsWith('profile_')) { profileResult(data); return; }
      if (String(data.cmd).startsWith('admin_link_')) { linkResult(data); return; }
      if (data.cmd === 'lan_set') { note(data.msg, data.ok); if (!data.ok) drawLinks(); return; }
      if (data.cmd === 'room_set') { roomResult(data); return; }
      if (['update_download', 'update_restart', 'open_mode', 'make_shortcut'].includes(data.cmd)) { note(data.msg, data.ok); if (!data.ok && data.cmd === 'update_download') { updPct = -1; drawUpd(); } return; }
      if (['music_qr', 'music_poll', 'music_logout', 'music_cookie'].includes(data.cmd)) { musicLoginResult(data); return; }
      if (data.cmd === 'mute_list' || data.cmd === 'unmute') { muteResult(data); return; }
      if (data.cmd === 'news_get' || data.cmd === 'news_set') { newsResult(data); return; }
      if (data.cmd === 'sc_read' || data.cmd === 'sc_read_all') { if (!data.ok) note(data.msg, false); return; }
      if (data.cmd === 'areas' || data.cmd === 'room_edit' || data.cmd === 'live_start' || data.cmd === 'live_stop') { roomResult(data); return; }
      note(data.msg, data.ok);
      if (data.cmd === 'say' && data.ok) $('sayinput').value = '';
    } else if (type === 'gift_thanked') {  // 礼物「已感谢」打勾，几台设备同步（2026-11-18）
      const it = [...S.gifts, ...S.guards].find(x => String(x.id) === String(data.id));
      if (it) { if (data.done) it.thanked = true; else delete it.thanked; soon(renderGifts, 'g'); }
      offThanked(data.id, data.done);
    } else if (type === 'sc_read') {
      S.sc_read = data; scRead = new Set(data.map(String)); renderSc();
    } else if (type === 'mutes') {
      askMutes();  // 有人被禁言 / 解除了：开着名单的话重新查一次
    } else if (type === 'update') {  // GitHub 上出了新版本
      S.update = data; drawUpd();
    } else if (type === 'update_progress') {  // 桌面版：下载更新的进度（-1 = 失败）
      updPct = data.pct; drawUpd();
    } else if (type === 'tags') {  // 改了身份标签 / 给谁加了标签（2026-11-26）
      S.tags = data.tags; S.bot_uids = data.bot_uids || [];
      applyTags(); drawTagSet(); renderDm(); renderUsers?.();
      if ($('card').classList.contains('open') && $('card').dataset.uid) drawCardTags(Number($('card').dataset.uid));
    } else if (type === 'mascot') {  // 在别的地方换了看板娘
      applyMascot(data);
    } else if (type === 'desktop') {
      S.desktop = data; updPct = null; drawUpd();
    } else if (type === 'face') {  // 没头像的人，后台去 B 站名片查到了（2026-11-25）：补上再画
      const f = data.face, uid = data.uid;
      const u = userOf(uid); if (u && !u.face) u.face = f;
      let hit = false;
      for (const list of [S.dm, S.gifts, S.guards, S.sc, S.enters]) for (const x of list || []) if (x.uid === uid && !x.face) { x.face = f; hit = true; }
      if (hit) { soon(renderGifts, 'g'); soon(renderDm, 'd'); soon(renderSc, 's'); soon(renderEnters, 'e'); }
    } else if (type === 'lan') {  // 手机打开（局域网）开关变了
      S.lan = data; drawLinks();
    } else if (type === 'connections') {
      S.connections = data; drawLinks();
    } else if (type === 'profiles') {
      S.profiles = data; drawPsets();
    } else if (type === 'warn') {
      showWarn(data);
    } else if (type === 'tpre') {
      S.title_presets = data; if (!$('tpremenu').hidden) drawTpre();
    } else if (type === 'xrooms') {  // 切直播间的名单、开关（2026-11-21）
      S.xrooms = data; xrShow(); if (!$('xroommenu').hidden) xroomMenu(); drawRoomList();
      if (!S.admin && S.side && !(data.open && data.rooms.some(x => xrKey(x) === String(S.side.room) || xrKey(x) === SIDE_ROOM))) xroomGo(0);
    } else if (type === 'guardlist') {
      S.guardlist = data; renderUsers();
    } else if (type === 'guards_all') {  // 后台补了陪伴天数（2026-11-20）
      S.guards = data; renderGifts();
    } else if (type === 'notes') {
      S.notes = data; renderDm(); if (userTab !== 'top') renderUsers();
    } else if (type === 'history') {
      if ($('hist').classList.contains('open') && !H.detail) loadHistList();  // 正在看列表时，新存的一场马上出现
    }
  };
}
setInterval(() => { if (window._ws?.readyState === 1 && Date.now() - lastMsgAt > 150000) window._ws.close(); }, 15000);
// 电脑睡醒、手机切回来时，断了就马上重连，不用等
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && window._ws && window._ws.readyState > 1) { wsRetry = 0; connect(); }
});
/* ---------- 打开时先显示上次的画面（存在这台电脑上），连上后台马上换成最新的，不会先白一下 ---------- */
function cacheView() {
  if (POP || preview || !S.room_id && !S.room.title) return;
  try {
    localStorage.setItem('xw-view', JSON.stringify({
      t: Date.now(), room: S.room, room_id: S.room_id, flow: S.flow, session_start: S.session_start, archive_id: S.archive_id, admin: S.admin,
      dm: S.dm.slice(-80), enters: S.enters.slice(-60), gifts: S.gifts.slice(-120), scs: S.scs.slice(-60), guards: S.guards.slice(-60),
      users: S.users.slice(0, 300), songs: S.songs || [], reqs: (S.reqs || []).slice(-100), user_count: S.userCount, dm_total: S.dmTotal,
      guardlist: S.guardlist || [], req_rules: S.req_rules,
    }));
  } catch {}
}
addEventListener('pagehide', cacheView);
function showCachedView() {
  let v = null;
  try { v = JSON.parse(localStorage.getItem('xw-view') || 'null'); } catch {}
  if (!v || preview || Date.now() - v.t > 12 * 3600e3 || wsOpen) return;  // 半天以前的就不拿出来了
  Object.assign(S, v); S.userCount = v.user_count; S.dmTotal = v.dm_total;
  document.body.classList.toggle('nomoney', !S.admin);
  setViewer(!S.admin);
  try { renderLayout(); renderAll(); } catch {}
  setText($('conn'), '连接中…'); $('conn').title = '先显示的是上次的画面，连上后会换成最新的';
}