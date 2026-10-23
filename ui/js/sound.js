// Sound effects: short recordings in ui/sfx, no music. One family: a chime (generated with ElevenLabs) is the motif,
// pitched into the chords of the results and the rarities; cards, chips, dice and glass are real recordings (Kenney, CC0).
// The roulette (a tick as each card passes the marker, the launch, the role and the champion found) and the binder
// cards (hover, booster, the back's wheel, flip, a reveal per rarity, the crowning). Off with the "Sons" setting;
// the volume comes from the settings too.
import { store } from "./ctx.js";

const FILES = ["tick", "spin", "stop_role", "stop_champ", "hover", "open", "wheel", "flip", "shatter", "rare", "epic", "legendary", "crown", "click"];
// loudness of each sound against the others (the files all peak at the same level)
const GAIN = { tick: 0.3, hover: 0.22, click: 0.4, spin: 0.5, stop_role: 0.6, stop_champ: 0.65, open: 0.6, wheel: 0.45, flip: 0.6,
  shatter: 0.6, rare: 0.55, epic: 0.6, legendary: 0.68, crown: 0.75 };

let ac = null, out = null, lastTick = 0, lastHover = 0;
const buffers = {}, loading = {};

function audio() {
  const p = store.profile || {};
  if (p.sounds === false) return null;
  try {
    if (!ac) {
      ac = new (window.AudioContext || window.webkitAudioContext)();
      out = ac.createGain();
      const comp = ac.createDynamicsCompressor();   // stacked sounds don't clip
      out.connect(comp).connect(ac.destination);
      FILES.forEach(load);   // small files: all ready before they're needed
    }
    if (ac.state === "suspended") ac.resume();
  } catch (e) {
    return null;   // no audio device: silent
  }
  out.gain.value = 0.9 * (p.sound_volume ?? 0.6);
  return ac;
}

function load(name) {
  loading[name] = loading[name] || fetch(`sfx/${name}.mp3`).then((r) => r.arrayBuffer()).then((b) => ac.decodeAudioData(b))
    .then((buf) => (buffers[name] = buf)).catch(() => null);
  return loading[name];
}

function play(name, { gain = 1, rate = 1 } = {}) {
  const a = audio();
  if (!a) return;
  const go = (buf) => {
    if (!buf) return;
    const s = a.createBufferSource(), g = a.createGain();
    s.buffer = buf;
    s.playbackRate.value = rate;
    g.gain.value = (GAIN[name] ?? 1) * gain;
    s.connect(g).connect(out);
    s.start();
  };
  if (buffers[name]) go(buffers[name]);
  else load(name).then(go);   // not decoded yet: plays a moment later
}

// --- roulette ---
export function tick(soft = false) {
  const now = performance.now();
  if (now - lastTick < 28) return;
  lastTick = now;
  play("tick", { gain: soft ? 0.6 : 1, rate: 0.96 + Math.random() * 0.08 });
}

export const spinStart = () => play("spin");

// a role found (small), a champion found (bigger)
export const win = (big = true) => play(big ? "stop_champ" : "stop_role");

// --- binder ---
export function hover(level) {
  const now = performance.now();
  if (now - lastHover < 70) return;
  lastHover = now;
  play("hover", { gain: level >= 2 ? 1 : 0.6, rate: level >= 4 ? 1.06 : 1 });
}

export const click = () => play("click");
export const rip = () => play("open");
// the back's roulette turns before the card flips over
export const wheel = () => play("wheel");
export const flip = () => play("flip");
export const shatter = () => play("shatter");   // the "Éclat d'argent" opening
export const reveal = (level) => play(level >= 4 ? "legendary" : level === 3 ? "epic" : "rare");
export const crown = () => play("crown");
