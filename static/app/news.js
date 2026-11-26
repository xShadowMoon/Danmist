// 雾幕主页面 · 功能一览和更新公告（内容在 static/news.json）、新版自动刷新
// 这几个文件按顺序加载，共用同一套全局变量。加载时只能直接用前面文件里的东西，用后面文件的函数要放进回调里
/* ---------- 功能一览 + 更新公告（内容在 static/news.json，上线新功能时改那个文件） ---------- */
let NEWS = null;
const newsSeen = () => { try { return localStorage.getItem('xw-news-seen') || ''; } catch { return ''; } };
// 每个功能可以带 go：点一下自动打开它所在的地方，再把那个位置圈出来。
// go 写法：几步用「 > 」隔开，最后一步是要圈出来的东西（CSS 选择器）。前面的步骤可以是：
//   set:页名（打开设置的某一页） lay（打开布局） hist（打开历史） obs（打开 OBS 设置） click:选择器（点一下，比如切到面板的某个标签）
let guideTab = 'feat', guideGrp = 0, newsMore = false;
// 分类图标用单色线条图标（原来是彩色 emoji，2026-11-19 换）
const GROUP_IC = { '直播工作台': 'mic', '弹幕': 'p-dm', '观众': 'p-users', 'SC': 'p-sc', '礼物': 'p-gift', '点歌': 'p-req', '朗读': 'volume', '数据': 'history', '界面': 'layers', 'OBS 弹幕': 'video', '直播间': 'tv' };
const gIcon = g => GROUP_IC[g.name] ? icon(GROUP_IC[g.name]) : esc(g.icon || '');
let featSeen = new Set();  // 看过的「新」功能（按功能名记），存在这个浏览器里
try { featSeen = new Set(JSON.parse(localStorage.getItem('xw-feat-seen') || '[]')); } catch {}
function newsDialog(tab) {
  if (!NEWS || document.body.classList.contains('viewer')) return;
  guideTab = tab;
  closeAll();
  $('guide').querySelectorAll('[data-gt]').forEach(b => b.classList.toggle('on', b.dataset.gt === tab));
  $('gsearch').style.display = tab === 'feat' ? '' : 'none';
  drawGuide();
  const latest = NEWS.news[0];
  if (tab === 'news' && latest) { try { localStorage.setItem('xw-news-seen', latest.v); } catch {} $('newsbtn').classList.remove('dot'); }
  $('guide').classList.add('open'); $('mask').classList.add('show');
}
function drawGuide() {
  const rail = $('grail'), body = $('gbody'), latestV = NEWS.news[0]?.v;
  if (guideTab === 'news') {
    rail.style.display = 'none';
    // 2026-11-19 减字：每次更新只显示一行标题，点开才看细节；最新那条默认展开；一次只列最近 12 次
    const list = NEWS.news.slice(0, newsMore ? 200 : 12);
    body.innerHTML = `<div class="nlist">${list.map((n, i) => `<details class="nrel"${i === 0 ? ' open' : ''}><summary><b>${esc(n.title || '更新')}</b><small>${esc(String(n.v).slice(5).replace(/^(\d+)\.(\d+).*$/, '$1/$2'))}</small></summary>${n.items.map(x => {
      const m = String(x).match(/^(\S{1,3})\s+(.*)$/s);  // 开头的图标单独放一格
      return `<div class="nline"><i>${m ? esc(m[1]) : '•'}</i><span>${esc(m ? m[2] : x)}</span></div>`;
    }).join('')}</details>`).join('')}${!newsMore && NEWS.news.length > 12 ? '<button class="btn sm nmore" id="nmore">更早的</button>' : ''}</div>`;
    if ($('nmore')) $('nmore').onclick = () => { newsMore = true; drawGuide(); };
    return;
  }
  rail.style.display = '';
  // 一次只看一类（左边点哪类右边就只显示哪类）；搜索时跨所有分类找
  const q = $('gsearch').value.trim().toLowerCase();
  // 「新」：最新一版加的功能，鼠标移上去（或点过）就记成看过，不再标；一类里都看过了，左边的小红点也消失
  const isNew = x => x.v && x.v === latestV && !featSeen.has(x.n);
  const tile = (x, g) => `<button class="gtile${isNew(x) ? ' new' : ''}${x.go ? '' : ' nogo'}" data-go="${esc(x.go || '')}" data-n="${esc(x.n)}" title="${esc(x.at || '')}${x.go ? '（点一下带你过去）' : ''}">${g ? `<i>${gIcon(g)}</i>` : ''}<span><b>${esc(x.n)}</b><small>${esc(x.at || '')}</small></span></button>`;
  rail.innerHTML = NEWS.features.map((g, gi) => `<button data-gg="${gi}"${!q && gi === guideGrp ? ' class="on"' : ''}><i>${gIcon(g)}</i><span>${esc(g.name)}</span>${g.items.some(isNew) ? '<em></em>' : ''}</button>`).join('');
  if (q) {
    const hits = NEWS.features.flatMap(g => g.items.filter(x => `${x.n} ${x.at} ${g.name}`.toLowerCase().includes(q)).map(x => tile(x, g)));
    body.innerHTML = hits.length ? `<div class="ghead"><h3>${icon('search')} ${hits.length} 个</h3></div><div class="ggrid">${hits.join('')}</div>` : '<div class="gnone">没找到</div>';
  } else {
    const g = NEWS.features[guideGrp] || NEWS.features[0];
    body.innerHTML = `<div class="ghead"><i>${gIcon(g)}</i><h3>${esc(g.name)}</h3><small>${g.items.length}</small></div><div class="ggrid">${g.items.map(x => tile(x)).join('')}</div>`;
  }
  body.scrollTop = 0;
  rail.querySelectorAll('[data-gg]').forEach(b => b.onclick = () => { guideGrp = Number(b.dataset.gg); $('gsearch').value = ''; drawGuide(); });
  body.querySelectorAll('.gtile:not(.nogo)').forEach(t => t.onclick = () => goTo(t.dataset.go, t.dataset.n));
  body.querySelectorAll('.gtile.new').forEach(t => t.addEventListener('pointerenter', () => {
    featSeen.add(t.dataset.n);
    try { localStorage.setItem('xw-feat-seen', JSON.stringify([...featSeen].slice(-300))); } catch {}
    t.classList.remove('new');
    NEWS.features.forEach((g, gi) => { if (!g.items.some(isNew)) rail.querySelector(`[data-gg="${gi}"] em`)?.remove(); });
  }, { once: true }));
}
$('guide').querySelectorAll('[data-gt]').forEach(b => b.onclick = () => newsDialog(b.dataset.gt));
$('gsearch').oninput = drawGuide;
$('gclose').onclick = closeAll;
$('newsbtn').onclick = () => { if (NEWS) newsDialog('feat'); };

// 跳到某个功能：一步步打开它所在的地方，然后圈出来
const sleepMs = ms => new Promise(r => setTimeout(r, ms));
async function goTo(go, name) {
  const steps = String(go).split(/\s*>\s*/).filter(Boolean), last = steps.pop();
  closeAll();
  for (const s of steps) {
    const [k, ...rest] = s.split(':'), v = rest.join(':');
    if (k === 'set') { openSettings(); $('stabs').querySelector(`[data-st="${v}"]`)?.click(); }
    else if (k === 'lay') setLay(true);
    else if (k === 'hist') openHist();
    else if (k === 'obs') $('obsbtn').click();
    else if (k === 'click') document.querySelector(v)?.click();
    else if (k === 'gear') {  // 2026-11-21：很多设置搬进了各模块标题栏的齿轮
      const panel = $('p-' + v);
      if (!panel || panel.closest('#pool')) {
        closeAll(); setLay(true); await sleepMs(320);
        const lm = document.querySelector(`[data-mon="${v}"]`)?.closest('.lmod');
        if (lm) { spotlight(lm, `先打开「${PANELS[v] || '这个模块'}」`); return; }
        note('没找到这个模块', false); return;
      }
      openSettings(v);  // 2026-11-21 齿轮 = 设置窗口里这一栏的那一页
    }
    await sleepMs(120);
  }
  await sleepMs(steps.length ? 320 : 60);  // 等抽屉滑出来
  let el = document.querySelector(last);
  // 在设置的另一页上：换到那一页（2026-11-21 设置改版后有些项换了页）
  const spg = el?.closest('#settings .spage');
  if (spg && !spg.classList.contains('on')) { $('stabs').querySelector(`[data-st="${spg.dataset.sp}"]`)?.click(); await sleepMs(120); }
  // 这个功能所在的面板现在没摆出来：带去「布局」里打开它
  const pool = el?.closest('#pool');
  if (pool) {
    const id = el.closest('.panel')?.dataset.id;
    closeAll(); setLay(true); await sleepMs(320);
    el = document.querySelector(`[data-mon="${id}"]`)?.closest('.lmod');
    name = `先打开「${PANELS[id] || '这个模块'}」`;
  }
  if (el && !el.getClientRects().length) el = el.closest('label, .chip, .opt') || el;  // 勾选框本身是藏着的，圈它外面那个按钮
  if (last === '#tedit' && !el?.getClientRects().length) { note('这个要先用主播的号登录：发送框左边的头像 → 扫码', false); return; }
  if (!el || !el.getClientRects().length) {
    note(el ? '这个功能在这里用不了（要管理身份，或者要先登录）' : '没找到这个位置', false);
    return;
  }
  el.closest('details')?.setAttribute('open', '');
  if (el.matches('input, select, textarea') || el.closest('.chip')) el = el.closest('.chip, .opt, .field, .lmod, .saybar, .songadd') || el;
  spotlight(el, name);
}
let spotT = 0;
function spotlight(el, tip, keep) {  // keep：模块教学时一直圈着，不自己消失
  el.scrollIntoView({ block: 'center', behavior: 'instant' });
  const r = el.getBoundingClientRect(), pad = 6, s = $('spot');
  Object.assign(s.style, { left: r.left - pad + 'px', top: r.top - pad + 'px', width: r.width + pad * 2 + 'px', height: r.height + pad * 2 + 'px' });
  s.classList.toggle('up', r.bottom + 60 > innerHeight);  // 太靠下：提示放上面
  $('spottip').textContent = tip || '';
  s.classList.remove('show'); void s.offsetWidth; s.classList.add('show');
  clearTimeout(spotT);
  if (!keep) spotT = setTimeout(() => s.classList.remove('show'), 3200);
}
addEventListener('pointerdown', () => { if ($('spot').classList.contains('show')) { clearTimeout(spotT); $('spot').classList.remove('show'); } }, true);
fetch('static/news.json', { cache: 'no-store' }).then(r => r.json()).then(j => {
  NEWS = j;
  const latest = j.news?.[0];
  if (!latest || newsSeen() === latest.v) return;
  $('newsbtn').classList.add('dot');
  // 有新版本：这个浏览器弹一次公告（别的弹窗开着就先不打扰，按钮上留个红点）
  setTimeout(() => { if (!POP && !document.querySelector('#card.open, #settings.open, #hist.open, #obsbox.open, #laydlg.open, #guide.open')) newsDialog('news'); }, 1500);
}).catch(() => {});

// 上线了新版：页面自己刷新（2026-11-19 重做）
// 以前开着「更新公告」这类弹窗就一直不刷新，公告不关的话下一次更新永远等着 → 用户每次都要手动刷。现在：
// · 只有正在往输入框里打字（框里有字、光标在里面）才等，最多等 2 分钟；弹窗开着照样刷新（设置都是马上存的，不会丢）
// · 直播中不自己整页刷新（免得打断朗读、特效），顶上出一条「有新版本，点这里更新」，下播后自动刷新
// · 没在直播、页面在后台（切到别的窗口）时直接刷新
let myVer = 0, verWait = 0, verSince = 0;
function checkVer(v) {
  const n = v?.['index.html'] && Object.keys(v).filter(k => !k.startsWith('obs')).sort().map(k => v[k]).join('.');  // 主页面、app/ 下的文件、workbench 任何一个换了都算新版
  if (!n) return;
  if (!myVer) { myVer = n; return; }
  if (n === myVer || verWait) return;
  verSince = Date.now();
  const tick = () => {
    const el = document.activeElement;
    const typing = el?.matches?.('input:not([type=checkbox]):not([type=range]):not([type=number]), textarea') && String(el.value || '').trim() !== '';
    const live = S.room && S.room.live === 1;
    if (live) { $('verbar').hidden = false; return; }  // 直播中：只提示，不自己刷（页面在后台也不刷，免得打断朗读）
    if (typing && !document.hidden && Date.now() - verSince < 120000) return;  // 正在打字：先等等（最多 2 分钟）
    location.reload();
  };
  verWait = setInterval(tick, 3000);
  tick();
}
$('verbar').onclick = () => location.reload();
// GitHub 上出了新版本（0.9.1 起）：顶栏状态标签旁边一个小标签，点开发布页看更新内容、下载；✕ 之后这个版本不再提示。
// 只给管理身份看（主播专属链接、普通链接都不显示）；程序不会自己更新，怎么更新见 README。
const updSkipped = () => { try { return localStorage.getItem('xw-upd-skip') || ''; } catch { return ''; } };
// 桌面版（2026-11-25）：在运行雾幕的这台电脑上，可以直接「下载更新」→「重启生效」，不用自己解压覆盖
let updPct = null;
function drawUpd() {
  const u = S.update, bar = $('updbar'), D = S.desktop;
  const ready = D?.staged && (!u || D.staged === u.v);
  const show = !!(((u && u.v) || ready) && S.admin && !S.host && (ready || updSkipped() !== u.v));
  bar.hidden = !show;
  drawDesktop();
  if (!show) return;
  const a = $('updlink'), v = ready ? D.staged : u.v;
  a.href = u && /^https:\/\/github\.com\//.test(u.url) ? u.url : 'https://github.com/xShadowMoon/Danmist/releases/latest';
  a.title = `现在是 v${S.app_version || '?'}。点开看更新内容`;
  a.textContent = `新版本 v${v}`;
  let act = $('updact');
  if (!act) { act = document.createElement('button'); act.id = 'updact'; act.className = 'updact'; a.after(act); }
  act.hidden = !D;  // 不是这台电脑（远程链接）就只给链接
  if (ready) { act.textContent = '重启生效'; act.disabled = false; act.dataset.cmd = 'update_restart'; }
  else if (updPct != null && updPct >= 0 && updPct < 100) { act.textContent = `下载中 ${updPct}%`; act.disabled = true; }
  else { act.textContent = updPct === -1 ? '重新下载' : '下载更新'; act.disabled = false; act.dataset.cmd = 'update_download'; }
}
document.addEventListener('click', e => {
  const b = e.target.closest('#updact'); if (!b || b.disabled) return;
  if (b.dataset.cmd === 'update_download') { updPct = 0; drawUpd(); }
  window._ws?.send(JSON.stringify({ cmd: b.dataset.cmd }));
});
function drawDesktop() {
  if ($('aboutver')) $('aboutver').textContent = S.app_version ? 'v' + S.app_version : '';
  const D = S.desktop, box = $('dkbox');
  if (!box) return;
  box.hidden = !D;
  if (!D) return;
  $('dkmode').querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.val === D.open));
  $('dkshortcut').hidden = !D.win;
  $('dkver').textContent = `现在是 v${S.app_version || '?'}${D.staged ? ` · v${D.staged} 已下载，重启生效` : S.update?.v ? ` · 有新版本 v${S.update.v}` : ''}`;
}
// 看板娘（2026-11-26）：换成自己的图。网页里把图从中间裁成正方形、缩成 5 个尺寸的 PNG 传给电脑，
// 软件里的图标、标签页 / 窗口 / 任务栏图标都走 /art/icon-{尺寸}.png，换完带上新的 ?v= 马上刷新
const MASCOT_SIZES = [512, 256, 192, 64, 32];
function applyMascot(v) {
  S.mascot = v || 0;
  const q = S.mascot ? '?v=' + S.mascot : '';
  document.querySelectorAll('img[src*="/art/icon-"], link[href*="/art/icon-"]').forEach(el => {
    const a = el.tagName === 'LINK' ? 'href' : 'src';
    if (el.getAttribute(a).startsWith('/static/')) return;  // 「关于」里固定是雾幕自己的图标
    el.setAttribute(a, el.getAttribute(a).replace(/(\/art\/icon-\d+\.png)(\?v=\d+)?/, '$1' + q));
  });
  if ($('mascotreset')) $('mascotreset').hidden = !S.mascot;
  if ($('mascotname')) $('mascotname').textContent = S.mascot ? '现在用的是你换的图' : '默认：雾冬Hanaki';
}
// 大图一次缩到 32 像素会很糊、有锯齿：先对半对半地缩，最后一步再缩到目标大小
function squarePng(img, n) {
  const s = Math.min(img.naturalWidth, img.naturalHeight);
  let src = img, sx = (img.naturalWidth - s) / 2, sy = (img.naturalHeight - s) / 2, size = s;
  while (size / 2 >= n * 1.5) {
    const half = document.createElement('canvas');
    half.width = half.height = Math.round(size / 2);
    const h = half.getContext('2d');
    h.imageSmoothingQuality = 'high';
    h.drawImage(src, sx, sy, size, size, 0, 0, half.width, half.height);
    src = half; sx = sy = 0; size = half.width;
  }
  const c = document.createElement('canvas');
  c.width = c.height = n;
  const g = c.getContext('2d');
  g.imageSmoothingQuality = 'high';
  g.drawImage(src, sx, sy, size, size, 0, 0, n, n);
  return new Promise(ok => c.toBlob(ok, 'image/png'));
}
async function mascotPost(path, body) {
  const r = await fetch(path, body ? { method: 'POST', body, headers: { 'Content-Type': 'image/png' } } : { method: 'POST' });
  if (r.status === 403) throw new Error('要用管理链接，或者在电脑上直接打开才能换');
  if (!r.ok) throw new Error((await r.text()) || '电脑那边没收下');
  return (await r.json()).v;
}
$('mascotfile')?.addEventListener('change', async e => {
  const f = e.target.files[0], tip = $('mascottip');
  e.target.value = '';
  if (!f) return;
  if (f.size > 30 * 1024 * 1024) { tip.textContent = '图太大了，换一张 30 MB 以内的'; return; }
  const url = URL.createObjectURL(f), img = new Image();
  try {
    await new Promise((ok, bad) => { img.onload = ok; img.onerror = () => bad(new Error('这张图打不开')); img.src = url; });
    tip.textContent = '正在换…';
    let v = 0;
    for (const n of MASCOT_SIZES) v = await mascotPost('api/mascot?size=' + n + (n === MASCOT_SIZES.at(-1) ? '&last=1' : ''), await squarePng(img, n));
    applyMascot(v);
    tip.textContent = '换好了';
  } catch (err) {
    tip.textContent = '没换成：' + (err.message || '出错了');
  } finally {
    URL.revokeObjectURL(url);
  }
});
$('mascotreset')?.addEventListener('click', async () => {
  const tip = $('mascottip');
  try { applyMascot(await mascotPost('api/mascot/reset')); tip.textContent = '换回默认了'; }
  catch (err) { tip.textContent = '没换成：' + (err.message || '出错了'); }
});
$('dkmode')?.addEventListener('click', e => { const b = e.target.closest('button'); if (b) window._ws?.send(JSON.stringify({ cmd: 'open_mode', mode: b.dataset.val })); });
$('dkshortcut')?.addEventListener('click', () => window._ws?.send(JSON.stringify({ cmd: 'make_shortcut' })));
$('dkcheck')?.addEventListener('click', () => {
  if (S.update?.v) { $('updbar').hidden = false; try { localStorage.removeItem('xw-upd-skip'); } catch {} drawUpd(); note(`有新版本 v${S.update.v}，点顶上的「下载更新」`, true); }
  else note('现在没有新版本（每天会自动查一次）', true);
});
$('updclose').onclick = () => { try { localStorage.setItem('xw-upd-skip', S.update?.v || ''); } catch {} $('updbar').hidden = true; };
// 连接状态：网页 ↔ 电脑（wsOpen），电脑 ↔ B 站（S.room.bili_ok）
let wsOpen = false;
function drawConn() {
  if (!wsOpen) return;
  const c = $('conn'), down = S.room.bili_ok === false;
  const r = S.room, recent = r.up_at && r.down_at && Date.now() / 1000 - r.up_at < 1800;  // 半小时内断过就写出来
  setText(c, down ? `B 站重连中…${r.down_at ? '（' + hhmm(r.down_at) + ' 起）' : ''}` : recent ? `已连接（${hhmm(r.down_at)}–${hhmm(r.up_at)} 断过）` : '已连接');
  c.className = 'pill' + (down ? ' bad' : '');
  c.title = down ? '一般几十秒内自动恢复' : '';
  $('netbar').classList.toggle('on', down);  // B 站那头断了也在顶上走一条细线
}
// 机器人号登录失效：只给管理身份看提示（能处理的人）
