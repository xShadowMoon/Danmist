// 放歌（2026-11-25）：弹幕点歌直接放的播放器。OBS 的 /obs-music 页面和开着「这页出声」的弹幕姬页面都用它。
// 服务器说现在放哪首、从什么时候开始放；这里只管去拿地址、对上进度放出来。几个页面同时开着各放各的，进度一样。
class MusicPlayer {
  constructor(base = '') {
    this.base = base;
    this.audio = new Audio();
    this.audio.preload = 'auto';
    this.cur = '';
    this.vol = 0.8;
    this.on = false;
    this.audio.addEventListener('error', () => { this.cur = ''; });
  }
  setVolume(v) { this.vol = Math.max(0, Math.min(1, v)); this.audio.volume = this.vol; }
  stop() { this.audio.pause(); this.audio.removeAttribute('src'); this.cur = ''; }
  async update(m) {
    const now = m?.list?.find(x => x.state === 'play');
    if (!this.on || !m?.on || m.mode !== 'web' || !now) { if (this.cur) this.stop(); return; }
    if (now.id === this.cur) return;
    this.cur = now.id;
    let j;
    try { j = await (await fetch(this.base + 'api/music/url?id=' + encodeURIComponent(now.id), { cache: 'no-store' })).json(); } catch { this.cur = ''; return; }
    if (this.cur !== now.id || !j.url) return;
    const a = this.audio;
    a.src = j.url;
    a.volume = this.vol;
    const go = () => {
      const pos = j.now - j.start + (performance.now() - t0) / 1000;
      if (pos < 0) { setTimeout(go, -pos * 1000); return; }
      try { a.currentTime = pos; } catch {}
      a.play().catch(() => { this.blocked?.(); });
    };
    const t0 = performance.now();
    if (a.readyState >= 1) go(); else a.addEventListener('loadedmetadata', go, { once: true });
  }
}
