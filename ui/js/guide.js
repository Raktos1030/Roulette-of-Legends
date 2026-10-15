// Guide of a champion + role combo: illustrated header, live numbers and guide tabs.
import { esc, pct, int, kilo, signed, img, roleIcon, linkify, firstSentence, ICONS, spellMeta, countUp, stagger, CHAOS_ICON, t, LANG } from "./util.js";
import { store, backdrop, toast, openMenu } from "./ctx.js";
import { call } from "./api.js";

const TABS = [
  ["summary", "Résumé"],
  ["build", "Build"],
  ["early", "Début de partie"],
  ["lane", "Phase de lane"],
  ["matchups", "Matchups"],
  ["duo", "Duo"],        // bot lane only: best partners
  ["late", "Mid & late"],
  ["kit", "Sorts"],
];
let currentTab = "summary";
let lastKey = null;   // a new guide opens on Summary; the same guide keeps its tab

const hints = () => store.profile && store.profile.glossary_hints !== false;
// abilities spotted in the text: the guide champion's (and the opponent's in matchup notes)
let SP = null;
const L = (t, used, opp = null) => linkify(t, used, hints(), SP ? { own: SP, opp } : null);
const P = (t, used) => (t ? `<p class="prose">${L(t, used)}</p>` : "");
const bullets = (list, used) =>
  list && list.length ? `<ul class="bullets">${list.map((x) => `<li class="prose">${L(x, used)}</li>`).join("")}</ul>` : "";
function card(title, body, cls = "", aside = "") {
  return `<section class="card ${cls}"><h3 class="card-title">${esc(title)}${aside ? `<span class="aside">${aside}</span>` : ""}</h3>${body}</section>`;
}
const ordinal = (n) => (LANG === "en" ? n + (n % 10 === 1 && n % 100 !== 11 ? "st" : n % 10 === 2 && n % 100 !== 12 ? "nd" : n % 10 === 3 && n % 100 !== 13 ? "rd" : "th")
  : n === 1 ? "1er" : `${n}e`);
const SUF = () => (LANG === "en" ? "%" : " %");   // suffix of the counting numbers
const toneOf = (d) => (d >= 3 ? "good2" : d >= 1.5 ? "good" : d > -1.5 ? "even" : d > -3 ? "bad" : "bad2");

// ---------------------------------------------------------------------------------------------
export function renderGuide(root, v, opts = {}) {
  store.current = v;
  SP = v.champ.key;
  backdrop(v.champ.key);
  if (v.key !== lastKey) currentTab = "summary";
  lastKey = v.key;
  if (opts.tab) currentTab = opts.tab;
  if (v.role === "jgl") TABS[3][1] = "Jungle";
  else TABS[3][1] = "Phase de lane";   // translated at display
  const tabs = TABS.filter(([id]) => (id !== "duo" || v.duo) && (id !== "matchups" || v.matchups));
  if (!tabs.some(([id]) => id === currentTab)) currentTab = "summary";
  root.innerHTML = `
    <div class="guide page-enter">
      ${heroHTML(v)}
      ${v.chaos ? chaosBand(v) : ""}
      <nav class="tabs">${tabs.map(([id, l]) => `<button class="tab${id === currentTab ? " on" : ""}" data-tab="${id}">${esc(t(l))}</button>`).join("")}</nav>
      <div class="tab-body"></div>
    </div>`;
  const body = root.querySelector(".tab-body");
  const show = (id) => {
    currentTab = id;
    root.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === id));
    body.classList.remove("tab-body");
    void body.offsetWidth;
    body.classList.add("tab-body");
    body.innerHTML = tabHTML(id, v);
    wireTab(body, v, show);
    stagger(body.querySelectorAll(".card, .note, .mrow:not(.head)"));
    countUp(body);
  };
  root.querySelectorAll(".tab").forEach((b) => (b.onclick = () => show(b.dataset.tab)));
  show(currentTab);
  wireHero(root, v);
  countUp(root.querySelector(".hero"));
}

// chaos guide: where each part of the guide comes from
function chaosBand(v) {
  const c = v.chaos;
  const from = `<a href="#" data-guide-from="${esc(c.from)}" class="t-gold">${esc(t("fiche {0}", c.from_label))}</a>`;
  return `<section class="chaos-band">
    <span class="cb-ic">${CHAOS_ICON}</span>
    <div class="cb-t">
      <div class="cb-k">${esc(t("Fiche chaos"))} · <span class="t-${c.tone}">${esc(c.level)}</span></div>
      <p>${c.real ? esc(t("Build, ordre des sorts et matchups : les vraies parties de {0} {1} ({2} parties, Émeraude+, 30 jours).", v.champ.name, v.role_label.toLowerCase(), int(c.games)))
        : esc(t("Trop peu de parties de {0} {1} pour les chiffrer ({2}) : build de la", v.champ.name, v.role_label.toLowerCase(), int(c.games))) + " " + from + esc(t(", adapté au poste."))}
        ${esc(t("Les conseils sont ceux de la"))} ${from}${esc(t(", à adapter."))}</p>
      ${c.rule ? `<p class="cb-rule">${esc(c.rule)}</p>` : ""}
    </div></section>`;
}

function heroChaosStats(v) {
  const c = v.chaos, m = v.month;
  return [
    `<div class="stat big"><div class="l">${esc(t("Niveau de chaos"))}</div><div class="v t-${c.tone}">${esc(c.level)}</div><div class="s">${esc(c.share != null ? t("{0} des parties de {1}", pct(c.share, 1), v.champ.name) : t("presque jamais joué ici"))}</div></div>`,
    m ? `<div class="stat"><div class="l">${esc(t("Victoires · 30 j"))}</div><div class="v num">${pct(m.wr, 2)}</div><div class="s">${esc(t("à ce poste"))}</div></div>` : "",
    `<div class="stat"><div class="l">${esc(t("Parties"))}</div><div class="v num">${kilo(c.games)}</div><div class="s">${esc(v.champ.name)} ${esc(v.role_label.toLowerCase())}</div></div>`,
    `<div class="stat"><div class="l">${esc(t("Conseils"))}</div><div class="v small">${esc(c.from_label)}</div><div class="s">${esc(t("fiche la plus proche"))}</div></div>`,
  ].join("");
}

function heroHTML(v) {
  const g = v.guide || {};
  const others = v.roles.filter((r) => r.role !== v.role);
  const m = v.month || {};
  const pt = v.patch;
  const u = v.ugg;
  const trend = pt ? pt.wr - m.wr : null;
  const stats = [
    `<div class="stat big"><div class="l">${esc(t("Victoires · 30 j"))}</div><div class="v num t-${v.form.tone}" data-count="${m.wr}" data-dec="2" data-suf="${SUF()}">${pct(m.wr, 2)}</div><div class="s t-${v.form.tone}">${esc(v.form.label)}</div></div>`,
    pt ? `<div class="stat" title="${esc(pt.thin ? t("Trop peu de parties sur le patch {0} pour ce champion : chiffres du patch {1}.", pt.thin, pt.label) : t("{0} parties sur ce patch", int(pt.games)))}"><div class="l">${esc(t("Patch {0}", pt.label || v.patch_name || ""))}</div><div class="v num" data-count="${pt.wr}" data-dec="2" data-suf="${SUF()}">${pct(pt.wr, 2)}</div><div class="s ${pt.thin ? "t-warn" : trend >= 0.3 ? "t-good" : trend <= -0.3 ? "t-bad" : ""}">${pt.thin ? esc(t("peu de parties sur {0}", pt.thin)) : `${trend >= 0.3 ? "▲" : trend <= -0.3 ? "▼" : "="} ${esc(t("{0} vs 30 j", signed(trend, 1)))}`}</div></div>` : "",
    u ? `<div class="stat"><div class="l">u.gg</div><div class="v num" data-count="${u.wr}" data-dec="2" data-suf="${SUF()}">${pct(u.wr, 2)}</div><div class="s">${esc(u.rank ? t("rang {0}/{1}", u.rank, u.rank_total) : t("{0} parties", int(u.games)))}</div></div>` : "",
    `<div class="stat"><div class="l">Pick</div><div class="v num" data-count="${m.pr}" data-dec="1" data-suf="${SUF()}">${pct(m.pr, 1)}</div><div class="s">Ban ${pct(m.br, 1)}</div></div>`,
    m.tier ? `<div class="stat"><div class="l">Tier</div><div class="v num">${esc(m.tier)}</div><div class="s">${m.rank ? esc(t("{0} sur {1}", ordinal(m.rank), m.rank_total)) : ""}</div></div>` : "",
    `<div class="stat"><div class="l">${esc(t("Parties"))}</div><div class="v num">${kilo(m.games)}</div><div class="s">${esc(t("30 jours · Émeraude+"))}</div></div>`,
  ].join("");
  if (v.chaos) return `
    <section class="hero chaos">
      <div class="hero-art" style="background-image:url('${img.splash(v.champ.key)}')"></div>
      <div class="hero-shade"></div>
      <div class="hero-kicker">${roleIcon(v.role, "chaos")}<span class="t-bad">${esc(v.role_long)} · CHAOS</span>
        <span class="other">${esc(t("ses vrais postes :"))} ${v.roles.map((r) => `${esc(r.label)} (${pct(r.share, 0)})`).join(", ")}</span></div>
      <h1 class="hero-name">${esc(v.champ.name.toUpperCase())}</h1>
      <p class="hero-tag">${esc(firstSentence(g.identity || ""))}</p>
      <div class="stats">${heroChaosStats(v)}</div>
    </section>`;
  return `
    <section class="hero">
      <div class="hero-art" style="background-image:url('${img.splash(v.champ.key)}')"></div>
      <div class="hero-shade"></div>
      <div class="hero-fav"><button class="fav-btn${v.fav ? " on" : ""}" title="${esc(t("Clic droit : choisir les rôles"))}">${ICONS.star}<span>${esc(v.fav ? t("Favori {0}", v.role_label) : t("Ajouter aux favoris"))}</span></button></div>
      <div class="hero-kicker">${roleIcon(v.role)}<span>${esc(v.role_long)}</span>
        <span class="other">${esc(t("{0} de ses parties", pct(v.share, 0)))}${others.length ? " · " + esc(t("aussi")) + " " + others.map((r) => `${esc(r.label)} (${pct(r.share, 0)})`).join(", ") : ""}</span></div>
      <h1 class="hero-name">${esc(v.champ.name.toUpperCase())}</h1>
      <p class="hero-tag">${esc(firstSentence(g.identity || ""))}</p>
      <div class="stats">${stats}</div>
    </section>`;
}

function wireHero(root, v) {
  root.querySelectorAll("[data-guide-from]").forEach((a) => (a.onclick = (e) => {
    e.preventDefault();
    import("./guides.js").then((m) => m.openCombo(a.dataset.guideFrom));
  }));
  const btn = root.querySelector(".fav-btn");
  if (!btn) return;
  btn.onclick = async () => {
    const r = await call("fav_toggle_combo", { key: v.champ.key, role: v.role });
    if (r.error) return toast(r.error, "bad");
    v.fav = r.on;
    btn.classList.toggle("on", r.on);
    btn.querySelector("span").textContent = r.on ? t("Favori {0}", v.role_label) : t("Ajouter aux favoris");
  };
  btn.oncontextmenu = (e) => {
    e.preventDefault();
    favMenu(e.clientX, e.clientY, v.champ.key, (prof) => {
      const on = prof.fav_champs.includes(v.champ.key) || prof.fav_combos.includes(v.key);
      v.fav = on;
      btn.classList.toggle("on", on);
      btn.querySelector("span").textContent = on ? t("Favori {0}", v.role_label) : t("Ajouter aux favoris");
    });
  };
}

// "favorite for some roles" menu (shared with the Favorites page)
export function favMenu(x, y, key, after) {
  const ch = store.boot.champions.find((c) => c.key === key);
  if (!ch) return;
  const p = store.profile;
  const roles = ch.roles;
  const isGlobal = p.fav_champs.includes(key);
  const has = (r) => isGlobal || p.fav_combos.includes(`${key}|${r}`);
  openMenu(x, y, (m) => {
    m.innerHTML = `<div class="menu-title">${esc(ch.name)}</div>
      <div class="menu-item${isGlobal ? " on" : ""}" data-a="global"><span class="ck"></span>${esc(t("Favori pour tous ses rôles"))}</div>
      <div class="menu-sep"></div>
      ${roles.map((r) => `<div class="menu-item${has(r.role) ? " on" : ""}" data-role="${r.role}"><span class="ck"></span>${roleIcon(r.role)}${esc(store.boot.roles.find((x) => x.id === r.role).label)}<span class="aside">${esc(t("{0} de ses parties", pct(r.share, 0)))}</span></div>`).join("")}`;
    m.onclick = async (e) => {
      const it = e.target.closest(".menu-item");
      if (!it) return;
      let r;
      if (it.dataset.a === "global") r = await call("fav_toggle_global", { key });
      else r = await call("fav_toggle_combo", { key, role: it.dataset.role });
      if (r.error) return toast(r.error, "bad");
      store.profile = r.profile;
      m.hidden = true;
      after && after(r.profile);
    };
  });
}

// ---------------------------------------------------------------------------------------------
function tabHTML(id, v) {
  const g = v.guide;
  if (!g && id !== "matchups" && id !== "kit" && id !== "duo") {
    return `<div class="grid g2">${card(t("Fiche"), `<p class="prose muted">${esc(t("La fiche de jeu de cette combinaison n'est pas encore rédigée. Les statistiques, les matchups et les sorts restent consultables dans leurs onglets."))}</p>`)}</div>`;
  }
  const used = new Set();
  switch (id) {
    case "summary": return summaryHTML(v, g, used);
    case "early": return earlyHTML(v, g, used);
    case "lane": return laneHTML(v, g, used);
    case "matchups": return matchupsHTML(v, g, used);
    case "duo": return duoHTML(v);
    case "late": return lateHTML(v, g, used);
    case "kit": return kitHTML(v);
    case "build": return buildHTML(v);
  }
  return "";
}

function formCard(v) {
  const m = v.month || {};
  const ref = v.form.ref || 50;
  const w = (x) => Math.max(3, Math.min(100, ((x - 44) / 14) * 100));
  const bar = (label, val, refv, tone) =>
    val == null ? "" : `<div class="bar-row"><span class="lab">${label}</span><div class="bar t-${tone}"><i style="width:${w(val)}%"></i><span class="ref" style="left:${w(refv)}%"></span></div><span class="val">${pct(val, 2)}</span></div>`;
  const pt = v.patch, u = v.ugg;
  return card(
    t("Forme actuelle"),
    `<div class="form-big"><span class="v" data-count="${m.wr}" data-dec="2" data-suf="${SUF()}">${pct(m.wr, 2)}</span><span class="pill t-${v.form.tone}">${esc(v.form.label)}</span></div>
     <div class="bars">
       ${bar(esc(t("30 jours · lolalytics")), m.wr, ref, v.form.tone)}
       ${pt ? bar(esc(t("Patch {0}", pt.label || v.patch_name || "")), pt.wr, ref, toneOf(pt.wr - ref)) : ""}
       ${u ? bar(esc(t("u.gg · 2 patchs")), u.wr, 50, toneOf(u.wr - 50)) : ""}
     </div>`,
    "teal",
    esc(t("en direct"))
  );
}

function mxCard(v) {
  const m = v.matchups;
  const item = (e) => `<div class="mx-item"><img src="${img.icon(e.key)}" alt=""><span>${esc(e.name)}</span><span class="d t-${e.tone}">${signed(e.delta)}</span></div>`;
  return card(
    t("Matchups express"),
    `<div class="mx"><div><h4 class="t-good">${esc(t("Tu les bats"))}</h4>${m.good.slice(0, 3).map(item).join("")}</div>
       <div><h4 class="t-bad">${esc(t("Ils te battent"))}</h4>${m.bad.slice(0, 3).map(item).join("")}</div></div>
     <p class="more-link"><a href="#" data-goto="matchups" class="t-gold">${esc(t("Tous les matchups →"))}</a></p>`
  );
}

function summaryHTML(v, g, used) {
  const spikes = (g.power_spikes || []).map((s) => {
    const sep = s.indexOf(" : ") > 0 ? " : " : ": ";   // "Niveau 6 : ..." or "Level 6: ..."
    const i = s.indexOf(sep);
    return i > 0 ? `<li class="prose"><b>${esc(s.slice(0, i))}</b> — ${L(s.slice(i + sep.length), used)}</li>` : `<li class="prose">${L(s, used)}</li>`;
  });
  return `<div class="grid g2">
    ${card(t("Identité"), P(g.identity, used))}
    ${card(t("Style de jeu"), P(g.playstyle, used))}
    ${v.month ? formCard(v) : v.chaos ? card(t("Niveau de chaos"), `<div class="form-big"><span class="v t-${v.chaos.tone}">${esc(v.chaos.level)}</span></div><p class="prose small muted">${v.chaos.share != null ? esc(t("{0} des parties de {1} se jouent {2}.", pct(v.chaos.share, 1), v.champ.name, v.role_label.toLowerCase())) : ""}</p>`, "orange") : ""}
    ${card(t("Condition de victoire"), `<p class="quote">${esc(g.win_condition.replace(/^Pour gagner cette partie, tu veux /, "Tu veux ").replace(/^To win this game, you want to /, "You want to "))}</p>`, "gold")}
    ${card(t("Power spikes"), `<ul class="timeline">${spikes.join("")}</ul>`)}
    ${v.matchups ? mxCard(v) : ""}
    ${card(t("À retenir"), `<p class="quote">${esc(g.final_tip)}</p>`, "gold span-all")}
  </div>`;
}

// Aphelios doesn't level his abilities: each point picks a stat from his HUD menu (Q, W, E keys)
const APH_STATS = { Q: "Dégâts d'attaque", W: "Vitesse d'attaque", E: "Létalité", R: "Ultime" };   // translated at display
const APH_SHORT = { Q: "AD", W: "VA", E: "Léta", R: "R" };
const isAph = (v) => v.champ && v.champ.key === "Aphelios";
const aphNote = () => `<p class="prose small" style="color:var(--text-2);margin-top:10px">${esc(t("Aphelios n'apprend pas ses sorts : à chaque point, il choisit dans son menu du HUD entre dégâts d'attaque (touche Q), vitesse d'attaque (W) et létalité (E). Ses armes et son ultime arrivent tout seuls."))}</p>`;

// evolving abilities: most played order (u.gg, Emerald+) and what triggers each evolution (game rules)
const EVOLVE_HOW = {   // translated at display
  Khazix: "Un point d'évolution à chaque rang de l'ultime (niveaux 6, 11 et 16), à dépenser avant de monter un autre sort. Le 4e point ne s'obtient qu'en éliminant Rengar.",
  Viktor: "Chaque amélioration coûte 100 fragments Hextech : 1 par sbire ou monstre, 10 par sbire de siège ou monstre épique, 20 par élimination de champion. L'ultime ne s'améliore qu'une fois les trois autres sorts améliorés.",
  Kaisa: "Les évolutions se débloquent toutes seules quand tes objets donnent assez de statistiques : c'est ton build qui fixe l'ordre.",
};
function evolveCard(v) {
  const ev = v.evolve;
  if (!ev || !ev.order) return "";
  const key = v.champ.key;
  const order = key === "Kaisa" ? ev.order.replace("R", "") : ev.order;   // Kai'Sa's ultimate doesn't evolve
  const steps = [...order].map((k, i) => `<span class="evo-step${key === "Khazix" && i > 2 ? " dim" : ""}">
      <img src="${img.spell(key, k)}" alt=""><b>${k}</b><small>${esc((v.kit[k] || {}).name || "")}${key === "Khazix" ? `<em>${esc([t("niveau {0}", 6), t("niveau {0}", 11), t("niveau {0}", 16), "Rengar"][i] || "")}</em>` : ""}</small></span>`).join('<span class="barrow">›</span>');
  return card(key === "Viktor" ? t("Ordre des améliorations") : t("Ordre des évolutions"),
    `<div class="evo">${steps}</div><p class="prose small" style="color:var(--text-2);margin-top:10px">${esc(t(EVOLVE_HOW[key] || ""))}</p>`,
    "", ev.games ? esc(t("{0} parties (u.gg)", int(ev.games))) : "");
}

function skillCard(v) {
  const sk = v.skills || {};
  const order = sk.order15 || "";
  const aph = isAph(v);
  let grid = `<div class="h"></div>${Array.from({ length: 15 }, (_, i) => `<div class="h">${i + 1}</div>`).join("")}`;
  for (const k of ["Q", "W", "E", "R"]) {
    grid += aph ? `<div class="k aph" title="${esc(t(APH_STATS[k]))}">${esc(t(APH_SHORT[k]))}</div>` : `<div class="k">${k}</div>`;
    for (let i = 0; i < 15; i++) grid += `<div class="c${order[i] === k ? " on" + (k === "R" ? " r" : "") : ""}">${order[i] === k ? k : ""}</div>`;
  }
  const paths = (sk.paths || []).map((p) => `<span class="path"><span class="keys">${[...p.path].map((c) => `<i>${c}</i>`).join("")}</span><span class="num t-gold">${pct(p.pct, 0)}</span></span>`).join("");
  return card(
    aph ? t("Points d'Aphelios") : t("Ordre des sorts"),
    `${order ? `<div class="skill-grid">${grid}</div>` : ""}
     ${paths ? `<div class="paths">${paths}</div>` : ""}${aph ? aphNote() : ""}`,
    "",
    esc(t("en direct"))
  ) + evolveCard(v);
}

function earlyHTML(v, g, used) {
  const sk = v.skills || {};
  const p0 = (sk.paths || [])[0];
  const lv = (n, text, extra = "") => `<section class="card lvl"><div class="lv"><span>${esc(t("Niv."))}</span><b>${n}</b></div><div>${P(text, used)}${extra}</div></section>`;
  const ult = v.kit && v.kit.R ? `<div class="live-note" style="color:var(--gold)">${esc(t("Ultime : {0}", v.kit.R.name))}</div>` : "";
  return `<div class="grid g2">
    ${card(t("Early game"), P(g.early_game, used), "span-all")}
    <div class="levels span-all">
      ${lv(1, g.level_1, p0 ? `<div class="live-note">${esc(t("En ce moment : départ {0} dans {1} des parties", [...p0.path.slice(0, 3)].join(" → "), pct(p0.pct, 0)))}</div>` : "")}
      ${lv(2, g.level_2)}
      ${lv(3, g.level_3)}
      ${lv(6, g.level_6, ult)}
    </div>
    ${skillCard(v)}
    ${card(t("Power spikes"), bullets(g.power_spikes, used))}
  </div>`;
}

function laneHTML(v, g, used) {
  const jungle = v.role === "jgl";
  const hard = ((v.matchups && v.matchups.bad) || []).slice(0, 3);
  const live = hard.length
    ? `<div class="live-note">${esc(t("En ce moment, tes matchups les plus durs :"))} ${hard.map((e) => `${esc(e.name)} (${signed(e.delta)})`).join(", ")}</div>`
    : "";
  return `<div class="grid g2">
    ${card(jungle ? t("Plan de jungle") : t("Plan de lane"), P(jungle ? g.jungle_plan : g.lane_plan, used))}
    ${card(jungle ? t("Escarmouches, ganks et duels") : t("Trades et conditions d'engage"), P(g.trading, used))}
    ${card(t("À surveiller"), bullets(g.threats, used) + live, "orange")}
    ${card(t("Erreurs à éviter"), bullets(g.mistakes, used))}
  </div>`;
}

function mrow(e) {
  const w = Math.min(50, (Math.abs(e.delta) / 6) * 50);
  const cls = e.delta >= 0 ? "p" : "n";
  const chk = e.check === "ok" ? "t-good" : e.check === "contradiction" ? "t-warn" : "t-muted";
  return `<div class="mrow">
    <div class="who"><img src="${img.icon(e.key)}" alt=""><div><div class="nm">${esc(e.name)}</div><div class="fr">${e.freq_rank ? esc(t("n°{0} des adversaires", e.freq_rank)) : ""}</div></div></div>
    <div class="wrbar"><span class="wr num t-${e.tone}">${pct(e.wr, 1)}</span><span class="dbar"><i class="${cls}" style="width:${w}%"></i></span><span class="dl t-${e.tone}">${signed(e.delta)}</span></div>
    <div class="cell num">${int(e.n)}<small>${esc(t("parties"))}</small></div>
    <div class="cell">${e.ugg_wr != null ? `<span class="num">${pct(e.ugg_wr, 1)}</span><small>${esc(t("{0} parties u.gg", int(e.ugg_n)))}</small>` : `<span class="t-muted">—</span>`}</div>
    <div class="cell num c-gold">${e.gd15 != null ? signed(e.gd15, 0) : "—"}<small>${esc(t("or à 15 min"))}</small></div>
    <div class="cell"><span class="pill ${chk}">${esc(e.check_label || "")}</span>${e.rel === "limited" ? `<small class="t-warn">${esc(t("échantillon limité"))}</small>` : ""}</div>
  </div>`;
}

function mtable(title, rows, tone, clear, warn, base = null) {
  // the delta is against the guide champion's average (all players, Emerald+), not the player's own
  const head = `<div class="mrow head"><div>${esc(t("Adversaire"))}</div><div>${esc(t("Victoires · écart à sa moyenne"))}${base != null ? ` (${pct(base, 1)})` : ""}</div><div>${esc(t("Parties"))}</div><div>u.gg</div><div class="c-gold">${esc(t("Or @15"))}</div><div>${esc(t("Recoupement"))}</div></div>`;
  return card(
    t(title),
    `${!clear ? `<p class="warn-line">${esc(t(warn))}</p>` : ""}${rows.length ? `<div class="mtable">${head}${rows.map(mrow).join("")}</div>` : `<p class="muted">${esc(t("Aucun matchup ne ressort avec un échantillon suffisant."))}</p>`}`,
    `span-all ${tone}`
  );
}

function matchupsHTML(v, g, used) {
  const m = v.matchups;
  const who = v.role === "jgl" ? "le jungler adverse" : "ton adversaire direct de lane";
  const notes = (v.notes || []).map((n) => {
    const e = n.live;
    const sub = esc(e ? (e.freq_rank ? t("n°{0} des adversaires", e.freq_rank) + " · " : "") + t("{0} parties", int(e.n)) : t("pas assez de parties pour chiffrer"));
    return `<div class="note">
      <div class="note-head">${n.key ? `<img src="${img.icon(n.key)}" alt="">` : ""}<div><div class="nm">${esc(n.name)}</div><div class="sub">${sub}</div></div>
        ${e ? `<span class="pill t-${e.tone}" title="${esc(t("{0} de victoires, {1} par rapport à sa moyenne", pct(e.wr, 1), signed(e.delta)))}">${esc(e.verdict)} · ${signed(e.delta)}</span>` : `<span class="pill t-muted">${esc(t("non chiffré"))}</span>`}</div>
      <p class="prose">${L(n.text, used, n.key)}</p></div>`;
  });
  return `<div class="grid">
    ${notes.length ? card(t("Conseils par adversaire"), `<div class="notes">${notes.join("")}</div>`, "span-all") : ""}
    ${mtable("Matchups favorables", m.good, "green", m.good_clear, "Aucun matchup n'est nettement favorable : voici les meilleurs.", m.base)}
    ${mtable("Matchups difficiles", m.bad, "orange", m.bad_clear, "Aucun matchup n'est nettement défavorable : voici les moins bons.", m.base)}
    ${mtable("Adversaires les plus fréquents", m.frequent, "", true, "", m.base)}
    ${m.n_opps < 10 ? `<p class="warn-line">${esc(t("Attention : seulement {0} adversaires ont assez de parties pour être analysés. Les tendances sont à prendre avec prudence.", m.n_opps))}</p>` : ""}
    <div class="span-all"><button class="btn sm" data-all>${esc(t("Voir les {0} adversaires", m.all.length))}</button><div data-allbox></div></div>
  </div>`;
}

// Bot lane: partners this champion wins with (supports of an ADC, ADCs of a support)
function duoHTML(v) {
  const du = v.duo;
  const who = du.partner === "sup" ? "supports" : "ADC";
  const me = v.champ;
  const go = (e) => (e.combo ? `data-combo="${esc(e.combo)}" title="${esc(t("Voir la fiche {0} {1}", e.name, du.partner_label))}"` : "disabled");
  const big = (e, i) => `
    <button class="duo-card${i === 0 ? " best" : ""}" ${go(e)} style="--art:url('${img.tall(e.key)}')">
      ${i === 0 ? `<span class="duo-ribbon">${esc(t("Duo idéal"))}</span>` : ""}
      <span class="duo-pair"><img src="${img.icon(me.key)}" alt=""><b>+</b></span>
      <span class="duo-foot">
        <span class="duo-name">${esc(e.name)}</span>
        <span class="duo-wr t-${toneOf(e.delta)}">${pct(e.wr, 1)}</span>
        <span class="duo-sub">${esc(t("{0} vs sa moyenne · {1} parties", signed(e.delta, 1), kilo(e.n)))}</span>
      </span>
    </button>`;
  const mini = (e) => `
    <button class="duo-mini" ${go(e)}>
      <img src="${img.icon(e.key)}" alt="">
      <span class="dm-n">${esc(e.name)}<small>${esc(t("{0} parties", kilo(e.n)))}</small></span>
      <span class="dm-w t-${toneOf(e.delta)}">${pct(e.wr, 1)}<small>${signed(e.delta, 1)}</small></span>
    </button>`;
  return `<div class="grid">
    <section class="card span-all duo-hero">
      <h3 class="card-title">${esc(who === "ADC" ? t("Avec quels ADC {0} gagne", me.name) : t("Avec quels supports {0} gagne", me.name))}<span class="aside">${esc(t("victoires du duo · moyenne de {0} {1}", me.name, pct(du.base, 1)))}</span></h3>
      <div class="duo-row">${du.good.slice(0, 5).map(big).join("")}</div>
    </section>
    <div class="grid g2 span-all">
      ${du.bad.length ? card(t("Duos à éviter"), `<div class="duo-minis">${du.bad.map(mini).join("")}</div>`, "orange") : ""}
      ${card(who === "ADC" ? t("ADC les plus fréquents") : t("Supports les plus fréquents"), `<div class="duo-minis">${du.frequent.map(mini).join("")}</div>`)}
    </div>
    <p class="src-line span-all">${esc(t("lolalytics · 30 jours · Émeraude+ · {0} {1} avec au moins {2} parties en duo · classement lissé (un duo sur peu de parties ne passe pas devant un duo éprouvé)", du.n_partners, who, int(du.min_n)))}</p>
  </div>`;
}

function lateHTML(v, g, used) {
  return `<div class="grid g2">
    ${card(t("Mid game"), P(g.mid_game, used))}
    ${card(t("Late game"), P(g.late_game, used))}
    ${card(t("Si tu es devant"), P(g.ahead, used), "green")}
    ${card(t("Si tu es derrière"), P(g.behind, used), "orange")}
    ${card(t("À retenir"), `<p class="quote">${esc(g.final_tip)}</p>`, "gold span-all")}
  </div>`;
}

function kitHTML(v) {
  const kit = v.kit || {};
  const spells = ["P", "Q", "W", "E", "R"].filter((k) => kit[k]).map((k) => `
    <section class="card spell"><div class="sk"><img src="${img.spell(v.champ.key, k)}" alt="" onerror="this.replaceWith(document.createTextNode('${k}'))"></div>
      <div><div class="sn"><small>${k === "P" ? esc(t("Passif")) : k}</small>${esc(kit[k].name)}</div>${spellMeta(kit[k]) ? `<div class="smeta">${esc(spellMeta(kit[k]))}</div>` : ""}<p class="prose small" style="color:var(--text-2)">${esc(kit[k].desc)}</p></div></section>`);
  return `<div class="grid"><div class="spells">${spells.join("")}</div>${skillCard(v)}</div>`;
}

// ---------------------------------------------------------------------------------------------
// Build tab: recommended build and variants (u.gg), runes, summoner spells, items, skill order
const rate = (x) => (x && x.games ? esc(t("{0} · {1} parties", pct(x.wr, 2), int(x.games))) : "");
const itemImg = (it, cls = "") =>
  `<img class="bi ${cls}" src="/img/items/${it.id}.png" alt="" title="${esc(it.name || "")}${it.gold ? ` · ${esc(t("{0} PO", it.gold))}` : ""}" onerror="this.classList.add('missing')">`;

function buildHTML(v) {
  const list = v.builds || [];
  if (!list.length) return `<div class="grid">${card(t("Build"), `<p class="prose muted">${esc(t("Pas encore de build pour cette fiche : il arrive avec la prochaine mise à jour des statistiques."))}</p>`)}</div>`;
  const cur = list.find((b) => b.id === v.build_pick) || list[0];
  const tabs = `<div class="bvars">
      <button class="bimp" data-import="${esc(cur.id)}" title="${esc(t("Envoie cette variante dans le client LoL : page de runes et set d'objets (sorts d'invocateur pendant la sélection)"))}">${IMPORT_SVG}${esc(t("Importer dans LoL"))}</button>
      ${list.map((b) => `
        <button class="bvar${b.id === cur.id ? " on" : ""}" data-bvar="${esc(b.id)}">
          <span class="bv-l">${esc(t(b.label))}</span>
          <span class="bv-ic"><img src="/img/runes/${b.runes.keystone}.png" alt="">${b.core.list[0] ? itemImg(b.core.list[0]) : ""}</span>
          ${b.games ? `<span class="bv-s">${pct(b.wr, 1)} · ${kilo(b.games)}</span>` : ""}
        </button>`).join("")}
      </div>`;
  const r = cur.runes;
  const rune = (x, small = false) => `<img class="rn${x.on ? " on" : ""}${small ? " sm" : ""}" src="/img/runes/${x.id}.png" alt="" title="${esc(x.name)}" onerror="this.classList.add('missing')">`;
  const tree = (t, rows, sec = false) => `
    <div class="rtree">
      <div class="rt-head"><img src="/img/runes/${t.id}.png" alt="">${esc(t.name)}</div>
      ${rows.map((row, i) => `<div class="rrow${!sec && i === 0 ? " key" : ""}">${row.map((x) => rune(x)).join("")}</div>`).join("")}
    </div>`;
  const shards = `<div class="rtree shards"><div class="rt-head">${esc(t("Fragments"))}</div>${r.shards.map((row) => `<div class="rrow">${row.map((x) => rune(x, true)).join("")}</div>`).join("")}</div>`;
  const runesCard = card(t("Runes"), `<div class="runes">${tree(r.pri, r.tree_pri)}${tree(r.sec, r.tree_sec, true)}${shards}</div>`, "bcard", rate(r));
  const sums = card(t("Sorts d'invocateur"), `<div class="bsums">${cur.sums.list.map((x) => `<span><img src="/img/sums/${x.id}.png" alt="">${esc(x.name)}</span>`).join("")}</div>`, "bcard", rate(cur.sums));
  const items = card(t("Objets"), `
    <div class="bblock"><div class="bb-l">${esc(t("Départ"))}</div><div class="bb-i">${cur.start.list.map((it) => `<span class="bslot">${itemImg(it)}${it.count > 1 ? `<b>×${it.count}</b>` : ""}</span>`).join("")}</div><div class="bb-r">${rate(cur.start)}</div></div>
    <div class="bblock core"><div class="bb-l">${esc(t("Build principal"))}</div><div class="bb-i">${cur.core.list.map((it) => `<span class="bslot">${itemImg(it)}</span>`).join('<span class="barrow">›</span>')}</div><div class="bb-r">${rate(cur.core)}</div></div>
    <div class="bopts">${[t("4e objet"), t("5e objet"), t("6e objet")].map((l, i) => (cur.opts[i] || []).length ? `
      <div class="bopt"><div class="bb-l">${esc(l)}</div>${cur.opts[i].map((it) => `<div class="bo">${itemImg(it)}<span>${it.wr != null ? `<b>${pct(it.wr, 1)}</b>${esc(t("{0} parties", int(it.games)))}` : esc(it.name)}</span></div>`).join("")}</div>` : "").join("")}</div>`, "bcard wide");
  const skills = skillGrid(v, cur.skills);
  // champ select or game in progress with this guide: items to plan against the enemy comp
  const lv = store.live;
  const ctr = lv && lv.combo === v.key && (lv.counters || []).length ? card(t("Contre leur compo"), lv.counters.map((o) =>
    `<div class="bblock"><div class="bb-l">${esc(o.label)}</div><div class="bb-i">${itemImg(o)}</div><div class="bb-r">${esc(o.name)} · ${esc(o.why)}${o.in_core ? " · " + esc(t("déjà dans le build")) : ""}</div></div>`).join(""),
    "bcard wide") : "";
  const note = v.chaos ? `<p class="chaos-note">${CHAOS_ICON}${esc(v.chaos.real ? t("Build réel de {0} {1} ({2} parties).", v.champ.name, v.role_label.toLowerCase(), int(v.chaos.games))
    : v.role === "jgl" ? t("Build de la fiche {0}, adapté au poste : Châtiment et compagnon de jungle. Ses chiffres ne valent plus ici.", v.chaos.from_label)
    : v.role === "sup" ? t("Build de la fiche {0}, adapté au poste : objet de support. Ses chiffres ne valent plus ici.", v.chaos.from_label)
    : t("Build de la fiche {0}, adapté au poste. Ses chiffres ne valent plus ici.", v.chaos.from_label))}</p>` : "";
  return `<div class="grid">${note}${tabs}<div class="bgrid">${runesCard}${sums}${items}${ctr}${skills}</div></div>`;
}

const IMPORT_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5v11"/><path d="m7.5 10 4.5 4.5 4.5-4.5"/><path d="M4.5 15.5v3a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-3"/></svg>`;

async function importBuild(v, variant, btn, replace = false) {
  btn.disabled = true;
  btn.classList.add("busy");
  const r = await call("import_build", { key: v.key, variant, replace });
  btn.disabled = false;
  btn.classList.remove("busy");
  if (r.error) return toast(r.error, "warn");
  const ok = r.results.filter((x) => x.state === "ok").map((x) => x.label.toLowerCase());
  const full = r.results.find((x) => x.id === "runes" && x.state === "full");
  const bad = r.results.filter((x) => x.state === "error");
  if (ok.length) toast(t("{0} : {1} importés dans le client.", r.label, ok.join(", ")) + (r.in_cs ? "" : " " + t("Les sorts d'invocateur s'importent pendant la sélection.")), "teal");
  if (bad.length) toast(bad.map((x) => t("{0} : {1}", x.label, x.text)).join(" · "), "bad");
  if (full) {
    const { confirmBox } = await import("./ctx.js");
    if (await confirmBox(t("Plus de place pour une nouvelle page de runes. Remplacer la page sélectionnée dans le client par celle-ci ?"), t("Remplacer")))
      importBuild(v, variant, btn, true);
  } else if (ok.length) {
    btn.classList.add("done");
    setTimeout(() => btn.classList.remove("done"), 1800);
  }
}

function skillGrid(v, sk) {
  if (!sk || !sk.path) return "";
  const path = sk.path.slice(0, 18);
  const aph = isAph(v);
  const rows = ["Q", "W", "E", "R"].map((k) => `
    <div class="sgrow">${aph ? `<span class="aph-stat" title="${esc(t(APH_STATS[k]))}">${esc(t(APH_SHORT[k]))}</span>` : `<img src="${img.spell(v.champ.key, k)}" alt="" title="${esc((v.kit[k] || {}).name || k)}">`}<b>${k}</b>
      ${[...path].map((c, i) => `<i class="${c === k ? "on" : ""}">${c === k ? i + 1 : ""}</i>`).join("")}</div>`).join("");
  const prio = (sk.prio || "").split("").map((k) => aph ? `<b>${esc(t(APH_STATS[k] || k))}</b>` : `<img src="${img.spell(v.champ.key, k)}" alt="" title="${esc((v.kit[k] || {}).name || k)}"><b>${k}</b>`).join('<span class="barrow">›</span>');
  return card(aph ? t("Points d'Aphelios") : t("Ordre des sorts"), `${prio ? `<div class="sgprio">${esc(t("Priorité"))} ${prio}</div>` : ""}<div class="sgrid">${rows}</div>${aph ? aphNote() : ""}`, "bcard wide", rate(sk));
}

function wireTab(body, v, show) {
  const ib = body.querySelector("[data-import]");
  if (ib) ib.onclick = () => importBuild(v, ib.dataset.import, ib);
  body.querySelectorAll("[data-combo]").forEach((b) => (b.onclick = () => import("./guides.js").then((m) => m.openCombo(b.dataset.combo))));
  body.querySelectorAll("[data-bvar]").forEach((b) => (b.onclick = async () => {
    v.build_pick = b.dataset.bvar;
    show("build");
    const r = await call("build_pick", { key: v.key, variant: b.dataset.bvar });
    if (r.error) toast(r.error, "bad");
    else if (r.reimport) toast(t("Build réimporté dans le client (runes, sorts, set d'objets)."), "teal");
  }));
  body.querySelectorAll("[data-goto]").forEach((a) => (a.onclick = (e) => {
    e.preventDefault();
    show(a.dataset.goto);
    document.getElementById("main").scrollTo({ top: body.closest(".guide").offsetTop - 10 });
  }));
  const allBtn = body.querySelector("[data-all]");
  if (allBtn) {
    allBtn.onclick = () => {
      const box = body.querySelector("[data-allbox]");
      if (box.innerHTML) {
        box.innerHTML = "";
        allBtn.textContent = t("Voir les {0} adversaires", v.matchups.all.length);
        return;
      }
      allBtn.textContent = t("Masquer");
      box.innerHTML = `<div style="margin-top:12px">${mtable("Tous les adversaires mesurés", v.matchups.all, "", true, "", v.matchups.base)}</div>`;
    };
  }
}
