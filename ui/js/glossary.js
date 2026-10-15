// Glossary page: League jargon, for beginners.
import { esc, norm, t } from "./util.js";
import { store, toast } from "./ctx.js";
import { call } from "./api.js";

const state = { q: "", cat: "all" };
let root = null;

export function renderGlossary(page) {
  root = page;
  const g = store.boot.glossary || { categories: [], terms: [] };
  page.innerHTML = `
  <div class="page-enter">
    <header class="page-head"><div>
      <div class="kicker">${esc(t("Pour les débutants"))}</div>
      <h1 class="page-title">${esc(t("Lexique"))}</h1>
    </div></header>
    <div class="lex-tools">
      <input class="input" id="l-q" placeholder="${esc(t("Chercher un terme (dive, pink, kite…)"))}" spellcheck="false" value="${esc(state.q)}">
      <button class="chip${state.cat === "all" ? " on" : ""}" data-cat="all">${esc(t("Tout"))}</button>
      ${g.categories.map((c) => `<button class="chip${state.cat === c.id ? " on" : ""}" data-cat="${esc(c.id)}">${esc(c.label)}</button>`).join("")}
      <span class="grow"></span>
      <label class="row small muted" style="gap:10px;cursor:pointer">${esc(t("Définitions au survol dans les fiches"))}
        <span class="switch"><input type="checkbox" id="l-hints" ${store.profile.glossary_hints !== false ? "checked" : ""}><i></i></span></label>
    </div>
    <div class="lex-grid" id="l-grid"></div>
  </div>`;
  const q = page.querySelector("#l-q");
  q.oninput = () => {
    state.q = q.value;
    paint();
  };
  page.querySelectorAll("[data-cat]").forEach((c) => (c.onclick = () => {
    state.cat = c.dataset.cat;
    page.querySelectorAll("[data-cat]").forEach((x) => x.classList.toggle("on", x.dataset.cat === state.cat));
    paint();
  }));
  page.querySelector("#l-hints").onchange = async (e) => {
    const r = await call("set_pref", { key: "glossary_hints", value: e.target.checked });
    if (r.error) return toast(r.error, "bad");
    store.profile = r.profile;
  };
  paint();
  setTimeout(() => q.focus(), 50);
}

function mark(text, q) {
  const safe = esc(text);
  if (!q) return safe;
  // highlights the search, ignoring accents
  const plain = text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const i = plain.indexOf(q.toLowerCase());
  if (i < 0) return safe;
  return esc(text.slice(0, i)) + "<mark>" + esc(text.slice(i, i + q.length)) + "</mark>" + esc(text.slice(i + q.length));
}

function paint() {
  const g = store.boot.glossary || { categories: [], terms: [] };
  const cats = Object.fromEntries(g.categories.map((c) => [c.id, c.label]));
  const qn = norm(state.q);
  const qplain = state.q.trim().normalize("NFD").replace(/[̀-ͯ]/g, "");
  const list = g.terms
    .filter((x) => state.cat === "all" || x.cat === state.cat)
    .filter((x) => !qn || [x.term, ...(x.aliases || []), x.def].some((y) => norm(y).includes(qn)))
    .sort((a, b) => norm(a.term).localeCompare(norm(b.term)));
  const grid = root.querySelector("#l-grid");
  if (!list.length) {
    grid.innerHTML = `<div class="empty" style="grid-column:1/-1">${esc(t("Aucun terme ne correspond."))}</div>`;
    return;
  }
  let out = "", letter = "";
  for (const term of list) {
    const L = norm(term.term)[0].toUpperCase();
    if (!qn && L !== letter) {
      letter = L;
      out += `<div class="lex-letter">${esc(L)}</div>`;
    }
    out += `<article class="lex-card" id="t-${esc(term.id)}">
      <span class="badge cat">${esc(cats[term.cat] || "")}</span>
      <h3>${mark(term.term, qplain)}</h3>
      ${term.aliases && term.aliases.length ? `<div class="al">${esc(t("aussi :"))} ${term.aliases.map((a) => mark(a, qplain)).join(", ")}</div>` : ""}
      <p class="selectable">${mark(term.def, qplain)}</p>
      ${term.ex ? `<div class="ex selectable">${esc(term.ex)}</div>` : ""}
    </article>`;
  }
  grid.innerHTML = out;
}
