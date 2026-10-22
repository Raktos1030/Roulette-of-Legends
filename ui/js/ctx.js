// Shared UI state and small services (toasts, context menu, modal, background).
import { esc, img, glossaryTerm, spellKits, shortDesc, spellMeta, t } from "./util.js";
import { call } from "./api.js";

export const store = {
  boot: null,          // boot data (champions, profile, glossary...)
  profile: null,
  current: null,       // shown guide (view returned by the core)
  spinning: false,
  recent: [],
  lol: null,
  cs: null,
  update: null,
  status: { text: "", tone: "muted" },
  listeners: new Set(),
};

// simple pub/sub: a page subscribes to event types and unsubscribes when leaving
export function on(fn) {
  store.listeners.add(fn);
  return () => store.listeners.delete(fn);
}
export function dispatch(type, data) {
  for (const fn of [...store.listeners]) {
    try {
      fn(type, data);
    } catch (e) {
      console.error(e);
    }
  }
}

// Lite edition: roulette, favorites and history; no guides, overlay, imports or Game page.
// A roll result links to u.gg.
export const isLite = () => !!(store.boot && store.boot.lite);
export const isMac = () => !!(store.boot && store.boot.platform === "mac");
export function openUgg(key, role) {
  call("open_ugg", { key, role });
}
export const UGG_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/></svg>`;

export function go(route) {
  if (location.hash !== "#/" + route) location.hash = "#/" + route;
  else dispatch("route", route);
}

// completion ring around champion portraits: one segment per role (top first, clockwise), colored by the level of
// that card in the binder; champions without any card have none
const RING = ["rgba(255, 255, 255, .12)", "#c38d64", "#dfe6f0", "#f0d58f", "#b48cff"];
export function paintRings(scope = document) {
  const rings = (store.boot && store.boot.binder_rings) || {};
  scope.querySelectorAll("img[data-champ], img[data-ring]").forEach((im) => {
    const code = rings[im.dataset.champ || im.dataset.ring];
    if (im.dataset.ringCode === (code || "")) return;
    im.dataset.ringCode = code || "";
    if (!code) {
      im.classList.remove("ringed", "ring-master");
      im.style.background = "";
      return;
    }
    const seg = 72, gap = 5;
    const stops = [...code].map((lv, i) => `${RING[+lv]} ${i * seg + gap / 2}deg ${(i + 1) * seg - gap / 2}deg, transparent ${(i + 1) * seg - gap / 2}deg ${(i + 1) * seg + gap / 2}deg`);
    im.style.background = `conic-gradient(from -36deg, transparent 0deg ${gap / 2}deg, ${stops.join(", ")})`;
    im.classList.add("ringed");
    im.classList.toggle("ring-master", code === "44444");
  });
}

// champion portrait that opens its guide on click (app.js); none in the Lite, which has no guides
export function champAttr(key, role) {
  return key && !isLite() ? ` data-champ="${esc(key)}"${role ? ` data-role="${esc(role)}"` : ""}` : "";
}

// the open window can be reopened when coming back from a guide opened in it (e.g. game details)
let modalReturn = null;
export function setModalBack(label, reopen) {
  modalReturn = { label, reopen };
}
export function modalBack() {
  return modalReturn;
}

// LoL in exclusive fullscreen: one click switches it to borderless through the client
export function wireBorderless(box) {
  const b = box.querySelector("[data-borderless]");
  if (b) b.onclick = async () => {
    b.disabled = true;
    const r = await call("borderless");
    if (r.error) {
      toast(r.error, "bad", 7000);
      b.disabled = false;
    } else toast(r.text, "good", 6000);
  };
}

// --- toasts ---
export function toast(text, tone = "gold", ms = 4600) {
  const box = document.getElementById("toasts");
  const t = document.createElement("div");
  t.className = `toast t-${tone}`;
  t.innerHTML = `<span>${esc(text)}</span>`;
  box.appendChild(t);
  while (box.children.length > 4) box.firstElementChild.remove();
  setTimeout(() => {
    t.classList.add("out");
    setTimeout(() => t.remove(), 320);
  }, ms);
}

export function setStatus(text, tone = "muted") {
  store.status = { text, tone };
  dispatch("status", store.status);
}

// --- logo: the wheel spins like a real roulette (momentum, slowdown, stops in the middle of a slot) ---
// A new push while spinning restarts from the current angle (without slowing it if it already has more momentum).
let logoAngle = 0, logoAnim = null;
export function spinLogo(turns = 1.2) {
  const wheel = document.querySelector("#rail .l-wheel");
  const ptr = document.querySelector("#rail .l-ptr");
  if (!wheel) return;
  const want = turns * 360;
  if (logoAnim && logoAnim.end - logoAngle >= want) return;   // enough momentum already
  const start = logoAngle;
  let end = start + want + Math.random() * 360 * Math.min(1, turns);
  end = end - (end % 36) + 18;          // 10 slots of 36°: the pointer stops in the middle of one
  const dur = 1100 + ((end - start) / 360) * 650;
  const t0 = performance.now();
  const anim = { end };
  logoAnim = anim;
  let seg = Math.floor(start / 36);
  const frame = (now) => {
    if (logoAnim !== anim) return;      // restarted meanwhile
    const t = Math.min(1, (now - t0) / dur);
    logoAngle = start + (end - start) * (1 - Math.pow(1 - t, 3));
    wheel.style.transform = `rotate(${logoAngle.toFixed(2)}deg)`;
    const s = Math.floor(logoAngle / 36);
    if (s !== seg && ptr) {             // a divider passes under the pointer: small click
      seg = s;
      ptr.classList.remove("tick");
      void ptr.offsetWidth;
      ptr.classList.add("tick");
    }
    if (t < 1) requestAnimationFrame(frame);
    else logoAnim = null;
  };
  requestAnimationFrame(frame);
}

// background hextech mechanism: kick on launch, then the role ring stops on the rolled role
const MECH_ORDER = ["top", "jgl", "mid", "adc", "sup"];   // emblems at 0°, 72°, 144°, 216°, 288°
const mechAngles = { m1: 0, m2: 0, m3: 0, m4: 0 };
function mechTurn(cls, deg, ms, set = false) {
  const img = document.querySelector(`.bg-mech .${cls} img`);
  if (!img) return;
  mechAngles[cls] = set ? deg : mechAngles[cls] + deg;
  img.style.transition = ms ? `transform ${ms}ms cubic-bezier(.12,.72,.18,1)` : "none";
  img.style.transform = `rotate(${mechAngles[cls].toFixed(1)}deg)`;
}
export function mechKick() {
  mechTurn("m1", 110 + Math.random() * 60, 5200);
  mechTurn("m2", -(150 + Math.random() * 80), 4600);
  mechTurn("m4", 200 + Math.random() * 90, 3800);
  mechTurn("m3", 540 + Math.random() * 180, 6000);   // the role ring spins while waiting for the result
}
export function mechRole(role, instant = false) {
  const i = MECH_ORDER.indexOf(role);
  if (i < 0) return;
  const target = 180 - i * 72;                        // the emblem comes to the left, facing the pointer
  let t = target;
  const cur = mechAngles.m3;
  if (instant) t = target;
  else while (t < cur + 200) t += 360;                // at least part of a turn before settling
  mechTurn("m3", t, instant ? 0 : 2600, true);
}

// --- background: blurred art of the shown champion ---
let bdIndex = 0;
let bdKey = null;
export function backdrop(key) {
  if (!key || key === bdKey) return;
  bdKey = key;
  const layers = document.querySelectorAll("#backdrop .bd-layer");
  const next = layers[bdIndex % 2];
  const prev = layers[(bdIndex + 1) % 2];
  const im = new Image();
  im.onload = () => {
    next.style.backgroundImage = `url("${img.splash(key)}")`;
    next.classList.add("on");
    prev.classList.remove("on");
    bdIndex++;
  };
  im.src = img.splash(key);
}

// --- tooltips: glossary terms and abilities mentioned in guides ---
function spellTip(ref) {
  const [key, slot] = ref.split("|");
  const c = spellKits[key];
  const sp = c && c.kit && c.kit[slot];
  if (!sp) return null;
  const d = shortDesc(sp.desc);
  const meta = spellMeta(sp);
  const mine = store.current && store.current.champ && store.current.champ.key === key;
  return `<div class="tip-sp"><span class="tip-ic"><img src="${img.spell(key, slot)}" alt="" onerror="this.remove()"></span>
      <div><div class="tip-k"><span class="spk${mine ? "" : " opp"}">${slot === "P" ? esc(t("Passif")) : slot}</span>${esc(c.name)}${mine ? "" : " · " + esc(t("adversaire"))}</div>
      <b>${esc(sp.name)}</b></div></div>
    <p class="tip-d">${esc(d.text)}</p>
    ${meta || d.cut ? `<div class="tip-m">${esc(meta)}${meta && d.cut ? " · " : ""}${d.cut ? esc(t("détails dans l'onglet Sorts")) : ""}</div>` : ""}`;
}

export function setupTips() {
  const tip = document.getElementById("tip");
  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest(".term, [data-sp]");
    if (!t) return;
    let html = null;
    if (t.dataset.sp) {
      html = spellTip(t.dataset.sp);
      tip.classList.add("sp-tip");
    } else {
      const term = glossaryTerm(t.dataset.term, store.boot && store.boot.glossary);
      if (term) html = `<b>${esc(term.term)}</b>${esc(term.def)}${term.ex ? `<span class="ex">${esc(term.ex)}</span>` : ""}`;
      tip.classList.remove("sp-tip");
    }
    if (!html) return;
    tip.innerHTML = html;
    tip.hidden = false;
    const r = t.getBoundingClientRect();
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = Math.min(window.innerWidth - w - 12, Math.max(12, r.left + r.width / 2 - w / 2));
    let y = r.top - h - 10;
    if (y < 8) y = r.bottom + 10;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest(".term, [data-sp]")) tip.hidden = true;
  });
  document.addEventListener("scroll", () => (tip.hidden = true), true);
}

// --- context menu ---
export function openMenu(x, y, build) {
  const m = document.getElementById("menu");
  m.innerHTML = "";
  build(m);
  m.hidden = false;
  const w = m.offsetWidth, h = m.offsetHeight;
  m.style.left = Math.min(x, window.innerWidth - w - 10) + "px";
  m.style.top = Math.min(y, window.innerHeight - h - 10) + "px";
  const close = (ev) => {
    if (ev && m.contains(ev.target)) return;
    m.hidden = true;
    document.removeEventListener("mousedown", close, true);
    document.removeEventListener("keydown", onKey, true);
  };
  const onKey = (ev) => ev.key === "Escape" && close();
  setTimeout(() => {
    document.addEventListener("mousedown", close, true);
    document.addEventListener("keydown", onKey, true);
  });
  return close;
}

// --- modal ---
let modalClose = null;
export function openModal(markup, onClose) {
  const box = document.getElementById("modal");
  box.innerHTML = `<div class="modal-box scroll">${markup}<button class="modal-close" title="${esc(t("Fermer"))}">×</button></div>`;
  box.hidden = false;
  modalReturn = null;
  const close = () => {
    box.hidden = true;
    box.innerHTML = "";
    modalReturn = null;
    document.removeEventListener("keydown", onKey);
    modalClose = null;
    onClose && onClose();
  };
  const onKey = (e) => e.key === "Escape" && close();
  box.querySelector(".modal-close").onclick = close;
  box.onclick = (e) => e.target === box && close();
  document.addEventListener("keydown", onKey);
  modalClose = close;
  return { box: box.querySelector(".modal-box"), close };
}
export function closeModal() {
  modalClose && modalClose();
}
export function modalOpen() {
  return !document.getElementById("modal").hidden;
}

export function confirmBox(text, okLabel = t("Confirmer")) {
  return new Promise((resolve) => {
    const { box, close } = openModal(
      `<div style="padding:34px 36px 28px;max-width:520px">
         <div class="card-title">${esc(t("Confirmation"))}</div>
         <p class="prose">${esc(text)}</p>
         <div class="row" style="justify-content:flex-end;margin-top:22px;gap:10px">
           <button class="btn" data-a="no">${esc(t("Annuler"))}</button><button class="btn-gold" data-a="yes">${esc(okLabel)}</button>
         </div></div>`,
      () => resolve(false)
    );
    box.style.width = "auto";
    box.querySelector('[data-a="no"]').onclick = () => close();
    box.querySelector('[data-a="yes"]').onclick = () => {
      resolve(true);
      close();
    };
  });
}
