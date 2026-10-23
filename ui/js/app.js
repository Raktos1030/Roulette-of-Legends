// UI entry point: boot, navigation, core events, champ select banner.
import { call, listen } from "./api.js";
import { esc, img, ICONS, roleIcon, setupGlossary, setupSpells, fmtDate, setupLang, t } from "./util.js";
import { store, on, dispatch, toast, setStatus, setupTips, modalOpen, closeModal, spinLogo, mechRole, isLite, wireBorderless, champAttr, paintRings } from "./ctx.js";
import { renderRoulette, rouletteKey, launch, preloadSkin } from "./roulette.js";
import { renderGuides, showGuide, openChamp, restoreBack, clearBack } from "./guides.js";
import { setAmbient } from "./ambient.js";
import { renderHistory } from "./history.js";
import { renderFavorites } from "./favorites.js";
import { renderBinder } from "./binder.js";
import { renderGlossary } from "./glossary.js";
import { renderSettings } from "./settings.js";
import { renderLive } from "./live.js";

const PAGES = {
  roulette: { label: "Roulette", icon: ICONS.roulette, render: renderRoulette },
  guides: { label: "Fiche", icon: ICONS.guide, render: renderGuides },
  game: { label: "Partie", icon: ICONS.live, render: renderLive },
  favorites: { label: "Favoris", icon: ICONS.star, render: renderFavorites },
  binder: { label: "Classeur", icon: ICONS.binder, render: renderBinder },
  history: { label: "Historique", icon: ICONS.history, render: renderHistory },
  glossary: { label: "Lexique", icon: ICONS.book, render: renderGlossary },
  settings: { label: "Réglages", icon: ICONS.gear, render: renderSettings },
};
let current = null;
// Lite: only these pages (no guides, Game page or glossary)
const SIMPLE_PAGES = ["roulette", "favorites", "binder", "history", "settings"];
const pageOn = (id) => !!PAGES[id] && (!isLite() || SIMPLE_PAGES.includes(id));

// looks picked in the rewards path: the roulette skin (the booster opening is read when it opens)
function applyLooks(p) {
  document.documentElement.dataset.roulette = p.roulette || "classic";
  preloadSkin();   // its images ready before the Roulette tab opens
}

async function boot() {
  const b = await call("boot");
  if (b.error) {
    document.getElementById("page").innerHTML = `<div class="card empty">${esc(t("Impossible de joindre l'application : {0}", b.error))}</div>`;
    return;
  }
  await setupLang(b.lang);
  store.boot = b;
  store.profile = b.profile;
  store.recent = b.recent;
  store.lol = b.lol;
  store.cs = b.cs;
  store.update = b.update;
  store.roll = b.roll;
  if (b.app && b.app.name) document.title = b.app.name;
  if (b.status && b.status.text) store.status = b.status;
  setupGlossary(b.glossary);
  setAmbient(b.profile.ambient !== false);
  applyLooks(b.profile);
  const k = await call("kits");
  if (!k.error) setupSpells(k.kits);
  if (b.window && b.window.frameless) buildTitlebar();
  buildRail();
  paintLol();
  call("live").then((v) => {
    if (!v.error) {
      store.live = v;
      paintLiveNav();
    }
  });
  paintUpdate();
  paintAppUpdate();
  paintCS();
  setupTips();
  if (b.current && !b.lite) {
    const v = await call("combo", { key: b.current });
    if (!v.error) store.current = v;
  }
  // the background mechanism shows the role of the open guide (or of the current roll)
  const r0 = (store.current && store.current.role) || (store.roll && store.roll.role);
  if (r0) mechRole(r0, true);
  window.addEventListener("hashchange", route);
  on((type) => type === "route" && route());
  on((type) => type === "guide_nav" && paintGuideNav());
  route();
  listen(onEvent);
  document.addEventListener("keydown", onKey);
  // completion rings on the portraits drawn from now on
  let ringQueued = false;
  new MutationObserver(() => {
    if (ringQueued) return;
    ringQueued = true;
    requestAnimationFrame(() => {
      ringQueued = false;
      paintRings();
    });
  }).observe(document.body, { childList: true, subtree: true });
  paintRings();
  // champion portraits open their guide, wherever they are (history, game details, Game page, guides...)
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-champ]");
    if (!el || store.spinning) return;
    e.preventDefault();
    e.stopPropagation();
    openChamp(el.dataset.champ, el.dataset.role);
  }, true);
  if (b.updated) setTimeout(() => toast(t("Mise à jour terminée : version {0}.", b.updated), "good", 7000), 900);
  if (b.update_notice) {
    // stats updated while the window was closed
    setTimeout(() => toast(t("Nouvelles statistiques : patch {0} (données du {1}).", b.update_notice.patch, fmtDate(b.update_notice.generated)), "good", 7000), 900);
    call("update_seen");
  }
  document.addEventListener("contextmenu", (e) => {
    if (!e.target.closest("input, textarea, .selectable")) e.preventDefault();
  });
}

// frameless window: title bar blended into the UI (drag, double-click to maximize, buttons)
function buildTitlebar() {
  document.body.classList.add("frameless");
  const bar = document.createElement("header");
  bar.id = "titlebar";
  bar.innerHTML = `<div class="tb-drag" title=""></div><div class="tb-btns">
    <button data-w="minimize" title="${esc(t("Réduire"))}"><svg viewBox="0 0 11 11"><path d="M1 5.5h9"/></svg></button>
    <button data-w="maximize" title="${esc(t("Agrandir"))}"><svg viewBox="0 0 11 11"><rect x="1" y="1" width="9" height="9"/></svg></button>
    <button data-w="close" class="close" title="${esc(t("Fermer (la roulette continue dans la zone de notification)"))}"><svg viewBox="0 0 11 11"><path d="M1 1l9 9M10 1l-9 9"/></svg></button></div>`;
  document.body.appendChild(bar);
  const act = async (action, edge) => {
    const r = await call("window", edge ? { action, edge } : { action });
    if (r && "maximized" in r) document.body.classList.toggle("maximized", !!r.maximized);
  };
  bar.querySelectorAll("[data-w]").forEach((b) => (b.onclick = () => act(b.dataset.w)));
  const drag = bar.querySelector(".tb-drag");
  drag.addEventListener("mousedown", (e) => e.button === 0 && e.detail === 1 && act("move"));
  drag.addEventListener("dblclick", () => act("maximize"));
  for (const edge of ["n", "s", "e", "w", "ne", "nw", "se", "sw"]) {
    const z = document.createElement("div");
    z.className = "rz " + edge;
    z.addEventListener("mousedown", (e) => e.button === 0 && act("resize", edge));
    document.body.appendChild(z);
  }
}

function buildRail() {
  const nav = document.getElementById("rail-nav");
  nav.innerHTML = Object.entries(PAGES).filter(([id]) => pageOn(id)).map(([id, p]) => `<a class="nav-item" href="#/${id}" data-p="${id}">${p.icon}<span>${esc(t(p.label))}</span></a>`).join("") +
    `<span class="nav-ind" id="nav-ind"></span>`;
  paintBinderBadge();
  document.getElementById("rail-lol").onclick = () => (location.hash = "#/settings");
  document.querySelector("#rail .rail-logo").addEventListener("mouseenter", () => spinLogo(1.2));
}

function route() {
  const id = (location.hash.replace(/^#\/?/, "") || "roulette").split("/")[0];
  if (store.spinning && current && id !== current) {   // a roll in progress holds the app: no other page meanwhile
    history.replaceState(null, "", "#/" + current);
    return;
  }
  const p = pageOn(id) ? PAGES[id] : PAGES.roulette;
  current = pageOn(id) ? id : "roulette";
  document.getElementById("menu").hidden = true;   // an open menu doesn't survive a page change
  document.querySelectorAll(".nav-item").forEach((a) => a.classList.toggle("on", a.dataset.p === current));
  const page = document.getElementById("page");
  const main = document.getElementById("main");
  main.style.scrollBehavior = "auto";
  main.scrollTop = 0;
  main.style.scrollBehavior = "";
  p.render(page);
  if (!restoreBack() && current !== "guides") clearBack();   // other page: guides opened before have no way back
  paintGuideNav();
  moveNavIndicator();
  spinLogo(0.7);   // small wheel spin on every page change
}

function moveNavIndicator() {
  const ind = document.getElementById("nav-ind");
  const a = document.querySelector(".nav-item.on");
  if (!ind || !a) return;
  ind.style.transform = `translateY(${a.offsetTop + 14}px)`;
  ind.style.height = a.offsetHeight - 28 + "px";
  ind.style.opacity = 1;
}

// cards waiting to be opened in the binder
function paintBinderBadge() {
  const a = document.querySelector('.nav-item[data-p="binder"]');
  if (!a) return;
  const n = store.boot.binder_pending || 0, rw = store.boot.rewards_unseen || 0;
  let b = a.querySelector(".nav-badge");
  if (!n && !rw) return b && b.remove();
  if (!b) {
    b = document.createElement("b");
    b.className = "nav-badge";
    a.appendChild(b);
  }
  b.textContent = n ? (n > 99 ? "99+" : n) : "★";   // a star: only rewards to see
  a.title = [n ? t("{0} cartes à ouvrir", n) : "", rw ? t("{0} récompenses débloquées", rw) : ""].filter(Boolean).join(" · ");
}

// the Guides tab shows the portrait of the open guide's champion
function paintGuideNav() {
  const a = document.querySelector('.nav-item[data-p="guides"]');
  if (!a) return;
  const v = store.current;
  const key = v ? v.champ.key : null;
  if (a.dataset.key === (key || "")) return;
  a.dataset.key = key || "";
  a.innerHTML = (key ? `<span class="nav-portrait"><img src="${img.icon(key)}" alt=""></span>` : ICONS.guide) + `<span>${esc(t("Fiche"))}</span>`;
  a.title = v ? t("Fiche : {0} {1}", v.champ.name, v.role_label) : t("Aucune fiche ouverte");
}

// --- core events ---
async function onEvent(msg) {
  const { type, data } = msg;
  switch (type) {
    case "status":
      setStatus(data.text, data.tone);
      if (data.toast && current !== "roulette") toast(data.text, data.tone);
      else if (data.toast && ["good", "bad", "shield", "teal", "warn"].includes(data.tone) && !store.spinning) toast(data.text, data.tone);
      break;
    case "lol":
      store.lol = data;
      paintLol();
      dispatch("lol", data);
      break;
    case "cs":
      store.cs = data;
      paintCS();
      break;
    case "live":
      store.live = data;
      paintLiveNav();
      dispatch("live", data);
      break;
    case "history":
      store.recent = data.recent;
      store.roll = data.roll;
      dispatch("recent", data.recent);
      dispatch("roll", data.roll);
      break;
    case "profile":
      store.profile = data;
      setAmbient(data.ambient !== false);
      applyLooks(data);
      dispatch("profile", data);
      break;
    case "show_combo": {
      if (store.spinning || isLite()) break;
      const v = await call("combo", { key: data.key });
      if (v.error) break;
      showGuide(v);   // champion locked in champ select: open its guide
      break;
    }
    case "game":
      dispatch("game", data);
      break;
    case "binder":
      store.boot.binder_pending = data.pending;
      store.boot.binder_rings = data.rings;
      store.boot.card_back = data.card_back;
      paintBinderBadge();
      paintRings();
      if (data.new > 0) toast(data.new === 1 ? t("Nouvelle carte à ouvrir dans ton classeur !") : t("{0} nouvelles cartes à ouvrir dans ton classeur !", data.new), "gold", 6500);
      dispatch("binder", data);
      break;
    case "rewards":
      store.boot.rewards_unseen = data.unseen;
      if (data.joker) store.boot.joker = data.joker;
      paintBinderBadge();
      if ((data.new || []).length) toast(t("Récompense débloquée : {0}", data.new.join(", ")), "gold", 7000);
      dispatch("rewards", data);
      break;
    case "app_update": {
      const fresh = (store.boot.app_update || {}).version !== data.version;
      store.boot.app_update = data;
      paintAppUpdate();
      // scrolled down the page: the notice at the top is out of sight
      if (fresh && !data.state && data.version !== (store.profile || {}).app_update_seen && document.getElementById("main").scrollTop > 60)
        toast(t("Nouvelle version {0} disponible.", data.version), "gold", 7000);
      dispatch("app_update", data);
      break;
    }
    case "update":
      store.update = data;
      paintUpdate();
      dispatch("update", data);
      break;
    case "data_reloaded": {
      const b = await call("boot");
      if (!b.error) {
        store.boot = b;
        store.profile = b.profile;
        setupGlossary(b.glossary);
      }
      const k = await call("kits");
      if (!k.error) setupSpells(k.kits);
      if (store.current) {
        const v = await call("combo", { key: store.current.key });
        if (!v.error) {
          store.current = v;
          if (current === "guides") route();
        }
      }
      toast(t("Statistiques mises à jour : patch {0} (données du {1}).", data.patch, fmtDate(data.generated)), "good", 7000);
      call("update_seen");
      dispatch("data_reloaded", data);
      break;
    }
    case "lang":
      location.reload();   // new language: redraw the whole UI
      break;
    case "overlay_placed":
      toast(t("Position de l'overlay enregistrée."), "good");
      dispatch("profile", store.profile);
      break;
  }
}

// the Game tab lights up during champ select or a game
function paintLiveNav() {
  const a = document.querySelector('.nav-item[data-p="game"]');
  if (a) a.classList.toggle("live", !!(store.live && store.live.mode));
}

function paintLol() {
  const l = store.lol || {};
  const btn = document.getElementById("rail-lol");
  btn.classList.toggle("on", !!l.connected);
  btn.classList.toggle("game", !!l.in_game);
  btn.querySelector(".rail-lol-txt").textContent = l.connected ? (l.in_game ? t("En jeu") : "LoL") : "LoL";
  btn.title = l.connected
    ? `${l.text}${l.summoner ? " — " + l.summoner : ""}${l.rank ? "\n" + t("Solo/duo : {0}", l.rank) : ""}${l.flex ? "\n" + t("Flexible : {0}", l.flex) : ""}`
    : t("Client LoL non détecté : lance-le pour relier tes parties");
}

// newer version of the app published on GitHub: notice until installed or dismissed for that version
function paintAppUpdate() {
  const u = store.boot.app_update;
  const box = document.getElementById("app-update");
  const busy = !!u && ["download", "install", "restart"].includes(u.state);
  const show = !!u && (busy || u.state === "error" || u.version !== (store.profile || {}).app_update_seen);
  box.hidden = !show;
  if (!show) return;
  const pct = Math.round((u.progress || 0) * 100);
  const text = {
    download: t("Téléchargement de la version {0}… {1} %", u.version, pct),
    install: t("Installation de la version {0}…", u.version),
    restart: t("Redémarrage sur la version {0}…", u.version),
    error: u.text,
  }[u.state] || t("Nouvelle version {0} disponible.", u.version);
  const label = u.state === "error" ? t("Réessayer") : u.auto ? t("Mettre à jour") : t("Télécharger");
  box.classList.toggle("busy", busy);
  box.classList.toggle("bad", u.state === "error");
  box.innerHTML = `<span class="au-dot"></span><span>${esc(text)}</span>
    ${busy ? "" : `<button class="btn-gold" data-go>${esc(label)}</button>
    <button class="au-close" data-x title="${esc(t("Masquer"))}">×</button>`}
    ${u.state === "download" ? `<span class="au-bar"><i style="width:${pct}%"></i></span>` : ""}`;
  if (busy) return;
  box.querySelector("[data-go]").onclick = async () => {
    const r = await call("install_update");
    if (r.error) toast(r.error, "bad");
  };
  box.querySelector("[data-x]").onclick = async () => {
    const r = await call("set_pref", { key: "app_update_seen", value: u.version });
    if (r.profile) store.profile = r.profile;
    store.boot.app_update = { ...u, state: null };
    paintAppUpdate();
  };
}

function paintUpdate() {
  const u = store.update || {};
  const box = document.getElementById("rail-update");
  const busy = u.state === "downloading" || u.state === "building";
  box.hidden = !busy;
  if (busy) {
    const p = Math.max(0.02, Math.min(1, u.progress || 0));
    box.querySelector(".ru-fg").style.strokeDashoffset = (94.25 * (1 - p)).toFixed(1);
    box.querySelector("span").textContent = Math.round(p * 100);
    box.title = u.text || t("Mise à jour des statistiques");
  }
}

function paintCS() {
  const cs = store.cs;
  const box = document.getElementById("cs-banner");
  if (!cs) {
    box.hidden = true;
    box.innerHTML = "";
    document.documentElement.style.setProperty("--banner-h", "0px");
    return;
  }
  box.hidden = false;
  box.innerHTML = `
    <div class="cs-role">${cs.assigned ? roleIcon(cs.assigned) : "?"}</div>
    <div>
      <div class="cs-title">${esc(t("Sélection des champions"))} — ${cs.assigned ? esc(t("rôle attribué : {0}", cs.assigned_label)) : esc(t("pas de rôle attribué"))}</div>
      ${cs.pending ? `<div class="cs-line" style="color:var(--gold-pale)">${esc(t("Ton tirage :"))} <b>${esc(cs.pending.name)}</b> — ${esc(cs.pending.role === "jgl" ? "Jungle" : cs.pending.role === "sup" ? "Support" : cs.pending.role === "adc" ? "ADC" : cs.pending.role === "mid" ? "Mid" : "Top")}</div>` : ""}
      ${cs.lines.map((l) => `<div class="cs-line t-${l.tone}">${esc(l.text)}</div>`).join("")}
      ${(store.lol || {}).fullscreen ? `<div class="cs-line t-warn">${esc(t("LoL est en plein écran : l'overlay ne pourra pas s'afficher pendant la partie."))}</div>` : ""}
      ${cs.duo ? `<div class="cs-line cs-duo t-${cs.duo.tone}"><img src="${img.icon(cs.duo.me_key)}" alt=""${champAttr(cs.duo.me_key, cs.duo.me_role)}><b>+</b><img src="${img.icon(cs.duo.key)}" alt=""${champAttr(cs.duo.key, cs.duo.role)}>${esc(cs.duo.text)}</div>` : ""}
      ${cs.imports ? `<div class="cs-imp"><span class="ci-t">${esc(t("Importé pour {0} :", cs.imports.label))}</span>${cs.imports.results.map((r) =>
        `<span class="ci ${r.state}" title="${esc(r.text)}">${r.state === "ok" ? "✓" : r.state === "full" ? "!" : "✕"} ${esc(r.label)}</span>`).join("")}</div>` : ""}
    </div>
    <div class="cs-btns">${(store.lol || {}).fullscreen ? `<button class="btn" data-borderless>${esc(t("Passer en Sans bordure"))}</button>` : ""}${current !== "game" && !isLite() ? `<a class="btn" href="#/game">${esc(t("Voir les équipes"))}</a>` : ""}${cs.buttons.map((b, i) => `<button class="btn-gold" data-i="${i}">${esc(b.label)}</button>`).join("")}
      ${cs.imports && cs.imports.results.some((r) => r.id === "runes" && r.state === "full") ? `<button class="btn" data-replace title="${esc(t("Plus de place pour une nouvelle page : la page de runes sélectionnée dans le client sera remplacée"))}">${esc(t("Remplacer ma page de runes"))}</button>` : ""}</div>`;
  // guide tabs stick right under the banner
  requestAnimationFrame(() => document.documentElement.style.setProperty("--banner-h", box.offsetHeight + "px"));
  wireBorderless(box);
  const rep = box.querySelector("[data-replace]");
  if (rep) rep.onclick = async () => {
    rep.disabled = true;
    const r = await call("import", { action: "replace" });
    if (r.error) toast(r.error, "bad");
  };
  box.querySelectorAll("[data-i]").forEach((b) => (b.onclick = () => {
    const x = cs.buttons[+b.dataset.i];
    if (current !== "roulette") location.hash = "#/roulette";
    setTimeout(() => launch({ role: x.role, reason: x.reason }), current !== "roulette" ? 250 : 0);
  }));
}

function onKey(e) {
  if (e.key === "Escape" && modalOpen()) return closeModal();
  if (modalOpen()) return;
  if (current === "roulette" && rouletteKey(e)) e.preventDefault();
}

boot();
