// Binder page: one card per champion and role, filled by the games played on a roll (collection.py). New or improved
// cards stay face down until opened, one by one, in the booster window.
import { esc, img, roleIcon, norm, ROLES, ROLE_LABEL, CHAOS_ICON, t } from "./util.js";
import { store, on, toast, backdrop, openModal } from "./ctx.js";
import { call } from "./api.js";
import * as sound from "./sound.js";

const LEVELS = [
  { id: "locked", label: "À obtenir" },
  { id: "known", label: "Connue" },
  { id: "rare", label: "Rare" },
  { id: "epic", label: "Épique" },
  { id: "legendary", label: "Légendaire" },
];
const HOW = {
  known: "Tiré par la roulette officielle, pas encore joué",
  rare: "Joué sur un tirage de la roulette officielle",
  epic: "Victoire hors classée sur la Faille",
  legendary: "Victoire en classée (Solo/duo ou Flex)",
};
const state = { page: "col", view: "cards", role: "all", show: "all", q: "", chaos: true };
const PIP = ["none", "played", "rare", "epic", "legendary"];
// a card back, in the chosen design (animated for the unlocked ones): a light turns over the metal and the gems
// catch it as it passes (each back at its own point of the turn); hovered, or about to be revealed, they all light up
// in turn
const BACK_PARTS = `<span class="tb-sheen"></span><span class="tb-flare"></span><span class="tb-gems">${"<i></i>".repeat(17)}</span>`;
const backHTML = (skin = data && data.card_back, attrs = "", inner = "") =>
  `<div class="tc back" data-skin="${esc(skin || "hextech")}" style="--phase:-${(Math.random() * 8).toFixed(2)}s"${attrs}>${BACK_PARTS}${inner}</div>`;
const NEED = {
  cards: (n) => t("{0} cartes obtenues", n),
  chaos: (n) => t("{0} cartes de rôles chaos", n),
  legendary: (n) => t("{0} légendaires", n),
  masters: (n) => (n === 1 ? t("1 champion maître") : t("{0} champions maîtres", n)),
};
let root = null, unsub = null, data = null;

export function renderBinder(page) {
  root = page;
  backdrop(store.boot.hero);
  page.innerHTML = `
  <div class="page-enter">
    <header class="page-head"><div>
      <div class="kicker">${esc(t("Collection"))}</div>
      <h1 class="page-title">${esc(t("Classeur"))}<span class="bd-title" id="bd-title" hidden></span></h1>
      <p class="page-sub muted">${esc(t("Une carte par champion et par rôle, gagnée avec la roulette officielle : joue le champion tiré pour l'obtenir, gagne pour la faire monter, gagne en classée pour la légendaire."))}</p>
    </div></header>
    <div class="seg bd-pages" id="bd-pages"></div>
    <div id="bd-col">
      <div id="bd-stats" class="bd-stats"></div>
      <div id="bd-booster"></div>
      <div id="bd-backs"></div>
      <div id="bd-tools" class="bd-tools"></div>
      <div id="bd-grid" class="bd-grid"></div>
    </div>
    <div id="bd-rw" hidden></div>
  </div>`;
  paintPages();
  load();
  unsub && unsub();
  unsub = on((type) => {
    if (!root || !document.body.contains(root)) return;
    if (type === "binder" || type === "history") load();
    if (type === "rewards") paintPages();
  });
}

// --- the two pages of the binder: the collection, the rewards path -----------------------------
function paintPages() {
  const box = root.querySelector("#bd-pages");
  const unseen = store.boot.rewards_unseen || 0;
  box.innerHTML = [["col", t("Collection")], ["rw", t("Récompenses")]].map(([p, l]) =>
    `<button data-page="${p}" class="${state.page === p ? "on" : ""}">${esc(l)}${p === "rw" && unseen ? `<b class="bd-new">${unseen}</b>` : ""}</button>`).join("");
  box.querySelectorAll("[data-page]").forEach((b) => (b.onclick = () => {
    state.page = b.dataset.page;
    showPage();
  }));
  root.querySelector("#bd-col").hidden = state.page !== "col";
  root.querySelector("#bd-rw").hidden = state.page !== "rw";
}

async function showPage() {
  paintPages();
  if (state.page !== "rw") return;
  const r = await call("rewards");
  if (!root || r.error) return;
  paintRewards(r);
  if (r.steps.some((s) => s.new)) setTimeout(() => call("rewards_seen"), 1500);   // shown once as new
}

const COND = {
  rolls: (n) => t("{0} tirages joués", n),
  cards: (n) => t("{0} cartes (rare ou mieux)", n),
  flawless: (n) => (n === 1 ? t("Une victoire sans mourir") : t("{0} victoires sans mourir", n)),
  chaos: (n) => t("{0} cartes de rôles chaos", n),
  epics: (n) => t("{0} cartes épiques ou légendaires", n),
  domination: () => t("Le plus de dégâts des 10 joueurs d'une partie"),
  roles: (n) => t("{0} cartes dans chacun des 5 rôles", n),
  penta: () => t("Un pentakill"),
  legendary: (n) => t("{0} légendaires", n),
  masters: () => t("Un champion maître (ses 5 rôles légendaires)"),
};
const KIND_ICON = {
  title: `<svg viewBox="0 0 24 24"><path d="M6 4h12v3.5a6 6 0 0 1-12 0z"/><path d="M12 13.5V18"/><path d="M8 20h8"/><path d="M6 6H3.5a3 3 0 0 0 3 3.6M18 6h2.5a3 3 0 0 1-3 3.6"/></svg>`,
  joker: `<svg viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="18" rx="2.5"/><path d="M12 7.5l1.3 2.9 3.1.3-2.4 2 .8 3.1L12 14.2 9.2 15.8l.8-3.1-2.4-2 3.1-.3z"/></svg>`,
  stamp: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="5"/><path d="M12 7v1.6M12 15.4V17M7 12h1.6M15.4 12H17"/></svg>`,
  back: `<svg viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="18" rx="2.5"/><circle cx="12" cy="12" r="3.6"/><path d="M12 6v2.4M12 15.6V18"/></svg>`,
  roulette: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="2.5"/><path d="M12 3.5v6M12 14.5v6M3.5 12h6M14.5 12h6"/></svg>`,
  opening: `<svg viewBox="0 0 24 24"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/></svg>`,
};

function paintRewards(r) {
  const box = root.querySelector("#bd-rw");
  const done = r.steps.filter((s) => s.done).length;
  const next = r.steps.find((s) => !s.done);
  const pct = (s) => Math.min(...s.conds.map((c) => c.have / c.goal));
  const cond = (s) => s.conds.map((c) => COND[c.counter](c.goal)).join(t(" et "));
  const have = (s) => s.conds.map((c) => `${c.have}/${c.goal}`).join(" · ");
  const reward = (x) => `<span class="rw-gift ${x.kind}${x.ready ? "" : " soon"}" title="${esc(x.ready ? "" : t("Arrive dans une prochaine version"))}">${KIND_ICON[x.kind] || ""}${esc(x.label)}${x.ready ? "" : `<em>${esc(t("bientôt"))}</em>`}</span>`;
  const j = r.joker;
  box.innerHTML = `
    <section class="card rw-hero">
      <div class="rw-count"><span class="kicker">${esc(t("Parcours de récompenses"))}</span><b>${done}<small> / ${r.steps.length}</small></b>
        <i class="rw-bar"><em style="width:${((100 * done) / r.steps.length).toFixed(1)}%"></em></i></div>
      ${next ? `<div class="rw-next"><span class="kicker">${esc(t("Prochain palier"))}</span><b>${esc(next.name)}</b>
        <span class="muted">${esc(cond(next))} · ${esc(have(next))}</span><i class="rw-bar"><em style="width:${(100 * pct(next)).toFixed(1)}%"></em></i>
        <div class="rw-gifts">${next.rewards.map(reward).join("")}</div></div>`
        : `<div class="rw-next"><b>${esc(t("Parcours terminé : bravo !"))}</b></div>`}
    </section>
    <div class="rw-side">
      <section class="card rw-joker${j.available ? " on" : ""}">
        <h3 class="card-title">${KIND_ICON.joker}${esc(t("Joker"))}</h3>
        <p>${esc(!j.unlocked ? t("Se débloque au premier palier.") : j.available ? t("Disponible : sur ton tirage en attente, il le passe sans le compter comme annulé, et la roulette relance.")
          : t("Revient dans {0} tirages joués.", j.next_in))}</p>
        <small class="muted">${esc(t("Un seul en réserve, regagné tous les 10 tirages joués : le hasard reste roi."))}</small>
      </section>
      <section class="card rw-looks">
        ${Object.entries(LOOKS).map(([kind, L]) => `<h3 class="card-title">${KIND_ICON[kind]}${esc(t(L.title))}</h3>
        <div class="rw-themes">${r.looks[kind].options.map((x) => `<button class="rw-theme${r.looks[kind].current === x.id ? " on" : ""}" data-look="${kind}" data-id="${x.id}"
          ${x.unlocked ? "" : "disabled"} style="--sw:${L.swatch[x.id]}"><i></i>${esc(t(L.names[x.id]))}${x.unlocked ? "" : `<small>${esc(x.ready ? t("Palier {0}", x.step) : t("bientôt"))}</small>`}</button>`).join("")}</div>`).join("")}
      </section>
      <section class="card rw-titles">
        <h3 class="card-title">${KIND_ICON.title}${esc(t("Ton titre"))}</h3>
        ${r.titles.length ? `<div class="rw-chips">${[{ id: "", label: t("Aucun") }, ...r.titles].map((x) =>
          `<button class="chip${(r.title || "") === x.id ? " on" : ""}" data-title="${esc(x.id)}"><span class="ck"></span>${esc(x.label)}</button>`).join("")}</div>
          <small class="muted">${esc(t("Affiché dans ton classeur et dans le texte « Copier » de la roulette de groupe."))}</small>`
          : `<p class="muted">${esc(t("Le premier titre arrive au premier palier."))}</p>`}
      </section>
    </div>
    <section class="card rw-path">
      <h3 class="card-title">${esc(t("Les paliers"))}</h3>
      ${r.steps.map((s, i) => `<div class="rw-step${s.done ? " done" : ""}${s.new ? " new" : ""}${s === next ? " next" : ""}">
        <span class="rw-n">${s.done ? "✓" : i + 1}</span>
        <div class="rw-main"><b>${esc(s.name)}${s.new ? `<em class="rw-tag">${esc(t("Nouveau"))}</em>` : ""}</b><small>${esc(cond(s))}</small>
          ${s.done ? "" : `<i class="rw-bar"><em style="width:${(100 * pct(s)).toFixed(1)}%"></em></i>`}</div>
        <div class="rw-gifts">${s.rewards.map(reward).join("")}</div>
        <span class="rw-have">${s.done ? esc(t("Débloqué")) : esc(have(s))}</span>
      </div>`).join("")}
    </section>
    <section class="card rw-stamps">
      <h3 class="card-title">${KIND_ICON.stamp}${esc(t("Les tampons d'exploit"))}</h3>
      <p class="muted">${esc(t("Ils se posent sur la carte du champion et du rôle de la partie, pour toujours."))}</p>
      <div class="rw-stamp-list">${STAMP_INFO.map(([id, name, how]) => `<div><i class="tc-stamp ${id}">${STAMP_SVG[id]}</i><b>${esc(t(name))}</b><small>${esc(t(how))}</small></div>`).join("")}</div>
    </section>`;
  box.querySelectorAll("[data-look]").forEach((b) => (b.onclick = async () => {
    const res = await call("set_look", { kind: b.dataset.look, id: b.dataset.id });
    if (res.error) return toast(res.error, "bad");
    showPage();
  }));
  box.querySelectorAll("[data-title]").forEach((b) => (b.onclick = async () => {
    const res = await call("set_title", { title: b.dataset.title || null });
    if (res.error) return toast(res.error, "bad");
    load();
  }));
}

// looks unlocked in the rewards path (rewards.LOOKS): their names and swatches
const split = (bg, acc) => `linear-gradient(135deg, ${bg} 0 55%, ${acc} 55% 100%)`;
const LOOKS = {
  roulette: { title: "Roulette", names: { classic: "Classique", infernal: "Infernale", prism: "Prismatique", void: "Néant", gold: "Dorée" },
    swatch: { classic: split("#0a1220", "#e8d09a"), infernal: 'url(hud/infernal_primary.webp) center / 100% 100%',
      prism: 'url(hud/prism_primary.webp) center / 100% 100%', void: 'url(hud/void_primary.webp) center / 100% 100%',
      gold: 'url(hud/gold_primary.webp) center / 100% 100%' } },
  opening: { title: "Ouverture des boosters", names: { classic: "Classique", silver: "Éclat d'argent" },
    swatch: { classic: split("#0a1220", "#e8d09a"), silver: "linear-gradient(135deg, #5d6878, #f4f7fb 45%, #9aa6b8 60%, #e6ebf2)" } },
};

// exploit stamps on the cards (rewards.py)
const STAMP_SVG = {
  flawless: `<svg viewBox="0 0 24 24"><path d="M12 3l7 2.8v5.6c0 4.3-3 7.9-7 9.6-4-1.7-7-5.3-7-9.6V5.8z"/><path d="M8.6 12.1l2.3 2.3 4.5-4.6"/></svg>`,
  domination: `<svg viewBox="0 0 24 24"><path d="M5 5l9.5 9.5M19 5L9.5 14.5"/><path d="M12.8 16.2l2 2M11.2 16.2l-2 2"/><path d="M5 5h3v3M19 5h-3v3"/><path d="M16 17.5l2.5 2.5M8 17.5L5.5 20"/></svg>`,
  penta: `<svg viewBox="0 0 24 24"><path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.8z"/></svg>`,
};
const STAMP_INFO = [
  ["flawless", "Sans faillir", "Gagner sans mourir une seule fois."],
  ["domination", "Domination", "Faire le plus de dégâts aux champions des 10 joueurs."],
  ["penta", "Pentakill", "Réussir un pentakill."],
];

async function load() {
  const r = await call("binder");
  if (!root || r.error) return;
  data = r;
  const title = root.querySelector("#bd-title");
  title.hidden = !r.title;
  title.textContent = r.title || "";
  if (state.page === "rw") showPage();
  paintStats();
  paintBooster();
  paintBacks();
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
    tile(t("Connus"), n(1), total, "") +
    tile(t("Cartes obtenues"), n(2), total, "win") +
    tile(t("Légendaires"), n(4), total, "leg") +
    tile(t("Champions maîtres"), data.masters.length, champs, "master");
}

function paintBooster() {
  const box = root.querySelector("#bd-booster");
  const n = data.pending.length;
  if (!n) return (box.innerHTML = "");
  box.innerHTML = `<section class="card bd-booster">
    <div class="bd-pack">${backHTML().repeat(3)}</div>
    <div class="grow"><div class="kicker">${esc(t("Booster"))}</div>
      <h3>${esc(n === 1 ? t("1 nouvelle carte à ouvrir") : t("{0} nouvelles cartes à ouvrir", n))}</h3>
      <p class="muted">${esc(t("Tes dernières parties sur la roulette ont rempli ton classeur."))}</p></div>
    <button class="btn-gold" data-open>${esc(t("Ouvrir"))}</button>
  </section>`;
  box.querySelector("[data-open]").onclick = () => openBooster(data.pending);
}

// card backs: the ones unlocked can be chosen, the others show what unlocks them
function paintBacks() {
  const box = root.querySelector("#bd-backs");
  box.innerHTML = `<section class="card bd-backs">
    <h3 class="card-title">${esc(t("Dos de carte"))}<span class="aside">${esc(t("{0} / {1} débloqués", data.backs.filter((b) => b.unlocked).length, data.backs.length))}</span></h3>
    <div class="bd-back-row">${data.backs.map((b) => `
      <button class="bd-back${b.id === data.card_back ? " on" : ""}${b.unlocked ? "" : " locked"}" data-back="${esc(b.id)}" ${b.unlocked ? "" : "disabled"}>
        ${backHTML(b.id)}
        <b>${esc(b.label)}</b>
        <small>${b.id === data.card_back ? esc(t("Choisi")) : b.unlocked ? esc(t("Débloqué")) : esc(NEED[b.need](b.goal)) + ` · ${Math.min(b.have, b.goal)}/${b.goal}`}</small>
      </button>`).join("")}</div>
  </section>`;
  box.querySelectorAll(".bd-back:not(.locked)").forEach((el) => (el.onclick = async () => {
    const r = await call("set_card_back", { back: el.dataset.back });
    if (r.error) return toast(r.error, "bad");
    data.card_back = r.card_back;
    sound.click();
    paintBooster();
    paintBacks();
    paintGrid();
  }));
}

function paintTools() {
  const box = root.querySelector("#bd-tools");
  const per = (r) => data.cards.filter((c) => (r === "all" || c.role === r) && c.level >= 2 && (state.chaos || c.guide)).length;
  const max = (r) => data.cards.filter((c) => (r === "all" || c.role === r) && (state.chaos || c.guide)).length;
  const champs = state.view === "champs";
  box.innerHTML = `
    <div class="bd-left">
      <div class="seg sm bd-view">${[["cards", t("Cartes")], ["champs", t("Champions")]].map(([v, l]) => `<button data-view="${v}" class="${state.view === v ? "on" : ""}">${esc(l)}</button>`).join("")}</div>
      ${champs ? "" : `<div class="bd-roles">${["all", ...ROLES].map((r) => `<button class="bd-role${state.role === r ? " on" : ""}" data-role="${r}">
      ${r === "all" ? "" : roleIcon(r)}<span>${esc(r === "all" ? t("Tous") : ROLE_LABEL[r])}</span><small>${per(r)}/${max(r)}</small></button>`).join("")}</div>`}
    </div>
    <div class="bd-filters">
      <div class="seg sm">${[["all", t("Toutes")], ["got", t("Obtenues")], ["todo", t("À obtenir")]].map(([v, l]) => `<button data-show="${v}" class="${state.show === v ? "on" : ""}">${esc(l)}</button>`).join("")}</div>
      <label class="bd-chaos" title="${esc(t("Les rôles où le champion n'a pas de fiche : ils comptent pour le master set"))}"><input type="checkbox" id="bd-chaos" ${state.chaos ? "checked" : ""}>${CHAOS_ICON}${esc(t("Rôles chaos"))}</label>
      <input class="input bd-search" id="bd-q" value="${esc(state.q)}" placeholder="${esc(t("Chercher un champion…"))}" spellcheck="false">
    </div>`;
  box.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => {
    state.view = b.dataset.view;
    paintTools();
    paintGrid();
  }));
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

// a card: metal frame by level, art window, role icon in the frame's ring, name plate
export function cardHTML(c, opts = {}) {
  if (opts.back) return backHTML(data.card_back, ` data-id="${esc(c.id)}" title="${esc(t("Carte à ouvrir"))}"`, `<span class="tc-new">${esc(t("à ouvrir"))}</span>`);
  const lv = opts.level != null ? opts.level : shown(c);
  const L = levelOf(lv);
  const master = lv === 4 && data && data.masters.includes(c.key);
  const how = lv ? t(HOW[L.id]) : t("Joue ce champion à ce poste quand la roulette te le tire");
  const detail = c.at && lv ? ` · ${c.queue || ""} · ${c.at} · ${t("{0} parties, {1} victoires", c.games, c.wins)}` : "";
  return `<div class="tc lv${lv}${master ? " master" : ""}" data-id="${esc(c.id)}" title="${esc(`${c.name} ${ROLE_LABEL[c.role]} — ${t(L.label)}. ${how}${detail}`)}">
    <div class="tc-art"><img src="${img.tall(c.key)}" alt="" loading="lazy"><span class="tc-foil"></span></div>
    <span class="tc-frame"></span><span class="tc-prism"></span>
    <span class="tc-medal">${roleIcon(c.role)}</span>
    ${c.guide ? "" : `<span class="tc-chaos" title="${esc(t("Rôle chaos"))}">${CHAOS_ICON}</span>`}
    ${(c.stamps || []).length ? `<span class="tc-stamps">${c.stamps.map((s) => `<i class="tc-stamp ${s}" title="${esc(t((STAMP_INFO.find((x) => x[0] === s) || [])[1] || ""))}">${STAMP_SVG[s]}</i>`).join("")}</span>` : ""}
    ${master ? `<img class="tc-crown" src="/img/cards/crown.webp" alt="" title="${esc(t("Champion maître"))}">` : ""}
    <div class="tc-plate"><b>${esc(c.name)}</b><span class="tc-sub">${esc(ROLE_LABEL[c.role])} · ${esc(master ? t("Maître") : t(L.label))}</span></div>
  </div>`;
}

// only the cards in sight move: a binder holds hundreds of them, the others' animations wait (class "off")
const inSight = new IntersectionObserver((list) => list.forEach((e) => e.target.classList.toggle("off", !e.isIntersecting)));

function watchCards() {
  inSight.disconnect();
  root.querySelectorAll(".tc").forEach((el) => inSight.observe(el));
}

function paintGrid() {
  if (state.view === "champs") {
    paintChamps();
    return watchCards();
  }
  const box = root.querySelector("#bd-grid");
  box.className = "bd-grid";
  const q = norm(state.q);
  const list = data.cards.filter((c) => (state.role === "all" || c.role === state.role) && (state.chaos || c.guide)
    && (!q || norm(c.name).includes(q))
    && (state.show === "all" || (state.show === "got" ? c.level >= 2 : c.level < 4)));
  if (!list.length) {
    box.innerHTML = `<div class="card empty">${esc(t("Aucune carte ici pour l'instant."))}</div>`;
    return watchCards();
  }
  // obtained cards first, best first; then the rest by name
  list.sort((a, b) => b.level - a.level || a.name.localeCompare(b.name) || ROLES.indexOf(a.role) - ROLES.indexOf(b.role));
  box.innerHTML = list.map((c) => cardHTML(c, { back: data.pending.includes(c.id) })).join("");
  box.querySelectorAll(".tc.back").forEach((el) => (el.onclick = () => openBooster([el.dataset.id])));
  box.querySelectorAll(".tc:not(.back):not(.lv0)").forEach((el) => (el.onclick = () => openCard(el.dataset.id)));
  watchCards();
}

// one tile per champion: completion ring, how many roles done, the five roles by level; a click shows its cards
function paintChamps() {
  const box = root.querySelector("#bd-grid");
  box.className = "bd-champs";
  const q = norm(state.q);
  const by = {};
  data.cards.forEach((c) => (by[c.key] = by[c.key] || { key: c.key, name: c.name, cards: [] }).cards.push(c));
  const list = Object.values(by).filter((ch) => {
    const got = ch.cards.filter((c) => c.level >= 2).length;
    return (!q || norm(ch.name).includes(q)) && (state.show === "all" || (state.show === "got" ? got > 0 : !data.masters.includes(ch.key)));
  });
  const score = (ch) => ch.cards.reduce((n, c) => n + c.level, 0);
  list.sort((a, b) => score(b) - score(a) || a.name.localeCompare(b.name));
  if (!list.length) {
    box.innerHTML = `<div class="card empty">${esc(t("Aucun champion ici pour l'instant."))}</div>`;
    return;
  }
  box.innerHTML = list.map((ch) => {
    const got = ch.cards.filter((c) => c.level >= 2).length, best = ch.cards.filter((c) => c.level === 4).length;
    const master = data.masters.includes(ch.key);
    return `<button class="bd-champ${master ? " master" : ""}" data-name="${esc(ch.name)}">
      <img src="${img.icon(ch.key)}" alt="" data-ring="${esc(ch.key)}">
      <span class="bc-name">${esc(ch.name)}${master ? ' <img class="bc-crown" src="/img/cards/crown.webp" alt="">' : ""}</span>
      <span class="bc-count">${esc(t("{0}/5 rôles · {1} légendaires", got, best))}</span>
      <span class="bc-roles">${ch.cards.map((c) => `<i class="bc-pip ${PIP[c.level]}${c.guide ? "" : " chaos"}" title="${esc(`${ROLE_LABEL[c.role]} — ${t(levelOf(c.level).label)}`)}">${roleIcon(c.role)}</i>`).join("")}</span>
    </button>`;
  }).join("");
  box.querySelectorAll(".bd-champ").forEach((el) => (el.onclick = () => {
    state.view = "cards";
    state.role = "all";
    state.show = "all";
    state.q = el.dataset.name;
    paintTools();
    paintGrid();
  }));
}

// a card under the pointer: its sound (a soft swish, a glint on the best ones)
let hovered = null;
document.addEventListener("pointerover", (e) => {
  const el = e.target.closest && e.target.closest(".bd-grid .tc, .bd-back .tc, .bd-pack, .bk-face .tc");
  if (el === hovered) return;
  hovered = el;
  if (el && !el.closest(".bd-back.locked")) sound.hover(el.classList.contains("back") ? 2 : +((el.className.match(/\blv(\d)/) || [])[1] || 0));
});

// cards tilt toward the pointer; the foil and sheen follow it
document.addEventListener("pointermove", (e) => {
  const el = e.target.closest && e.target.closest(".tc:not(.lv0):not(.lv1)");
  if (!el || el.closest(".bd-pack")) return;
  const r = el.getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
  el.classList.add("tilt");
  el.style.setProperty("--mx", x.toFixed(3));
  el.style.setProperty("--my", y.toFixed(3));
  el.style.setProperty("--rx", ((0.5 - y) * 14).toFixed(2) + "deg");
  el.style.setProperty("--ry", ((x - 0.5) * 18).toFixed(2) + "deg");
});
document.addEventListener("pointerout", (e) => {
  const el = e.target.closest && e.target.closest(".tc");
  if (!el || (e.relatedTarget && el.contains(e.relatedTarget))) return;
  el.classList.remove("tilt");
  el.style.setProperty("--rx", "0deg");
  el.style.setProperty("--ry", "0deg");
});

// --- a card's details (clicked): the card big, how it was earned, its best win and the elo of it ---------
function openCard(id) {
  const c = data.cards.find((x) => x.id === id);
  if (!c) return;
  const lv = shown(c), L = levelOf(lv);
  const master = lv === 4 && data.masters.includes(c.key);
  const row = (k, v) => `<div class="cd-row"><span>${esc(k)}</span><b>${v}</b></div>`;
  const e = c.elo;
  const { box } = openModal(`<div class="cd">
    <div class="cd-card">${cardHTML(c)}</div>
    <div class="cd-info">
      <span class="kicker">${esc(master ? t("Champion maître") : t(L.label))}</span>
      <h2>${esc(c.name)} · ${esc(ROLE_LABEL[c.role])}${c.guide ? "" : ` <span class="bk-chaos">${CHAOS_ICON}${esc(t("chaos"))}</span>`}</h2>
      <p class="muted">${esc(lv ? t(HOW[L.id]) : "")}</p>
      ${row(t("Parties jouées"), c.games)}${row(t("Victoires"), c.wins)}
      ${c.at ? row(t("Obtenue"), esc(`${c.queue || ""} · ${c.at}`)) : ""}
      ${c.rbuild && c.rbuild.games ? row(t("Build random"), esc(c.rbuild.best ? t("Oui, sur la partie qui l'a obtenue")
        : c.rbuild.games > 1 ? t("Sur {0} parties", c.rbuild.games) : t("Sur 1 partie"))) : ""}
      ${row(t("Meilleure victoire"), e ? `<i class="cd-tier t-${e.tier.toLowerCase()}">${esc(e.label)}</i><small>${esc(e.where)}${e.date ? " · " + esc(e.date) : ""}</small>`
        : `<small>${esc(c.wins ? t("Elo inconnu (victoire d'avant la version 2.6, ou sans rang)") : t("Pas encore de victoire"))}</small>`)}
      ${(c.stamps || []).length ? `<div class="cd-stamps">${c.stamps.map((s) => {
        const info = STAMP_INFO.find((x) => x[0] === s) || [s, s, ""];
        return `<div><i class="tc-stamp ${s}">${STAMP_SVG[s]}</i><b>${esc(t(info[1]))}</b><small>${esc(t(info[2]))}</small></div>`;
      }).join("")}</div>` : ""}
    </div></div>`);
  box.style.width = "auto";
}

// --- booster: cards revealed one by one ---------------------------------------------------------
// "Éclat d'argent" opening: the back cracks from its wheel, then bursts into shards (polygons in % of the card)
function shatterHTML(skin) {
  const C = [50, 47], K = 9;
  const norm = (a) => (a + 2 * Math.PI) % (2 * Math.PI);
  const exit = (a) => {   // where the ray from the wheel leaves the card
    const dx = Math.cos(a), dy = Math.sin(a);
    const tx = dx > 0 ? (100 - C[0]) / dx : dx < 0 ? -C[0] / dx : Infinity;
    const ty = dy > 0 ? (100 - C[1]) / dy : dy < 0 ? -C[1] / dy : Infinity;
    const k = Math.min(tx, ty);
    return [C[0] + dx * k, C[1] + dy * k];
  };
  const angles = Array.from({ length: K }, (_, i) => ((i + 0.2 + Math.random() * 0.6) / K) * 2 * Math.PI);
  const hits = angles.map(exit);
  const mids = angles.map((a, i) => {   // a bend on each crack, shared by the two shards on its sides
    const f = 0.3 + Math.random() * 0.25, off = (Math.random() - 0.5) * 7;
    return [C[0] + (hits[i][0] - C[0]) * f - Math.sin(a) * off, C[1] + (hits[i][1] - C[1]) * f + Math.cos(a) * off];
  });
  const corners = [[100, 100], [0, 100], [0, 0], [100, 0]].map((p) => ({ p, a: norm(Math.atan2(p[1] - C[1], p[0] - C[0])) }));
  const between = (a, b) => corners.filter((c) => (b > a ? c.a > a && c.a < b : c.a > a || c.a < b))
    .sort((u, v) => norm(u.a - a) - norm(v.a - a)).map((c) => c.p);
  const pieces = [];
  for (let i = 0; i < K; i++) {
    const j = (i + 1) % K;
    pieces.push({ pts: [C, mids[i], mids[j]], inner: true });
    pieces.push({ pts: [mids[i], hits[i], ...between(angles[i], angles[j]), hits[j], mids[j]] });
  }
  const pt = ([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`;
  const cracks = hits.map((h, i) => `<path d="M${pt(C)} L${pt(mids[i])} L${pt(h)}" pathLength="1"/>`).join("")
    + mids.map((m, i) => `<path class="ring" d="M${pt(m)} L${pt(mids[(i + 1) % K])}" pathLength="1"/>`).join("");
  const shards = pieces.map(({ pts, inner }) => {
    const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length, cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
    const dx = cx - C[0], dy = cy - C[1], len = Math.hypot(dx, dy) || 1;
    const push = (inner ? 300 : 190) + Math.random() * 140;
    const r = (n) => ((Math.random() - 0.5) * n).toFixed(0);
    return `<i style="clip-path:polygon(${pts.map(([x, y]) => `${x.toFixed(1)}% ${y.toFixed(1)}%`).join(",")});transform-origin:${cx.toFixed(1)}% ${cy.toFixed(1)}%;`
      + `--tx:${((dx / len) * push).toFixed(0)}px;--ty:${((dy / len) * push + 60).toFixed(0)}px;--rz:${r(200)}deg;--rx:${r(140)}deg;--ry:${r(140)}deg;--d:${(Math.random() * 0.07).toFixed(2)}s"></i>`;
  }).join("");
  const src = `/img/cards/back${skin && skin !== "hextech" ? "_" + skin : ""}.webp`;
  return `<svg class="bk-cracks" viewBox="0 0 100 100" preserveAspectRatio="none">${cracks}</svg>
    <div class="bk-shards" style="--img:url('${src}')">${shards}</div><div class="bk-impact"></div>`;
}

function openBooster(ids) {
  const queue = ids.map((id) => data.cards.find((c) => c.id === id)).filter(Boolean)
    .sort((a, b) => a.level - b.level);   // the best card last
  if (!queue.length) return;
  const box = document.createElement("div");
  box.className = "bk";
  document.body.appendChild(box);
  sound.rip();
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
  // the reveal that completes a mastered champion (no card of it left to open after this one) crowns it
  const keyOf = (id) => (data.cards.find((x) => x.id === id) || {}).key;
  const crowns = (n) => {
    const c = queue[n];
    const done = new Set(queue.slice(0, n + 1).map((x) => x.id));
    return c.level === 4 && data.masters.includes(c.key) && data.pending.every((id) => done.has(id) || keyOf(id) !== c.key);
  };
  const silver = store.profile.opening === "silver";
  const show = () => {
    const c = queue[i];
    const L = levelOf(c.level);
    const was = c.shown ? levelOf(c.shown) : null;
    const crown = crowns(i);
    const royal = crown && data.masters.length === 1 && data.backs.find((b) => b.id === "crown");
    const sparks = Array.from({ length: crown ? 60 : c.level >= 3 ? 34 : 18 }, () =>
      `<i style="left:${(Math.random() * 100).toFixed(1)}%;--s:${(2 + Math.random() * 3).toFixed(1)}px;--d:${(2.6 + Math.random() * 2.4).toFixed(2)}s;--w:${(Math.random() * 2.5).toFixed(2)}s;--x:${((Math.random() - 0.5) * 160).toFixed(0)}px"></i>`).join("");
    box.innerHTML = `
      <div class="bk-shade"></div>
      <div class="bk-stage lv${c.level}${crown ? " crowning" : ""}${silver ? " silver" : ""}">
        <div class="bk-glow"></div>
        <div class="bk-sparks">${sparks}</div>
        <div class="bk-count">${esc(t("Carte {0} sur {1}", i + 1, queue.length))}</div>
        <div class="bk-ribbon">${esc(was ? t("Amélioration : {0} → {1}", t(was.label), t(L.label)) : t("Nouvelle carte"))}</div>
        <div class="bk-card">${crown ? `<div class="bk-fan">${data.cards.filter((x) => x.key === c.key && x.id !== c.id)
          .map((x) => `<div class="bk-fan-card">${cardHTML(x, { level: 4 })}</div>`).join("")}</div>` : ""}<div class="bk-flip">
          <div class="bk-face bk-front">${cardHTML(c, { level: c.level })}</div>
          <div class="bk-face bk-rear">${backHTML()}</div>${silver ? shatterHTML(data.card_back) : ""}
        </div><div class="bk-burst"></div>${crown ? `<div class="bk-shock"></div><div class="bk-crownfall"><img src="/img/cards/crown.webp" alt=""></div>` : ""}</div>
        ${crown ? '<div class="bk-flash"></div>' : ""}
        <div class="bk-text">
          <div class="bk-tier">${esc(t(L.label))}</div>
          <h2>${esc(c.name)} · ${esc(ROLE_LABEL[c.role])}${c.guide ? "" : ` <span class="bk-chaos">${CHAOS_ICON}${esc(t("chaos"))}</span>`}</h2>
          <p class="muted">${esc(t(HOW[L.id]))}${c.at ? esc(` · ${c.queue || ""} · ${c.at}`) : ""}</p>
          ${crown ? `<p class="bk-master-line">${esc(t("Ses cinq rôles sont légendaires : {0} rejoint tes champions maîtres.", c.name))}${royal ? `<br><b>${esc(t("Dos de carte {0} débloqué !", royal.label))}</b>` : ""}</p>` : ""}
        </div>
        <div class="bk-btns">
          ${queue.length - i > 1 ? `<button class="btn" data-all>${esc(t("Tout révéler"))}</button>` : ""}
          <button class="btn-gold" data-next>${esc(queue.length - i > 1 ? t("Suivante ({0})", queue.length - i - 1) : t("Terminer"))}</button>
        </div>
      </div>`;
    call("binder_open", { ids: [c.id] });
    // the back's roulette spins, then the card turns over; a champion completed is then crowned
    const stage = box.querySelector(".bk-stage");
    sound.wheel();
    requestAnimationFrame(() => setTimeout(() => {
      if (!stage.isConnected) return;   // skipped in the meantime
      stage.classList.add("flipped");
      if (silver) sound.shatter();
      else sound.flip();
      setTimeout(() => stage.isConnected && sound.reveal(c.level), 260);
    }, 1150));
    if (silver) setTimeout(() => stage.isConnected && stage.classList.add("cracking"), 720);
    if (crown) setTimeout(() => {
      if (!stage.isConnected) return;
      stage.classList.add("crowned");
      stage.querySelector(".bk-tier").textContent = t("Champion maître");
      setTimeout(() => stage.isConnected && sound.crown(), 600);   // when the crown lands
    }, 2400);
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
