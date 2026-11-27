// 放歌（2026-11-25）：弹幕点歌直接放的播放器。OBS 的 /obs-music 页面和开着「这页出声」的雾幕页面都用它。
// 服务器说现在放哪首、从什么时候开始放；这里只管去拿地址、对上进度放出来。几个页面同时开着各放各的，进度一样。
// 2026-11-26：音量跟着点歌姬面板上的音量条（m.vol）；换歌时渐入、快放完和切歌时渐出，不会一下子很响
class MusicPlayer {
  constructor(base = '') {
    this.base = base;
    this.audio = new Audio();
    this.audio.preload = 'auto';
    this.cur = '';
    this.vol = 0.8;     // 面板上的音量
    this.scale = 1;     // OBS 网址里的 vol（只在 OBS 放歌源上用，跟面板上的乘起来）
    this.fade = 1;      // 渐入渐出：0 ~ 1
    this.on = false;
    this.fadeT = 0;
    this.audio.addEventListener('error', () => { this.cur = ''; });
    this.audio.addEventListener('timeupdate', () => {  // 最后 2 秒渐出
      const a = this.audio, left = a.duration - a.currentTime;
      if (isFinite(left) && left < 2 && this.fade > 0) this.ramp(0, Math.max(200, left * 1000));
    });
  }
  apply() { this.audio.volume = Math.max(0, Math.min(1, this.vol * this.scale * this.fade)); }
  setVolume(v) { this.vol = Math.max(0, Math.min(1, v)); this.apply(); }
  ramp(to, ms) {
    clearInterval(this.fadeT);
    const from = this.fade, t0 = performance.now();
    return new Promise(done => {
      this.fadeT = setInterval(() => {
        const k = Math.min(1, (performance.now() - t0) / ms);
        this.fade = from + (to - from) * k; this.apply();
        if (k >= 1) { clearInterval(this.fadeT); done(); }
      }, 40);
    });
  }
  async stop() {
    if (!this.audio.paused) await this.ramp(0, 500);
    this.audio.pause(); this.audio.removeAttribute('src'); this.cur = '';
  }
  async update(m) {
    if (m && typeof m.vol === 'number') this.setVolume(m.vol / 100);
    const now = m?.list?.find(x => x.state === 'play');
    if (!this.on || !m?.on || m.mode !== 'web' || !now) { if (this.cur) this.stop(); return; }
    if (now.id === this.cur) return;
    const switching = !!this.cur && !this.audio.paused;
    this.cur = now.id;
    let j;
    try { j = await (await fetch(this.base + 'api/music/url?id=' + encodeURIComponent(now.id), { cache: 'no-store' })).json(); } catch { this.cur = ''; return; }
    if (this.cur !== now.id || !j.url) return;
    if (switching) await this.ramp(0, 500);  // 切歌：先把上一首渐出
    if (this.cur !== now.id) return;
    const a = this.audio;
    a.src = j.url;
    this.fade = 0; this.apply();
    const go = () => {
      const pos = j.now - j.start + (performance.now() - t0) / 1000;
      if (pos < 0) { setTimeout(go, -pos * 1000); return; }
      try { a.currentTime = pos; } catch {}
      a.play().then(() => this.ramp(1, 1200)).catch(() => { this.blocked?.(); });
    };
    const t0 = performance.now();
    if (a.readyState >= 1) go(); else a.addEventListener('loadedmetadata', go, { once: true });
  }
}
