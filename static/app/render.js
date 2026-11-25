// 雾幕主页面 · 画各个面板：弹幕、SC、礼物、进房、观众、时间便签；自定义布局
// 这几个文件按顺序加载，共用同一套全局变量。加载时只能直接用前面文件里的东西，用后面文件的函数要放进回调里
/* ---------- 渲染 ---------- */
// 弹幕里夹的小表情（[妙]、[哇] 这种）换成图：B 站在每条弹幕里给了图片地址，见过的都记在 EMO 里，旧弹幕也能显示
const EMO = {};
function emoText(d) {
  const map = d.emots ? Object.assign(EMO, d.emots) : EMO;
  const s = esc(d.text);
  return s.includes('[') ? s.replace(/\[[^\[\]\s]{1,12}\]/g, k => map[k] ? `<img class="emo" src="img?u=${encodeURIComponent(map[k])}" alt="${k}" title="${k}">` : k) : s;
}
function dmHtml(d) {
  // 禁言提示（2026-11-18）：和 B 站直播间一样，一行粉色小字
  if (d.kind === 'mute') return `<div class="dm dmsys" data-uid="${d.uid}" data-i="${d.i ?? ''}"><span>${icon('ban')}</span><span class="txt"><b>${esc(d.name)}</b> ${esc(d.text)}</span><span class="time">${hhmm(d.t)}</span></div>`;
  const tags = [];
  if (d.plat) tags.push(platTag(d.plat));  // 其他平台的弹幕（2026-11-25）
  if (S.room.uid && d.uid === S.room.uid) tags.push('<span class="tag anchor" title="主播本人">主播</span>');  // 2026-11-19 跟 B 站一样
  if (d.wealth) tags.push(wealthHtml(d.wealth));
  if (d.guard) tags.push(`<span class="tag g${d.guard}" title="${GN[d.guard]}">${GS[d.guard]}</span>`);
  if (d.admin) tags.push('<span class="tag admin" title="房管">房</span>');
  if (d.medal) tags.push(medalHtml(d.medal, d.medal_level, d.guard, d.medal_dim));
  if ((S.bot_uids || []).includes(d.uid)) tags.push('<span class="tag bot" title="机器人发的弹幕">机器人</span>');
  if (isMuted(d.uid)) tags.push('<span class="tag mute">不读</span>');
  const nt = noteOf(d.uid);
  if (nt) tags.push(`<span class="tag note" title="${esc(nt)}">${icon('p-note')} ${esc(nt)}</span>`);
  const txt = (d.reply ? `<span class="reply" title="回复 ${esc(d.reply)}">@${esc(d.reply)}</span> ` : '')
    + (d.emoticon ? `<img src="img?u=${encodeURIComponent(d.emoticon)}" alt="${esc(d.text)}" title="${esc(d.text)}">` : emoText(d));
  const hl = !d.emoticon && hlWords().some(w => String(d.text).toLowerCase().includes(w));
  return `<div class="dm${hl ? ' hl' : ''}${d.guard ? ' g' + d.guard : ''}" data-uid="${d.uid}" data-i="${d.i ?? ''}"${d.dmid ? ` data-dmid="${esc(d.dmid)}"` : ''}>${avatar(d.face, d.name, d.guard)}<div class="body"><div class="who">${tags.join('')}<span class="n${d.guard ? ' guard n' + d.guard : ''}">${esc(d.name)}</span></div><div class="txt">${txt}</div></div><span class="time">${hhmm(d.t)}</span></div>`;
}
// 弹幕自动跟到最新：只要人往上滚（滚轮、触屏、拖滚动条），马上停止跟随，不会被新弹幕拽回去；
// 滚回最底下（或点「回到最新」）再接着跟
const dmList = $('dmlist');
let stick = true, autoScroll = false, touchY = 0, holdUntil = 0;  // holdUntil：进房细栏弹出 / 收起期间不判断人是不是在往上翻
// 弹幕在小窗里时用小窗的画面刷新：主窗口最小化后浏览器会停掉它的刷新，小窗就不动了
const frame = fn => (pipWin || window).requestAnimationFrame(fn);
function toBottom() {
  autoScroll = true;
  dmList.scrollTop = dmList.scrollHeight;
  frame(() => { autoScroll = false; });
}
// 跟着最新弹幕时平滑地往上推，不再一下跳过去：每一帧把剩下的距离走掉一部分，新弹幕连着来也是一直匀匀地滑
// （只改滚动位置，浏览器直接合成，很省）。动画关掉、页面在后台时还是直接到底
let glideId = 0, glideAt = 0;
function glideBottom() {
  if (cfg.dm.anim === 'none' || document.hidden) return toBottom();
  if (glideId) return;
  glideAt = performance.now();
  const step = now => {
    const dt = Math.min(64, now - glideAt), left = dmList.scrollHeight - dmList.clientHeight - dmList.scrollTop;
    glideAt = now;
    if (!stick || left <= 0.5) { glideId = 0; if (stick) dmList.scrollTop = dmList.scrollHeight; frame(() => { if (!glideId) autoScroll = false; }); return; }
    autoScroll = true;
    // 积压太多（刷屏）先跳到只差半屏，再滑
    if (left > dmList.clientHeight) dmList.scrollTop += left - dmList.clientHeight / 2;
    else dmList.scrollTop += Math.max(1, left * (1 - Math.exp(-dt / Math.max(60, cfg.dm.animMs / 3.5))));
    glideId = frame(step);
  };
  glideId = frame(step);
}
// 往上翻看时来了几条新的：底下按钮写上条数，点一下回到最新
let newCount = 0;
function hideNewbar() { newCount = 0; $('newbar').style.display = 'none'; }
function unstick() {
  if (!stick) return;
  stick = false;
  autoScroll = false;
}
// 手机上手指滑是一点点滚的：以前刚往上滚几像素，还离底不到 30 像素，就又被算成「跟到最新」，
// 下一条弹幕一来又被拽回最底下，看起来就是滑不动（2026-11-12 修）。
// 现在：手指按着的时候不跟随；只有往下滚到底才重新跟随，往上滚永远不会被算成跟随
// 2026-11-25 再修（B 站评论 nana 反馈）：弹幕满 300 条后每来一条都会删掉最上面的旧弹幕，浏览器为了让看着的内容不动，
// 会把滚动位置往回调，这个「往上」的滚动以前被当成人在往上翻，于是不再跟随、一直显示「↓ n 条新弹幕」。
// 现在：只有最近真的有人动过（滚轮、键盘、鼠标按下、手指滑）才算往上翻；删旧弹幕、图片撑高这些页面自己引起的滚动不算
let touching = false, lastTop = 0, userAt = 0;
const userInput = () => { userAt = performance.now(); };
for (const t of ['wheel', 'pointerdown', 'touchmove']) dmList.addEventListener(t, userInput, { passive: true });
addEventListener('keydown', userInput, true);
dmList.addEventListener('scroll', () => {
  const top = dmList.scrollTop, down = top >= lastTop;
  lastTop = top;
  if (autoScroll || touching || performance.now() < holdUntil) return;  // 自己滚到底产生的，不算人在滚
  if (down && dmList.scrollHeight - top - dmList.clientHeight < 30) { stick = true; hideNewbar(); }
  else if (!down && performance.now() - userAt < 800) stick = false;
});
dmList.addEventListener('wheel', e => { if (e.deltaY < 0) { unstick(); hoverHeld = false; } }, { passive: true });
// 鼠标停在弹幕上：先不往下滚（方便看清某一条、点名字），移开再接着跟到最新。设置 → 弹幕里能关
// 2026-11-25 修（B 站评论反馈）：以前鼠标只是放在弹幕栏上不动，也一直停着不跟，观众的新弹幕变成「↓ n 条新弹幕」，只能自己去滚。
// 现在：鼠标在弹幕上动的时候才停；停着不动 2 秒就接着跟到最新；停的时候不弹「新弹幕」条
let hoverHeld = false, hoverMoveAt = 0;
function hoverResume() { if (!hoverHeld) return; hoverHeld = false; stick = true; toBottom(); hideNewbar(); }
dmList.addEventListener('mousemove', () => {
  hoverMoveAt = performance.now();
  if (cfg.dm.hoverPause && stick && !touching && !hoverHeld) { hoverHeld = true; stick = false; }
});
dmList.addEventListener('mouseleave', hoverResume);
setInterval(() => { if (hoverHeld && performance.now() - hoverMoveAt > 2000) hoverResume(); }, 500);
dmList.addEventListener('touchstart', e => { touchY = e.touches[0].clientY; touching = true; unstick(); }, { passive: true });
dmList.addEventListener('touchmove', e => { if (e.touches[0].clientY > touchY + 3) unstick(); }, { passive: true });
const touchEnd = () => { touching = false; if (dmList.scrollHeight - dmList.scrollTop - dmList.clientHeight < 30) { stick = true; hideNewbar(); } };
dmList.addEventListener('touchend', touchEnd, { passive: true });
dmList.addEventListener('touchcancel', touchEnd, { passive: true });
dmList.addEventListener('pointerdown', e => { if (e.offsetX > dmList.clientWidth) unstick(); });  // 按住滚动条
// 表情图片晚一点加载完会把高度撑高，跟随时再滚到底
dmList.addEventListener('load', e => { if (stick && !e.target.classList?.contains('avf')) toBottom(); }, true);  // 头像框图大小固定，加载完不用再滚
$('newbar').onclick = () => { stick = true; toBottom(); hideNewbar(); };
// 高亮关键词（设置里改），弹幕筛选（弹幕面板右上角选）
const hlWords = () => String(cfg.hlWords || '').toLowerCase().split(/[\s,，、;；]+/).filter(Boolean);
function dmPass(d) {
  const f = cfg.dmFilter;
  if (f === 'guard') return !!d.guard;
  if (f === 'medal') {
    const myRoom = S.room.room_real || S.room_id;
    return d.medal_level >= cfg.dmMedalMin && (!d.medal_room || !myRoom || d.medal_room === myRoom);
  }
  if (f === 'nobot') return !(S.bot_uids || []).includes(d.uid);
  if (f === 'hl') return hlWords().some(w => String(d.text).toLowerCase().includes(w));
  return true;
}
const dmMatch = d => dmPass(d) && (!dmQuery || String(d.name).toLowerCase().includes(dmQuery) || String(d.text).toLowerCase().includes(dmQuery));
// 新弹幕先攒着，每一帧画面最多更新一次（刷屏时一秒几十条也只排一次版）
let dmPending = [], dmQueued = false;
function addDm(d) {
  if (!dmMatch(d)) return;
  dmPending.push(d);
  if (!dmQueued) { dmQueued = true; frame(flushDm); }
}
function flushDm() {
  dmQueued = false;
  if (!dmPending.length) return;
  const items = dmPending.slice(-300);
  dmPending = [];
  dmList.querySelector('.empty')?.remove();
  const tpl = document.createElement('template');
  tpl.innerHTML = items.map(dmHtml).join('');
  // 一下来很多条（刷屏）时不做动画，省 CPU；平常每条都轻轻滑进来
  if (items.length <= 6) for (const el of tpl.content.children) el.classList.add('new');
  dmList.append(tpl.content);
  if (stick) {
    // 只数一次再删，不在循环里反复查整列（刷屏时省 CPU）
    const rows = dmList.querySelectorAll(':scope > .dm'), extra = rows.length - 300;
    if (extra > 0) {
      autoScroll = true;  // 删旧弹幕引起的滚动不算人在翻（glideBottom 滑完会放开）
      for (let k = 0; k < extra; k++) rows[k].remove();
      olderFrom(rows[extra].dataset.i, true);  // 删掉的旧弹幕往上翻还能再加载回来
    }
    glideBottom();
  } else {
    // 在往上翻看时先不删旧的，免得看着的内容往上跳
    while (dmList.children.length > 1500) dmList.firstElementChild.remove();
    if (hoverHeld) return;  // 只是鼠标停在上面：一会儿自己会接着跟，不用提示
    newCount += items.length;
    $('newbar').textContent = `↓ ${newCount} 条新弹幕`;
    $('newbar').style.display = 'block';
    { const p = $('p-dm').getBoundingClientRect(), l = dmList.getBoundingClientRect(); $('newbar').style.bottom = Math.max(10, p.bottom - l.bottom + 10) + 'px'; }  // 贴着列表底边，不盖住发弹幕框
  }
}
// 本场全部弹幕都存在电脑上：网页里只放最近一段，往上翻到顶会接着加载更早的；搜索也是搜整场
const DMV = { more: false, next: 0, loading: false, seq: 0 };
function olderFrom(i, more) {
  DMV.next = i === '' || i == null ? 0 : Number(i);
  DMV.more = !!more && DMV.next > 0;
  dmList.querySelector('.dmmore')?.remove();
  if (DMV.more) dmList.insertAdjacentHTML('afterbegin', '<button class="btn sm dmmore">↑ 更早的弹幕</button>');
}
async function loadOlder() {
  if (DMV.loading || !DMV.more) return;
  DMV.loading = true;
  const seq = DMV.seq;
  try {
    const p = new URLSearchParams({ before: DMV.next, limit: 200 });
    if (dmQuery) p.set('q', dmQuery);
    const j = await (await fetch('api/dm?' + p, { cache: 'no-store' })).json();
    if (seq !== DMV.seq) return;  // 这期间换了搜索词，结果作废
    const items = j.items.filter(dmPass);
    const h = dmList.scrollHeight, top = dmList.scrollTop;
    dmList.querySelector('.empty')?.remove();
    dmList.querySelector('.dmmore')?.remove();
    dmList.insertAdjacentHTML('afterbegin', items.map(dmHtml).join(''));
    olderFrom(j.next, j.more);
    if (top > 0 || !stick) dmList.scrollTop = top + (dmList.scrollHeight - h);  // 看着的内容不跳
    if (dmQuery) $('dmn').textContent = `${dmList.querySelectorAll(':scope > .dm').length}${DMV.more ? '+' : ''} 条`;
  } catch {} finally { DMV.loading = false; }
}
dmList.addEventListener('scroll', () => { if (dmList.scrollTop < 80 && !autoScroll) loadOlder(); });
dmList.addEventListener('click', e => { if (e.target.closest('.dmmore')) { e.stopPropagation(); loadOlder(); } });
async function renderDm() {
  dmPending = [];
  const seq = ++DMV.seq;
  const filtering = dmQuery || (cfg.dmFilter && cfg.dmFilter !== 'all');
  let arr, more = !!S.dm_more, next = S.dm[0]?.i;
  if (dmQuery && !S.demo) {
    // 搜索：问电脑要整场里搜到的
    dmList.innerHTML = '<div class="empty">搜索中…</div>';
    try {
      const j = await (await fetch('api/dm?' + new URLSearchParams({ q: dmQuery, limit: 200 }), { cache: 'no-store' })).json();
      if (seq !== DMV.seq) return;
      arr = j.items.filter(dmPass); more = j.more; next = j.next;
    } catch { if (seq !== DMV.seq) return; arr = S.dm.filter(dmMatch); }
  } else arr = S.dm.filter(dmMatch);
  dmList.innerHTML = arr.length ? arr.map(dmHtml).join('') : `<div class="empty">${filtering ? '没有匹配的' : '暂无弹幕'}</div>`;
  olderFrom(dmQuery ? next : arr[0]?.i ?? next, more);
  $('dmn').textContent = filtering ? `${arr.length}${DMV.more ? '+' : ''} 条` : '';
  stick = true; toBottom(); hideNewbar();
}
// 其它面板（最新的在最上面）刷新时：如果正往下翻着看，保持看到的内容不动
// 只有之前没出现过的那几条才淡入，整个列表重画时不会一闪一闪
// 2026-11-20 修：切页签（上舰 → 全部）、改门槛时，以前的礼物会被当成新的一起发光。
// 现在：这个列表以前出现过的都不算新；带时间（data-t）的，10 秒以前的也不算新
function setList(el, html) {
  const top = el.scrollTop, h = el.scrollHeight, prev = el._keys, seen = el._seen || (el._seen = new Set()), now = Date.now() / 1000;
  el.innerHTML = html;
  const keys = new Set();
  for (const ch of el.children) {
    const k = ch.dataset.k;
    if (!k) continue;
    keys.add(k);
    const old = ch.dataset.t && now - Number(ch.dataset.t) > 10;
    if (prev && !prev.has(k) && !seen.has(k) && !old) ch.classList.add('new');
    seen.add(k);
  }
  if (seen.size > 3000) el._seen = new Set(keys);
  el._keys = keys;
  if (top > 4) el.scrollTop = top + (el.scrollHeight - h);
}
let dmSearchT;
$('dmsearch').addEventListener('input', e => { clearTimeout(dmSearchT); dmSearchT = setTimeout(() => { dmQuery = e.target.value.trim().toLowerCase(); renderDm(); }, 250); });
$('dmfilter').value = cfg.dmFilter;
$('dmfilter').onchange = e => { cfg.dmFilter = e.target.value; saveCfg(); renderDm(); };
$('screadall').onclick = () => { S.scs.forEach(s => scRead.add(String(s.id))); saveScRead(); renderSc(); if (scSynced()) window._ws?.send(JSON.stringify({ cmd: 'sc_read_all' })); };

function renderSc() {
  const unread = S.scs.filter(s => !scRead.has(String(s.id))).length;
  $('scn').textContent = S.scs.length ? `${S.scs.length} 条${unread ? ` · 未读 ${unread}` : ''}${S.admin ? ` · ${yuan(S.flow.sc)}` : ''}` : '';
  $('screadall').style.display = unread ? '' : 'none';
  // 还在置顶的排最上面（跟 B 站一样），其余按时间新的在上
  const now = Date.now() / 1000;
  const rd = s => scRead.has(String(s.id));
  // 置顶时间到了仅淡化外观，不改变已读或回应状态（可选）
  // 到时淡化仅影响外观，既不标为已读，也不标为已回应。
  const list = S.scs.filter(s => !(cfg.sc.min > 0) || s.price >= cfg.sc.min).sort((a, b) => (cfg.sc.unreadTop ? rd(a) - rd(b) : 0) || ((b.end > now) - (a.end > now)) || b.t - a.t);
  setList($('sclist'), list.length ? list.map(s => scHtml(s, true)).join('') : `<div class="empty${S.scs.length ? '' : ' xw'}">${S.scs.length ? `没有 ¥${cfg.sc.min} 以上的 SC` : '暂无 SC'}</div>`);
}
// 倒计时每秒走一下；有 SC 到时间了就重新排一次
setInterval(() => {
  let expired = false;
  for (const el of document.querySelectorAll('#sclist .sc[data-end]')) {
    const end = Number(el.dataset.end), left = end - Date.now() / 1000;
    if (left <= 0) { expired = true; continue; }
    el.querySelector('.left').textContent = scLeft(end);
    el.querySelector('.bar i').style.transform = `scaleX(${left / Number(el.dataset.total)})`;  // 2026-11-21 省 CPU：改宽度每帧都要重新排版，缩放交给显卡
  }
  if (expired) renderSc();
}, 1000);
// SC 上的 ▶：马上把这条再读一遍（朗读关着也读），正在读别的就先停下
document.addEventListener('click', e => {
  const b = e.target.closest('[data-saysc]');
  if (!b) return;
  e.stopPropagation();
  const s = [...S.scs, ...(H.detail?.scs || [])].find(x => String(x.id) === b.dataset.saysc);
  if (s) sayNow(scText(s));
}, true);
document.addEventListener('click', e => {
  const b = e.target.closest('[data-read]');
  if (!b) return;
  e.stopPropagation();
  const id = b.dataset.read;
  const was = scRead.has(id);
  if (was) scRead.delete(id); else scRead.add(id);
  if (scSynced()) window._ws?.send(JSON.stringify({ cmd: 'sc_read', id, read: !was }));
  saveScRead(); renderSc();
}, true);

// 礼物图：刚送来的几秒播 B 站的动图，之后换回静态小图（2026-11-18）
const GIFT_ANIM_MS = 5000;
function giftIcon(g) {
  const moving = cfg.giftAnim !== false && g.anim && g._at && Date.now() - g._at < GIFT_ANIM_MS;
  const src = moving ? g.anim : g.img;
  return src ? `<img class="gi${moving ? ' moving' : ''}" src="img?u=${encodeURIComponent(src)}">` : '';
}
// 大礼物特效（2026-11-18）：大额礼物在礼物栏中间播一次，4 秒左右收起；一下来好几个就排队
// 有 B 站官方满屏特效（大多数 10 元以上礼物都有）就播官方的高清特效视频；没有或加载失败就用礼物动图（原图 140 像素）放大
const giftFxQueue = [];
let giftFxBusy = false;
function bigGiftFx(g) {
  if (!g.anim && !g.fx && !g._guard) return;
  giftFxQueue.push(g);
  if (giftFxQueue.length > 5) giftFxQueue.shift();
  if (!giftFxBusy) nextGiftFx();
}
function nextGiftFx() {
  const g = giftFxQueue.shift(), panel = $('p-gift'), list = $('giftlist');  // 放在礼物栏里，不挡弹幕
  if (!g || !panel || !panel.offsetParent) { giftFxBusy = false; return; }
  giftFxBusy = true;
  const fx = document.createElement('div');
  fx.className = 'giftfx';
  fx.style.top = list.offsetTop + 'px';
  if (g._guard) {
    // 上舰：先放我们自己做的（锚徽章放大 + 光圈 + 用户画的上舰横幅，1 总督 2 提督 3 舰长）；
    // 有 B 站官方上舰特效（恭喜舰长登船…）的，视频一能播就换成官方的，中间那条写上名字
    const lv = [1, 2, 3].includes(g.level) ? g.level : 3;
    fx.className = 'giftfx guardfx l' + lv;
    fx.innerHTML = `<div class="rays"></div><div class="spark"></div><img class="gbig" src="/static/art/guard${lv}.png?v=2" alt="" onerror="this.remove()">`
      + `<div class="gban" style="background-image:url(/static/art/banner${lv}.png)"><div class="gbt"><b>${esc(g.name)}</b><span>开通了${esc(g.level_name || '舰长')} × ${g.num || 1}${esc(g.unit || '月')}</span></div></div><canvas class="vap"></canvas>`;
    panel.appendChild(fx);
    let done = false, stop = () => {}, timer;
    const finish = () => { if (done) return; done = true; fx.classList.add('out'); setTimeout(() => { stop(); fx.remove(); nextGiftFx(); }, 600); };
    timer = setTimeout(finish, g.fx ? 6000 : 4400);
    if (g.fx && g.fxj) vapPlay(fx.querySelector('canvas.vap'), g.fx, g.fxj, guardSlotImg(g), [0.766, 0.8]).then(r => {  // 官方上舰特效结尾自带「3秒后关闭」（在画面 77%–80% 高的地方），盖掉
      if (done) { r.stop(); return; }
      stop = r.stop; fx.classList.add('vapon'); clearTimeout(timer);
      timer = setTimeout(finish, Math.min(12000, Math.max(2500, r.dur * 1000 - 200)));
      r.video.onended = () => { clearTimeout(timer); finish(); };
    }).catch(() => {});
    return;
  }
  // 下面一条横幅：头像 + 名字 投喂 礼物 + 礼物小图，样子仿 B 站直播间
  fx.innerHTML = `<div class="rays"></div><div class="spark"></div>${g.anim ? `<img class="big" src="img?u=${encodeURIComponent(g.anim)}&s=big" alt="">` : ''}<canvas class="vap"></canvas>` +
    `<div class="gtw"><div class="gt">${avatar(g.face, g.name, g.guard, 26)}<span class="who">${esc(g.name)}</span><span>投喂</span><b>${esc(g.gift)}</b>${g.num > 1 ? `<span>×${g.num}</span>` : ''}${g.img ? `<img class="gi" src="img?u=${encodeURIComponent(g.img)}" alt="">` : ''}</div><img class="clap" src="/static/art/xw-clap.webp" alt="" onerror="this.remove()"></div>`;
  panel.appendChild(fx);
  let done = false, stop = () => {}, timer;
  const finish = () => {
    if (done) return;
    done = true; fx.classList.add('out');
    setTimeout(() => { stop(); fx.remove(); nextGiftFx(); }, 600);
  };
  timer = setTimeout(finish, g.anim ? 4000 : 6000);  // 只有特效没有动图时多等一会儿让视频加载
  if (g.fx && g.fxj) vapPlay(fx.querySelector('canvas.vap'), g.fx, g.fxj).then(r => {
    if (done) { r.stop(); return; }
    stop = r.stop; fx.classList.add('vapon');  // 视频开始了：换下放大的小图，按视频长短收起
    clearTimeout(timer); timer = setTimeout(finish, Math.min(12000, Math.max(2500, r.dur * 1000 - 200)));
    r.video.onended = () => { clearTimeout(timer); finish(); };
  }).catch(() => {});
}
// 播 B 站带透明通道的特效 mp4：json 里 rgbFrame 是彩色那块、aFrame 是透明度那块（灰度），用 WebGL 拼成透明画面
const vapCache = new Map();
async function vapPlay(cv, src, conf, srcImg, cut) {  // cut = [上, 下]：这一条（画面高度的比例）不画，用来盖掉视频里自带的字
  const meta = await (await fetch(conf, { referrerPolicy: 'no-referrer' })).json(), info = meta.info;
  const gl = cv.getContext('webgl', { premultipliedAlpha: false, alpha: true, antialias: false });
  if (!gl || !info || !info.rgbFrame || !info.aFrame) throw new Error('vap');
  // B 站视频带别的网站来源会 403，所以不带来源先整段拿下来（几百 KB 到 2 MB），再交给 video
  let blob = vapCache.get(src);  // 同一个礼物再送不用重新下载（只留最近 6 个）
  if (!blob) {
    const r = await fetch(src, { referrerPolicy: 'no-referrer' });
    if (!r.ok) throw new Error('vap');
    blob = await r.blob(); vapCache.set(src, blob);
    if (vapCache.size > 6) vapCache.delete(vapCache.keys().next().value);
  }
  const v = document.createElement('video'), url = URL.createObjectURL(blob);
  v.muted = true; v.playsInline = true; v.preload = 'auto'; v.src = url;
  const OW = info.w || info.rgbFrame[2], OH = info.h || info.rgbFrame[3];
  cv.width = info.rgbFrame[2]; cv.height = info.rgbFrame[3]; gl.viewport(0, 0, cv.width, cv.height);
  const sh = (type, code) => { const x = gl.createShader(type); gl.shaderSource(x, code); gl.compileShader(x); return x; };
  const pg = gl.createProgram();
  gl.attachShader(pg, sh(gl.VERTEX_SHADER, 'attribute vec2 p;attribute vec2 c;attribute vec2 a;attribute vec2 o;varying vec2 vc;varying vec2 va;varying vec2 vo;void main(){vc=c;va=a;vo=o;gl_Position=vec4(p,0.,1.);}'));
  // 可替换的图（比如上舰特效里写名字的那条）：在 rect 那块按 mrect 里的遮罩把自己画的图叠上去
  gl.attachShader(pg, sh(gl.FRAGMENT_SHADER, 'precision mediump float;uniform sampler2D t;uniform sampler2D s;uniform float on;uniform vec4 rect;uniform vec4 mrect;uniform vec2 cut;varying vec2 vc;varying vec2 va;varying vec2 vo;'
    + 'void main(){vec4 col=vec4(texture2D(t,vc).rgb,texture2D(t,va).r);'
    + 'if(on>.5){vec2 lp=(vo-rect.xy)/rect.zw;if(lp.x>=0.&&lp.y>=0.&&lp.x<=1.&&lp.y<=1.){float m=texture2D(t,mrect.xy+lp*mrect.zw).r;vec4 sx=texture2D(s,lp);float k=sx.a*m;float oa=k+col.a*(1.-k);col=vec4((sx.rgb*k+col.rgb*col.a*(1.-k))/max(oa,.001),oa);}}'
    + 'if(vo.y>cut.x&&vo.y<cut.y)col.a=0.;gl_FragColor=col;}'));
  gl.linkProgram(pg);
  if (!gl.getProgramParameter(pg, gl.LINK_STATUS)) throw new Error('vap');
  gl.useProgram(pg);
  const W = info.videoW, H = info.videoH;
  const quad = f => { const [x, y, w, h] = f, l = x / W, r = (x + w) / W, t = y / H, b = (y + h) / H; return [l, t, l, b, r, t, r, b]; };
  const attr = (name, data) => {
    const loc = gl.getAttribLocation(pg, name); if (loc < 0) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer()); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  };
  attr('p', [-1, 1, -1, -1, 1, 1, 1, -1]); attr('c', quad(info.rgbFrame)); attr('a', quad(info.aFrame)); attr('o', [0, 0, 0, 1, 1, 0, 1, 1]);
  const tex = (unit, img) => {
    gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
    for (const [k, val] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, val);
    if (img) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
  };
  const U = n => gl.getUniformLocation(pg, n);
  // 特效里有可替换的图、而且我们给了图：记下每一帧它在哪
  const slot = srcImg && Array.isArray(meta.src) && meta.src[0] && Array.isArray(meta.frame) ? new Map() : null;
  if (slot) for (const f of meta.frame) for (const o of f.obj || []) if (String(o.srcId) === String(meta.src[0].srcId)) slot.set(f.i, o);
  tex(1, slot ? srcImg : null); tex(0, null);
  gl.uniform1i(U('t'), 0); gl.uniform1i(U('s'), 1); gl.uniform1f(U('on'), 0); gl.uniform2f(U('cut'), cut ? cut[0] : 2, cut ? cut[1] : 2);
  gl.clearColor(0, 0, 0, 0);
  let alive = true;
  const draw = (now, md) => {
    if (!alive) return;
    if (v.readyState >= 2) {
      if (slot) {
        const o = slot.get(Math.floor(((md && md.mediaTime) ?? v.currentTime) * (info.fps || 30) + 0.001));
        gl.uniform1f(U('on'), o ? 1 : 0);
        if (o) { const [x, y, w, h] = o.frame, [mx, my, mw, mh] = o.mFrame; gl.uniform4f(U('rect'), x / OW, y / OH, w / OW, h / OH); gl.uniform4f(U('mrect'), mx / W, my / H, mw / W, mh / H); }
      }
      gl.activeTexture(gl.TEXTURE0);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, v); gl.clear(gl.COLOR_BUFFER_BIT); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
    if (!v.ended) v.requestVideoFrameCallback ? v.requestVideoFrameCallback(draw) : requestAnimationFrame(draw);
  };
  const stop = () => { alive = false; v.pause(); v.removeAttribute('src'); v.load(); URL.revokeObjectURL(url); gl.getExtension('WEBGL_lose_context')?.loseContext(); };
  try {
    await new Promise((ok, bad) => { v.oncanplay = ok; v.onerror = bad; setTimeout(bad, 8000); });
    await v.play();
  } catch (e) { stop(); throw e; }
  draw();
  return { video: v, dur: v.duration || info.f / info.fps || 4, stop, slot: meta.src && meta.src[0] };
}
// 上舰特效中间那条：画一张「名字 开通了舰长」的图交给特效（大小跟特效里留的位置一样）
function guardSlotImg(g, w = 495, h = 94) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const k = c.getContext('2d');
  k.textAlign = 'center'; k.textBaseline = 'middle'; k.fillStyle = '#fff';
  k.shadowColor = 'rgba(0,0,0,.55)'; k.shadowBlur = 6;
  const sub = `开通了${g.level_name || '舰长'} ${g.num || 1}${g.unit || '月'}`;
  let name = String(g.name || ''), fs = Math.round(h * 0.4);
  k.font = `700 ${fs}px "Microsoft YaHei", "PingFang SC", sans-serif`;
  while (name.length > 1 && k.measureText(name).width > w * 0.92) name = name.slice(0, -2) + '…';
  k.fillText(name, w / 2, h * 0.33);
  k.font = `600 ${Math.round(h * 0.26)}px "Microsoft YaHei", "PingFang SC", sans-serif`;
  k.fillText(sub, w / 2, h * 0.76);
  return c;
}
let gfxGuardLv = 3;
$('gfxguard').onclick = async () => {
  const lv = gfxGuardLv; gfxGuardLv = lv === 1 ? 3 : lv - 1;  // 舰长 → 提督 → 总督 轮着看
  let fx = {};
  try { fx = (await (await fetch('api/guard_fx')).json())[lv] || {}; } catch {}
  bigGiftFx({ _guard: true, level: lv, level_name: { 1: '总督', 2: '提督', 3: '舰长' }[lv], num: 1, unit: '月', name: '预览的观众', face: '', fx: fx.fx, fxj: fx.fxj });
};
$('gfxprev').onclick = async () => {
  try {
    const list = await (await fetch('api/gift_anims')).json();
    const g = list.find(x => x.name === '告白花束') || list.find(x => x.fx) || list[0];
    if (g) bigGiftFx({ anim: g.anim, fx: g.fx, fxj: g.fxj, img: g.img, gift: g.name, name: '预览的观众', num: 1, face: '', guard: 0 });
  } catch {}
};
// 设置 → 提醒 →「预览动图」：摆几个常见礼物的动图看看，再点一下收起
$('gaprev').onclick = async () => {
  const box = $('gaprevbox');
  if (box.childElementCount) { box.innerHTML = ''; return; }
  box.innerHTML = '<div class="empty">加载中…</div>';
  try {
    const list = await (await fetch('api/gift_anims')).json();
    box.innerHTML = list.length ? list.map(g => `<figure><img src="img?u=${encodeURIComponent(g.anim)}" alt=""><figcaption>${esc(g.name)}</figcaption></figure>`).join('')
      : '<div class="empty">还没拿到动图列表，稍后再试</div>';
  } catch { box.innerHTML = '<div class="empty">没连上，稍后再试</div>'; }
};
let rankRange = 'session';
const rankCache = {};
let rankLoading = '';
async function loadRank(range) {
  if (rankLoading === range || !S.admin) return;
  rankLoading = range;
  try {
    const j = await (await fetch('api/gift_rank?range=' + range)).json();
    rankCache[range] = { at: Date.now(), items: j.items || [] };
  } catch { rankCache[range] = { at: Date.now() - 20000, items: [] }; }
  rankLoading = '';
  if (giftTab === 'rank' && rankRange === range) renderGifts();
}
$('giftlist').addEventListener('click', e => {
  const t = e.target.closest('[data-rr]');
  if (!t) return;
  rankRange = t.dataset.rr;
  renderGifts();
});
// 礼物 / 上舰「已感谢」打勾（2026-11-18）：点一下这一条变淡，再点取消
const thxBtn = g => S.admin && g.id ? `<button class="gthx${g.thanked ? ' on' : ''}" data-thx="${esc(String(g.id))}" title="${g.thanked ? '已感谢（点一下取消）' : '标成已感谢'}">✓</button>` : '';
$('giftlist').addEventListener('click', e => {
  const b = e.target.closest('[data-thx]'); if (!b) return;
  e.stopPropagation();
  const it = [...S.gifts, ...S.guards].find(x => String(x.id) === b.dataset.thx); if (!it) return;
  const done = !it.thanked; if (done) it.thanked = true; else delete it.thanked; renderGifts();
  window._ws?.send(JSON.stringify({ cmd: 'gift_thank', id: String(it.id), done }));
}, true);
function renderGifts() {
  const el = $('giftlist');
  if (giftTab === 'guard') {
    setList(el, S.guards.length ? S.guards.slice().reverse().map(guardRow).join('') : '<div class="empty xw">暂无上舰</div>');
    return;
  }
  if (giftTab === 'rank') {
    // 本场：每个人送了多少由服务器算好（礼物 + SC + 上舰，原价）；本周 / 本月（2026-11-18）：服务器把历史场次和下播期间的加起来
    if (!S.admin) rankRange = 'session';  // 周榜月榜只给管理身份看（有金额）
    const bar = !S.admin ? '' : `<div class="rankrange">${[['session', '本场'], ['week', '本周'], ['month', '本月']].map(([k, t]) => `<span class="tab${rankRange === k ? ' on' : ''}" data-rr="${k}">${t}</span>`).join('')}</div>`;
    let arr;
    if (rankRange === 'session') arr = S.users.filter(u => u.spend > 0).sort((a, b) => b.spend - a.spend).slice(0, 50);
    else {
      const c = rankCache[rankRange];
      if (!c || Date.now() - c.at > 30000) loadRank(rankRange);
      if (!c) { setList(el, bar + '<div class="empty">加载中…</div>'); return; }
      arr = c.items;
    }
    setList(el, bar + (arr.length ? arr.map(rankRow).join('') : '<div class="empty">暂无</div>'));
    return;
  }
  // 2026-11-25：上一段下播带过来的，点了感谢就不再列（「下播期间」页里还有）
  const carried = g => g.source === '下播' && g.thanked && g.t < (S.session_start || 0);
  const items = [
    ...S.gifts.filter(g => (g.yuan == null || g.yuan >= cfg.giftMin) && !carried(g)).map(g => ({ t: g.t, html: `<div class="gift${g.yuan >= 50 || g.big ? ' big' : ''}" data-uid="${g.uid}" data-k="${g.id}" data-t="${g.t}">${avatar(g.face, g.name, g.guard)}<div class="body"><div class="n"><span class="nm">${esc(g.name)}</span>${g.plat ? platTag(g.plat) : ''}${g.source === '下播' ? '<span class="tag off" title="下播期间送的">下播</span>' : ''}</div><div class="g">${g.blind ? `${esc(g.blind)} 爆出 ${esc(g.gift)}` : `投喂 ${esc(g.gift)}`} × ${g.num} · ${g.source === '下播' ? fmtMd(g.t) : hhmm(g.t)}</div></div>${giftIcon(g)}${thxBtn(g)}${g.yuan == null ? '' : `<span class="y">${yuan(g.yuan)}</span>`}</div>` })),
    ...S.guards.filter(g => !carried(g)).map(g => ({ t: g.t, html: guardRow(g).slice(0, -6) + thxBtn(g) + '</div>' })),
  ].sort((a, b) => b.t - a.t).slice(0, 200);
  setList(el, items.length ? items.map(x => x.html).join('') : '<div class="empty xw">暂无礼物</div>');
}

const ACT = { enter: '进入直播间', follow: '关注了主播', share: '分享了直播间', like: '点赞了直播间' };
function enterRow(e) {
  const g = e.guard || userOf(e.uid)?.guard || 0;
  return `<div class="row" data-uid="${e.uid}" data-k="e${e.uid}-${e.t}-${e.kind}">${avatar(e.face, e.name, g, 24)}<span class="n">${esc(e.name)}</span>${e.plat ? platTag(e.plat) : ''}${g ? `<span class="tag g${g}" title="${GN[g]}">${GS[g]}</span>` : ''}<span class="act ${e.kind}">${ACT[e.kind] || ''}</span><span class="r">${hhmm(e.t)}</span></div>`;
}
function renderEnters() {
  setText($('entern'), S.enters.length ? `${S.enters.length} 条` : '');
  setList($('enterlist'), S.enters.length ? S.enters.slice(-100).reverse().map(enterRow).join('') : '<div class="empty">暂无</div>');
}
// 进房很频繁：只把新的一条插到最上面，不整列重画
let enterPending = [], enterQueued = false;
// 进房并入弹幕：弹幕栏顶上闪一条，几秒后消失；一下子进来很多人只显示最新的
let enterTipT = 0, epT = 0;
// 进房提示的内容：名字 + 做了什么；cfg.enterTip.avatar 关掉就不带头像
function enterTipHtml(e) {
  const g = e.guard, what = ACT[e.kind] || '进入直播间';
  return `${cfg.enterTip.avatar ? avatar(e.face, e.name, g, 20) : ''}<b>${esc(e.name)}</b>${e.plat ? platTag(e.plat) : ''}${g ? `<span class="tag g${g}">${GS[g]}</span>` : ''}<span>${what}</span>`;
}
const enterTipCls = e => (e.guard ? ' g' + e.guard : '') + (e.kind === 'follow' ? ' follow' : '');
function enterWanted(e) {
  const T = cfg.enterTip;
  return T[e.kind === 'follow' ? 'follow' : e.kind === 'share' ? 'share' : e.kind === 'like' ? 'like' : 'enter'] !== false && (!T.guardOnly || e.guard);
}
// 进房提示（2026-11-18 重做）：放在弹幕列表外面的一条细栏里，不盖住弹幕，也不插进弹幕列表
// （以前「混在弹幕里」会插进列表、消失时挪动滚动位置，雾幕当成「人往上翻了」就不再跟到最新，看起来像卡住）
// flow（默认）= 弹幕区最下面常驻一条小栏，字停几秒淡出；top / bottom = 平时收起，有人进来时在顶上 / 底下弹出，停几秒收起
const tipMs = () => (Number(cfg.enterTip.sec) || 3.5) * 1000;
const tipBox = () => (dmList.closest('#p-dm') || dmList.parentElement).querySelector('#entertip');
function setTipPos() {
  const tip = tipBox();
  if (!tip) return null;
  const pos = cfg.enterMerge ? cfg.enterTip.pos : 'off';
  if (tip.dataset.pos !== pos) {
    tip.dataset.pos = pos;
    tip.classList.remove('show');
    if (pos === 'top') dmList.before(tip); else dmList.after(tip);
  }
  return tip;
}
// 细栏弹出 / 收起会改变弹幕列表的高度：这段时间的滚动不算人在翻，原来跟着最新的就继续跟着
function holdScroll(follow) {
  holdUntil = performance.now() + 450;
  if (!follow) return;
  stick = true;
  frame(() => { if (stick) toBottom(); });
  setTimeout(() => { if (stick) toBottom(); }, 460);
}
function flashEnter(e) {
  if (!enterWanted(e)) return;
  const tip = setTipPos();
  if (!tip || tip.dataset.pos === 'off') return;
  const pop = tip.dataset.pos !== 'flow';
  tip.innerHTML = `<div class="et${enterTipCls(e)}">${enterTipHtml(e)}</div>`;
  if (pop && !tip.classList.contains('show')) holdScroll(stick);
  tip.classList.add('show');
  clearTimeout(enterTipT);
  enterTipT = setTimeout(() => {
    if (pop) holdScroll(stick);
    tip.classList.remove('show');
  }, tipMs());
}
setTipPos();
// 设置里的预览：改一下选项就按新样子演一遍
function previewEnter() {
  const box = $('enterprev'), tip = $('eptip'), rows = box.querySelector('.ep-rows');
  $('entopts').classList.toggle('off', !cfg.enterMerge);
  setTipPos();
  const pos = cfg.enterTip.pos;
  const e = { name: '路过的舰长', face: '', guard: cfg.enterTip.guardOnly || !cfg.enterTip.enter ? 3 : 0, kind: !cfg.enterTip.enter && cfg.enterTip.follow ? 'follow' : 'enter' };
  clearTimeout(epT);
  tip.dataset.pos = pos;
  if (pos === 'top') rows.before(tip); else rows.after(tip);
  tip.innerHTML = `<div class="et${enterTipCls(e)}">${enterTipHtml(e)}</div>`;
  tip.classList.remove('show');
  void tip.offsetWidth;
  tip.classList.add('show');
  epT = setTimeout(() => tip.classList.remove('show'), tipMs());
}
function addEnter(e) {
  if (cfg.enterMerge) flashEnter(e);
  enterPending.push(e);
  if (!enterQueued) { enterQueued = true; requestAnimationFrame(flushEnters); }
}
function flushEnters() {
  enterQueued = false;
  const el = $('enterlist'), items = enterPending.slice(-100).reverse();
  enterPending = [];
  if (!items.length) return;
  el.querySelector('.empty')?.remove();
  const top = el.scrollTop, h = el.scrollHeight;
  const tpl = document.createElement('template');
  tpl.innerHTML = items.map(enterRow).join('');
  el._keys ??= new Set();
  for (const ch of tpl.content.children) el._keys.add(ch.dataset.k);  // 进房也很频繁，不做淡入
  el.prepend(tpl.content);
  const added = top > 4 ? el.scrollHeight - h : 0;  // 正往下翻着看：上面多出来多高，就往下挪多少
  while (el.children.length > 100) { el._keys.delete(el.lastElementChild.dataset.k); el.lastElementChild.remove(); }
  if (added) el.scrollTop = top + added;
  setText($('entern'), `${S.enters.length} 条`);
}

// 舰长名单：快到期的在最前面；到期时间带「约」的是雾幕自己记下的上舰时间估的
function guardDays(g) { return g.until ? Math.ceil((g.until - Date.now() / 1000) / 86400) : null; }
function renderGuardList() {
  const el = $('userlist'), L = (S.guardlist || []).slice();
  L.sort((a, b) => (a.until || 9e12) - (b.until || 9e12) || a.level - b.level || b.days - a.days);
  setList(el, L.length ? L.map(g => {
    const left = guardDays(g), soon = left != null && left <= 7;
    const r = left == null ? `陪伴 ${g.days} 天` : `${g.est ? '约 ' : ''}${left <= 0 ? '今天到期' : left + ' 天后到期'}<br><small>陪伴 ${g.days} 天</small>`;
    const nt = noteOf(g.uid);
    return `<div class="row" data-uid="${g.uid}" data-k="gl${g.uid}">${avatar(g.face, g.name, g.level, 26)}<span class="n">${esc(g.name)}</span><span class="tag g${g.level}" title="${GN[g.level]}">${GS[g.level]}</span>${nt ? `<span class="nt" title="${esc(nt)}">${icon('p-note')}</span>` : ''}<span class="r${soon ? ' soon' : ''}" title="${g.until ? new Date(g.until * 1000).toLocaleDateString('zh-CN') + ' 到期' + (g.est ? '（按雾幕记下的上舰时间估的）' : '') : 'B 站只告诉主播本人准确的到期时间：主播在发送框左边扫码登录自己的号后就能看到'}">${r}</span></div>`;
  }).join('') : '<div class="empty">暂无</div>');
}
function renderUsers() {
  const el = $('userlist');
  setText($('guardn'), S.guardlist?.length ? String(S.guardlist.length) : '');
  if (userTab === 'guard') { renderGuardList(); return; }
  if (userTab === 'mute') { renderMutes(); return; }
  if (userTab === 'top') {
    const top = S.room.top || [];
    setList(el, top.length ? top.map((u, i) =>
      `<div class="row" data-uid="${u.uid}" data-k="t${u.uid}"><span class="rank r${i + 1}">${i + 1}</span>${avatar(u.face, u.name, u.guard, 26)}<span class="n">${esc(u.name)}</span>${u.guard ? `<span class="tag g${u.guard}" title="${GN[u.guard]}">${GS[u.guard]}</span>` : ''}<span class="r">${u.score ? num(u.score) : ''}</span></div>`).join('')
      : '<div class="empty">暂无</div>');
    return;
  }
  const us = S.users.slice().sort((a, b) => b.last - a.last).slice(0, 150);
  setList(el, us.length ? us.map(u => {
    const bits = [];
    if (u.dm) bits.push(`弹幕${u.dm}`);
    if (u.spend) bits.push(yuan(u.spend));
    return `<div class="row" data-uid="${u.uid}" data-k="u${u.uid}">${avatar(u.face, u.name, u.guard, 24)}<span class="n">${esc(u.name)}</span>${u.guard ? `<span class="tag g${u.guard}" title="${GN[u.guard]}">${GS[u.guard]}</span>` : ''}<span class="r">${bits.join(' · ') || '来过'}<br>${hhmm(u.last)}</span></div>`;
  }).join('') : '<div class="empty">暂无</div>');
}

// 字没变就不动它，省得浏览器白白重新排版
function setText(el, v) { if (el.textContent !== v) el.textContent = v; }
let statsQueued = false;
function renderStats() {
  // 一帧最多更新一次顶部数字
  if (!statsQueued) { statsQueued = true; requestAnimationFrame(drawStats); }
}
function drawStats() {
  statsQueued = false;
  const f = S.flow, total = f.gift + f.sc + f.guard;
  setText($('income'), yuan(total / 2));
  setText($('flowdetail'), `流水 ${yuan(total)} · 礼物 ${yuan(f.gift)} · SC ${yuan(f.sc)} · 上舰 ${yuan(f.guard)}`);
  $('t-money').title = `收益 = 流水 × 50%
${$('flowdetail').textContent}`;  // 明细不占地方，鼠标停上去看
  setText($('watched'), num(S.room.watched));
  setText($('online'), num(S.room.online));
  setText($('onlinen'), S.room.online ? num(S.room.online) : '');
  setText($('users'), num(S.userCount ?? S.users.length));
  setText($('dmcount'), `弹幕 ${num(S.dmTotal ?? S.dm.length)} 条`);
  setText($('likes'), '点赞 ' + num(S.room.likes));
  setText($('title'), S.room.title || ((S.room.anchor_name || '主播') + ' 的直播间'));
  drawRoomBtns();
  const live = $('live');
  setText(live, S.room.live ? '直播中' : '未开播');
  live.classList.toggle('on', !!S.room.live);
  // 人气榜 / 分区小时榜排名（2026-11-19，B 站开播后推过来才有）
  const rp = $('rankpill'), ranks = [];
  if (S.room.live && S.room.pop_rank) ranks.push(`人气榜 ${S.room.pop_rank}`);
  if (S.room.live && S.room.area_rank) ranks.push(`${String(S.room.area_rank_name || '小时榜').replace(/小时榜$/, '')}小时榜 ${S.room.area_rank}`);
  rp.hidden = !ranks.length; setText(rp, ranks.join(' · '));
  const t = (S.room.live ? '🔴 直播中 · ' : '') + '雾幕';
  if (document.title !== t) document.title = t;
}
function tick() {
  if (!S.room.live) { $('dur').textContent = '—'; return; }
  let start = S.session_start;
  if (S.room.live_time && S.room.live_time !== '0000-00-00 00:00:00') {
    const t = Date.parse(S.room.live_time.replace(' ', 'T') + '+08:00') / 1000;
    if (t) start = t;
  }
  $('dur').textContent = dur(Date.now() / 1000 - start);
}
setInterval(tick, 10000);

function renderAll() { renderStats(); renderDm(); renderSc(); renderGifts(); renderEnters(); renderUsers(); renderReqs(); renderExtra(); tick(); }
// 可选模块：只画已经加到布局里的
const shownMod = id => cfg.layout.cols.some(c => c.items.some(it => it.id === id));
function renderExtra() {
  if (shownMod('rank')) { const a = S.users.filter(u => u.spend > 0).sort((x, y) => y.spend - x.spend).slice(0, 50); setList($('x-rank'), a.length ? a.map(rankRow).join('') : '<div class="empty">还没有人送礼</div>'); }
  if (shownMod('guards')) { setText($('xn-guards'), S.guards.length ? S.guards.length + ' 位' : ''); setList($('x-guards'), S.guards.length ? S.guards.slice().reverse().map(guardRow).join('') : '<div class="empty">本场还没有人上舰</div>'); }
  if (shownMod('top')) { const top = S.room.top || []; setList($('x-top'), top.length ? top.map((u, i) => `<div class="row" data-uid="${u.uid}" data-k="t${u.uid}"><span class="rank r${i + 1}">${i + 1}</span>${avatar(u.face, u.name, u.guard, 26)}<span class="n">${esc(u.name)}</span><span class="r">${num(u.score)}</span></div>`).join('') : '<div class="empty">暂时没有</div>'); }
  if (shownMod('follow')) { const f = S.enters.filter(e => e.kind === 'follow').slice(-100).reverse(); setText($('xn-follow'), f.length ? f.length + ' 人' : ''); setList($('x-follow'), f.length ? f.map(e => `<div class="row" data-uid="${e.uid}" data-k="f${e.uid}-${e.t}">${avatar(e.face, e.name, 0, 24)}<span class="n">${esc(e.name)}</span><span class="r">${hhmm(e.t)}</span></div>`).join('') : '<div class="empty">暂无</div>'); }
  drawClock();
}
function drawClock() {
  if (!shownMod('clock')) return;
  const d = new Date();
  setText($('clk-now'), String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'));
  setText($('clk-dur'), '本场 ' + $('dur').textContent);
}
setInterval(drawClock, 5000);
try { $('notepad').value = localStorage.getItem('xw-note') || ''; } catch {}
$('notepad').addEventListener('input', e => { try { localStorage.setItem('xw-note', e.target.value); } catch {} });

/* ---------- 自定义布局 ---------- */
// 布局 = 几列，每列从上到下几个面板；w 是列宽比例，h 是面板高度比例
function fixLayout(L) {
  const seen = new Set();
  L.cols = (Array.isArray(L.cols) ? L.cols : []).map(c => ({
    w: Number(c.w) > 0 ? Number(c.w) : 1,
    items: (Array.isArray(c.items) ? c.items : []).filter(it => PANELS[it?.id] && !seen.has(it.id) && seen.add(it.id))
      .map(it => ({ id: it.id, h: Number(it.h) > 0 ? Number(it.h) : 1 })),
  }));
  L.hidden = (Array.isArray(L.hidden) ? L.hidden : []).filter(id => PANELS[id] && !seen.has(id) && seen.add(id));
  if (!L.cols.length) L.cols.push({ w: 1, items: [] });
  for (const id of Object.keys(PANELS)) if (!seen.has(id)) { if (EXTRA.includes(id)) L.hidden.push(id); else L.cols[L.cols.length - 1].items.push({ id, h: 1 }); }
  L.tiles = { ...DEF_LAYOUT.tiles, ...(L.tiles || {}) };
  return L;
}
const mk = (cls, attrs = {}) => { const e = document.createElement('div'); e.className = cls; Object.assign(e.dataset, attrs); return e; };
function renderLayout() {
  const L = cfg.layout, main = $('main'), pool = $('pool');
  const keepScroll = stick;
  const away = id => pipWin && id === 'dm';  // 弹幕在小窗里，先不搬回来
  for (const id of Object.keys(PANELS)) if (!away(id)) pool.appendChild($('p-' + id));
  main.innerHTML = '';
  L.cols.forEach((col, ci) => {
    if (ci > 0) main.appendChild(mk('vsplit', { ci: ci - 1 }));
    const c = mk('colw', { ci });
    c.style.flex = `${col.w} 1 0`;
    col.items.forEach((it, ii) => {
      if (ii > 0) c.appendChild(mk('hsplit', { ci, ii: ii - 1 }));
      if (away(it.id)) {
        const ph = mk('panel popph');
        ph.innerHTML = '<div class="empty">' + icon('popout') + ' 弹幕在小窗里<br><button class="btn sm" data-popback>收回来</button></div>';
        ph.style.flex = `${it.h} 1 0`;
        c.appendChild(ph);
        return;
      }
      const p = $('p-' + it.id);
      p.style.flex = `${it.h} 1 0`;
      c.appendChild(p);
    });
    main.appendChild(c);
  });
  // 进房并入弹幕时：进房栏先不摆出来（布局里的位置留着，取消合并就回来）
  const ep = $('p-enter');
  ep.style.display = '';
  ep.parentElement?.querySelectorAll(':scope > .hsplit').forEach(x => x.style.display = '');
  if (cfg.enterMerge && ep.closest('#main')) {
    const col = ep.parentElement;
    ep.style.display = 'none';
    const sp = ep.previousElementSibling?.classList.contains('hsplit') ? ep.previousElementSibling : ep.nextElementSibling;
    if (sp?.classList.contains('hsplit')) sp.style.display = 'none';
    if (![...col.children].some(x => x.classList.contains('panel') && x.style.display !== 'none')) {
      col.style.display = 'none';
      const vs = col.previousElementSibling?.classList.contains('vsplit') ? col.previousElementSibling : col.nextElementSibling;
      if (vs?.classList.contains('vsplit')) vs.style.display = 'none';
    }
  }
  // 顶部数据块
  const shown = Object.keys(TILES).filter(k => L.tiles[k] && (k !== 'money' || S.admin));  // 收益只有管理身份看得到
  Object.keys(TILES).forEach(k => $('t-' + k).style.display = L.tiles[k] ? '' : 'none');
  $('stats').style.display = shown.length ? '' : 'none';
  $('stats').style.setProperty('--tiles', shown.map(k => k === 'money' ? 'minmax(0, 1.5fr)' : 'minmax(0, 1fr)').join(' ') || '1fr');
  renderLayoutBar();
  renderExtra();
  if (keepScroll) toBottom();
}
function renderLayoutBar() {
  const L = cfg.layout, box = $('laybody');
  if (!$('laydlg').classList.contains('open')) return;
  const colOf = id => L.cols.findIndex(c => c.items.some(it => it.id === id));
  const mods = Object.keys(PANELS).map(id => `<label class="lmod${colOf(id) < 0 ? ' off' : ''}"><div class="lm-t"><b>${icon('p-' + id)}${PANELS[id]}</b><small>${PANEL_TIPS[id]}</small></div>
    <span class="switch"><input type="checkbox" data-mon="${id}"${colOf(id) < 0 ? '' : ' checked'}><i></i></span></label>`).join('');
  box.innerHTML = `<p class="lhint">拖标题换位置，拖缝隙改大小</p>
    <h4>排列</h4>
    <div class="opt"><span>列数</span><span style="display:flex;gap:4px;margin-left:auto">${[1, 2, 3, 4].map(n => `<button class="chipbtn${L.cols.length === n ? ' on' : ''}" data-cols="${n}">${n} 列</button>`).join('')}</span></div>
    <div class="opt"><span>${icon('compact')} 紧凑</span><label class="switch" style="margin-left:auto"><input type="checkbox" id="lbcompact"${cfg.compact ? ' checked' : ''}><i></i></label></div>
    <div class="opt"><button class="btn sm" id="lbeqw">宽度均分</button><button class="btn sm" id="lbeqh">高度均分</button><button class="btn sm" id="layoutreset" style="margin-left:auto">恢复默认</button></div>
    <h4>模块</h4>${mods}
    <h4>顶部数据</h4>${Object.entries(TILES).filter(([k]) => k !== 'money' || S.admin).map(([k, n]) => `<label class="lmod${L.tiles[k] ? '' : ' off'}"><div class="lm-t"><b>${n}</b></div><span class="switch"><input type="checkbox" data-tile="${k}"${L.tiles[k] ? ' checked' : ''}><i></i></span></label>`).join('')}`;
  const done = () => { pruneCols(L); saveCfg(); renderLayout(); };
  box.querySelectorAll('[data-cols]').forEach(b => b.onclick = () => setCols(Number(b.dataset.cols)));
  $('lbcompact').onchange = toggleCompact;
  $('lbeqw').onclick = () => { L.cols.forEach(c => c.w = 1); done(); };
  $('lbeqh').onclick = () => { L.cols.forEach(c => c.items.forEach(it => it.h = 1)); done(); };
  $('layoutreset').onclick = () => { cfg.layout = clone(DEF_LAYOUT); saveCfg(); renderLayout(); };
  // 打开：放到面板最少的那一列；关掉：收起来
  box.querySelectorAll('[data-mon]').forEach(s => s.onchange = () => {
    const id = s.dataset.mon;
    L.cols.forEach(c => c.items = c.items.filter(it => it.id !== id));
    L.hidden = L.hidden.filter(x => x !== id);
    if (s.checked) L.cols.reduce((a, c) => c.items.length < a.items.length ? c : a, L.cols[0]).items.push({ id, h: 1 });
    else L.hidden.push(id);
    done();
  });
  box.querySelectorAll('[data-tile]').forEach(b => b.onchange = () => { L.tiles[b.dataset.tile] = b.checked; saveCfg(); renderLayout(); });
}
function setEditing(on) {
  document.body.classList.toggle('editing', on);
  $('layoutbtn').classList.toggle('on', on);
  if (!on) {
    // 空的列不要了
    const L = cfg.layout;
    if (L.cols.some(c => !c.items.length) && L.cols.some(c => c.items.length)) L.cols = L.cols.filter(c => c.items.length);
    saveCfg(); renderLayout();
  }
}
function setLay(on) { $('laydlg').classList.toggle('open', on); $('layoutbtn').classList.toggle('on', on); if (on) renderLayoutBar(); }
$('layoutbtn').onclick = () => setLay(!$('laydlg').classList.contains('open'));
$('layclose').onclick = () => setLay(false);
// 面板标题：加「?」说明，移除按钮只留 ✕
document.querySelectorAll('.panel').forEach(p => {
  const id = p.dataset.id, ttl = p.querySelector(':scope > header .ttl'), x = p.querySelector('[data-hide]');
  if (ttl && PANEL_TIPS[id]) ttl.title = PANEL_TIPS[id];  // 说明放在标题的悬停提示里，不再多占一个「?」
  if (x) { x.textContent = '✕'; x.title = '移除'; }
});
// 有空列又有不空的列时，把空列去掉
const pruneCols = L => { if (L.cols.some(c => !c.items.length) && L.cols.some(c => c.items.length)) L.cols = L.cols.filter(c => c.items.length); };
$('layoutopen').onclick = () => { closeAll(); setLay(true); };
document.addEventListener('click', e => {
  const b = e.target.closest('[data-hide]');
  if (!b) return;
  const L = cfg.layout, id = b.dataset.hide;
  L.cols.forEach(c => c.items = c.items.filter(it => it.id !== id));
  if (!L.hidden.includes(id)) L.hidden.push(id);
  saveCfg(); renderLayout();
});
// 缝隙随时都能拖（改宽窄、高矮）；按住面板标题换位置要先点「布局」
document.addEventListener('pointerdown', e => {
  if (e.button > 0) return;
  const vs = e.target.closest('.vsplit'), hs = e.target.closest('.hsplit');
  if (vs) return resizeCols(e, vs);
  if (hs) return resizeRows(e, hs);
  // 按住面板标题拖一小段就开始挪（只是点一下不会动）
  const head = e.target.closest('.panel > header');
  if (!head || e.target.closest('button, input, select, textarea, a, .tab, .pinfo')) return;
  const x0 = e.clientX, y0 = e.clientY;
  const mv = ev => { if (Math.hypot(ev.clientX - x0, ev.clientY - y0) > 6) { off(); movePanel(e, head.parentElement); } };
  const off = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', off); removeEventListener('pointercancel', off); };
  addEventListener('pointermove', mv); addEventListener('pointerup', off); addEventListener('pointercancel', off);
});
function track(e, onMove, onUp) {
  e.preventDefault();
  const move = ev => onMove(ev), up = ev => { removeEventListener('pointermove', move); removeEventListener('pointerup', up); removeEventListener('pointercancel', up); onUp(ev); };
  addEventListener('pointermove', move); addEventListener('pointerup', up); addEventListener('pointercancel', up);
}
function dragLook(bar, axis, on) {
  bar.classList.toggle('drag', on);
  document.body.classList.toggle('resizing', on);
  document.body.classList.toggle(axis, on);
}
function resizeCols(e, bar) {
  const ci = Number(bar.dataset.ci), L = cfg.layout, cols = [...$('main').querySelectorAll(':scope > .colw')];
  const px = cols.map(c => c.getBoundingClientRect().width), x0 = e.clientX, a0 = px[ci], b0 = px[ci + 1];
  const min = Math.min(200, (a0 + b0) / 2 - 1);
  dragLook(bar, 'rx', true);
  track(e, ev => {
    const a = Math.max(min, Math.min(a0 + b0 - min, a0 + ev.clientX - x0));
    px[ci] = a; px[ci + 1] = a0 + b0 - a;
    cols.forEach((c, i) => { L.cols[i].w = px[i] / 100; c.style.flex = `${L.cols[i].w} 1 0`; });
  }, () => { dragLook(bar, 'rx', false); saveCfg(); });
}
function resizeRows(e, bar) {
  const ci = Number(bar.dataset.ci), ii = Number(bar.dataset.ii);
  const col = cfg.layout.cols[ci], panels = [...$('main').querySelectorAll(`:scope > .colw[data-ci="${ci}"] > .panel`)];
  const px = panels.map(p => p.getBoundingClientRect().height), y0 = e.clientY, a0 = px[ii], b0 = px[ii + 1];
  const min = Math.min(80, (a0 + b0) / 2 - 1);
  dragLook(bar, 'ry', true);
  track(e, ev => {
    const a = Math.max(min, Math.min(a0 + b0 - min, a0 + ev.clientY - y0));
    px[ii] = a; px[ii + 1] = a0 + b0 - a;
    panels.forEach((p, i) => { col.items[i].h = px[i] / 100; p.style.flex = `${col.items[i].h} 1 0`; });
  }, () => { dragLook(bar, 'ry', false); saveCfg(); });
}
// 选列数：少了就把多出来的面板并到最后一列，多了就从面板最多的列匀一个过去
function setCols(n) {
  const L = cfg.layout;
  while (L.cols.length > n) { const c = L.cols.pop(); L.cols[L.cols.length - 1].items.push(...c.items); }
  while (L.cols.length < n) L.cols.push({ w: 1, items: [] });
  for (const c of L.cols) {
    if (c.items.length) continue;
    const donor = L.cols.reduce((a, x) => x.items.length > a.items.length ? x : a, L.cols[0]);
    if (donor.items.length > 1) c.items.push(donor.items.pop());
  }
  L.cols.forEach(c => c.w = 1);
  saveCfg(); renderLayout();
}
function movePanel(e, panel) {
  const r = panel.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
  const ph = document.createElement('div');
  ph.className = 'ph'; ph.style.height = Math.min(r.height, 220) + 'px';
  panel.before(ph);
  panel.classList.add('ghost');
  document.body.classList.add('moving');
  if (cfg.layout.cols.length < 4) $('main').appendChild(mk('colw newcol'));
  Object.assign(panel.style, { width: r.width + 'px', height: r.height + 'px', left: r.left + 'px', top: r.top + 'px' });
  track(e, ev => {
    panel.style.left = ev.clientX - dx + 'px'; panel.style.top = ev.clientY - dy + 'px';
    const col = document.elementsFromPoint(ev.clientX, ev.clientY).map(el => el.closest('.colw')).find(Boolean);
    if (!col) return;
    const others = [...col.querySelectorAll(':scope > .panel')].filter(p => p !== panel);
    const before = others.find(p => { const b = p.getBoundingClientRect(); return ev.clientY < b.top + b.height / 2; });
    if (before) { if (ph.nextElementSibling !== before) before.before(ph); }
    else if (col.lastElementChild !== ph) col.appendChild(ph);
  }, () => {
    ph.replaceWith(panel);
    panel.classList.remove('ghost');
    document.body.classList.remove('moving');
    Object.assign(panel.style, { width: '', height: '', left: '', top: '' });
    // 按现在页面上的顺序重新记布局
    const L = cfg.layout, hOf = {};
    L.cols.forEach(c => c.items.forEach(it => hOf[it.id] = it.h));
    L.cols = [...$('main').querySelectorAll(':scope > .colw')].map((c, i) => ({
      w: L.cols[i]?.w || 1,
      items: [...c.querySelectorAll(':scope > .panel')].map(p => ({ id: p.dataset.id, h: hOf[p.dataset.id] || 1 })),
    }));
    pruneCols(L);
    saveCfg(); renderLayout();
  });
}

