// 放歌（2026-11-25）：弹幕点歌直接放的播放器。雾幕自己的窗口和 OBS 的 /obs-music 页面都用它。
// 服务器说现在放哪首、从什么时候开始放；这里只管去拿地址、对上进度放出来。几个页面同时开着各放各的，进度一样。
// 2026-11-26：音量跟着点歌姬面板上的音量条（m.vol）；换歌时渐入、快放完和切歌时渐出；
//             响度均衡（m.norm）：一直量着这首歌有多响，太响的压一点、太小的抬一点（音频经雾幕转一手，同源才量得到）
class MusicPlayer {
  constructor(base = '') {
    this.base = base;
    this.audio = new Audio();
    this.audio.preload = 'auto';
    this.cur = '';
    this.vol = 0.8;     // 面板上的音量
    this.scale = 1;     // OBS 网址里的 vol（只在 OBS 放歌源上用，跟面板上的乘起来）
    this.fade = 1;      // 渐入渐出：0 ~ 1
    this.norm = true;
    this.on = false;
    this.fadeT = 0;
    this.ctx = null;    // 响度均衡用的 Web Audio（第一次放的时候才建）
    this.audio.addEventListener('error', () => { this.cur = ''; });
    this.audio.addEventListener('timeupdate', () => {  // 最后 2 秒渐出
      const a = this.audio, left = a.duration - a.currentTime;
      if (isFinite(left) && left < 2 && this.fade > 0) this.ramp(0, Math.max(200, left * 1000));
    });
  }
  graph() {
    if (this.ctx || !window.AudioContext) return;
    try {
      const c = new AudioContext();
      const src = c.createMediaElementSource(this.audio);
      this.an = c.createAnalyser(); this.an.fftSize = 2048;
      this.ng = c.createGain();                                   // 响度均衡的增益
      const comp = c.createDynamicsCompressor();                  // 抬上去以后别破音
      comp.threshold.value = -6; comp.ratio.value = 8; comp.attack.value = 0.003; comp.release.value = 0.25;
      this.mg = c.createGain();                                   // 音量 × 渐入渐出
      src.connect(this.an); src.connect(this.ng); this.ng.connect(comp); comp.connect(this.mg); this.mg.connect(c.destination);
      this.ctx = c; this.buf = new Float32Array(this.an.fftSize); this.loud = null;
      if (typeof outDev === 'string' && outDev && c.setSinkId) c.setSinkId(outDev).catch(() => {});  // 设置 → 朗读 → 声音从哪出
      setInterval(() => this.measure(), 250);
    } catch { this.ctx = null; }
  }
  measure() {
    if (!this.ctx || this.audio.paused) return;
    this.an.getFloatTimeDomainData(this.buf);
    let s = 0; for (const x of this.buf) s += x * x;
    const db = 10 * Math.log10(s / this.buf.length + 1e-12);
    if (db < -50) return;  // 安静的地方不算
    const k = this.loud == null ? 1 : (this.audio.currentTime < 4 ? 0.25 : 0.03);  // 刚开始快点对上，之后慢慢跟
    this.loud = this.loud == null ? db : this.loud + (db - this.loud) * k;
    const want = this.norm ? Math.max(0.4, Math.min(2.5, Math.pow(10, (-18 - this.loud) / 20))) : 1;
    this.ng.gain.setTargetAtTime(want, this.ctx.currentTime, 0.6);
  }
  apply() {
    const v = Math.max(0, Math.min(1, this.vol * this.scale * this.fade));
    if (this.ctx) { this.audio.volume = 1; this.mg.gain.value = v; } else this.audio.volume = v;
  }
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
    if (m && typeof m.norm === 'boolean') this.norm = m.norm;
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
    this.graph();
    if (this.ctx?.state === 'suspended') this.ctx.resume().catch(() => {});
    this.loud = null;
    a.src = /^https?:/.test(j.url) ? j.url : this.base + j.url;
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
