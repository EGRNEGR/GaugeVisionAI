// Звуковая сигнализация на Web Audio API: без звуковых файлов.
//   warning — дискретный двухтональный сигнал 440 / 880 Гц;
//   alert   — непрерывная сирена, частотная модуляция 600–1200 Гц.
import { $ } from './util.js';

export const Sound = {
  ctx: null,
  enabled: localStorage.getItem('gv.sound') !== 'off',
  mode: 'none',
  nodes: [],
  timer: null,

  ensure() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      this.ctx = new AC();
    }
    if (this.ctx.state === 'suspended') this.ctx.resume().catch(() => {});
    return this.ctx;
  },
  get ready() { return !!this.ctx && this.ctx.state === 'running'; },

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    for (const n of this.nodes) {
      try { if (n.stop) n.stop(); } catch (_) { /* уже остановлен */ }
      try { n.disconnect(); } catch (_) { /* уже отключён */ }
    }
    this.nodes = [];
  },

  beep(freq, at, dur, vol = 0.18) {
    const ctx = this.ctx;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'square';
    osc.frequency.value = freq;
    const t = ctx.currentTime + at;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(vol, t + 0.015);
    g.gain.setValueAtTime(vol, t + dur - 0.03);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(g).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + dur + 0.02);
  },

  startWarning() {
    const play = () => { if (this.ready) { this.beep(440, 0, 0.22); this.beep(880, 0.28, 0.22); } };
    play();
    this.timer = setInterval(play, 1800);
  },

  startAlert() {
    const ctx = this.ctx;
    const osc = ctx.createOscillator();
    const lfo = ctx.createOscillator();
    const lfoGain = ctx.createGain();
    const filter = ctx.createBiquadFilter();
    const out = ctx.createGain();
    osc.type = 'sawtooth';
    osc.frequency.value = 900;
    lfo.type = 'sine';
    lfo.frequency.value = 0.8;
    lfoGain.gain.value = 300;
    filter.type = 'lowpass';
    filter.frequency.value = 2600;
    out.gain.value = 0.0001;
    out.gain.exponentialRampToValueAtTime(0.14, ctx.currentTime + 0.15);
    lfo.connect(lfoGain).connect(osc.frequency);
    osc.connect(filter).connect(out).connect(ctx.destination);
    osc.start();
    lfo.start();
    this.nodes = [osc, lfo, lfoGain, filter, out];
  },

  setMode(mode) {
    if (!this.enabled) mode = 'none';
    if (mode === this.mode && (mode === 'none' || this.nodes.length || this.timer || !this.ready)) return;
    this.stop();
    this.mode = mode;
    // до первого жеста оператора режим только запоминается: звук запустит обработчик жеста
    if (mode !== 'none' && this.ready) {
      if (mode === 'alert') this.startAlert();
      else this.startWarning();
    }
  },

  toggle() {
    this.enabled = !this.enabled;
    localStorage.setItem('gv.sound', this.enabled ? 'on' : 'off');
    const m = this.mode;
    this.mode = 'none';
    this.stop();
    if (this.enabled) { this.ensure(); this.setMode(m); }
    renderSoundButton();
    if (this.enabled && this.ready) this.beep(880, 0, 0.08, 0.08);
  },
};

export function renderSoundButton() {
  const btn = $('#btnSound');
  const blocked = Sound.enabled && !Sound.ready;
  btn.setAttribute('aria-pressed', String(Sound.enabled));
  btn.querySelector('use').setAttribute('href', Sound.enabled ? '#i-sound' : '#i-mute');
  btn.title = !Sound.enabled ? 'Звук выключен — включить сигнализацию'
    : blocked ? 'Браузер не даёт звук до первого нажатия на страницу'
      : 'Звук включён — выключить сигнализацию';
}

// Браузеры разрешают звук только после жеста пользователя.
['pointerdown', 'keydown'].forEach((evName) => document.addEventListener(evName, () => {
  if (!Sound.enabled) return;
  Sound.ensure();
  setTimeout(() => {
    renderSoundButton();
    if (Sound.ready && Sound.mode !== 'none' && !Sound.nodes.length && !Sound.timer) {
      const m = Sound.mode; Sound.mode = 'none'; Sound.setMode(m);
    }
  }, 60);
}, { passive: true }));
