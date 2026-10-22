// Binder page: one card per champion and role, filled by the games played on a roll (collection.py). New or improved
// cards stay face down until opened, one by one, in the booster window.
import { esc, img, roleIcon, norm, ROLES, ROLE_LABEL, CHAOS_ICON, t } from "./util.js";
import { store, on, toast, backdrop } from "./ctx.js";
import { call } from "./api.js";

const LEVELS = [
  { id: "locked", label: "À obtenir" },
  { id: "played", label: "Jouée" },
  { id: "rare", label: "Rare" },
  { id: "epic", label: "Épique" },
  { id: "legendary", label: "Légendaire" },
];
const HOW = {
  played: "Champion tiré et joué",
  rare: "Victoire hors classée, rôle choisi",
  epic: "Victoire en classée avec rôle choisi, ou hors classée en full random",
  legendary: "Victoire en classée, full random",
};
const state = { role: "all", show: "all", q: "", chaos: true };
let root = null, unsub = null, data = null;

export function renderBinder(page) {
  root = page;
  backdrop(store.boot.hero);
  page.innerHTML = `
  <div class="page-enter">
    <header class="page-head"><div>
      <div class="kicker">${esc(t("Collection"))}</div>
      <h1 class="page-title">${esc(t("Classeur"))}</h1>
      <p class="page-sub muted">${esc(t("Une carte par champion et par rôle. Joue le champion que la roulette te tire pour l'obtenir, gagne avec pour la faire monter. Le full random en classée donne les légendaires."))}</p>
    </div></header>
    <div id="bd-stats" class="bd-stats"></div>
    <div id="bd-booster"></div>
    <div id="bd-tools" class="bd-tools"></div>
    <div id="bd-grid" class="bd-grid"></div>
  </div>`;
  load();
  unsub && unsub();
  unsub = on((type) => {
    if (!root || !document.body.contains(root)) return;
    if (type === "binder" || type === "history") load();
  });
}

async function load() {
  const r = await call("binder");
  if (!root || r.error) return;
  data = r;
  paintStats();
  paintBooster();
  paintTools();
  paintGrid();
}

const shown = (c) => (data.pending.includes(c.id) ? c.shown : c.level);
const levelOf = (n) => LEVELS[n] || LEVELS[0];

function paintStats() {
  const cards = data.cards;
  const total = cards.length, champs = total / ROLES.length;
  const n = (min) => cards.filter((c) => c.level >= min).length;
  const tile = (label, v, max, cls) => `<div class="bd-stat ${cls}"><span class="l">${esc(label)}</span>
    <b>${v}<small> / ${max}</small></b><i><em style="width:${((100 * v) / max).toFixed(1)}%"></em></i></div>`;
  root.querySelector("#bd-stats").innerHTML =
    tile(t("Cartes obtenues"), n(1), total, "") +
    tile(t("Victoires"), n(2), total, "win") +
    tile(t("Légendaires"), n(4), total, "leg") +
    tile(t("Champions maîtres"), data.masters.length, champs, "master");
}

function paintBooster() {
  const box = root.querySelector("#bd-booster");
  const n = data.pending.length;
  if (!n) return (box.innerHTML = "");
  box.innerHTML = `<section class="card bd-booster">
    <div class="bd-pack">${[0, 1, 2].map(() => `<span class="tc back"></span>`).join("")}</div>
    <div class="grow"><div class="kicker">${esc(t("Booster"))}</div>
      <h3>${esc(n === 1 ? t("1 nouvelle carte à ouvrir") : t("{0} nouvelles cartes à ouvrir", n))}</h3>
      <p class="muted">${esc(t("Tes dernières parties sur la roulette ont rempli ton classeur."))}</p></div>
    <button class="btn-gold" data-open>${esc(t("Ouvrir"))}</button>
  </section>`;
  box.querySelector("[data-open]").onclick = () => openBooster(data.pending);
}

function paintTools() {
  const box = root.querySelector("#bd-tools");
  const per = (r) => data.cards.filter((c) => (r === "all" || c.role === r) && c.level >= 1 && (state.chaos || c.guide)).length;
  const max = (r) => data.cards.filter((c) => (r === "all" || c.role === r) && (state.chaos || c.guide)).length;
  box.innerHTML = `
    <div class="bd-roles">${["all", ...ROLES].map((r) => `<button class="bd-role${state.role === r ? " on" : ""}" data-role="${r}">
      ${r === "all" ? "" : roleIcon(r)}<span>${esc(r === "all" ? t("Tous") : ROLE_LABEL[r])}</span><small>${per(r)}/${max(r)}</small></button>`).join("")}</div>
    <div class="bd-filters">
      <div class="seg sm">${[["all", t("Toutes")], ["got", t("Obtenues")], ["todo", t("À obtenir")]].map(([v, l]) => `<button data-show="${v}" class="${state.show === v ? "on" : ""}">${esc(l)}</button>`).join("")}</div>
      <label class="bd-chaos" title="${esc(t("Les rôles où le champion n'a pas de fiche : ils comptent pour le master set"))}"><input type="checkbox" id="bd-chaos" ${state.chaos ? "checked" : ""}>${CHAOS_ICON}${esc(t("Rôles chaos"))}</label>
      <input class="input bd-search" id="bd-q" value="${esc(state.q)}" placeholder="${esc(t("Chercher un champion…"))}" spellcheck="false">
    </div>`;
  box.querySelectorAll("[data-role]").forEach((b) => (b.onclick = () => {
    state.role = b.dataset.role;
    paintTools();
    paintGrid();
  }));
  box.querySelectorAll("[data-show]").forEach((b) => (b.onclick = () => {
    state.show = b.dataset.show;
    paintTools();
    paintGrid();
  }));
  box.querySelector("#bd-chaos").onchange = (e) => {
    state.chaos = e.target.checked;
    paintTools();
    paintGrid();
  };
  const q = box.querySelector("#bd-q");
  q.oninput = () => {
    state.q = q.value;
    paintGrid();
  };
}

export function cardHTML(c, opts = {}) {
  const lv = opts.level != null ? opts.level : shown(c);
  const L = levelOf(lv);
  const master = data && data.masters.includes(c.key);
  const face = opts.back ? "back" : `lv${lv}${master ? " master" : ""}`;
  if (opts.back) return `<div class="tc back" data-id="${esc(c.id)}" title="${esc(t("Carte à ouvrir"))}"><span class="tc-new">${esc(t("à ouvrir"))}</span></div>`;
  const how = lv ? t(HOW[L.id]) : t("Joue ce champion à ce poste quand la roulette te le tire");
  const detail = c.at && lv ? ` · ${c.queue || ""} · ${c.at} · ${t("{0} parties, {1} victoires", c.games, c.wins)}` : "";
  return `<div class="tc ${face}${c.guide ? "" : " chaos"}" data-id="${esc(c.id)}" title="${esc(`${c.name} ${ROLE_LABEL[c.role]} — ${t(L.label)}. ${how}${detail}`)}">
    <img src="${img.tall(c.key)}" alt="" loading="lazy">
    <span class="tc-foil"></span>
    ${c.guide ? "" : `<span class="tc-chaos">${CHAOS_ICON}</span>`}
    ${master ? `<span class="tc-crown" title="${esc(t("Champion maître"))}">♛</span>` : ""}
    <span class="tc-foot"><b>${esc(c.name)}</b><span class="tc-role">${roleIcon(c.role)}${esc(ROLE_LABEL[c.role])}</span>
      <span class="tc-lvl">${esc(t(L.label))}</span></span>
  </div>`;
}

function paintGrid() {
  const box = root.querySelector("#bd-grid");
  const q = norm(state.q);
  const list = data.cards.filter((c) => (state.role === "all" || c.role === state.role) && (state.chaos || c.guide)
    && (!q || norm(c.name).includes(q))
    && (state.show === "all" || (state.show === "got" ? c.level >= 1 : c.level < 4)));
  if (!list.length) {
    box.innerHTML = `<div class="card empty">${esc(t("Aucune carte ici pour l'instant."))}</div>`;
    return;
  }
  // obtained cards first, best first; then the rest by name
  list.sort((a, b) => b.level - a.level || a.name.localeCompare(b.name) || ROLES.indexOf(a.role) - ROLES.indexOf(b.role));
  box.innerHTML = list.map((c) => cardHTML(c, { back: data.pending.includes(c.id) })).join("");
  box.querySelectorAll(".tc.back").forEach((el) => (el.onclick = () => openBooster([el.dataset.id])));
}

// holographic foil follows the pointer
document.addEventListener("pointermove", (e) => {
  const el = e.target.closest && e.target.closest(".tc.lv4, .tc.lv3, .bk-card .tc");
  if (!el) return;
  const r = el.getBoundingClientRect();
  el.style.setProperty("--mx", ((e.clientX - r.left) / r.width).toFixed(3));
  el.style.setProperty("--my", ((e.clientY - r.top) / r.height).toFixed(3));
});

// --- booster: cards revealed one by one ---------------------------------------------------------
function openBooster(ids) {
  const queue = ids.map((id) => data.cards.find((c) => c.id === id)).filter(Boolean)
    .sort((a, b) => a.level - b.level);   // the best card last
  if (!queue.length) return;
  const box = document.createElement("div");
  box.className = "bk";
  document.body.appendChild(box);
  let i = 0;
  const close = async () => {
    box.remove();
    document.removeEventListener("keydown", onKey);
    await load();
  };
  const onKey = (e) => {
    if (e.key === "Escape") close();
    else if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      next();
    }
  };
  document.addEventListener("keydown", onKey);
  const show = () => {
    const c = queue[i];
    const L = levelOf(c.level);
    const was = c.shown ? levelOf(c.shown) : null;
    box.innerHTML = `
      <div class="bk-shade"></div>
      <div class="bk-stage lv${c.level}">
        <div class="bk-count">${esc(t("Carte {0} sur {1}", i + 1, queue.length))}</div>
        <div class="bk-card"><div class="bk-flip">
          <div class="bk-face bk-front">${cardHTML(c, { level: c.level })}</div>
          <div class="bk-face bk-rear"><div class="tc back"></div></div>
        </div><div class="bk-burst"></div></div>
        <div class="bk-text">
          <div class="bk-tier t-${L.id}">${esc(t(L.label))}</div>
          <h2>${esc(c.name)} · ${esc(ROLE_LABEL[c.role])}${c.guide ? "" : ` <span class="bk-chaos">${CHAOS_ICON}${esc(t("chaos"))}</span>`}</h2>
          <p class="muted">${esc(was ? t("Amélioration : {0} → {1}", t(was.label), t(L.label)) : t("Nouvelle carte !"))} ${esc(t(HOW[L.id]))}${c.at ? esc(` · ${c.queue || ""} · ${c.at}`) : ""}</p>
        </div>
        <div class="bk-btns">
          ${queue.length - i > 1 ? `<button class="btn" data-all>${esc(t("Tout révéler"))}</button>` : ""}
          <button class="btn-gold" data-next>${esc(queue.length - i > 1 ? t("Suivante ({0})", queue.length - i - 1) : t("Terminer"))}</button>
        </div>
      </div>`;
    call("binder_open", { ids: [c.id] });
    requestAnimationFrame(() => setTimeout(() => box.querySelector(".bk-stage").classList.add("flipped"), 350));
    box.querySelector("[data-next]").onclick = next;
    const all = box.querySelector("[data-all]");
    if (all) all.onclick = async () => {
      await call("binder_open", { ids: queue.slice(i).map((x) => x.id) });
      toast(t("{0} cartes ajoutées à ton classeur.", queue.length - i), "good");
      close();
    };
    box.querySelector(".bk-shade").onclick = close;
  };
  const next = () => {
    i += 1;
    if (i >= queue.length) close();
    else show();
  };
  show();
}
