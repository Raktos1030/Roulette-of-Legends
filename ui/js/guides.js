// Guides page: the guide list (every champion) and, once picked, a single guide.
//   #/guides            every guide (role filter, search) + shortcut to the current roll
//   #/guides/Ahri|mid   one guide
import { esc, img, roleIcon, norm, pct, ROLES, ROLE_LABEL, stagger, CHAOS_ICON, t } from "./util.js";
import { store, on, backdrop, toast, setStatus, openMenu, dispatch } from "./ctx.js";
import { call } from "./api.js";
import { renderGuide } from "./guide.js";

const state = { q: "", role: "all", chaos: false };
let root = null, unsub = null;

function subKey() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  return parts[0] === "guides" && parts[1] ? decodeURIComponent(parts[1]) : "";
}

export function renderGuides(page) {
  root = page;
  unsub && unsub();
  unsub = null;
  const key = subKey();
  if (!key) return renderList(page);
  if (store.current && store.current.key === key) return renderOne(page, store.current);
  page.innerHTML = `<div class="page-enter"><div class="card empty">${esc(t("Ouverture de la fiche…"))}</div></div>`;
  call("combo", { key }).then((v) => {
    if (root !== page || subKey() !== key) return;
    if (v.error) {
      toast(v.error, "bad");
      location.hash = "#/guides";
      return;
    }
    store.current = v;
    dispatch("guide_nav");
    renderOne(page, v);
  });
}

// --- single guide ---
function renderOne(page, v) {
  page.innerHTML = `<div class="page-enter"><div class="guide-bar" id="fbar"></div><div id="fguide"></div></div>`;
  paintBar();
  const tab = store.nextTab;   // tab requested by the opening page (e.g. Matchups from the Game page)
  store.nextTab = null;
  renderGuide(page.querySelector("#fguide"), v, tab ? { tab } : {});
  unsub = on((type) => {
    if (!root || !document.body.contains(root)) return;
    if (type === "roll") paintBar();
  });
}

function paintBar() {
  const bar = root.querySelector("#fbar");
  if (!bar) return;
  const v = store.current, r = store.roll;
  const mine = r && r.combo === v.key;
  const who = `<img src="${img.icon(v.champ.key)}" alt=""><b>${esc(v.champ.name)}</b>${roleIcon(v.role)}<span>${esc(v.role_label)}</span>`;
  const back = `<a class="btn sm fb-back" href="#/guides" title="${esc(t("Toutes les fiches"))}"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>${esc(t("Toutes les fiches"))}</a>`;
  if (mine) {
    bar.className = "guide-bar mine";
    bar.innerHTML = `${back}
      <span class="fb-badge"><i class="fb-dot"></i>${esc(r.status === "in_game" ? t("Partie en cours") : t("Ton tirage"))}</span>
      <span class="fb-who">${who}</span>
      <span class="fb-sub">${esc(r.mode || "")}</span>
      <span class="grow"></span>
      <a class="btn sm" href="#/roulette">${esc(t("Nouveau tirage"))}</a>`;
  } else {
    bar.className = "guide-bar";
    bar.innerHTML = `${back}
      <span class="fb-badge other">${esc(t("Fiche consultée"))}</span>
      <span class="fb-who">${who}</span>
      <span class="grow"></span>
      ${r ? `<button class="btn sm" data-back>${esc(t("Revenir à ton tirage : {0} {1}", r.name, r.role_label))}</button>` : `<a class="btn sm" href="#/roulette">${esc(t("Nouveau tirage"))}</a>`}`;
    const b = bar.querySelector("[data-back]");
    if (b) b.onclick = () => openCombo(r.combo);
  }
}

// --- guide list ---
function renderList(page) {
  backdrop(store.boot.hero);
  const n = store.boot.meta.combos;
  page.innerHTML = `
  <div class="page-enter">
    <header class="page-head"><div>
      <div class="kicker">${esc(t("{0} fiches · patch {1}", n, store.boot.meta.patch))}</div>
      <h1 class="page-title">${esc(t("Fiches"))}</h1>
    </div></header>
    <div class="fl-quick" id="fl-quick"></div>
    <div class="fav-tools" id="fl-tools"></div>
    <div class="fl-grid" id="fl-grid"></div>
  </div>`;
  paintQuick();
  paintTools();
  paintGrid(true);
  unsub = on((type) => {
    if (!root || !document.body.contains(root)) return;
    if (type === "roll") paintQuick();
  });
}

function paintQuick() {
  const box = root.querySelector("#fl-quick");
  if (!box) return;
  const r = store.roll, v = store.current;
  const cards = [];
  if (r) {
    cards.push(`<button class="flq mine" data-k="${esc(r.combo)}">
      <img src="${img.icon(r.key)}" alt="">
      <span class="flq-t"><span class="fb-badge"><i class="fb-dot"></i>${esc(r.status === "in_game" ? t("Partie en cours") : t("Ton tirage en cours"))}</span>
        <b>${esc(r.name)}</b><span class="flq-r">${roleIcon(r.role)}${esc(r.role_label)}</span></span>
      <span class="flq-go">${esc(t("Ouvrir la fiche"))}<svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></span></button>`);
  }
  if (v && (!r || v.key !== r.combo)) {
    cards.push(`<button class="flq" data-k="${esc(v.key)}">
      <img src="${img.icon(v.champ.key)}" alt="">
      <span class="flq-t"><span class="fb-badge other">${esc(t("Dernière fiche consultée"))}</span>
        <b>${esc(v.champ.name)}</b><span class="flq-r">${roleIcon(v.role)}${esc(v.role_label)}</span></span>
      <span class="flq-go">${esc(t("Rouvrir"))}<svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></span></button>`);
  }
  box.innerHTML = cards.join("");
  box.hidden = !cards.length;
  box.querySelectorAll(".flq").forEach((b) => (b.onclick = () => openCombo(b.dataset.k)));
}

function paintTools() {
  const box = root.querySelector("#fl-tools");
  box.innerHTML = `
    <input class="input" id="fl-q" placeholder="${esc(t("Rechercher un champion…"))}" value="${esc(state.q)}" spellcheck="false">
    ${["all", ...ROLES].map((r) => `<button class="chip${state.role === r ? " on" : ""}" data-role="${r}">${r === "all" ? esc(t("Tous")) : roleIcon(r) + esc(ROLE_LABEL[r])}</button>`).join("")}
    <button class="chip chaos${state.chaos ? " on" : ""}" data-chaos title="${esc(t("Tous les champions à tous les postes : les postes sans fiche (en rouge) ouvrent une fiche chaos"))}">${CHAOS_ICON}${esc(t("Postes chaos"))}</button>
    <span class="grow"></span>
    <span class="t-teal small" id="fl-count"></span>`;
  const q = box.querySelector("#fl-q");
  q.oninput = () => {
    state.q = q.value;
    paintGrid();
  };
  box.querySelectorAll("[data-role]").forEach((c) => (c.onclick = () => {
    state.role = c.dataset.role;
    paintTools();
    paintGrid(true);
  }));
  box.querySelector("[data-chaos]").onclick = () => {
    state.chaos = !state.chaos;
    paintTools();
    paintGrid(true);
  };
}

// roles of a champion, most played first (the first is its main role); in chaos mode, roles without a guide
// follow, flagged chaos. With a role filter, the others stay visible but dimmed.
function rolesOf(c) {
  const real = [...c.roles].sort((a, b) => b.share - a.share);
  const all = state.chaos
    ? [...real, ...ROLES.filter((r) => !c.roles.some((x) => x.role === r)).map((r) => ({ role: r, share: 0, chaos: true }))]
    : real;
  return all.map((r) => ({ ...r, dim: state.role !== "all" && r.role !== state.role }));
}

function visible() {
  const q = norm(state.q);
  return store.boot.champions.filter((c) => {
    if (q && !norm(c.name).includes(q) && !norm(c.name_en).includes(q)) return false;
    if (state.role !== "all" && !state.chaos && !c.roles.some((r) => r.role === state.role)) return false;
    return true;
  });
}

function tileHTML(c) {
  const roles = rolesOf(c);
  return `<button class="ltile" data-k="${esc(c.key)}" title="${esc(c.name)} — ${roles.filter((r) => !r.chaos).map((r) => `${ROLE_LABEL[r.role]} ${pct(r.share, 0)}`).join(", ")}">
    <img src="${img.tall(c.key)}" alt="" loading="lazy" decoding="async">
    <span class="lt-roles">${roles.map((r) => `<span class="${r.chaos ? "chaos" : ""}${r.dim ? " dim" : ""}" title="${esc(ROLE_LABEL[r.role] + (r.chaos ? " (chaos)" : " · " + t("{0} de ses parties", pct(r.share, 0))))}">${roleIcon(r.role)}</span>`).join("")}</span>
    <b>${esc(c.name)}</b></button>`;
}

function paintGrid(animate = false) {
  const list = visible();
  const grid = root.querySelector("#fl-grid");
  grid.innerHTML = list.length ? list.map(tileHTML).join("") : `<div class="empty" style="grid-column:1/-1">${esc(t("Aucun champion ne correspond."))}</div>`;
  const count = root.querySelector("#fl-count");
  const guideCount = list.reduce((s, c) => s + rolesOf(c).filter((r) => !r.chaos && !r.dim).length, 0);
  const chaosN = state.chaos ? list.reduce((s, c) => s + rolesOf(c).filter((r) => r.chaos && !r.dim).length, 0) : 0;
  if (count) count.textContent = (list.length > 1 ? t("{0} champions", list.length) : t("{0} champion", list.length)) + " · "
    + (guideCount > 1 ? t("{0} fiches", guideCount) : t("{0} fiche", guideCount)) + (chaosN ? " + " + t("{0} postes chaos", chaosN) : "");
  grid.querySelectorAll(".ltile").forEach((t) => (t.onclick = (e) => pick(t.dataset.k, e)));
  if (animate) stagger(grid.querySelectorAll(".ltile"), 12, 24);
}

// a single role (or a role filter): open the guide; otherwise a small menu to pick the role
function pick(key, e) {
  const c = store.boot.champions.find((x) => x.key === key);
  if (!c) return;
  const roles = rolesOf(c).filter((r) => !r.dim);   // role filter: only that role's guide opens
  if (roles.length === 1) return openCombo(`${key}|${roles[0].role}`);
  const sorted = [...roles].sort((a, b) => (a.chaos - b.chaos) || (b.share - a.share));
  openMenu(e.clientX, e.clientY, (m) => {
    m.innerHTML = `<div class="menu-title">${esc(t("{0} — quel rôle ?", c.name))}</div>
      ${sorted.map((r) => `<div class="menu-item${r.chaos ? " chaos" : ""}" data-role="${r.role}">${roleIcon(r.role, r.chaos ? "chaos" : "")}${esc(ROLE_LABEL[r.role])}<span class="aside">${esc(r.chaos ? t("fiche chaos") : t("{0} de ses parties", pct(r.share, 0)))}</span></div>`).join("")}`;
    m.onclick = (ev) => {
      const it = ev.target.closest(".menu-item");
      if (!it) return;
      m.hidden = true;
      openCombo(`${key}|${it.dataset.role}`);
    };
  });
}

// guide to show (after a roll, a click in the history, a locked champion...)
export function showGuide(v) {
  store.current = v;
  const h = "#/guides/" + encodeURIComponent(v.key);
  if (location.hash !== h) location.hash = h;
  else dispatch("route", "guides");
}

export async function openCombo(key, tab = null) {
  store.nextTab = tab;
  const v = await call("combo", { key });
  if (v.error) return toast(v.error, "bad");
  setStatus(t("Fiche : {0} {1}", v.champ.name, v.role_label), "teal");
  showGuide(v);
}
