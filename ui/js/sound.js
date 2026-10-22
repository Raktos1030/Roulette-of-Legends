// Sound effects, synthesized on the fly (no audio files): the roulette (ticks as the cards pass the marker, a chime
// on the result) and the binder cards (hover, booster, flip, a reveal per rarity, the crowning). No music.
// Off with the "Sons" setting; the volume comes from the settings too.
import { store } from "./ctx.js";

let ac = null, out = null, noiseBuf = null, lastTick = 0, lastHover = 0;

function audio() {
  const p = store.profile || {};
  if (p.sounds === false) return null;
  try {
    if (!ac) {
      ac = new (window.AudioContext || window.webkitAudioContext)();
      out = ac.createGain();
      const comp = ac.createDynamicsCompressor();   // stacked sounds don't clip
      out.connect(comp).connect(ac.destination);
    }
    if (ac.state === "suspended") ac.resume();
  } catch (e) {
    return null;   // no audio device: silent
  }
  out.gain.value = 0.6 * (p.sound_volume ?? 0.6);
  return ac;
}

// one oscillator with a quick attack and an exponential decay; to: pitch glide
function tone(a, f, t, dur, { type = "sine", gain = 0.2, attack = 0.004, to = null } = {}) {
  const o = a.createOscillator(), g = a.createGain();
  o.type = type;
  o.frequency.setValueAtTime(f, t);
  if (to) o.frequency.exponentialRampToValueAtTime(to, t + dur);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(gain, t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(out);
  o.start(t);
  o.stop(t + dur + 0.05);
}

// filtered noise: clicks, swishes, whooshes, the air of an impact
function noise(a, t, dur, { gain = 0.15, freq = 2500, to = null, q = 1, type = "bandpass", attack = 0.003 } = {}) {
  if (!noiseBuf) {
    noiseBuf = a.createBuffer(1, a.sampleRate, a.sampleRate);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  }
  const s = a.createBufferSource(), f = a.createBiquadFilter(), g = a.createGain();
  s.buffer = noiseBuf;
  s.loop = true;
  f.type = type;
  f.Q.value = q;
  f.frequency.setValueAtTime(freq, t);
  if (to) f.frequency.exponentialRampToValueAtTime(to, t + dur);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(gain, t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  s.connect(f).connect(g).connect(out);
  s.start(t, Math.random() * 0.5);
  s.stop(t + dur + 0.05);
}

// a metal chime: a few inharmonic partials fading at different speeds
function bell(a, f, t, dur = 1.2, gain = 0.12) {
  for (const [r, g, d] of [[1, 1, 1], [2.76, 0.45, 0.55], [5.4, 0.22, 0.3], [8.93, 0.1, 0.18]]) {
    tone(a, f * r, t, dur * d, { gain: gain * g, attack: 0.002 });
  }
}

function boom(a, t, gain = 0.35, dur = 0.6) {
  tone(a, 110, t, dur, { gain, to: 38 });
  noise(a, t, dur * 0.7, { gain: gain * 0.5, freq: 380, type: "lowpass" });
}

function shimmer(a, t, dur, gain = 0.05) {
  noise(a, t, dur, { gain, freq: 6500, type: "highpass", attack: 0.08 });
  for (let i = 0; i < 7; i++) bell(a, 2400 + Math.random() * 2600, t + Math.random() * dur * 0.8, 0.35, 0.02);
}

// --- roulette ---
export function tick(soft = false) {
  const a = audio(), now = performance.now();
  if (!a || now - lastTick < 28) return;
  lastTick = now;
  const t = a.currentTime;
  noise(a, t, 0.02, { gain: soft ? 0.09 : 0.16, freq: 2600 + Math.random() * 500, q: 3 });
  tone(a, 1500 + Math.random() * 120, t, 0.03, { type: "triangle", gain: soft ? 0.025 : 0.04 });
}

export function spinStart() {
  const a = audio();
  if (!a) return;
  noise(a, a.currentTime, 0.55, { gain: 0.09, freq: 300, to: 2200, type: "lowpass", attack: 0.2 });
}

// a role found (small), a champion found (bigger)
export function win(big = true) {
  const a = audio();
  if (!a) return;
  const t = a.currentTime;
  if (!big) {
    bell(a, 880, t, 0.9, 0.1);
    bell(a, 1319, t + 0.06, 0.9, 0.08);
    return;
  }
  boom(a, t, 0.25, 0.4);
  [784, 988, 1175, 1568].forEach((f, i) => bell(a, f, t + 0.02 + i * 0.07, 1.4, 0.11));
  shimmer(a, t + 0.1, 0.8, 0.04);
}

// --- binder ---
// pointer on a card: a soft foil swish, a glint on the best ones
export function hover(level) {
  const a = audio(), now = performance.now();
  if (!a || now - lastHover < 70) return;
  lastHover = now;
  const t = a.currentTime;
  noise(a, t, 0.08, { gain: level >= 2 ? 0.035 : 0.018, freq: 3000, to: 5200, q: 0.8 });
  if (level >= 3) bell(a, level >= 4 ? 2637 : 2093, t + 0.01, 0.5, level >= 4 ? 0.03 : 0.02);
}

export function click() {
  const a = audio();
  if (!a) return;
  const t = a.currentTime;
  tone(a, 1150, t, 0.05, { type: "triangle", gain: 0.06 });
  noise(a, t, 0.03, { gain: 0.05, freq: 3500, q: 2 });
}

// a booster opens: the pack tears
export function rip() {
  const a = audio();
  if (!a) return;
  noise(a, a.currentTime, 0.28, { gain: 0.12, freq: 1800, to: 6500, q: 0.7, type: "highpass" });
}

// the back's roulette turns (1.1 s, slowing down) while its gems light up one after the other
export function wheel() {
  const a = audio();
  if (!a) return;
  const t = a.currentTime;
  let at = 0, gap = 0.035;
  while (at < 1.05) {
    noise(a, t + at, 0.018, { gain: 0.1, freq: 1900, q: 3 });
    at += gap;
    gap *= 1.16;
  }
  [1047, 1175, 1319, 1568, 1760, 2093, 2349, 2637].forEach((f, i) => bell(a, f, t + 0.1 + i * 0.075, 0.45, 0.03));
}

export function flip() {
  const a = audio();
  if (!a) return;
  const t = a.currentTime;
  noise(a, t, 0.16, { gain: 0.16, freq: 900, to: 3600, q: 0.9 });
  tone(a, 170, t + 0.05, 0.14, { gain: 0.1, to: 90 });
}

// the card revealed: the better it is, the richer the chime
export function reveal(level) {
  const a = audio();
  if (!a) return;
  const t = a.currentTime;
  if (level <= 2) {
    bell(a, 1047, t, 1.1, 0.1);
    bell(a, 1568, t + 0.09, 1.1, 0.08);
    shimmer(a, t, 0.4, 0.025);
  } else if (level === 3) {
    [784, 1047, 1319, 1568].forEach((f, i) => bell(a, f, t + i * 0.08, 1.5, 0.1));
    for (const f of [523, 659, 784]) tone(a, f, t, 1.4, { type: "triangle", gain: 0.035, attack: 0.08 });
    shimmer(a, t + 0.1, 0.8, 0.04);
  } else {
    boom(a, t, 0.4, 0.8);
    [523, 659, 784, 1047, 1319, 1568, 2093].forEach((f, i) => bell(a, f, t + 0.05 + i * 0.07, 1.8, 0.1));
    for (const f of [262, 330, 392, 523]) tone(a, f, t + 0.05, 2.4, { type: "triangle", gain: 0.04, attack: 0.25 });
    shimmer(a, t + 0.15, 1.6, 0.06);
  }
}

// the crown lands on a mastered champion: impact, then a fanfare chord
export function crown() {
  const a = audio();
  if (!a) return;
  const t = a.currentTime;
  boom(a, t, 0.5, 0.9);
  for (const f of [392, 494, 587, 784]) {
    const o = a.createOscillator(), lp = a.createBiquadFilter(), g = a.createGain();
    o.type = "sawtooth";
    o.frequency.value = f;
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(900, t);
    lp.frequency.exponentialRampToValueAtTime(2600, t + 0.3);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.045, t + 0.06);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 1.8);
    o.connect(lp).connect(g).connect(out);
    o.start(t);
    o.stop(t + 1.9);
  }
  [1568, 1976, 2349, 3136].forEach((f, i) => bell(a, f, t + 0.12 + i * 0.06, 1.4, 0.06));
  shimmer(a, t + 0.2, 1.8, 0.06);
}
