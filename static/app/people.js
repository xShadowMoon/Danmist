// 雾幕主页面 · 观众卡片、历史场次
// 这几个文件按顺序加载，共用同一套全局变量。加载时只能直接用前面文件里的东西，用后面文件的函数要放进回调里
/* ---------- 用户卡片 ---------- */
document.addEventListener('click', e => {
  const el = e.target.closest('[data-uid]');
  if (!el || el.closest('#card, #hist') || document.body.classList.contains('editing')) return;  // 2026-11-21 普通链接也能点开（不显示花了多少、备注、以前、禁言）
  const uid = Number(el.dataset.uid);
  if (uid) openUser(uid);
});
function openUser(uid) {
  const side = !!S.side;  // 正在看别的直播间（2026-11-21）：不显示主播这边的档案、备注、禁言
  const u = userOf(uid) || {};
  const pick = arr => arr.filter(x => x.uid === uid);
  const dms = pick(S.dm), gifts = pick(S.gifts), scs = pick(S.scs), guards = pick(S.guards);
  const top = (S.room.top || []).find(x => x.uid === uid);
  const hu = H.detail?.rank?.find(x => x.uid === uid);
  const name = u.name || dms[0]?.name || gifts[0]?.name || scs[0]?.name || top?.name || hu?.name || ('UID ' + uid);
  const face = u.face || dms[0]?.face || top?.face || hu?.face || '';
  const guard = u.guard || top?.guard || hu?.guard || 0;
  const spend = gifts.reduce((a, g) => a + g.yuan, 0) + scs.reduce((a, s) => a + s.price, 0) + guards.reduce((a, g) => a + g.yuan, 0);
  const histOf = dms => [
    ...dms.map(d => ({ t: d.t, h: `${icon('p-dm')} ${esc(d.text)}` })),
    ...gifts.map(g => ({ t: g.t, h: `${icon('p-gift')} 投喂 ${esc(g.gift)} × ${g.num}${g.yuan == null ? '' : `（${yuan(g.yuan)}）`}` })),
    ...scs.map(s => ({ t: s.t, h: `${icon('p-sc')} ¥${s.price} SC：${esc(s.text)}` })),
    ...guards.map(g => ({ t: g.t, h: `${icon('anchor')} 开通${g.level_name} × ${g.num}${esc(g.unit)}${g.yuan == null ? '' : `（${yuan(g.yuan)}）`}` })),
    ...pick(S.enters).map(e => ({ t: e.t, h: e.kind === 'follow' ? icon('heart') + ' 关注了' + ANCHOR() : e.kind === 'share' ? '↗ 分享了直播间' : icon('p-enter') + ' 进入直播间' })),
  ].sort((a, b) => b.t - a.t).slice(0, 200);
  const histHtml = h => h.length ? h.map(x => `<div class="it"><span class="tm">${hhmm(x.t)}</span><span>${x.h}</span></div>`).join('') : '<div class="empty">暂无记录</div>';
  const hist = histOf(dms);
  const mp = u.medal ? u.medal.split(' ') : [];
  const medal = u.medal ? medalHtml(mp[0], Number(mp[1]) || 0, guard, mp[2] === 'dim') : '';
  const nt = noteOf(uid);
  $('card').innerHTML = `
    <div class="head">${avatar(face, name, guard)}<div style="min-width:0"><div class="nm">${esc(name)}</div>
      <div class="sub">${guard ? `<span class="tag g${guard}" title="${GN[guard]}">${GS[guard]}</span>` : ''}${medal}<span>UID ${uid}</span>${u.first ? `<span>本场 ${hhmm(u.first)} 第一次出现</span>` : ''}</div></div></div>
    <div class="nums"><div><b>${dms.length || u.dm || 0}</b><span>本场弹幕</span></div>${S.admin ? `<div><b>${yuan(u.spend || spend || 0)}</b><span>本场送出</span></div>` : ''}<div><b>${u.enter || pick(S.enters).filter(e => e.kind === 'enter').length}</b><span>进房次数</span></div></div>
    ${S.admin && !side ? `<div class="noteedit" title="只有你看得到；回车保存，清空就是删掉">${icon('p-note')}<input id="cardnote" maxlength="60" placeholder="写个备注" value="${esc(nt)}"></div>
    <div class="ctabs"><button data-ct="now" class="on">本场</button><button data-ct="past">以前</button></div>` : ''}
    <div class="hist" id="chist">${histHtml(hist)}</div>
    <div class="acts"><a class="btn" href="https://space.bilibili.com/${uid}" target="_blank" rel="noopener" title="打开 B 站主页">${icon('link')} 主页</a>
      ${side ? '<span class="cside">这是别的直播间的观众</span>' : `<button class="btn${isMuted(uid) ? ' on' : ''}" id="cardmute" title="${isMuted(uid) ? '现在朗读会跳过他，点一下恢复' : '朗读时跳过他'}">${icon('mute')} 不读</button>`}
      ${S.admin && !side ? `<button class="btn" id="cardreply" title="回复他最近的一条弹幕">${icon('reply')} 回复</button><button class="btn danger" id="cardban" title="禁言到本场结束">${icon('ban')} 禁言</button>` : ''}
      <button class="btn" id="cardclose" style="margin-left:auto" title="关闭">✕</button></div>`;
  $('cardclose').onclick = () => { $('card').classList.remove('open'); if (!$('hist').classList.contains('open')) $('mask').classList.remove('show'); };
  // 本场说过的话：网页里只有最近的弹幕，去电脑上拿这个人本场全部的
  let nowHist = hist;
  if (!side && S.admin) fetch('api/dm?' + new URLSearchParams({ uid, limit: 300 }), { cache: 'no-store' }).then(r => r.json()).then(j => {
    if (!$('card').classList.contains('open') || $('card').dataset.uid !== String(uid) || !j.items?.length) return;
    nowHist = histOf(j.items);
    if (!$('card').querySelector('[data-ct=past].on')) $('chist').innerHTML = histHtml(nowHist);
  }).catch(() => {});
  $('card').dataset.uid = uid;
  if (S.admin && !side) {
    const saveNote = () => {
      const v = $('cardnote').value.trim();
      if (v === noteOf(uid)) return;
      window._ws?.send(JSON.stringify({ cmd: 'note_set', uid, name, text: v }));
      note(v ? '备注已保存' : '备注已删掉');
    };
    $('cardnote').onkeydown = e => { if (e.key === 'Enter') { saveNote(); e.target.blur(); } };
    $('cardnote').onblur = saveNote;
    // 观众档案：这个人以前各场来过几次、发了多少弹幕、送了多少
    $('card').querySelectorAll('[data-ct]').forEach(b => b.onclick = async () => {
      $('card').querySelectorAll('[data-ct]').forEach(x => x.classList.toggle('on', x === b));
      if (b.dataset.ct === 'now') { $('chist').innerHTML = histHtml(nowHist); return; }
      $('chist').innerHTML = '<div class="empty">加载中…</div>';
      try {
        const j = await (await fetch('api/viewer/' + uid, { cache: 'no-store' })).json();
        const ss = (j.sessions || []).sort((a, c) => c.start - a.start);
        if (!b.classList.contains('on')) return;
        if (!ss.length) { $('chist').innerHTML = '<div class="empty">以前没来过<br><small>（有记录的场次里）</small></div>'; return; }
        const tot = ss.reduce((a, s) => ({ dm: a.dm + (s.dm || 0), spend: a.spend + (s.spend || 0) }), { dm: 0, spend: 0 });
        $('chist').innerHTML = `<div class="psum"><span>${icon('calendar')} 来过 ${ss.length} 场</span><span>${icon('p-dm')} ${num(tot.dm)} 条</span>${tot.spend ? `<span>${icon('p-gift')} ${yuan(tot.spend)}</span>` : ''}<span>${icon('clock')} 上次 ${fmtDay(ss[0].start)}</span></div>` +
          ss.map(s => `<div class="prow" data-sid="${s.id}"><span class="pd">${fmtDay(s.start).replace(/ 周.$/, '')}</span><span class="pt">${esc(s.title || '')}</span><span class="pn">${s.dm ? `${icon('p-dm')}${s.dm}` : ''}${s.spend ? ` <b>${yuan(s.spend)}</b>` : ''}</span></div>`).join('');
        $('chist').querySelectorAll('[data-sid]').forEach(r => r.onclick = () => { $('card').classList.remove('open'); openHist().then(() => openHistItem(r.dataset.sid)); });
      } catch { $('chist').innerHTML = '<div class="empty">加载失败</div>'; }
    });
    // 回复（2026-11-21）：回复他最近的一条弹幕；用自己的号发时 B 站上是真的回复，默认账号只能 @
    $('cardreply').onclick = () => { $('cardclose').onclick(); const last = dms[dms.length - 1]; setReply({ uid, name, dmid: last?.dmid || '', text: last?.text || '' }); };
    let arm = 0;
    $('cardban').onclick = () => {
      if (!sayAcct() && !S.room.bot_admin) { note(`${S.room.bot_name || '默认账号'} 不是房管，换成自己的号再禁言`, false); return; }
      if (Date.now() - arm > 3000) { arm = Date.now(); $('cardban').textContent = '再点确认'; return; }
      window._ws?.send(JSON.stringify({ cmd: 'mute', uid, name, acct: sayAcct() })); $('cardban').innerHTML = icon('ban') + ' 禁言'; arm = 0;
    };
  }
  if ($('cardmute')) $('cardmute').onclick = () => {
    if (isMuted(uid)) cfg.tts.muted = cfg.tts.muted.filter(m => m.uid !== uid);
    else cfg.tts.muted.push({ uid, name });
    saveCfg(); renderMuted(); openUser(uid); renderDm();
  };
  $('card').classList.add('open'); $('mask').classList.add('show');
}
function renderMuted() {
  const el = $('mutedlist');
  el.innerHTML = cfg.tts.muted.length ? cfg.tts.muted.map(m => `<span class="pill" style="margin:2px">${esc(m.name)} <a href="#" data-unmute="${m.uid}" style="color:var(--ink3);text-decoration:none">✕</a></span>`).join('') : icon('mute') + ' 点弹幕里的名字，可以设成不读';
  el.querySelectorAll('[data-unmute]').forEach(a => a.onclick = ev => {
    ev.preventDefault(); cfg.tts.muted = cfg.tts.muted.filter(m => m.uid !== Number(a.dataset.unmute)); saveCfg(); renderMuted(); renderDm();
  });
}

/* ---------- 历史场次 ---------- */
const H = { list: [], admin: false, detail: null };
const WEEK = '日一二三四五六';
const fmtDay = t => { const d = new Date(t * 1000); return `${d.getMonth() + 1}月${d.getDate()}日 周${WEEK[d.getDay()]}`; };
async function openHist() {
  $('hist').classList.add('open'); $('mask').classList.add('show');
  await loadHistList();
}
async function loadHistList() {
  H.detail = null;
  $('htitle').innerHTML = icon('history') + ' 历史场次'; $('hback').style.display = 'none';
  $('hbody').innerHTML = '<div class="empty">加载中…</div>';
  try {
    const j = await (await fetch('api/history', { cache: 'no-store' })).json();
    H.list = j.items || []; H.admin = !!j.admin;
    renderHistList();
  } catch { $('hbody').innerHTML = '<div class="empty">加载失败</div>'; }
}
function renderHistList() {
  const L = H.list;
  if (!L.length) { $('hbody').innerHTML = '<div class="empty">暂无<br><small>下播后自动存档</small></div>'; return; }
  const money = H.admin;  // 不是管理身份的话，服务器本来就不给金额，这里也不显示
  const val = b => money ? b.income : b.dm_total;  // 条形图：管理看收益，其他人看弹幕数
  const best = L.reduce((a, b) => val(b) > val(a) ? b : a, L[0]);
  const max = Math.max(val(best), 1);
  const sum = L.reduce((a, b) => a + (b.income || 0), 0);
  const recent = L.filter(b => b.start > Date.now() / 1000 - 30 * 86400);
  const avgDur = dur(L.reduce((a, b) => a + (b.end - b.start), 0) / L.length);
  $('hbody').innerHTML = `
    <div class="hsum">${money ? `
      <div class="stat money"><div class="k">${icon('coin')} 近 30 天预估收益</div><div class="v">${yuan(recent.reduce((a, b) => a + b.income, 0))}</div><div class="s">${recent.length} 场</div></div>
      <div class="stat"><div class="k">${icon('history')} 一共记录</div><div class="v">${L.length} 场</div><div class="s">累计预估收益 ${yuan(sum)}</div></div>
      <div class="stat"><div class="k">${icon('clock')} 平均每场</div><div class="v">${avgDur}</div><div class="s">平均收益 ${yuan(sum / L.length)}</div></div>
      <div class="stat"><div class="k">${icon('trophy')} 收益最高的一场</div><div class="v">${yuan(best.income)}</div><div class="s">${esc(fmtDay(best.start))}</div></div>` : `
      <div class="stat"><div class="k">${icon('history')} 近 30 天</div><div class="v">${recent.length} 场</div><div class="s">一共记录 ${L.length} 场</div></div>
      <div class="stat"><div class="k">${icon('clock')} 平均每场</div><div class="v">${avgDur}</div><div class="s">&nbsp;</div></div>
      <div class="stat"><div class="k">${icon('p-dm')} 平均弹幕</div><div class="v">${num(Math.round(L.reduce((a, b) => a + b.dm_total, 0) / L.length))}</div><div class="s">每场</div></div>
      <div class="stat"><div class="k">${icon('trophy')} 弹幕最多的一场</div><div class="v">${num(best.dm_total)}</div><div class="s">${esc(fmtDay(best.start))}</div></div>`}
    </div>
    ${money ? `<div class="hrow off" id="hoffrow"><div class="d">下播期间<small>不在任何一场里</small></div><div class="t"><div>下播时收到的舰长和礼物</div></div><div class="l"></div><div class="m" id="hoffm">…</div><div class="c" id="hoffc"></div></div>` : ''}
    ${L.map(b => `<div class="hrow" data-sid="${b.id}">
      <div class="d">${fmtDay(b.start)}<small>${hhmm(b.start)} – ${hhmm(b.end)}</small></div>
      <div class="t"><div>${esc(b.title || '（没有标题）')}</div><div class="bar"><i style="width:${Math.max(2, val(b) / max * 100)}%"></i></div></div>
      <div class="l">${icon('clock')} ${dur(b.end - b.start)}</div>
      <div class="m">${money ? `${yuan(b.income)}<small>流水 ${yuan(b.total)}</small>` : `${num(b.dm_total)}<small>条弹幕</small>`}</div>
      <div class="c">弹幕 ${num(b.dm_total)} · 来过 ${num(b.user_count)}<br>SC ${b.sc_count} · 上舰 ${b.guard_count}</div>
    </div>`).join('')}`;
  $('hbody').querySelectorAll('[data-sid]').forEach(r => r.onclick = () => openHistItem(r.dataset.sid));
  if ($('hoffrow')) {
    $('hoffrow').onclick = openOffline;
    fetch('api/offline', { cache: 'no-store' }).then(r => r.json()).then(o => {
      H.off = o;
      if ($('hoffm')) $('hoffm').innerHTML = `${yuan((o.total || 0) / 2)}<small>流水 ${yuan(o.total || 0)}</small>`;
      if ($('hoffc')) $('hoffc').innerHTML = `上舰 ${o.guards.length} · 礼物 ${num(o.gifts.length)}<br>${offUnthx(o) ? `<b class="todo">${offUnthx(o)} 条还没感谢</b>` : '都感谢过了'}`;
      drawOffDot();
    }).catch(() => {});
  }
}
// 下播期间收到的（2026-11-20）：不属于哪一场，单独一页。舰长和礼物放一个列表（下播收到的不多），每条能标「已感谢」
const offUnthx = o => o ? [...o.gifts, ...o.guards].filter(x => !x.thanked).length : 0;
function drawOffDot() {
  const n = offUnthx(H.off);
  $('histbtn').classList.toggle('dot', n > 0);
  $('histbtn').title = n ? `历史场次（下播期间有 ${n} 条还没感谢）` : '历史场次';
  if ($('hoffrow')) $('hoffrow').classList.toggle('dot', n > 0);
}
let offT = 0;
function refreshOffDot() {
  if (!S.admin) { H.off = null; drawOffDot(); return; }
  clearTimeout(offT);
  offT = setTimeout(() => fetch('api/offline', { cache: 'no-store' }).then(r => r.ok ? r.json() : null).then(o => {
    if (!o) return;
    H.off = o; drawOffDot();
    if (H.detail?.off) drawOffline();
  }).catch(() => {}), 300);
}
function offThanked(id, done) {
  const it = H.off && [...H.off.gifts, ...H.off.guards].find(x => String(x.id) === String(id));
  if (!it) return;
  if (done) { it.thanked = true; offJust.add(String(id)); } else delete it.thanked;
  drawOffDot();
  if (H.detail?.off) drawOffline();
}
// 2026-11-23 用户：以前感谢过的就不要再显示了 —— 只列还没感谢的；这次打开页面时刚打勾的先留着（变淡，点错了还能取消），
// 下次打开就不见了；最下面「看看已感谢的」可以全部摊开
let offJust = new Set(), offAll = false;
async function openOffline() {
  offJust = new Set(); offAll = false;
  $('hbody').innerHTML = '<div class="empty">加载中…</div>';
  try { H.off = await (await fetch('api/offline', { cache: 'no-store' })).json(); } catch {}
  if (!H.off) { $('hbody').innerHTML = '<div class="empty">加载失败</div>'; return; }
  H.detail = { off: true };
  $('htitle').innerHTML = `${icon('history')} 下播期间收到的`; $('hback').style.display = '';
  drawOffline(); drawOffDot();
}
function drawOffline() {
  const o = H.off, f = o.flow || {};
  const thx = g => `<button class="gthx${g.thanked ? ' on' : ''}" data-othx="${esc(String(g.id))}" title="${g.thanked ? '已感谢（点一下取消）' : '标成已感谢'}">✓</button>`;
  const gift = g => `<div class="gift${g.thanked ? ' thx' : ''}">${avatar(g.face, g.name, g.guard)}<div class="body"><div class="n"><span class="nm">${esc(g.name)}</span></div><div class="g">投喂 ${esc(g.gift)} × ${num(g.num)} · ${fmtMd(g.t)}</div></div>${g.img ? `<img class="gi" src="img?u=${encodeURIComponent(g.img)}" alt="">` : ''}${thx(g)}<span class="y">${yuan(g.yuan || 0)}</span></div>`;
  const left = offUnthx(o), byT = (a, b) => b.t - a.t;
  const nG = o.guards.filter(x => !x.thanked).length, nF = o.gifts.filter(x => !x.thanked).length;
  const show = x => offAll || !x.thanked || offJust.has(String(x.id));
  const gs = o.guards.filter(show), fs = o.gifts.filter(show), hid = o.guards.length + o.gifts.length - gs.length - fs.length;
  const none = (n, all) => `<div class="empty sm">${all ? '都感谢过了' : '无'}</div>`;
  $('hbody').innerHTML = `<div class="hoff">
    <div class="hsum">
      <div class="stat money" title="收益 = 流水 × 50%"><div class="k">${icon('coin')} 收益</div><div class="v">${yuan((o.total || 0) / 2)}</div><div class="s">流水 ${yuan(o.total || 0)}</div></div>
      <div class="stat"><div class="k">${icon('anchor')} 上舰</div><div class="v">${o.guards.length}</div><div class="s">${yuan(f.guard || 0)}</div></div>
      <div class="stat"><div class="k">${icon('p-gift')} 礼物</div><div class="v">${num(o.gifts.length)}</div><div class="s">${yuan(f.gift || 0)}</div></div>
      <div class="stat${left ? ' todo' : ''}"><div class="k">${icon('check')} 还没感谢</div><div class="v">${left}</div><div class="s">${left ? '点右边的 ✓ 标成已感谢' : '都感谢过了'}</div></div>
    </div>
    <div class="offcols">
      <div class="offbox"><h4>${icon('anchor')} 舰长${nG ? `<small class="todo">${nG} 条没感谢</small>` : ''}</h4><div class="lst offlist">${gs.length ? gs.slice().sort(byT).map(g => guardRow(g, 0, 0, true).slice(0, -6) + thx(g) + '</div>').join('') : none(0, o.guards.length)}</div></div>
      <div class="offbox"><h4>${icon('p-gift')} 礼物${nF ? `<small class="todo">${nF} 条没感谢</small>` : ''}</h4><div class="lst offlist">${fs.length ? fs.slice().sort(byT).map(gift).join('') : none(0, o.gifts.length)}</div></div>
    </div>
    ${hid || offAll ? `<div style="text-align:center;margin-top:10px"><button class="btn sm" id="offall">${offAll ? '收起已感谢的' : `看看已感谢的（${hid} 条）`}</button></div>` : ''}
  </div>`;
}
document.addEventListener('click', e => {
  if (e.target.closest('#offall')) { offAll = !offAll; drawOffline(); return; }
  const b = e.target.closest('[data-othx]'); if (!b || !H.off) return;
  e.stopPropagation();
  const it = [...H.off.gifts, ...H.off.guards].find(x => String(x.id) === b.dataset.othx); if (!it) return;
  const done = !it.thanked;
  offThanked(it.id, done);
  if (S.gifts.some(x => String(x.id) === String(it.id)) || S.guards.some(x => String(x.id) === String(it.id))) {
    const live = [...S.gifts, ...S.guards].find(x => String(x.id) === String(it.id)); if (done) live.thanked = true; else delete live.thanked; soon(renderGifts, 'g');
  }
  window._ws?.send(JSON.stringify({ cmd: 'gift_thank', id: String(it.id), done }));
}, true);
// 2026-11-23 找回：11-20 16:08 上线时这两个函数整段丢了，历史里点某一场会报 ReferenceError 打不开
async function openHistItem(sid) {
  $('hbody').innerHTML = '<div class="empty">加载中…</div>';
  try {
    const d = await (await fetch('api/history/' + encodeURIComponent(sid), { cache: 'no-store' })).json();
    H.detail = d; renderHistDetail(d);
  } catch { $('hbody').innerHTML = '<div class="empty">加载失败</div>'; }
}
function renderHistDetail(d) {
  $('htitle').innerHTML = `${icon('history')} ${fmtDay(d.start)} 的直播`; $('hback').style.display = '';
  const f = d.flow || {}, st = d.stats || {};
  const gmax = Math.max(...(d.gift_stats || []).map(g => g.yuan), 1);
  // 分类在左边，点哪类看哪类（记住上次看的那一类）；手机上分类排在顶上
  const tabs = [['sum', 'grid', '概览', ''], ['rank', 'trophy', '送礼榜', ''], ['sc', 'p-sc', 'SC', d.sc_count || ''], ['gift', 'p-gift', '礼物', ''], ['guard', 'anchor', '上舰', d.guard_count || '']];
  if (d.has_dm) tabs.push(['dm', 'p-dm', '弹幕', num(d.dm_total)]);
  if (!tabs.some(t => t[0] === H.tab)) H.tab = 'sum';
  $('hbody').innerHTML = `<div class="hd">
    <nav class="hnav" id="hnav">${tabs.map(([k, ic, n, c]) => `<button data-hn="${k}"${k === H.tab ? ' class="on"' : ''}>${icon(ic)}<span>${n}</span>${c ? `<small>${c}</small>` : ''}</button>`).join('')}</nav>
    <div class="hpages">
    <div class="hp" data-hp="sum">
    <div class="hmeta">${esc(d.title || '（没有标题）')}${d.area ? ' · ' + esc(d.area) : ''} · ${hhmm(d.start)} – ${hhmm(d.end)}（${dur(d.end - d.start)}）${d.reason && d.reason !== '下播' ? ' · ' + esc(d.reason) : ''}</div>
    <div class="hsum">
      ${H.admin ? `<div class="stat money" title="收益 = 流水 × 50%"><div class="k">${icon('coin')} 收益</div><div class="v">${yuan(d.income)}</div><div class="s">流水 ${yuan(d.total)} · 礼物 ${yuan(f.gift || 0)} · SC ${yuan(f.sc || 0)} · 上舰 ${yuan(f.guard || 0)}</div></div>` : `<div class="stat"><div class="k">${icon('clock')} 时长</div><div class="v">${dur(d.end - d.start)}</div><div class="s">${hhmm(d.start)} – ${hhmm(d.end)}</div></div>`}
      <div class="stat"><div class="k">${icon('p-dm')} 弹幕</div><div class="v">${num(d.dm_total)}</div><div class="s">来过 ${num(d.user_count)} 人 · 新关注 ${num(st.follows || 0)}</div></div>
      <div class="stat"><div class="k">${icon('snow')} 在线最多</div><div class="v">${num(d.peak_online || 0)}</div><div class="s">看过 ${num(st.watched || 0)} · 点赞 ${num(st.likes || 0)}</div></div>
      <div class="stat"><div class="k">${icon('p-sc')} SC / ${icon('anchor')} 上舰</div><div class="v">${d.sc_count} / ${d.guard_count}</div><div class="s">${H.admin ? `SC ${yuan(f.sc || 0)} · 上舰 ${yuan(f.guard || 0)}` : '条 / 位'}</div></div>
    </div>
    <div class="hboxes">
      <div class="hbox"><h4>${icon('trophy')} 送礼榜<a data-go="rank">全部</a></h4>${(d.rank || []).length ? d.rank.slice(0, 5).map(rankRow).join('') : '<div class="empty sm">无</div>'}</div>
      <div class="hbox"><h4>${icon('p-gift')} 收到最多的礼物<a data-go="gift">全部</a></h4>${(d.gift_stats || []).length ? d.gift_stats.slice(0, 5).map(g => `<div class="row"><span class="n">${esc(g.name)}</span><span style="color:var(--ink3);margin:0 8px">× ${num(g.num)}</span><span class="r money">${yuan(g.yuan)}</span></div>`).join('') : '<div class="empty sm">无</div>'}</div>
      <div class="hbox"><h4>${icon('anchor')} 上舰<a data-go="guard">全部</a></h4>${(d.guards || []).length ? d.guards.slice(0, 4).map(g => guardRow(g, 0, 0, true)).join('') : '<div class="empty sm">这场没有人上舰</div>'}</div>
      <div class="hbox"><h4>${icon('p-sc')} SC<a data-go="sc">全部</a></h4>${(d.scs || []).length ? d.scs.slice().sort((a, b) => (b.price || 0) - (a.price || 0)).slice(0, 3).map(s => `<div class="row"><span class="n">${esc(s.name)}</span><span style="flex:1;margin:0 8px;color:var(--ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.text || '')}</span><span class="r money">${yuan(s.price || 0)}</span></div>`).join('') : '<div class="empty sm">这场没有 SC</div>'}</div>
    </div>
    ${H.admin ? `<div style="margin-top:16px;text-align:right"><button class="btn sm danger" id="hdel">删除这场记录</button></div>` : ''}
    </div>
    <div class="hp" data-hp="rank" title="礼物 + SC + 上舰"><div class="lst">${(d.rank || []).length ? d.rank.map(rankRow).join('') : '<div class="empty">无</div>'}</div></div>
    <div class="hp" data-hp="sc"><div class="lst">${(d.scs || []).length ? d.scs.slice().reverse().map(s => scHtml(s)).join('') : '<div class="empty">无</div>'}</div></div>
    <div class="hp" data-hp="gift"><div class="lst">${(d.gift_stats || []).length ? d.gift_stats.map(g => `<div class="row"><span class="n" style="width:42%">${esc(g.name)}</span><span style="color:var(--ink3)">× ${num(g.num)}</span><span style="flex:1;margin:0 8px" class="bar"><span style="display:block;height:6px;border-radius:3px;background:var(--money-ink);opacity:.7;width:${Math.max(2, g.yuan / gmax * 100)}%"></span></span><span class="r money">${yuan(g.yuan)}</span></div>`).join('') : '<div class="empty">无</div>'}</div></div>
    <div class="hp" data-hp="guard"><div class="lst">${(d.guards || []).length ? d.guards.map(g => guardRow(g, 0, 0, true)).join('') : '<div class="empty">无</div>'}</div></div>
    ${d.has_dm ? `<div class="hp hdm" data-hp="dm"><input id="hdmq" placeholder="搜名字或内容"><div class="lst" id="hdmlist"><div class="empty">加载中…</div></div></div>` : ''}
    </div></div>`;
  const showTab = k => { H.tab = k; $('hnav').querySelectorAll('button').forEach(x => x.classList.toggle('on', x.dataset.hn === k)); $('hbody').querySelectorAll('.hp').forEach(x => x.classList.toggle('on', x.dataset.hp === k)); if (k === 'dm') { const l = $('hdmlist'); if (l) l.scrollTop = l.scrollHeight; } };
  $('hnav').onclick = e => { const x = e.target.closest('[data-hn]'); if (x) showTab(x.dataset.hn); };
  $('hbody').querySelectorAll('.hbox [data-go]').forEach(a => a.onclick = () => showTab(a.dataset.go));
  showTab(H.tab);
  if (d.has_dm) histDm(d.id, '');
  if (H.admin) {
    let arm = 0;
    $('hdel').onclick = async () => {
      if (Date.now() - arm > 3000) { arm = Date.now(); $('hdel').textContent = '再点一次删除'; return; }
      try { await fetch(`api/history/${encodeURIComponent(d.id)}/delete`, { method: 'POST' }); } catch {}
      loadHistList();
    };
  }
}
// 历史场次的整场弹幕：先给最后 300 条，往上翻 / 点「更早」接着加载；搜索是搜整场
async function histDm(sid, q, before) {
  const box = $('hdmlist');
  if (!box) return;
  const p = new URLSearchParams({ limit: 300 });
  if (q) p.set('q', q);
  if (before != null) p.set('before', before);
  let j;
  try { j = await (await fetch(`api/history/${encodeURIComponent(sid)}/dm?` + p, { cache: 'no-store' })).json(); } catch { if (before == null) box.innerHTML = '<div class="empty">加载失败</div>'; return; }
  if (H.detail?.id !== sid || ($('hdmq')?.value.trim() || '') !== q) return;
  const rows = j.items.map(x => `<div class="it" data-uid="${x.uid}"><span class="tm">${hhmm(x.t)}</span><b>${esc(x.name)}</b><span>${x.emoticon ? '〔表情〕' + esc(x.text) : emoText(x)}</span></div>`).join('');
  const more = j.more ? `<button class="btn sm more" data-before="${j.next}">↑ 更早</button>` : '';
  if (before == null) {
    box.innerHTML = more + (rows || '<div class="empty">没有</div>');
    box.scrollTop = box.scrollHeight;
  } else {
    const h = box.scrollHeight, top = box.scrollTop;
    box.querySelector('.more')?.remove();
    box.insertAdjacentHTML('afterbegin', more + rows);
    box.scrollTop = top + box.scrollHeight - h;
  }
  box.onclick = e => { const b = e.target.closest('.more'); if (b) { e.stopPropagation(); histDm(sid, q, b.dataset.before); } };
  box.onscroll = () => { const b = box.querySelector('.more'); if (b && box.scrollTop < 60 && !b.disabled) { b.disabled = true; histDm(sid, q, b.dataset.before); } };
  let t;
  $('hdmq').oninput = e => { clearTimeout(t); t = setTimeout(() => { box.innerHTML = '<div class="empty">搜索中…</div>'; histDm(sid, e.target.value.trim()); }, 300); };
}
$('histbtn').onclick = openHist;
// OBS 弹幕设置：直接在雾幕里打开（第一次点才加载，平时不占资源；关掉就卸载预览）
$('obsbtn').onclick = () => { closeAll(); $('obsframe').src = 'obs-setup'; $('obsbox').classList.add('open'); $('mask').classList.add('show'); };
$('obsclose').onclick = closeAll;
$('hback').onclick = loadHistList;
$('hclose').onclick = closeAll;

