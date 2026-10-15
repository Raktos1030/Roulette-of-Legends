// Shared helpers: language, escaping, number formatting (French or English), images, icons, glossary.

export const NBSP = " ";

// --- UI language: French is the key, ui/i18n/en.json gives the English ----------------------------------------
export let LANG = "fr";
let DICT = {};
export async function setupLang(lang) {
  LANG = lang === "en" ? "en" : "fr";
  document.documentElement.lang = LANG;
  DICT = {};
  if (LANG === "en") {
    try {
      DICT = await (await fetch("i18n/en.json", { cache: "no-cache" })).json();
    } catch (e) {
      DICT = {};
    }
  }
  ROLE_LABEL.random = t("Aléatoire");
}
// t("Copier"); t("{0} parties", 12): {0}, {1}... replaced by the (already formatted) values
export function t(fr, ...args) {
  // French non-breaking spaces (" : ", " ... ") are ignored when looking the text up
  const en = LANG === "en" ? DICT[fr] ?? DICT[String(fr).replace(/[  ]/g, " ")] : undefined;
  let s = en !== undefined ? en : fr;
  if (args.length) s = s.replace(/\{(\d)\}/g, (m, i) => (args[+i] ?? ""));
  return s;
}

export function esc(s) {
  // HTML escaping + French typography non-breaking spaces (before : ; ! ? », after «)
  const out = String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  return LANG === "en" ? out : out.replace(/ ([:;!?»])/g, " $1").replace(/« /g, "« ");
}

export function norm(s) {
  return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

export function num(x, d = 1) {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const s = Number(x).toFixed(d);
  return LANG === "en" ? s : s.replace(".", ",");
}
export const pct = (x, d = 1) => (x === null || x === undefined ? "—" : num(x, d) + (LANG === "en" ? "" : NBSP) + "%");
export function int(n) {
  if (n === null || n === undefined) return "—";
  return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, LANG === "en" ? "," : NBSP);
}
export function kilo(n) {
  if (!n) return "0";
  return n >= 1000 ? num(n / 1000, n >= 100000 ? 0 : 1) + (LANG === "en" ? "" : NBSP) + "k" : int(n);
}
export function signed(n, d = 1) {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  const s = d === 0 ? Math.abs(Math.round(v)).toString() : num(Math.abs(v), d);
  return (v > 0 ? "+" : v < 0 ? "−" : "") + s;
}

// images
export const img = {
  icon: (k) => `/img/icons/${encodeURIComponent(k)}.png`,
  tall: (k) => `/img/loading/${encodeURIComponent(k)}.jpg`,
  splash: (k) => `/img/splash/${encodeURIComponent(k)}.jpg`,
  spell: (k, s) => `/img/spells/${encodeURIComponent(k)}_${s}.png`,
};
export const ROLE_ICON = { top: "top", jgl: "jungle", mid: "middle", adc: "bottom", sup: "utility", random: "fill" };
export const ROLE_LABEL = { top: "Top", jgl: "Jungle", mid: "Mid", adc: "ADC", sup: "Support", random: "Aléatoire" };
export const ROLES = ["top", "jgl", "mid", "adc", "sup"];
export const CHAOS_ICON = `<svg class="chaos-ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5c.6 3.3 3.9 4.6 3.9 8.5a3.9 3.9 0 0 1-7.8 0c0-1.5.6-2.6 1.4-3.5.2 1.6 1 2.5 2 2.5-1.1-2.6-.4-5.5.5-7.5z"/><path d="M6.4 9.6C5.2 11 4.5 12.8 4.5 14.7A7.5 7.5 0 0 0 12 22.2a7.5 7.5 0 0 0 7.5-7.5c0-2-.8-3.9-2.1-5.3"/></svg>`;

export function roleIcon(role, cls = "") {
  return `<i class="ri ${cls}" style="--m:url('/img/roles/${ROLE_ICON[role] || "fill"}.png')"></i>`;
}
export const ICONS = {
  roulette: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><path d="M12 3v6M12 15v6M3 12h6M15 12h6M5.6 5.6l4.3 4.3M14.1 14.1l4.3 4.3M18.4 5.6l-4.3 4.3M9.9 14.1l-4.3 4.3"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="M12 3.2l2.7 5.5 6 .9-4.4 4.2 1 6-5.3-2.8-5.3 2.8 1-6-4.4-4.2 6-.9z"/></svg>',
  history: '<svg viewBox="0 0 24 24"><path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3 4v4.5h4.5"/><path d="M12 7.5V12l3 2"/></svg>',
  book: '<svg viewBox="0 0 24 24"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5"/><path d="M8.5 7.5h7M8.5 11h5"/></svg>',
  guide: '<svg viewBox="0 0 24 24"><path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/><path d="M9 11h7M9 14.5h7M9 18h4"/></svg>',
  live: '<svg viewBox="0 0 24 24"><path d="M14.5 17.5L3 6V3h3l11.5 11.5"/><path d="M13 19l6-6M16 16l4 4M19 21l2-2"/><path d="M14.5 6.5L18 3h3v3l-3.5 3.5"/><path d="M5 14l4 4M7 17l-3 3M3 19l2 2"/></svg>',
  gear: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
};

export function html(strings, ...vals) {
  // template: values are inserted as is (escape with esc when needed)
  return strings.reduce((a, s, i) => a + s + (i < vals.length ? (Array.isArray(vals[i]) ? vals[i].join("") : vals[i] ?? "") : ""), "");
}

export function el(markup) {
  const t = document.createElement("template");
  t.innerHTML = markup.trim();
  return t.content.firstElementChild;
}

export function firstSentence(t) {
  const m = String(t || "").match(/^.*?[.!?](?=\s|$)/);
  return m ? m[0] : t || "";
}

// --- glossary: spots terms in guide text ------------------------------------------------------
let linker = null;
export function setupGlossary(glossary) {
  const terms = (glossary && glossary.terms) || [];
  const map = new Map();
  const words = [];
  for (const t of terms) {
    if (t.hl === false) continue;
    for (const w of [t.term, ...(t.aliases || [])]) {
      if (!w || w.length < 2) continue;
      const k = w.toLowerCase();
      if (!map.has(k)) {
        map.set(k, t);
        words.push(w);
      }
    }
  }
  words.sort((a, b) => b.length - a.length);
  if (!words.length) {
    linker = null;
    return;
  }
  const alt = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  // a term may follow an elision ("d'engage", "l'ultime") but not be glued to another letter
  linker = { re: new RegExp(`(?<![\\p{L}\\p{N}-])(${alt})(?![\\p{L}\\p{N}-])`, "giu"), map };
}

// --- abilities: spots abilities mentioned in guides (name, "(Q)", Q/W/E/R, "ton ultime", "passif") ------------
export let spellKits = {};              // {key: {name, kit}} for every champion
let globalNames = new Map();            // multi-word ability names (distinctive enough) -> {key, slot}
const ctxCache = new Map();
const SLOTS = ["P", "Q", "W", "E", "R"];

export function setupSpells(kits) {
  spellKits = kits || {};
  globalNames = new Map();
  const seen = new Map();
  for (const [key, c] of Object.entries(spellKits)) {
    for (const slot of SLOTS) {
      const sp = (c.kit || {})[slot];
      if (!sp) continue;
      for (const n of spellNames(sp.name)) {
        if (n.split(/\s+/).length < 2 || n.length < 9) continue;
        const k = n.toLowerCase();
        seen.set(k, (seen.get(k) || 0) + 1);
        globalNames.set(k, { key, slot });
      }
    }
  }
  for (const [k, n] of seen) if (n > 1) globalNames.delete(k);   // shared name: ambiguous
  ctxCache.clear();
}

const nsp = (x) => x.replace(/[\s  ]+/g, " ").trim();

function spellNames(name) {
  // "Évasion / Enlèvement": the full name and each of its parts (non-breaking spaces normalized)
  name = nsp(name);
  const out = [name];
  if (name.includes("/")) out.push(...name.split("/").map((x) => x.trim()).filter((x) => x.length >= 6));
  return out;
}

function spellContext(own, opp) {
  const id = own + "|" + (opp || "");
  if (ctxCache.has(id)) return ctxCache.get(id);
  const names = new Map(globalNames);
  for (const key of [opp, own]) {   // the guide champion goes last: it takes priority
    const kit = key && spellKits[key] && spellKits[key].kit;
    if (!kit) continue;
    for (const slot of SLOTS) if (kit[slot]) for (const n of spellNames(kit[slot].name)) if (n.length >= 4) names.set(n.toLowerCase(), { key, slot });
  }
  const alt = [...names.keys()].sort((a, b) => b.length - a.length)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/ /g, "[\\s\\u00a0\\u202f]+")).join("|");
  const ctx = {
    names,
    re: alt ? new RegExp(`(?<![\\p{L}\\p{N}])(${alt})(?:\\s\\((Q|W|E|R|passif|passive)\\))?(?![\\p{L}\\p{N}])`, "giu") : null,
  };
  ctxCache.set(id, ctx);
  return ctx;
}

const PH_OPEN = "", PH_CLOSE = "";
const ph = (tokens, html) => PH_OPEN + String.fromCharCode(0xE100 + tokens.push(html) - 1) + PH_CLOSE;

function markSpells(s, sp, tokens) {
  const { own, opp } = sp;
  const ctx = spellContext(own, opp);
  const cls = (key) => (key !== own ? " opp" : "");
  const keycap = (key, slot, label) => `<kbd class="spk${cls(key)}" data-sp="${esc(key)}|${slot}">${esc(label)}</kbd>`;
  // 1. ability names (optionally followed by their key in parentheses)
  if (ctx.re) {
    s = s.replace(ctx.re, (m, name, tail) => {
      const hit = ctx.names.get(nsp(name).toLowerCase());
      if (!hit) return m;
      let html = `<span class="spn${cls(hit.key)}" data-sp="${esc(hit.key)}|${hit.slot}">${esc(name)}</span>`;
      if (tail) html += " " + keycap(hit.key, hit.slot, tail);
      return ph(tokens, html);
    });
  }
  // 2. "ton ultime", "son passif"... (the "son / sa" possessive means the opponent in a matchup note)
  const POSS = LANG === "en" ? /(^|[^\p{L}])(your|their|his|her|its|the)(\s)(ultimate|passive)(?![\p{L}\p{N}])/giu
    : /(^|[^\p{L}])(ton|ta|son|sa|le|du|l['’])(\s?)(ultime|passif)(?![\p{L}\p{N}])/giu;
  s = s.replace(POSS, (m, pre, det, sp_, word) => {
    const theirs = opp && (LANG === "en" ? /^(their|his|her|its)$/i.test(det) : /^s/i.test(det));
    const key = theirs ? opp : own;
    const slot = /^ult/i.test(word) ? "R" : "P";
    return `${pre}${det}${sp_}` + ph(tokens, `<span class="spn${cls(key)}" data-sp="${esc(key)}|${slot}">${esc(word)}</span>`);
  });
  // 3. bare keys: Q, W, E, R (uppercase, not glued to a word)
  s = s.replace(/(?<![\p{L}\p{N}'’])([QWER])(?![\p{L}\p{N}'’])/gu, (m, k, idx, full) => {
    const before = full.slice(Math.max(0, idx - 8), idx);
    const key = opp && (LANG === "en" ? /(^|[^\p{L}])(their|his|her|its)\s$/iu : /(^|[^\p{L}])(son|sa|ses)\s$/iu).test(before) ? opp : own;
    return ph(tokens, keycap(key, k, k));
  });
  return s;
}

// plain text -> escaped HTML: glossary terms underlined (first occurrence) and abilities marked
// sp = {own: guide champion key, opp: opponent key (matchup notes)} or null
export function linkify(text, used, enabled = true, sp = null) {
  const tokens = [];
  let s = String(text ?? "");
  if (sp && sp.own && spellKits[sp.own]) s = markSpells(s, sp, tokens);
  let out = esc(s);
  if (linker && enabled) {
    out = out.replace(linker.re, (m) => {
      const t = linker.map.get(m.toLowerCase());
      if (!t || (used && used.has(t.id))) return m;
      if (used) used.add(t.id);
      return `<span class="term" data-term="${esc(t.id)}">${m}</span>`;
    });
  }
  if (tokens.length) out = out.replace(/([-])/g, (m, c) => tokens[c.charCodeAt(0) - 0xE100]);
  return out;
}

// short description for the tooltip (full details stay in the Abilities tab)
export function shortDesc(desc, max = 240) {
  const parts = String(desc || "").split(/(?<=[.!?])\s+(?=[A-ZÀ-Ý«])/);
  let out = "";
  for (const p of parts) {
    if (out && (out + " " + p).length > max) return { text: out, cut: true };
    out = out ? out + " " + p : p;
    if (out.length > max) return { text: out.slice(0, max).replace(/\s+\S*$/, "") + "…", cut: true };
  }
  return { text: out, cut: false };
}

export function spellMeta(sp) {
  const bits = [];
  const cd = String(sp.cd || "").split("/").filter((x) => x && x !== "0");
  if (cd.length) {
    const f = (x) => (LANG === "en" ? x : x.replace(".", ","));
    bits.push(cd[0] === cd[cd.length - 1] ? t("Recharge {0} s", f(cd[0])) : t("Recharge {0} → {1} s", f(cd[0]), f(cd[cd.length - 1])));
  }
  const r = parseInt(sp.range, 10);
  if (r >= 20000) bits.push(t("portée globale"));
  else if (r > 0) bits.push(t("portée {0}", r));
  return bits.join(" · ");
}

export function glossaryTerm(id, glossary) {
  return ((glossary && glossary.terms) || []).find((t) => t.id === id);
}

export function debounce(fn, ms) {
  let h;
  return (...a) => {
    clearTimeout(h);
    h = setTimeout(() => fn(...a), ms);
  };
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// numbers counting up to their value (elements with data-count, data-dec and data-suf)
export function countUp(root, ms = 850) {
  const els = [...root.querySelectorAll("[data-count]")];
  if (!els.length || (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) return;
  const items = els.map((el) => ({ el, to: parseFloat(el.dataset.count), dec: +(el.dataset.dec || 1), suf: el.dataset.suf || "" }))
    .filter((x) => !Number.isNaN(x.to));
  const t0 = performance.now();
  const frame = (now) => {
    const t = Math.min(1, (now - t0) / ms);
    const e = 1 - Math.pow(1 - t, 3);
    for (const x of items) x.el.textContent = num(x.to * e, x.dec) + x.suf;
    if (t < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

// staggered appearance of elements (cards, rows...)
export function stagger(els, step = 45, max = 14) {
  [...els].forEach((el, i) => {
    el.classList.remove("rise");
    el.style.animationDelay = Math.min(i, max) * step + "ms";
    el.classList.add("rise");
  });
}

const MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function fmtDate(iso) {
  if (!iso) return "?";
  const [y, m, d] = iso.split("-");
  return LANG === "en" ? `${MONTHS_EN[+m - 1] || m} ${+d}, ${y}` : `${d}/${m}/${y}`;
}
