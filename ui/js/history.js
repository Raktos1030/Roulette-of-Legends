// History page: every game (with or without the roulette) and roll: summary, LP chart, list, game details.
// Games played without the app are caught up from the client's match history.
import { esc, signed, img, roleIcon, ROLES, ROLE_LABEL, stagger, t, LANG } from "./util.js";
import { on, toast, openModal, confirmBox, backdrop, isLite, openUgg, champAttr, setModalBack } from "./ctx.js";
import { call } from "./api.js";
import { openCombo } from "./guides.js";

const filt = { kind: "all", played_only: false, role: "all", champ: "all", mode: "all", queue: "all" };
const KINDS = [["all", "Toutes"], ["roulette", "Roulette"], ["free", "Hors roulette"]];
let root = null, unsub = null, openGame = null;

export function renderHistory(page) {
  root = page;
  page.innerHTML = `
  <div class="page-enter">
    <header class="page-head"><div>
      <div class="kicker">${esc(t("Tes parties et tes tirages"))}</div>
      <h1 class="page-title">${esc(t("Historique"))}</h1>
    </div></header>
    <div id="h-sum"></div>
    <div id="h-chart"></div>
    <div class="hist-filters" id="h-filt"></div>
    <div id="h-list"></div>
  </div>`;
  paintFilters();
  load();
  unsub && unsub();
  unsub = on((type, data) => {
    if (!root || !document.body.contains(root)) return;
    if (type === "recent") load();
    if (type === "game" && openGame) openGame.reload(data && data.game_id);
  });
}

async function load() {
  const r = await call("history", filt);
  if (r.error) return toast(r.error, "bad");
  paintSummary(r.summary);
  paintChart(r.chart);
  paintChampFilter(r.champs);
  paintQueueFilter(r.queues || []);
  paintList(r.rows);
}

function paintSummary(s) {
  const lp = s.lp_games ? s.lp_total : null;
  let lpSub = s.lp_games ? (s.lp_games > 1 ? t("sur {0} parties classées", s.lp_games) : t("sur {0} partie classée", s.lp_games)) : t("mesurés avec LoL ouvert");
  if (s.protected) lpSub += " · " + t("{0} sans perte", s.protected);
  const lpCard = ["LP", lp == null ? "—" : `${signed(lp, 0)} LP`, lp > 0 ? "t-good" : lp < 0 ? "t-bad" : "", lpSub];
  const sp = LANG === "en" ? "" : " ";
  const counted = s.games - s.games_protected;
  const rate = counted > 0 ? Math.round((100 * s.games_wins) / counted) : null;
  const games = [
    [t("Parties jouées"), s.games, "", filt.kind === "all" && s.roll_games ? t("dont {0} avec la roulette", s.roll_games) : ""],
    [t("Victoires"), `${s.games_wins}${rate != null ? ` · ${rate}${sp}%` : ""}`, "t-good", s.games_protected ? t("hors défaites sans perte") : ""],
    [t("KDA moyen"), s.kda ? s.kda.map((x) => (LANG === "en" ? String(x) : String(x).replace(".", ","))).join(" / ") : "—", "", ""],
    lpCard,
  ];
  if (filt.kind === "all") games.push([t("Tirages"), s.total, "", s.cancelled ? (s.cancelled > 1 ? t("{0} annulés", s.cancelled) : t("{0} annulé", s.cancelled)) : ""]);
  const cards = filt.kind !== "roulette" ? games : [
    [t("Tirages"), s.total, "", ""],
    [t("Parties jouées"), s.played, "", ""],
    [t("Champion tiré joué"), s.respected, "", s.played ? t("{0} des parties", `${Math.round((100 * s.respected) / s.played)}${sp}%`) : ""],
    [t("Victoires"), `${s.respected_wins}${s.rate != null ? ` · ${s.rate}${sp}%` : ""}`, "t-good", t("avec le champion tiré") + (s.respected_protected ? t(", hors défaites sans perte") : "")],
    lpCard,
    [t("Annulés"), s.cancelled, "t-warn", ""],
  ];
  root.querySelector("#h-sum").innerHTML = `<div class="sum-cards">${cards.map(([l, v, t, sub]) =>
    `<div class="sum"><div class="l">${l}</div><div class="v ${t}">${v}</div><div class="s">${esc(sub)}</div></div>`).join("")}</div>`;
}

function divisionOf(v) {
  const tiers = ["Fer", "Bronze", "Argent", "Or", "Platine", "Émeraude", "Diamant"].map((x) => t(x));
  if (v >= tiers.length * 400) return t("Maître+");
  return `${tiers[Math.floor(Math.max(0, v) / 400)]} ${["IV", "III", "II", "I"][Math.floor((Math.max(0, v) % 400) / 100)]}`;
}

function paintChart(pts) {
  const box = root.querySelector("#h-chart");
  if (!pts || pts.length < 2) {
    box.innerHTML = "";
    return;
  }
  const W = Math.max(600, (box.clientWidth || root.clientWidth) - 46), H = 200, L = 96, R = 20, T = 20, B = 18;
  const vals = pts.map((p) => p.v);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 40) {
    const mid = (hi + lo) / 2;
    lo = mid - 20;
    hi = mid + 20;
  }
  lo -= 6; hi += 6;
  const x = (i) => L + (i * (W - L - R)) / (pts.length - 1);
  const y = (v) => H - B - ((v - lo) / (hi - lo)) * (H - T - B);
  let grid = "";
  for (let b = Math.floor(lo / 100 + 1) * 100; b < hi; b += 100) {
    grid += `<line class="gl" x1="${L}" x2="${W - R}" y1="${y(b)}" y2="${y(b)}"/><text class="gt" x="${L - 10}" y="${y(b) + 4}" text-anchor="end">${divisionOf(b)}</text>`;
  }
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(pts.length - 1)},${H - B} L${x(0)},${H - B} Z`;
  const col = { win: "var(--green)", loss: "var(--red)", protected: "var(--shield)", start: "var(--gold-pale)", neutral: "var(--gold-hi)" };
  const dots = pts.map((p, i) => `<circle class="pt" style="animation-delay:${(0.3 + (1.1 * i) / Math.max(1, pts.length - 1)).toFixed(2)}s" cx="${x(i)}" cy="${y(p.v)}" r="5" fill="${col[p.kind] || "var(--gold-hi)"}"><title>${esc(p.label)}${p.delta != null ? ` (${signed(p.delta, 0)} LP)` : ""}${p.date ? " · " + esc(p.date) : ""}</title></circle>`).join("");
  const last = pts[pts.length - 1];
  box.innerHTML = `<section class="card" style="margin-top:16px">
    <h3 class="card-title">${esc(t("Courbe des LP · Solo/duo"))}<span class="aside"><b class="t-gold">${esc(last.label)}</b></span></h3>
    <div class="chart"><svg viewBox="0 0 ${W} ${H}">
      <defs><linearGradient id="lpgrad" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="rgba(200,170,110,.35)"/><stop offset="1" stop-color="rgba(200,170,110,0)"/></linearGradient></defs>
      ${grid}<path class="ar" d="${area}"/><path class="ln" d="${line}"/>${dots}</svg></div></section>`;
  const ln = box.querySelector(".ln");
  if (ln && ln.getTotalLength) {
    const L = ln.getTotalLength();
    ln.style.strokeDasharray = L;
    ln.style.strokeDashoffset = L;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      ln.style.transition = "stroke-dashoffset 1.4s cubic-bezier(.2,.8,.2,1)";
      ln.style.strokeDashoffset = 0;
    }));
  }
}

function paintFilters() {
  const box = root.querySelector("#h-filt");
  box.innerHTML = `
    ${KINDS.map(([k, l]) => `<button class="chip${filt.kind === k ? " on" : ""}" data-kind="${k}">${esc(t(l))}</button>`).join("")}
    <span style="width:8px"></span>
    <button class="chip${filt.played_only ? " on" : ""}" data-k="played"><span class="ck"></span>${esc(t("Parties jouées seulement"))}</button>
    <span style="width:8px"></span>
    ${["all", ...ROLES].map((r) => `<button class="chip${filt.role === r ? " on" : ""}" data-role="${r}">${r === "all" ? esc(t("Tous les rôles")) : roleIcon(r) + esc(ROLE_LABEL[r])}</button>`).join("")}
    <select class="input" id="h-champ"><option value="all">${esc(t("Tous les champions"))}</option></select>
    <select class="input" id="h-queue"><option value="all">${esc(t("Tous les modes"))}</option></select>
    <select class="input" id="h-mode">
      <option value="all">${esc(t("Tous les tirages"))}</option><option value="both">${esc(t("Rôle + champion"))}</option><option value="role">${esc(t("Rôle aléatoire"))}</option><option value="champ">${esc(t("Champion aléatoire"))}</option>
    </select>
    <span class="grow"></span>
    <button class="btn sm" id="h-refresh">${esc(t("Actualiser depuis LoL"))}</button>
    <button class="btn sm danger" id="h-clear">${esc(t("Effacer"))}</button>`;
  box.querySelectorAll("[data-kind]").forEach((c) => (c.onclick = () => {
    filt.kind = c.dataset.kind;
    if (filt.kind === "free") filt.mode = "all";
    paintFilters();
    load();
  }));
  box.querySelector('[data-k="played"]').onclick = () => {
    filt.played_only = !filt.played_only;
    paintFilters();
    load();
  };
  box.querySelectorAll("[data-role]").forEach((c) => (c.onclick = () => {
    filt.role = c.dataset.role;
    paintFilters();
    load();
  }));
  const mode = box.querySelector("#h-mode");
  mode.value = filt.mode;
  mode.style.display = filt.kind === "free" ? "none" : "";   // roll variants only apply to the roulette
  mode.onchange = () => {
    filt.mode = mode.value;
    load();
  };
  box.querySelector("#h-queue").onchange = (e) => {
    filt.queue = e.target.value;
    load();
  };
  box.querySelector("#h-champ").onchange = (e) => {
    filt.champ = e.target.value;
    load();
  };
  box.querySelector("#h-refresh").onclick = async () => {
    const r = await call("history_refresh");
    if (r.error) toast(r.error, "warn");
  };
  box.querySelector("#h-clear").onclick = async () => {
    if (await confirmBox(t("Effacer tout l'historique ? Tes 20 dernières parties seront reprises du client LoL à la prochaine connexion."), t("Effacer"))) {
      await call("history_clear");
      load();
    }
  };
}

function paintQueueFilter(queues) {
  const sel = root.querySelector("#h-queue");
  sel.innerHTML = `<option value="all">${esc(t("Tous les modes"))}</option>` + queues.map((q) => `<option value="${q.id}">${esc(q.name)}</option>`).join("");
  if (!queues.some((q) => String(q.id) === String(filt.queue))) filt.queue = "all";
  sel.value = filt.queue;
}

function paintChampFilter(champs) {
  const sel = root.querySelector("#h-champ");
  sel.innerHTML = `<option value="all">${esc(t("Tous les champions"))}</option>` + champs.map((c) => `<option value="${esc(c.key)}">${esc(c.name)}</option>`).join("");
  if (!champs.some((c) => c.key === filt.champ)) filt.champ = "all";
  sel.value = filt.champ;
}

function paintList(rows) {
  const box = root.querySelector("#h-list");
  if (!rows.length) {
    box.innerHTML = `<div class="card empty">${esc(t("Aucune partie ne correspond à ces filtres."))}</div>`;
    return;
  }
  box.innerHTML = `<div class="hlist">
    <div class="hrow head"><div>${esc(t("Champion"))}</div><div>${esc(t("Date"))}</div><div class="c-mode">${esc(t("Tirage"))}</div><div>${esc(t("Résultat"))}</div><div>KDA</div><div>LP</div><div>${esc(t("Détail"))}</div></div>
    ${rows.map((r) => `
    <div class="hrow" data-id="${r.id}">
      <div class="who"><img src="${img.icon(r.key)}" alt=""${champAttr(r.key, r.role)}><div><div class="nm">${esc(r.name)}</div><div class="rl">${r.role ? roleIcon(r.role) : ""}${esc(r.role_label)}</div></div></div>
      <div class="c num">${esc(r.date)}</div>
      <div class="c c-mode${r.free ? " t-muted" : ""}">${esc(r.mode)}</div>
      <div><span class="pill t-${r.tone}">${esc(r.glyph)} ${esc(r.result)}</span></div>
      <div class="kda">${r.kda ? r.kda.join(" / ") : ""}</div>
      <div class="lpd ${r.lp_delta > 0 ? "t-good" : r.lp_delta < 0 ? "t-bad" : "t-muted"}">${r.lp_delta != null ? signed(r.lp_delta, 0) + " LP" : ""}</div>
      <div class="c" title="${esc([r.queue, r.detail].filter(Boolean).join(" · "))}">${esc([r.queue, r.detail].filter(Boolean).join(" · "))}</div>
    </div>`).join("")}</div>`;
  stagger(box.querySelectorAll(".hrow[data-id]"), 30, 16);
  stagger(root.querySelectorAll(".sum"), 50);
  box.querySelectorAll(".hrow[data-id]").forEach((el) => (el.onclick = () => {
    const r = rows.find((x) => String(x.id) === el.dataset.id);
    if (r.has_game) showGame(r.id);
    else if (r.has_combo) isLite() ? openUgg(...r.combo.split("|")) : openCombo(r.combo);
  }));
}

// --- game details ----------------------------------------------------------------------------
async function showGame(id) {
  const v = await call("game", { id });
  if (v.error) return toast(v.error, "bad");
  const { box, close } = openModal(gameHTML(v), () => (openGame = null));
  setModalBack(t("Retour à la partie"), () => showGame(id));
  backdrop(v.played);
  // the header and the "See the guide" buttons open the roll's guide
  const wire = (view) => {
    box.querySelectorAll("[data-guide]").forEach((b) => (b.onclick = (e) => {
      e.stopPropagation();
      openCombo(b.dataset.guide);   // closes this window, which the guide can reopen
    }));
    const head = isLite() ? null : box.querySelector(".g-head.link");
    if (head) head.onclick = (e) => {
      if (e.target.closest(".stat, button, [data-champ]")) return;
      openCombo(view.combo);
    };
  };
  wire(v);
  openGame = {
    reload: async () => {
      const nv = await call("game", { id });
      if (!nv.error) box.innerHTML = gameHTML(nv) + `<button class="modal-close" title="${esc(t("Fermer"))}">×</button>`;
      box.querySelector(".modal-close").onclick = close;
      wire(nv);
    },
  };
}

function gameHTML(v) {
  const chips = (v.chips || []).map((c) => `<div class="stat"><div class="l">${esc(c.label)}</div><div class="v num">${esc(c.value)}</div><div class="s">${esc(c.sub)}</div></div>`).join("");
  let body = "";
  if (v.state !== "ok") {
    body = `<div class="empty">${esc(v.state === "loading" ? t("Détail en cours de récupération auprès du client LoL…") : t("Détail pas encore disponible : ouvre le client League of Legends pour le récupérer."))}</div>`;
  } else {
    body = v.teams.map((tm) => `
      <div class="team">
        <div class="team-head"><span class="bar-side" style="background:${tm.side === "blue" ? "var(--blue)" : "var(--red)"}"></span>
          <span class="tn ${tm.win ? "t-good" : "t-bad"}">${esc(tm.side === "blue" ? t("Équipe bleue") : t("Équipe rouge"))} — ${esc(tm.win ? t("Victoire") : t("Défaite"))}</span>
          ${tm.mine ? `<span class="badge mine">${esc(t("ton équipe"))}</span>` : ""}
          <span class="objs">${tm.objs.map(esc).join(" · ")}</span></div>
        <div class="prow head"><div></div><div>${esc(t("Joueur"))}</div><div>${esc(t("Niv."))}</div><div>KDA</div><div>${esc(t("Ratio"))}</div><div>${esc(t("Farm"))}</div><div>${esc(t("Or"))}</div><div>${esc(t("Dégâts"))}</div><div>${esc(t("Subis"))}</div><div>${esc(t("Vision"))}</div></div>
        ${tm.rows.map((p) => `
          <div class="prow${p.me ? " me" : ""}">
            <div>${p.role ? roleIcon(p.role) : ""}</div>
            <div class="who">${p.key ? `<img src="${img.icon(p.key)}" alt=""${champAttr(p.key, p.role)}>` : ""}<div style="min-width:0"><div class="nm">${esc(p.name)}</div><div class="ch">${esc(p.champ)}${p.tag ? " #" + esc(p.tag) : ""}</div></div></div>
            <div class="num">${p.level}</div><div class="num" style="color:var(--gold-pale)">${esc(p.kda)}</div><div class="num">${esc(p.ratio)}</div>
            <div class="num">${esc(p.cs)}</div><div class="num">${esc(p.gold)}</div>
            <div class="dmg"><span class="num">${esc(p.dmg_txt)}</span><i><b style="width:${(p.dmg_frac * 100).toFixed(1)}%;background:${tm.side === "blue" ? "var(--blue)" : "var(--red)"}"></b></i></div>
            <div class="num">${esc(p.taken)}</div><div class="num">${esc(p.vision)}</div>
          </div>`).join("")}
      </div>`).join("");
  }
  return `
    <div class="g-head${v.combo && !isLite() ? " link" : ""}" ${v.combo && !isLite() ? `title="${esc(t("Voir la fiche de {0}", v.combo_label))}"` : ""}>
      <div class="hero-art" style="background-image:url('${img.splash(v.played)}')"></div><div class="hero-shade"></div>
      <div style="position:relative">
        <h2 class="g-title t-${v.tone}">${esc(v.title.toUpperCase())}</h2>
        <div style="font-weight:600;color:var(--gold-pale)">${v.infos.map(esc).join("  ·  ")}</div>
        <div class="muted" style="margin:4px 0 14px">${esc(v.roll_text)}</div>
        ${v.group ? `<div class="g-group">${v.group.map((m) => `<span class="gg ${m.ok === true ? "ok" : m.ok === false ? "ko" : ""}" title="${esc(m.played ? t("a joué {0}", m.played) : t("pas retrouvé dans la partie"))}"><img src="${img.icon(m.key)}" alt=""${champAttr(m.key, m.role)}><b>${esc(m.name)}</b>${esc(m.champ)} · ${esc(m.role_label)}<i>${m.ok === true ? "✔" : m.ok === false ? "✘" : "?"}</i></span>`).join("")}${(() => { const k = v.group.filter((m) => m.ok != null); return k.length ? `<span class="gg-sum">${esc(t("{0} / {1} tirages respectés", k.filter((m) => m.ok).length, k.length))}</span>` : ""; })()}</div>` : ""}
        <div class="stats">${chips}</div>
      </div>
      <div class="g-guide">${isLite() ? "" : `
        ${v.combo ? `<button class="btn-gold" data-guide="${esc(v.combo)}">${esc(t("Voir la fiche · {0}", v.combo_label))}</button>` : ""}
        ${v.played_combo ? `<button class="btn sm" data-guide="${esc(v.played_combo)}">${esc(t("Fiche du champion joué · {0}", v.played_label))}</button>` : ""}`}
      </div>
    </div>
    <div class="g-body">${body}</div>`;
}
