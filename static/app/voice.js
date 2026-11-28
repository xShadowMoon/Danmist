// 雾幕主页面 · 语音朗读、提示声
// 这几个文件按顺序加载，共用同一套全局变量。加载时只能直接用前面文件里的东西，用后面文件的函数要放进回调里
/* ---------- 语音朗读（浏览器自带语音 + AI 音色） ---------- */
const synth = window.speechSynthesis;
const tts = { queue: [], cur: null, startedAt: 0, utt: null, audio: null };
let voices = [];
function loadVoices() { voices = synth ? synth.getVoices() : []; fillVoices(); }
function fillVoices() {
  const sel = $('voicesel');
  const zh = voices.filter(v => /^zh|cmn/i.test(v.lang));
  const rest = voices.filter(v => !/^zh|cmn/i.test(v.lang));
  // AI 音色（2026-11-24）：服务器上的 GPT-SoVITS，值写成 ai:名字；只有管理身份看得到
  const cur = cfg.tts.voice, ais = AI.voices.map(v => [v.id, v.name + (AI.online ? '' : '（服务没开）')]);
  if (isAiVoice(cur) && !ais.some(([id]) => 'ai:' + id === cur)) ais.push([cur.slice(3), cur.slice(3) + '（暂时用不了）']);
  sel.innerHTML = '<option value="">自动（优先中文女声）</option>' +
    (ais.length ? '<optgroup label="AI 音色">' + ais.map(([id, n]) => `<option value="ai:${esc(id)}">${esc(n)}</option>`).join('') + '</optgroup>' : '') +
    zh.map(v => `<option value="${esc(v.name)}">${esc(v.name)}${v.localService ? '' : '（要联网）'}</option>`).join('') +
    (rest.length ? '<optgroup label="其它语言">' + rest.map(v => `<option value="${esc(v.name)}">${esc(v.name)}</option>`).join('') + '</optgroup>' : '');
  sel.value = cur;
  if (sel.value !== cur) sel.value = '';
  drawAiRows();
}
/* AI 音色：网页把要念的字发给服务器（/api/tts），服务器交给本机的 GPT-SoVITS 合成，拿回 wav 播放。
   正在念这一句时就把后面两句先合成好；合成失败、太慢（AI_WAIT）就这一句改用浏览器语音，不会卡住。 */
const AI = { voices: [], online: false, failAt: 0 };
const AI_WAIT = 10000;
const isAiVoice = v => String(v || '').startsWith('ai:');
const aiId = () => isAiVoice(cfg.tts.voice) ? cfg.tts.voice.slice(3) : '';
// 浏览器语音的语速默认 1.15 倍，AI 声音 1 倍就是正常说话的速度，所以按比例换算
const aiSpeed = () => Math.min(1.6, Math.max(0.6, Math.round(cfg.tts.rate / 1.15 * 100) / 100));
function loadAiVoices() {
  if (!S.admin) { if (AI.voices.length) { AI.voices = []; fillVoices(); } return; }
  fetch('api/tts/voices', { cache: 'no-store' }).then(r => r.json()).then(j => {
    const was = JSON.stringify([AI.voices, AI.online]);
    AI.voices = Array.isArray(j.voices) ? j.voices : []; AI.online = !!j.online;
    if (JSON.stringify([AI.voices, AI.online]) !== was) fillVoices();
  }).catch(() => {});
}
setTimeout(loadAiVoices, 1500); setTimeout(loadAiVoices, 6000);  // 刚打开时还不知道是不是管理身份，多问一次
setInterval(loadAiVoices, 60000);
// 弹幕和 SC 是观众自己写的字（free）；默认 AI 声音只念感谢礼物、上舰这些固定的话，免得有人借主播的声音说怪话
function useAi(it) {
  const id = aiId();
  if (!id || !AI.online || !AI.voices.some(v => v.id === id) || Date.now() - AI.failAt < 20000) return false;
  return cfg.tts.aiScope === 'all' || !it.free;
}
function aiFetch(it) {
  if (it.ai !== undefined) return;
  it.ai = false;
  if (!useAi(it)) return;
  const ctl = new AbortController();
  it.abort = () => ctl.abort();
  it.ai = fetch('api/tts?' + new URLSearchParams({ voice: aiId(), text: it.text, speed: aiSpeed() }), { signal: ctl.signal })
    .then(r => { if (!r.ok) throw new Error(r.status); return r.blob(); })
    .then(b => it.dropped ? null : (it.url = URL.createObjectURL(b)))
    .catch(e => { if (e.name !== 'AbortError') { AI.failAt = Date.now(); if (String(e.message) === '403') AI.voices = []; } return null; });
}
const prefetch = () => tts.queue.slice(0, 2).forEach(aiFetch);
function dropItem(it) { it.dropped = true; it.abort?.(); if (it.url) URL.revokeObjectURL(it.url); it.url = null; }
// 选了 AI 音色才显示「AI 声音念哪些」；音调对 AI 声音不起作用
function drawAiRows() {
  const on = isAiVoice(cfg.tts.voice);
  document.querySelectorAll('.ai-only').forEach(el => el.style.display = on ? '' : 'none');
  const n = $('ainote');
  if (n) n.textContent = !on ? '' : !AI.online ? 'AI 音色服务现在没开，会先用浏览器的声音念。'
    : cfg.tts.aiScope === 'all' ? '弹幕和 SC 也用 AI 声音念。观众写什么就会念什么，屏蔽词照样有用。'
    : '弹幕和 SC 是观众自己写的字，照常用浏览器的声音念；礼物、上舰、关注、进房的感谢用 AI 声音。';
}
document.addEventListener('change', e => { if (e.target.id === 'voicesel' || e.target.dataset?.k === 'tts.aiScope') drawAiRows(); });
if (synth) { loadVoices(); synth.onvoiceschanged = loadVoices; }
function pickVoice() {
  if (cfg.tts.voice && !isAiVoice(cfg.tts.voice)) { const v = voices.find(x => x.name === cfg.tts.voice); if (v) return v; }
  const zh = voices.filter(v => /^zh[-_]CN|cmn/i.test(v.lang));
  return zh.find(v => /Xiaoxiao|晓晓/.test(v.name)) || zh.find(v => /Natural/.test(v.name)) || zh.find(v => /Huihui|慧慧|Yaoyao|瑶瑶/.test(v.name))
    || zh.find(v => v.localService) || zh[0] || voices.find(v => /^zh/i.test(v.lang)) || null;
}
const activated = () => !navigator.userActivation || navigator.userActivation.hasBeenActive;
function ttsUnlockHint() { $('ttshint').classList.toggle('show', cfg.tts.on && !activated()); }
document.addEventListener('pointerdown', () => setTimeout(() => { ttsUnlockHint(); pump(); }, 0), true);

function clean(text, maxLen, full) {
  let t = String(text ?? '')
    .replace(/https?:\/\/\S+/g, '链接')
    .replace(/\[([^\[\]]{1,10})\]/g, '$1')       // [牛] 这种小表情只读字
    .replace(/\s+/g, ' ').trim();
  // 连着重复很多的字：SC 原样全读；弹幕最多读 12 个，免得一条 wwww 刷屏读半分钟
  if (!full) t = t.replace(/(.)\1{12,}/gu, (m, c) => c.repeat(12));
  // 一串一样的字母（wwww、hhhh）语音会当成一个词只念一两声，中间加上停顿就会一个个念出来
  t = t.replace(/([a-zA-Z])\1{2,}/g, m => [...m].join(' '));
  const chars = [...t];
  if (maxLen && chars.length > maxLen) t = chars.slice(0, maxLen).join('');
  return t;
}
const shortName = n => { const c = [...String(n ?? '')]; return c.length > 12 ? c.slice(0, 12).join('') : c.join(''); };
const fill = (tpl, v) => String(tpl).replace(/\{(\w+)\}/g, (_, k) => v[k] ?? '');
function blocked(text) {
  const words = String(cfg.tts.block).split(/[\s,，、;；]+/).filter(Boolean);
  return words.some(w => String(text).toLowerCase().includes(w.toLowerCase()));
}
// prio：2 = SC/上舰，1 = 礼物，0 = 弹幕/进房；free：里面有观众自己写的字（弹幕、SC）
function say(text, prio = 0, force = false, free = false) {
  if ((!synth && !aiId()) || (!cfg.tts.on && !force) || !text) return;
  if (S.side && !force) return;  // 正在看别的直播间：不读（2026-11-21 用户要求；回到主播自动恢复，设置不变）
  const item = { text, prio, free };
  const i = tts.queue.findIndex(x => x.prio < prio);
  if (i < 0) tts.queue.push(item); else tts.queue.splice(i, 0, item);
  const low = tts.queue.filter(x => x.prio === 0);
  const keep = cfg.tts.zeroDelay ? 1 : 15;
  if (low.length > keep) { const drop = new Set(low.slice(0, low.length - keep)); drop.forEach(dropItem); tts.queue = tts.queue.filter(x => !drop.has(x)); }
  if (tts.queue.length > 40) tts.queue.splice(40).forEach(dropItem);
  pump();
}
function pump() {
  updateTtsBar();
  if (tts.cur) prefetch();  // 正在念的时候，后面排着的先合成
  if (tts.cur || !tts.queue.length) return;
  if (!activated()) { ttsUnlockHint(); return; }
  const it = tts.queue.shift();
  tts.cur = it; tts.startedAt = Date.now();
  aiFetch(it);
  prefetch();
  if (it.ai) {
    // 等 AI 合成好再念；等太久就这一句改用浏览器语音
    const late = setTimeout(() => { if (tts.cur === it && !it.started) { dropItem(it); speakBrowser(it); } }, AI_WAIT);
    it.ai.then(url => {
      clearTimeout(late);
      if (tts.cur !== it || it.started) return;
      if (url) playAi(it, url); else speakBrowser(it);
    });
  } else speakBrowser(it);
  updateTtsBar();
}
const ttsNext = it => { if (tts.cur !== it) return; dropItem(it); tts.cur = null; tts.utt = null; tts.audio = null; updateTtsBar(); setTimeout(pump, 80); };
function playAi(it, url) {
  it.started = true;
  const a = new Audio(url);
  sinkTo(a);
  a.volume = Math.min(1, Math.max(0, cfg.tts.volume));
  tts.audio = a; tts.startedAt = Date.now();
  a.onended = () => ttsNext(it);
  a.onerror = () => ttsNext(it);
  a.play().catch(() => { if (tts.cur === it && tts.audio === a) { tts.audio = null; dropItem(it); speakBrowser(it); } });
}
function speakBrowser(it) {
  it.started = true;
  if (!synth) return ttsNext(it);
  const u = new SpeechSynthesisUtterance(it.text);
  const v = pickVoice();
  if (v) u.voice = v;
  u.lang = v?.lang || 'zh-CN';
  u.volume = cfg.tts.volume; u.rate = cfg.tts.rate; u.pitch = cfg.tts.pitch;
  const done = () => { if (tts.utt === u) ttsNext(it); };
  u.onend = done; u.onerror = done;
  tts.utt = u; tts.startedAt = Date.now();  // 留着引用，不然 Chrome 有时不触发 onend
  synth.speak(u);
}
// 停掉正在念的这一句（不管是浏览器语音、AI 声音，还是还在等 AI 合成）
function stopCur() {
  const it = tts.cur;
  tts.cur = null; tts.utt = null;
  if (tts.audio) { tts.audio.onended = tts.audio.onerror = null; tts.audio.pause(); tts.audio = null; }
  if (it) dropItem(it);
  if (synth) synth.cancel();
}
setInterval(() => {
  if (!tts.cur) return;
  const v = tts.utt?.voice;
  // Chrome 的联网语音读太久会卡住，掐掉继续下一条；AI 声音一句最多 150 字，给 90 秒
  if (Date.now() - tts.startedAt > (tts.audio ? 90000 : tts.utt ? 30000 : AI_WAIT + 5000)) { stopCur(); pump(); }
  else if (tts.utt && v && !v.localService && synth.speaking) { synth.pause(); synth.resume(); }
}, 5000);
function ttsSkip() { stopCur(); setTimeout(pump, 50); }
function ttsClear() { tts.queue.forEach(dropItem); tts.queue = []; stopCur(); updateTtsBar(); }
function updateTtsBar() {
  const bar = $('ttsbar'), show = !!tts.cur;
  if (bar.classList.contains('show') !== show) bar.classList.toggle('show', show);
  if (tts.cur) { setText($('ttsnow'), tts.cur.text); $('ttsnow').title = tts.cur.text; }
  setText($('ttsq'), tts.queue.length ? `还有 ${tts.queue.length} 条` : '');
}
$('ttsskip').onclick = ttsSkip;
$('ttsclear').onclick = ttsClear;
// 插队马上读（试听、重听 SC 用）：朗读开关关着也读；正在读的那句先停掉
function sayNow(text, free = false) {
  if ((!synth && !aiId()) || !text) return;
  tts.queue.filter(x => x.now).forEach(dropItem);
  tts.queue = tts.queue.filter(x => !x.now);
  tts.queue.unshift({ text, prio: 9, now: true, free });
  if (tts.cur) stopCur();
  setTimeout(pump, 50);
}
// 每种消息读出来的话：真实朗读和试听用同一套，试听听到的就是直播时会读的
const scText = s => fill(cfg.tts.tpl.sc, { name: shortName(s.name), price: s.price, text: clean(s.text, 0, true) });
const dmText = d => fill(cfg.tts.readName ? cfg.tts.tpl.dm : '{text}', { name: shortName(d.name), text: clean(d.text, cfg.tts.maxLen) });
const giftText = it => fill(cfg.tts.tpl.gift, { name: shortName(it.name), num: it.num, gift: it.blind ? `${it.blind}爆出的${it.gift}` : it.gift }) + (cfg.tts.readPrice && it.yuan != null ? `，${Math.round(it.yuan * 100) / 100}元` : '');
const guardText = g => fill(cfg.tts.tpl.guard, { name: shortName(g.name), level: g.level_name, num: g.num });
const SAMPLE = {
  dm: () => dmText({ name: '冬天的鱼', text: ANCHOR() + '晚上好～今天唱什么呀' }),
  sc: () => scText({ name: '雾里看花', price: 50, text: `${ANCHOR()}辛苦啦，今天的歌超好听，早点休息哦` }),
  gift: () => giftText({ name: '雪糕不化', num: 5, gift: '小花花', yuan: 0.5 }),
  guard: () => guardText({ name: '路过的舰长', level_name: '舰长', num: 1 }),
  enter: () => fill(cfg.tts.tpl.enter, { name: '晚安主播' }),
  follow: () => fill(cfg.tts.tpl.follow, { name: '今天也想听歌' }),
};
document.addEventListener('click', e => { const b = e.target.closest('[data-tryt]'); if (b) sayNow(SAMPLE[b.dataset.tryt](), ['dm', 'sc'].includes(b.dataset.tryt)); });

// 各种消息怎么读
function speakDm(d) {
  const T = cfg.tts;
  if (!T.on || !T.dm || isMuted(d.uid)) return;
  if (T.skipBot && (S.bot_uids || []).includes(d.uid)) return;
  if (T.skipAnchor && isAnchor(d)) return;
  if (d.emoticon && !T.readEmoticon) return;
  if (blocked(d.text) || blocked(d.name)) return;
  const text = clean(d.text, T.maxLen);
  if (!text) return;
  say(fill(T.readName ? T.tpl.dm : '{text}', { name: shortName(d.name), text }), 0, false, true);
}
function speakSc(s) {
  const T = cfg.tts;
  if (!T.on || !T.sc || isMuted(s.uid) || blocked(s.text)) return;
  say(scText(s), 2, false, true);
}
const giftWait = new Map();
function speakGiftLater(g) {
  // 连击的礼物等停下来再读总数
  clearTimeout(giftWait.get(g.id));
  giftWait.set(g.id, setTimeout(() => {
    giftWait.delete(g.id);
    const T = cfg.tts, it = S.gifts.find(x => x.id === g.id) || g;
    if (!T.on || !T.gift || it.yuan < T.giftMin || isMuted(it.uid)) return;
    say(giftText(it), 1);
  }, 2500));
}
function speakGuard(g) {
  const T = cfg.tts;
  if (!T.on || !T.guard) return;
  say(guardText(g), 2);
}
function speakEnter(e) {
  const T = cfg.tts;
  if (!T.on || isMuted(e.uid)) return;
  if (e.kind === 'follow') { if (T.follow) say(fill(T.tpl.follow, { name: shortName(e.name) }), 0); return; }
  if (e.kind !== 'enter' || !T.enter) return;
  // 舰长进房的标记会晚一点到，等一下再看
  setTimeout(() => {
    const g = e.guard || userOf(e.uid)?.guard;
    if (T.enterGuardOnly && !g) return;
    say(fill(T.tpl.enter, { name: shortName(e.name) }), 0);
  }, 1500);
}

/* ---------- 提示音（2026-11-18）：每种事一个声音，在 设置 → 提醒 → 提示音 里分开开关，默认全关 ---------- */
const SND = { dm: [988], sc: [880, 1318.5], gift: [784, 1046.5], guard: [523.25, 659.25, 784, 1046.5], enterGuard: [659.25, 987.77], follow: [1174.7, 1568] };
const sndLast = {};
function sound(kind, force) {
  const C = cfg.snd;
  if (!force && (!C.on || !C[kind])) return;
  if (S.side && !force) return;  // 正在看别的直播间：提示音也不响
  const now = Date.now();
  if (!force && now - (sndLast[kind] || 0) < (kind === 'dm' ? 2000 : 500)) return;  // 刷屏时不连着响
  sndLast[kind] = now;
  ding(SND[kind], C.vol);
}
document.addEventListener('click', e => { const b = e.target.closest('[data-sndtry]'); if (b) sound(b.dataset.sndtry, true); });
// 总开关关着时，下面各项变淡（还能勾，打开总开关后才响）
const drawSnd = () => $('sndkinds')?.classList.toggle('off', !cfg.snd.on);
document.addEventListener('change', e => { if (e.target.dataset?.k === 'snd.on') drawSnd(); });
drawSnd();let actx;
let dingOff;
function ding(notes = [880, 1318.5], vol = 0.6) {
  if (!activated()) return;  // 浏览器规定点过页面才能出声
  try {
    if (!actx) { actx = new AudioContext(); if (outDev && typeof actx.setSinkId === 'function') actx.setSinkId(outDev).catch(() => {}); }
    if (actx.state === 'suspended') actx.resume();
    const peak = Math.max(0.01, Math.min(1, Number(vol) || 0.6)) * 0.3;
    notes.forEach((f, i) => {
      const o = actx.createOscillator(), g = actx.createGain(), t0 = actx.currentTime + i * .11;
      o.frequency.value = f; o.type = 'sine';
      g.gain.setValueAtTime(0, t0); g.gain.linearRampToValueAtTime(peak, t0 + .02); g.gain.exponentialRampToValueAtTime(.001, t0 + .6);
      o.connect(g).connect(actx.destination); o.start(t0); o.stop(t0 + .7);
    });
    // 响完就把声音通道停掉，不然它会一直在后台空转占 CPU
    clearTimeout(dingOff);
    dingOff = setTimeout(() => actx.suspend(), 1500 + notes.length * 110);
  } catch {}
}

// 设置 → 朗读 → AI 音色（2026-11-26）：填地址、选接口，保存时后台马上测一下连不连得上
async function drawAiBox() {
  if (!$('aiurl') || !S.admin) return;
  try {
    const j = await (await fetch('api/tts/voices', { cache: 'no-store' })).json();
    if (document.activeElement !== $('aiurl')) $('aiurl').value = j.url || '';
    $('aiapi').value = j.url ? (j.api || 'api_v2') : 'api_v2';  // 没设过的默认 GPT-SoVITS
    $('aitip').textContent = !j.url ? '没开' : j.online ? `连着，${(j.voices || []).length} 个音色` : '连不上';
  } catch {}
}
document.addEventListener('click', async e => {
  if (e.target.closest('[data-st="tts"], #setbtn')) drawAiBox();
  if (!e.target.closest('#aisave')) return;
  $('aitip').textContent = '正在测…';
  try {
    const j = await (await fetch('api/tts/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: $('aiurl').value.trim(), api: $('aiapi').value }) })).json();
    $('aitip').textContent = j.msg || (j.ok ? '好了' : '没成功');
    if (typeof loadVoices === 'function') loadVoices();
  } catch { $('aitip').textContent = '没保存上'; }
});

// 声音从哪出（2026-11-26，Gemini 反馈）：AI 朗读、提示音、页面放歌可以单独走耳机或者虚拟声卡，不进直播的桌面音频。
// 浏览器自带的朗读声音（不是 AI 音色的）浏览器不让换设备，只能跟系统默认走。选的设备只记在这台电脑的这个浏览器里
let outDev = '';
try { outDev = localStorage.getItem('xw-outdev') || ''; } catch {}
function sinkTo(el) {
  if (!el || typeof el.setSinkId !== 'function') return;
  el.setSinkId(outDev).catch(() => {});  // 设备拔掉了就还是从默认的出
}
async function listOutDevs(ask) {
  const sel = $('outdev');
  if (!sel || !navigator.mediaDevices?.enumerateDevices) return;
  try {
    // 不给一次麦克风权限，浏览器不告诉设备名字；只为读名字，拿到马上关，不录音
    if (ask) { const s = await navigator.mediaDevices.getUserMedia({ audio: true }); s.getTracks().forEach(t => t.stop()); }
    const list = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'audiooutput' && d.deviceId && d.deviceId !== 'default');
    sel.innerHTML = '<option value="">跟系统默认一样</option>' + list.map(d => `<option value="${esc(d.deviceId)}">${esc(d.label || '没名字的设备')}</option>`).join('');
    if (outDev && !list.some(d => d.deviceId === outDev)) sel.insertAdjacentHTML('beforeend', `<option value="${esc(outDev)}">之前选的设备（现在没接上）</option>`);
    sel.value = outDev;
    $('outdevask').hidden = list.some(d => d.label);
  } catch { $('outdevtip').textContent = '没拿到设备列表（要允许一次麦克风才能看到名字）'; }
}
function applyOutDev() {
  sinkTo(tts.audio);
  if (typeof mplayer !== 'undefined' && mplayer) sinkTo(mplayer.audio);
  if (actx && typeof actx.setSinkId === 'function') actx.setSinkId(outDev).catch(() => {});
}
document.addEventListener('change', e => {
  if (e.target.id !== 'outdev') return;
  outDev = e.target.value;
  try { outDev ? localStorage.setItem('xw-outdev', outDev) : localStorage.removeItem('xw-outdev'); } catch {}
  applyOutDev();
  sound('dm', true);
});
document.addEventListener('click', e => {
  if (e.target.closest('#outdevask')) listOutDevs(true);
  if (e.target.closest('[data-st="tts"], #setbtn')) listOutDevs(false);
});

// 设置 → 朗读 → AI 音色 → 音色列表（2026-11-26 桌面版：不用改 config.json）。
// 参考音频、模型文件是给这台电脑上的 GPT-SoVITS 读的，要的是文件路径：在本机打开的雾幕里点「选…」弹 Windows 的选文件窗口
let aiVoices = null, aiLocal = false;
const AI_LANGS = [['zh', '中文'], ['ja', '日语'], ['en', '英语'], ['ko', '韩语'], ['yue', '粤语']];
function drawAiVoices() {
  const box = $('aivlist');
  if (!box || !aiVoices) return;
  const pick = (i, f, kind, ph) => `<div class="aiv-f"><input data-av="${f}" value="${esc(aiVoices[i][f] || '')}" placeholder="${ph}" title="${esc(aiVoices[i][f] || '')}">${aiLocal ? `<button class="btn sm" data-avpick="${kind}" data-f="${f}">选…</button>` : ''}</div>`;
  box.innerHTML = aiVoices.length ? aiVoices.map((v, i) => `<div class="aiv" data-ai="${i}">
    <div class="aiv-h"><input data-av="name" value="${esc(v.name || '')}" placeholder="音色名字，比如 我的声音" maxlength="20"><button class="btn sm" data-avdel="${i}">删掉</button></div>
    <label>参考音频</label>${pick(i, 'ref_audio', 'audio', '3~10 秒的 wav 文件')}
    <label>它说的是</label><div class="aiv-f"><input data-av="ref_text" value="${esc(v.ref_text || '')}" placeholder="参考音频里说的话，一字不差" maxlength="200"><select data-av="ref_lang">${AI_LANGS.map(([k, n]) => `<option value="${k}"${(v.ref_lang || 'zh') === k ? ' selected' : ''}>${n}</option>`).join('')}</select></div>
    <label>GPT 模型</label>${pick(i, 'gpt', 'gpt', '可以不填（.ckpt）')}
    <label>SoVITS 模型</label>${pick(i, 'sovits', 'sovits', '可以不填（.pth）')}
  </div>`).join('') : '<div class="note">还没有音色，点「加一个音色」。</div>';
}
async function loadAiVoices() {
  try {
    const j = await (await fetch('api/tts/voices', { cache: 'no-store' })).json();
    aiLocal = !!j.local;
    $('aivoices').hidden = !(j.url && (j.api || 'api_v2') === 'api_v2');
    if (!$('aivlist').contains(document.activeElement)) { aiVoices = (j.conf_voices || []).map(v => ({ ...v })); drawAiVoices(); }
  } catch {}
}
document.addEventListener('input', e => {
  const r = e.target.closest('#aivlist .aiv'); if (!r || !aiVoices) return;
  aiVoices[Number(r.dataset.ai)][e.target.dataset.av] = e.target.value;
  $('aivtip').textContent = '有改动，记得点「保存音色」';
});
document.addEventListener('change', e => { if (e.target.closest('#aivlist') && e.target.tagName === 'SELECT') e.target.dispatchEvent(new Event('input', { bubbles: true })); });
document.addEventListener('click', async e => {
  if (e.target.closest('[data-st="tts"], #setbtn, #aisave')) setTimeout(loadAiVoices, e.target.closest('#aisave') ? 1500 : 0);
  if (!e.target.closest('#aivoices') || !aiVoices) return;
  if (e.target.closest('#aivadd')) { aiVoices.push({ name: '', ref_audio: '', ref_text: '', ref_lang: 'zh', gpt: '', sovits: '' }); drawAiVoices(); $('aivlist').querySelector('.aiv:last-child [data-av="name"]')?.focus(); return; }
  const d = e.target.closest('[data-avdel]');
  if (d) { aiVoices.splice(Number(d.dataset.avdel), 1); drawAiVoices(); $('aivtip').textContent = '有改动，记得点「保存音色」'; return; }
  const p = e.target.closest('[data-avpick]');
  if (p) {
    const r = p.closest('.aiv'), i = Number(r.dataset.ai);
    $('aivtip').textContent = '在弹出来的窗口里选文件…';
    try {
      const j = await (await fetch('api/pick_file?kind=' + p.dataset.avpick, { method: 'POST' })).json();
      if (j.path) { aiVoices[i][p.dataset.f] = j.path; drawAiVoices(); $('aivtip').textContent = '有改动，记得点「保存音色」'; }
      else $('aivtip').textContent = j.msg || '没选';
    } catch { $('aivtip').textContent = '选文件的窗口没打开'; }
    return;
  }
  if (e.target.closest('#aivsave')) {
    $('aivtip').textContent = '正在保存…';
    try {
      const j = await (await fetch('api/tts/voices', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ voices: aiVoices }) })).json();
      $('aivtip').textContent = j.msg || (j.ok ? '已保存' : '没保存上');
      if (j.ok && typeof loadVoices === 'function') loadVoices();
    } catch { $('aivtip').textContent = '没保存上'; }
  }
});
