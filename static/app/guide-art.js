// 功能页的插图（2026-11-26 用户：截图太密，自己画）。每张是一个小 SVG，只用这几种颜色（样式在 main.css 的 #guide .gimg）：
// A 主题色  T 主题色的浅色  C 卡片底色  S 灰（边框、底座）  W 白  K 主题色的线条
// 颜色都是 CSS 变量，跟着深色 / 浅色、主题色自己变。新加功能卡片：在这里加一张，id 和 news.json 的 cards 对上
const ART_CHECK = (x, y, r = 14) => `<circle cx="${x}" cy="${y}" r="${r}" class="A"/><path d="M${x - 7} ${y} l5 5 9-10" class="K" style="stroke:#fff"/>`;
const ART_ROWS = (x, y, n, w = 70) => Array.from({ length: n }, (_, i) => `<circle cx="${x + 6}" cy="${y + i * 20 + 6}" r="6" class="A" opacity="${1 - i * 0.18}"/><rect x="${x + 18}" y="${y + i * 20 + 1}" width="${w - i * 8}" height="5" rx="2.5" class="T"/><rect x="${x + 18}" y="${y + i * 20 + 9}" width="${w * 0.6}" height="4" rx="2" class="S"/>`).join('');
const GUIDE_ART = {
  login: `<rect x="52" y="10" width="56" height="100" rx="10" class="S"/><rect x="56" y="18" width="48" height="80" rx="6" class="C"/>
    <g class="A"><rect x="64" y="30" width="12" height="12" rx="2"/><rect x="84" y="30" width="12" height="12" rx="2"/><rect x="64" y="50" width="12" height="12" rx="2"/>
    <rect x="84" y="54" width="5" height="5"/><rect x="91" y="50" width="5" height="5"/><rect x="88" y="58" width="8" height="4"/><rect x="80" y="46" width="4" height="4"/></g>
    <rect x="64" y="72" width="32" height="5" rx="2.5" class="T"/><rect x="70" y="82" width="20" height="5" rx="2.5" class="T"/>${ART_CHECK(114, 86, 15)}`,
  switch: `<rect x="14" y="26" width="56" height="42" rx="7" class="S"/><rect x="18" y="30" width="48" height="34" rx="4" class="C"/><rect x="26" y="40" width="32" height="5" rx="2.5" class="T"/><rect x="26" y="50" width="22" height="5" rx="2.5" class="T"/>
    <rect x="90" y="40" width="56" height="42" rx="7" class="A"/><rect x="94" y="44" width="48" height="34" rx="4" class="C"/><rect x="102" y="54" width="32" height="5" rx="2.5" class="A"/><rect x="102" y="64" width="22" height="5" rx="2.5" class="A" opacity=".5"/>
    <path d="M60 84 q20 18 40 4" class="K"/><path d="M94 82 l6 6 -8 3" class="K"/><path d="M100 22 q-20 -12 -40 4" class="K" opacity=".5"/>`,
  dm: `<rect x="18" y="10" width="124" height="100" rx="10" class="C"/>${ART_ROWS(28, 20, 4, 86)}`,
  card: `<rect x="26" y="10" width="108" height="100" rx="12" class="C"/><circle cx="56" cy="36" r="14" class="A"/><rect x="76" y="28" width="44" height="7" rx="3.5" class="T"/><rect x="76" y="40" width="28" height="5" rx="2.5" class="S"/>
    <g><rect x="36" y="60" width="26" height="20" rx="5" class="T"/><rect x="67" y="60" width="26" height="20" rx="5" class="T"/><rect x="98" y="60" width="26" height="20" rx="5" class="T"/></g>
    <rect x="36" y="88" width="88" height="10" rx="5" class="S"/><path d="M40 93 h10" class="K" style="stroke-width:2.5"/>`,
  sc: `<rect x="22" y="14" width="116" height="42" rx="10" class="A"/><circle cx="38" cy="28" r="7" class="W" opacity=".9"/><rect x="50" y="24" width="34" height="7" rx="3.5" class="W" opacity=".85"/>
    <rect x="102" y="21" width="28" height="13" rx="6.5" class="W"/><text x="116" y="31" text-anchor="middle" font-size="10" font-weight="700" class="A">¥50</text><rect x="32" y="42" width="84" height="5" rx="2.5" class="W" opacity=".7"/>
    <rect x="22" y="64" width="116" height="38" rx="10" class="T"/><circle cx="38" cy="78" r="7" class="A" opacity=".6"/><rect x="50" y="74" width="30" height="7" rx="3.5" class="A" opacity=".45"/>
    <rect x="32" y="89" width="70" height="5" rx="2.5" class="A" opacity=".3"/><rect x="22" y="56" width="70" height="3" rx="1.5" class="A" opacity=".5"/>`,
  gift: `<rect x="46" y="46" width="68" height="54" rx="6" class="A"/><rect x="40" y="34" width="80" height="18" rx="5" class="A"/><rect x="74" y="34" width="12" height="66" class="W" opacity=".85"/>
    <path d="M80 34 q-22 -22 -26 -6 q-2 8 26 6 q28 2 26 -6 q-4 -16 -26 6z" class="T"/>${ART_CHECK(118, 92, 13)}<circle cx="30" cy="84" r="7" class="T"/><circle cx="24" cy="66" r="4" class="T"/>`,
  req: `<rect x="56" y="12" width="88" height="96" rx="10" class="C"/>${[0, 1, 2, 3].map(i => `<text x="68" y="${38 + i * 20}" font-size="11" font-weight="700" class="A" opacity="${1 - i * 0.2}">${i + 1}</text><rect x="80" y="${30 + i * 20}" width="${50 - i * 6}" height="6" rx="3" class="${i ? 'T' : 'A'}"/>`).join('')}
    <circle cx="28" cy="78" r="12" class="A"/><path d="M38 78 V30 l16 -6 v12 l-16 6" class="K" style="stroke-width:4"/>`,
  stats: `<rect x="16" y="14" width="128" height="92" rx="10" class="C"/><rect x="30" y="74" width="16" height="22" rx="3" class="T"/><rect x="54" y="58" width="16" height="38" rx="3" class="T"/><rect x="78" y="42" width="16" height="54" rx="3" class="A" opacity=".7"/><rect x="102" y="26" width="16" height="70" rx="3" class="A"/>
    <path d="M30 60 L62 44 L86 30 L122 20" class="K" opacity=".45"/>`,
  tts: `<path d="M36 48 h16 l20 -18 v60 l-20 -18 h-16z" class="A"/><path d="M84 46 q8 14 0 28" class="K"/><path d="M96 38 q16 22 0 44" class="K" opacity=".7"/><path d="M108 30 q24 30 0 60" class="K" opacity=".4"/>
    <rect x="96" y="92" width="48" height="18" rx="9" class="T"/><rect x="104" y="99" width="30" height="4" rx="2" class="A" opacity=".6"/>`,
  alert: `<path d="M80 20 c-20 0 -30 16 -30 34 v18 l-10 12 h80 l-10 -12 v-18 c0 -18 -10 -34 -30 -34z" class="A"/><circle cx="80" cy="94" r="8" class="A"/><rect x="76" y="12" width="8" height="10" rx="4" class="A"/>
    <path d="M38 30 q-12 16 0 32" class="K" opacity=".5"/><path d="M122 30 q12 16 0 32" class="K" opacity=".5"/><path d="M28 22 q-18 24 0 48" class="K" opacity=".3"/><path d="M132 22 q18 24 0 48" class="K" opacity=".3"/>`,
  obs: `<rect x="14" y="12" width="132" height="82" rx="9" class="S"/><rect x="20" y="18" width="120" height="70" rx="5" class="C"/><path d="M84 40 l18 12 -18 12z" class="T"/>
    <rect x="26" y="26" width="40" height="9" rx="4.5" class="A"/><rect x="26" y="40" width="30" height="9" rx="4.5" class="A" opacity=".7"/><rect x="26" y="54" width="44" height="9" rx="4.5" class="A" opacity=".5"/><rect x="26" y="68" width="24" height="9" rx="4.5" class="A" opacity=".3"/>
    <rect x="68" y="94" width="24" height="6" rx="2" class="S"/><rect x="56" y="100" width="48" height="5" rx="2.5" class="S"/>`,
  hist: `<rect x="38" y="26" width="92" height="76" rx="9" class="T"/><rect x="32" y="20" width="92" height="76" rx="9" class="S"/><rect x="26" y="14" width="92" height="76" rx="9" class="C"/>
    <rect x="26" y="14" width="92" height="18" rx="9" class="A"/><rect x="26" y="24" width="92" height="8" class="A"/>${[0, 1, 2].map(i => `<rect x="38" y="${42 + i * 14}" width="${60 - i * 10}" height="6" rx="3" class="T"/>`).join('')}${ART_CHECK(116, 92, 13)}`,
  layout: `<rect x="16" y="14" width="128" height="92" rx="10" class="S"/><rect x="22" y="20" width="56" height="80" rx="6" class="C"/><rect x="84" y="20" width="54" height="36" rx="6" class="C"/>
    <rect x="84" y="62" width="54" height="38" rx="6" class="T" stroke="currentColor" stroke-dasharray="4 4" style="stroke:var(--mist-d)" stroke-width="2"/><rect x="92" y="50" width="54" height="38" rx="6" class="A" opacity=".9"/>
    <path d="M110 64 l9 9 m0 -9 l-9 9" class="K" style="stroke:#fff"/><path d="M116 60 v20 m-10 -10 h20" class="K" style="stroke:#fff"/>`,
  look: `<circle cx="58" cy="58" r="32" class="A"/><path d="M58 26 a32 32 0 0 0 0 64z" class="C"/><circle cx="58" cy="58" r="32" class="K" style="stroke:var(--mist-d)"/>
    ${['#f4a9c4', '#8fdcbf', '#b3b6f7', '#f2c46b'].map((c, i) => `<circle cx="${110 + (i % 2) * 22}" cy="${40 + Math.floor(i / 2) * 26}" r="9" fill="${c}"/>`).join('')}<circle cx="121" cy="98" r="9" class="A"/>`,
  tags: `${[['A', 20, 26, 46], ['T', 74, 26, 64], ['A', 30, 56, 64], ['S', 102, 56, 40], ['T', 20, 86, 40], ['A', 68, 86, 70]].map(([c, x, y, w]) => `<rect x="${x}" y="${y}" width="${w}" height="20" rx="10" class="${c}"${c === 'A' ? '' : ''}/><circle cx="${x + 11}" cy="${y + 10}" r="3.5" class="${c === 'A' ? 'W' : 'A'}"/>`).join('')}`,
  room: `<rect x="30" y="34" width="100" height="66" rx="9" class="A"/><rect x="36" y="40" width="88" height="54" rx="5" class="C"/><path d="M60 14 l20 20 20 -20" class="K"/>
    <circle cx="58" cy="67" r="8" class="T"/><circle cx="80" cy="67" r="8" class="A" opacity=".7"/><circle cx="102" cy="67" r="8" class="T"/>`,
  backup: `<path d="M44 80 a22 22 0 0 1 4 -44 a30 30 0 0 1 56 4 a20 20 0 0 1 8 40z" class="T"/><path d="M80 92 V54 m-14 14 l14 -14 14 14" class="K" style="stroke-width:5"/>
    <circle cx="128" cy="94" r="14" class="A"/><circle cx="123" cy="92" r="2" class="W"/><circle cx="133" cy="92" r="2" class="W"/><path d="M123 99 q5 4 10 0" class="K" style="stroke:#fff;stroke-width:2"/>`,
  preflight: `<rect x="34" y="10" width="92" height="100" rx="10" class="C"/>${[0, 1, 2, 3].map(i => `<circle cx="52" cy="${32 + i * 22}" r="7" class="${i < 3 ? 'A' : 'S'}"/>${i < 3 ? `<path d="M48 ${32 + i * 22} l3 3 5 -6" class="K" style="stroke:#fff;stroke-width:2.5"/>` : ''}<rect x="66" y="${29 + i * 22}" width="${46 - i * 4}" height="6" rx="3" class="T"/>`).join('')}`,
  links: `<rect x="26" y="16" width="44" height="84" rx="9" class="S"/><rect x="30" y="24" width="36" height="64" rx="5" class="C"/>${ART_ROWS(33, 30, 3, 22)}
    <path d="M92 66 l14 -14 a10 10 0 0 1 14 14 l-8 8" class="K" style="stroke-width:5"/><path d="M118 54 l-14 14 a10 10 0 0 1 -14 -14 l8 -8" class="K" style="stroke-width:5" opacity=".6"/>`,
};
const guideArt = id => GUIDE_ART[id] ? `<svg viewBox="0 0 160 120" aria-hidden="true">${GUIDE_ART[id]}</svg>` : '';
