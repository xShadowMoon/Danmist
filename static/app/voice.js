// 弹幕姬主页面 · 语音朗读、提示声
// 这几个文件按顺序加载，共用同一套全局变量。加载时只能直接用前面文件里的东西，用后面文件的函数要放进回调里
/* ---------- 语音朗读（浏览器自带语音） ---------- */
const synth = window.speechSynthesis;
const tts = { queue: [], cur: null, startedAt: 0, utt: null };
let voices = [];
function loadVoices() { voices = synth ? synth.getVoices() : []; fillVoices(); }
function fillVoices() {
  const sel = $('voicesel');
  const zh = voices.filter(v => /^zh|cmn/i.test(v.lang));
  const rest = voices.filter(v => !/^zh|cmn/i.test(v.lang));
  sel.innerHTML = '<option value="">自动（优先中文女声）</option>' +
    zh.map(v => `<option value="${esc(v.name)}">${esc(v.name)}${v.localService ? '' : '（要联网）'}</option>`).join('') +
    (rest.length ? '<optgroup label="其它语言">' + rest.map(v => `<option value="${esc(v.name)}">${esc(v.name)}</option>`).join('') + '</optgroup>' : '');
  sel.value = cfg.tts.voice;
  if (sel.value !== cfg.tts.voice) sel.value = '';
}
if (synth) { loadVoices(); synth.onvoiceschanged = loadVoices; }
function pickVoice() {
  if (cfg.tts.voice) { const v = voices.find(x => x.name === cfg.tts.voice); if (v) return v; }
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
// prio：2 = SC/上舰，1 = 礼物，0 = 弹幕/进房
function say(text, prio = 0, force = false) {
  if (!synth || (!cfg.tts.on && !force) || !text) return;
  if (S.side && !force) return;  // 正在看别的直播间：不读（2026-11-21 用户要求；回到主播自动恢复，设置不变）
  const item = { text, prio };
  const i = tts.queue.findIndex(x => x.prio < prio);
  if (i < 0) tts.queue.push(item); else tts.queue.splice(i, 0, item);
  const low = tts.queue.filter(x => x.prio === 0);
  const keep = cfg.tts.zeroDelay ? 1 : 15;
  if (low.length > keep) { const drop = new Set(low.slice(0, low.length - keep)); tts.queue = tts.queue.filter(x => !drop.has(x)); }
  if (tts.queue.length > 40) tts.queue.splice(40);
  pump();
}
function pump() {
  updateTtsBar();
  if (!synth || tts.cur || !tts.queue.length) return;
  if (!activated()) { ttsUnlockHint(); return; }
  const it = tts.queue.shift();
  const u = new SpeechSynthesisUtterance(it.text);
  const v = pickVoice();
  if (v) u.voice = v;
  u.lang = v?.lang || 'zh-CN';
  u.volume = cfg.tts.volume; u.rate = cfg.tts.rate; u.pitch = cfg.tts.pitch;
  const done = () => { if (tts.utt !== u) return; tts.cur = null; tts.utt = null; updateTtsBar(); setTimeout(pump, 80); };
  u.onend = done; u.onerror = done;
  tts.cur = it; tts.utt = u; tts.startedAt = Date.now();  // 留着引用，不然 Chrome 有时不触发 onend
  synth.speak(u);
  updateTtsBar();
}
setInterval(() => {
  if (!tts.cur) return;
  const v = tts.utt?.voice;
  // Chrome 的联网语音读太久会卡住，掐掉继续下一条
  if (Date.now() - tts.startedAt > 30000) { synth.cancel(); tts.cur = null; tts.utt = null; pump(); }
  else if (v && !v.localService && synth.speaking) { synth.pause(); synth.resume(); }
}, 5000);
function ttsSkip() { if (synth) synth.cancel(); tts.cur = null; tts.utt = null; setTimeout(pump, 50); }
function ttsClear() { tts.queue = []; if (tts.cur && synth) synth.cancel(); tts.cur = null; tts.utt = null; updateTtsBar(); }
function updateTtsBar() {
  const bar = $('ttsbar'), show = !!tts.cur;
  if (bar.classList.contains('show') !== show) bar.classList.toggle('show', show);
  if (tts.cur) { setText($('ttsnow'), tts.cur.text); $('ttsnow').title = tts.cur.text; }
  setText($('ttsq'), tts.queue.length ? `还有 ${tts.queue.length} 条` : '');
}
$('ttsskip').onclick = ttsSkip;
$('ttsclear').onclick = ttsClear;
// 插队马上读（试听、重听 SC 用）：朗读开关关着也读；正在读的那句先停掉
function sayNow(text) {
  if (!synth || !text) return;
  tts.queue = tts.queue.filter(x => !x.now);
  tts.queue.unshift({ text, prio: 9, now: true });
  if (tts.cur) { synth.cancel(); tts.cur = null; tts.utt = null; }
  setTimeout(pump, 50);
}
// 每种消息读出来的话：真实朗读和试听用同一套，试听听到的就是直播时会读的
const scText = s => fill(cfg.tts.tpl.sc, { name: shortName(s.name), price: s.price, text: clean(s.text, 0, true) });
const dmText = d => fill(cfg.tts.readName ? cfg.tts.tpl.dm : '{text}', { name: shortName(d.name), text: clean(d.text, cfg.tts.maxLen) });
const giftText = it => fill(cfg.tts.tpl.gift, { name: shortName(it.name), num: it.num, gift: it.blind ? `${it.blind}爆出的${it.gift}` : it.gift }) + (cfg.tts.readPrice && it.yuan != null ? `，${Math.round(it.yuan * 100) / 100}元` : '');
const guardText = g => fill(cfg.tts.tpl.guard, { name: shortName(g.name), level: g.level_name, num: g.num });
const SAMPLE = {
  dm: () => dmText({ name: '冬天的鱼', text: '主播晚上好～今天唱什么呀' }),
  sc: () => scText({ name: '雾里看花', price: 50, text: '主播辛苦啦，今天的歌超好听，早点休息哦' }),
  gift: () => giftText({ name: '雪糕不化', num: 5, gift: '小花花', yuan: 0.5 }),
  guard: () => guardText({ name: '路过的舰长', level_name: '舰长', num: 1 }),
  enter: () => fill(cfg.tts.tpl.enter, { name: '晚安主播' }),
  follow: () => fill(cfg.tts.tpl.follow, { name: '今天也想听歌' }),
};
document.addEventListener('click', e => { const b = e.target.closest('[data-tryt]'); if (b) sayNow(SAMPLE[b.dataset.tryt]()); });

// 各种消息怎么读
function speakDm(d) {
  const T = cfg.tts;
  if (!T.on || !T.dm || isMuted(d.uid)) return;
  if (T.skipBot && (S.bot_uids || []).includes(d.uid)) return;
  if (T.skipAnchor && S.room.uid && d.uid === S.room.uid) return;
  if (d.emoticon && !T.readEmoticon) return;
  if (blocked(d.text) || blocked(d.name)) return;
  const text = clean(d.text, T.maxLen);
  if (!text) return;
  say(fill(T.readName ? T.tpl.dm : '{text}', { name: shortName(d.name), text }), 0);
}
function speakSc(s) {
  const T = cfg.tts;
  if (!T.on || !T.sc || isMuted(s.uid) || blocked(s.text)) return;
  say(scText(s), 2);
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
    actx ??= new AudioContext();
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

