// Favorites page: favorite roles and favorite champions (all their roles or only some).
import { esc, img, roleIcon, norm, ROLES, ROLE_LABEL, t } from "./util.js";
import { store, on, toast, confirmBox } from "./ctx.js";
import { call } from "./api.js";
import { favMenu } from "./guide.js";

const state = { q: "", role: "all", only: false };
let root = null, unsub = null;

export function renderFavorites(page) {
  root = page;
  page.innerHTML = `
  <div class="page-enter">
    <header class="page-head"><div>
      <div class="kicker">${esc(t("Tes préférences"))}</div>
      <h1 class="page-title">${esc(t("Favoris"))}</h1>
    </div></header>
    <section class="card">
      <h3 class="card-title">${esc(t("Rôles favoris"))}</h3>
      <div class="fav-roles" id="f-roles"></div>
    </section>
    <div class="fav-tools" id="f-tools"></div>
    <div class="fav-grid" id="f-grid"></div>
  </div>`;
  paintRoles();
  paintTools();
  paintGrid();
  unsub && unsub();
  unsub = on((type) => {
    if (!root || !document.body.contains(root)) return;
    if (type === "profile") {
      paintRoles();
      paintGrid();
      paintCount();
    }
  });
}

function paintRoles() {
  const p = store.profile;
  const box = root.querySelector("#f-roles");
  box.innerHTML = ROLES.map((r) => `<button class="role-btn${p.fav_roles.includes(r) ? " on" : ""}" data-r="${r}">${roleIcon(r)}<span>${ROLE_LABEL[r]}</span></button>`).join("");
  box.querySelectorAll(".role-btn").forEach((b) => (b.onclick = async () => {
    const r = await call("fav_toggle_role", { role: b.dataset.r });
    if (r.error) return toast(r.error, "bad");
    store.profile = r.profile;
    paintRoles();
    paintCount();
  }));
}

function paintTools() {
  const box = root.querySelector("#f-tools");
  box.innerHTML = `
    <input class="input" id="f-q" placeholder="${esc(t("Rechercher un champion…"))}" value="${esc(state.q)}" spellcheck="false">
    ${["all", ...ROLES].map((r) => `<button class="chip${state.role === r ? " on" : ""}" data-role="${r}">${r === "all" ? esc(t("Tous")) : roleIcon(r) + esc(ROLE_LABEL[r])}</button>`).join("")}
    <button class="chip${state.only ? " on" : ""}" data-only><span class="ck"></span>${esc(t("Favoris uniquement"))}</button>
    <span class="grow"></span>
    <span class="t-teal small" id="f-count"></span>
    <button class="btn sm danger" id="f-clear">${esc(t("Tout retirer"))}</button>`;
  const q = box.querySelector("#f-q");
  q.oninput = () => {
    state.q = q.value;
    paintGrid();
  };
  box.querySelectorAll("[data-role]").forEach((c) => (c.onclick = () => {
    state.role = c.dataset.role;
    paintTools();
    paintGrid();
    root.querySelector("#f-q").focus();
  }));
  box.querySelector("[data-only]").onclick = () => {
    state.only = !state.only;
    paintTools();
    paintGrid();
  };
  box.querySelector("#f-clear").onclick = async () => {
    if (!(await confirmBox(t("Retirer tous tes champions et rôles favoris ?"), t("Tout retirer")))) return;
    const r = await call("fav_clear");
    store.profile = r.profile;
    paintRoles();
    paintGrid();
    paintCount();
  };
  paintCount();
}

function paintCount() {
  const c = root.querySelector("#f-count");
  const nc = store.profile.fav_count, nr = store.profile.fav_roles.length;
  if (c) c.textContent = (nc > 1 ? t("{0} champions favoris", nc) : t("{0} champion favori", nc)) + " · " + (nr > 1 ? t("{0} rôles favoris", nr) : t("{0} rôle favori", nr));
}

function favState(key, roles) {
  const p = store.profile;
  if (p.fav_champs.includes(key)) return { full: true, roles: roles.map((r) => r.role) };
  return { full: false, roles: roles.map((r) => r.role).filter((r) => p.fav_combos.includes(`${key}|${r}`)) };
}

function tileHTML(c) {
  const st = favState(c.key, c.roles);
  const cls = st.full ? "full" : st.roles.length ? "part" : "";
  return `<div class="ftile ${cls}" data-k="${esc(c.key)}" title="${esc(c.name)} — ${esc(c.roles.map((r) => ROLE_LABEL[r.role]).join(", "))}&#10;${esc(t("Clic : favori pour tous ses rôles · clic droit : choisir les rôles"))}">
    ${st.full ? `<svg class="star" viewBox="0 0 24 24"><path d="M12 3.2l2.7 5.5 6 .9-4.4 4.2 1 6-5.3-2.8-5.3 2.8 1-6-4.4-4.2 6-.9z"/></svg>` : ""}
    <img src="${img.icon(c.key)}" alt="" loading="lazy">
    ${!st.full && st.roles.length ? `<span class="froles">${st.roles.map((r) => roleIcon(r)).join("")}</span>` : ""}
    <span class="nm">${esc(c.name)}</span></div>`;
}

function paintGrid() {
  const q = norm(state.q);
  const list = store.boot.champions.filter((c) => {
    if (q && !norm(c.name).includes(q) && !norm(c.name_en).includes(q)) return false;
    if (state.role !== "all" && !c.roles.some((r) => r.role === state.role)) return false;
    if (state.only) {
      const st = favState(c.key, c.roles);
      if (!st.full && !st.roles.length) return false;
    }
    return true;
  });
  const grid = root.querySelector("#f-grid");
  grid.innerHTML = list.length ? list.map(tileHTML).join("") : `<div class="empty" style="grid-column:1/-1">${esc(t("Aucun champion ne correspond."))}</div>`;
  grid.querySelectorAll(".ftile").forEach((t) => {
    t.onclick = async () => {
      const r = await call("fav_toggle_global", { key: t.dataset.k });
      if (r.error) return toast(r.error, "bad");
      store.profile = r.profile;
      refreshTile(t.dataset.k);
    };
    t.oncontextmenu = (e) => {
      e.preventDefault();
      favMenu(e.clientX, e.clientY, t.dataset.k, () => refreshTile(t.dataset.k));
    };
  });
}

function refreshTile(key) {
  const t = root.querySelector(`.ftile[data-k="${CSS.escape(key)}"]`);
  const c = store.boot.champions.find((x) => x.key === key);
  if (!t || !c) return;
  if (state.only) return paintGrid();
  const n = document.createElement("div");
  n.innerHTML = tileHTML(c);
  const nt = n.firstElementChild;
  t.replaceWith(nt);
  nt.onclick = t.onclick;
  nt.oncontextmenu = t.oncontextmenu;
  paintCount();
}
