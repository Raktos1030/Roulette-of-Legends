// Game page (live game).
//   Champ select: both teams face to face, role by role (enemy roles guessed until the game shows them), bans,
//   and for each enemy: its 3 worst matchups (clickable), its win condition, the player's win rate against it.
//   Clicking a champion opens its guide (enemy: Matchups tab).
//   In game: the real roles, then each player's rank and recent form (read from the client).
import { esc, img, roleIcon, pct, int, signed, stagger, t, LANG } from "./util.js";
import { store, on, backdrop, champAttr } from "./ctx.js";
import { call } from "./api.js";
import { openCombo } from "./guides.js";

let root = null, unsub = null;

export function renderLive(page) {
  root = page;
  page.innerHTML = `<div class="page-enter" id="lv"></div>`;
  paint(store.live, true);
  call("live").then((v) => {
    if (!v.error && root === page) {
      store.live = v;
      paint(v);
    }
  });
  unsub && unsub();
  unsub = on((type, data) => {
    if (!root || !document.body.contains(root)) return;
    if (type === "live") paint(data);
  });
}

const TIER_CLASS = { IRON: "iron", BRONZE: "bronze", SILVER: "silver", GOLD: "gold", PLATINUM: "plat", EMERALD: "emerald",
  DIAMOND: "diamond", MASTER: "master", GRANDMASTER: "gm", CHALLENGER: "chall" };

function paint(v, first = false) {
  const box = root.querySelector("#lv");
  if (!box) return;
  if (!v || !v.mode) {
    backdrop(store.boot.hero);
    box.innerHTML = `
      <header class="page-head"><div>
        <div class="kicker">${esc(t("Ta partie en direct"))}</div>
        <h1 class="page-title">${esc(t("Partie"))}</h1>
      </div></header>
      <section class="card empty lv-empty">${esc(store.lol && store.lol.connected ? t("Aucune partie en cours.") : t("Client LoL non détecté."))}</section>`;
    return;
  }
  const cs = v.mode === "cs";
  const guessed = v.rows.some((r) => r.enemy && r.enemy.guessed);
  box.innerHTML = `
    <header class="page-head lv-head"><div>
      <div class="kicker">${esc(v.queue || t("Ta partie en direct"))}</div>
      <h1 class="page-title">${esc(cs ? t("Sélection") : t("Partie en cours"))}</h1>
    </div>
    ${v.combo ? `<button class="btn sm" data-guide="${esc(v.combo)}">${esc(t("Ta fiche : {0}", v.combo_label))}</button>` : ""}</header>
    ${v.bans && v.bans.length ? `<div class="lv-bans"><span class="lv-k">${esc(t("Bannis"))}</span>${v.bans.map((b) => `<img src="${img.icon(b.key)}" alt="" title="${esc(b.name)}"${champAttr(b.key)}>`).join("")}</div>` : ""}
    <section class="card lv-board">
      <div class="lv-cols"><span class="ally">${esc(t("Ton équipe"))}</span><span></span><span class="enemy">${esc(t("Équipe adverse"))}</span></div>
      ${v.rows.map((r) => rowHTML(r, cs)).join("")}
    </section>
    ${duel(v)}
    ${duoCard(v)}
    <div class="lv-bottom">
      ${profiles(v)}
      ${counters(v)}
    </div>`;
  box.querySelectorAll("[data-guide]").forEach((b) => (b.onclick = (e) => {
    e.stopPropagation();
    openCombo(b.dataset.guide, b.dataset.tab || null);
  }));
  if (first) stagger(box.querySelectorAll(".lv-row2"), 40, 10);
}

function rowHTML(r, cs) {
  return `<div class="lv-row2">
    ${side(r.ally, "ally", cs)}
    <div class="lv-mid" title="${esc(r.role_label)}">${r.role ? roleIcon(r.role) : ""}<span>${esc(r.role_label)}</span></div>
    ${side(r.enemy, "enemy", cs)}
  </div>`;
}

function guideKey(p) {
  return p.key && p.role && p.has_guide ? `${p.key}|${p.role}` : null;
}

function side(p, which, cs) {
  if (!p) return `<div class="lv-side ${which} empty"><span class="lv-wait">${which === "enemy" && cs ? esc(t("pas encore choisi")) : "—"}</span></div>`;
  const f = guideKey(p);
  const pic = p.key ? `<img class="lv-ic" src="${img.icon(p.key)}" alt="">` : `<span class="lv-ic empty">?</span>`;
  const who = p.player ? esc(p.player) : p.me ? esc(t("Toi")) : `<span class="t-muted">${esc(which === "enemy" ? t("Adversaire") : t("Joueur caché"))}</span>`;
  const rank = p.rank
    ? `<span class="lv-rank ${TIER_CLASS[p.rank.tier] || ""}">${esc(p.rank.label)}</span>${p.rank.wr != null ? `<span class="lv-sub">${esc(t("{0} · {1} parties", pct(p.rank.wr, 0), int(p.rank.games)))}</span>` : ""}`
    : p.loading ? `<span class="lv-sub">${esc(t("lecture…"))}</span>` : "";
  const r = p.recent;
  const kda = (x) => (LANG === "en" ? String(x) : String(x).replace(".", ","));
  const recent = r ? `<span class="lv-sub">${esc(t("{0} V / {1} D sur ses {2} dernières", r.wins, r.n - r.wins, r.n))}${r.champ_n ? " · " + esc(t("{0} sur {1} ({2} V, KDA {3})", r.champ_n, p.champ || t("ce champion"), r.champ_wins, kda(r.champ_kda))) : ""}</span>` : "";
  const tags = r && r.tags.length ? `<span class="lv-tags">${r.tags.map(([t, txt]) => `<span class="lv-tag ${t}">${esc(txt)}</span>`).join("")}</span>` : "";
  const vs = p.vs ? `<span class="lv-vs ${p.vs.delta >= 1.5 ? "good" : p.vs.delta <= -1.5 ? "bad" : ""}" title="${esc(t("Ton taux de victoire contre {0} ({1} parties, Émeraude+)", p.champ, int(p.vs.n)))}">${esc(t("toi : {0}", pct(p.vs.wr, 1)))}</span>` : "";
  const ctr = cs && p.counters && p.counters.length ? `<span class="lv-ctr"><span class="lv-sub">${esc(t("contré par"))}</span>${p.counters.map((c) =>
    `<button class="lv-mini" data-guide="${esc(c.key)}|${esc(p.role)}" title="${esc(t("{0} : {1} ne gagne que {2} contre lui ({3} parties)", c.name, p.champ, pct(c.wr, 1), int(c.n)))}"><img src="${img.icon(c.key)}" alt=""><b>${pct(c.wr, 0)}</b></button>`).join("")}</span>` : "";
  const wants = p.wants ? `<span class="lv-wants">${esc(t("Veut : {0}", p.wants))}</span>` : "";
  return `<div class="lv-side ${which}${p.me ? " me" : ""}${p.lane ? " lane" : ""}${p.locked === false ? " hover" : ""}${p.guessed ? " guessed" : ""}">
    ${f ? `<button class="lv-pic" data-guide="${esc(f)}" ${which === "enemy" ? 'data-tab="matchups"' : ""} title="${esc(which === "enemy" ? t("Ouvrir la fiche (matchups)") : t("Ouvrir la fiche"))}">${pic}</button>` : pic}
    <div class="lv-main">
      <div class="lv-l1"><b>${p.champ ? esc(p.champ) : "…"}</b>${p.guessed ? `<span class="lv-guess" title="${esc(t("Poste supposé"))}">${roleIcon(p.role)}?</span>` : ""}${p.locked === false ? `<span class="lv-sub">${esc(t("survole"))}</span>` : ""}${vs}</div>
      <div class="lv-l2">${who} ${rank}</div>
      ${recent}${tags}${ctr}${wants}
    </div>
  </div>`;
}

function duel(v) {
  const row = v.rows.find((r) => r.ally && r.ally.me);
  const e = row && row.enemy;
  if (!e || !e.key || !(e.note || e.vs)) return "";
  return `<section class="card lv-duel">
    <img src="${img.icon(row.ally.key)}" alt=""${champAttr(row.ally.key, row.ally.role)}><span class="lv-vsx">${esc(t("contre"))}</span><img src="${img.icon(e.key)}" alt=""${champAttr(e.key, e.role || row.ally.role)}>
    <div><h3 class="card-title">${esc(t("Ton duel : {0} contre {1}", row.ally.champ, e.champ))}${e.guessed ? esc(t(" (poste supposé)")) : ""}</h3>
      ${e.vs ? `<div class="lv-sub">${esc(t("Ton taux de victoire :"))} <b class="${e.vs.delta >= 1.5 ? "t-good" : e.vs.delta <= -1.5 ? "t-bad" : ""}">${pct(e.vs.wr, 1)}</b> ${esc(t("sur {0} parties (Émeraude+)", int(e.vs.n)))}</div>` : ""}
      ${e.note ? `<p class="prose">${esc(e.note)}</p>` : ""}</div>
  </section>`;
}

function duoCard(v) {
  const d = v.duo;
  if (!d) return "";
  const cls = d.wr == null ? "" : d.delta >= 1.5 ? "t-good" : d.delta <= -1.5 ? "t-bad" : "";
  return `<section class="card lv-duel lv-duo">
    <img src="${img.icon(d.me_key)}" alt=""${champAttr(d.me_key, d.me_role)}><span class="lv-vsx">+</span><img src="${img.icon(d.key)}" alt=""${champAttr(d.key, d.role)}>
    <div><h3 class="card-title">${esc(t("Ton duo : {0} + {1}", d.me_name, d.name))}${d.guessed ? esc(t(" (poste supposé)")) : ""}${d.best ? `<span class="pill t-gold" style="margin-left:12px">${esc(t("★ un des meilleurs duos"))}</span>` : ""}</h3>
      ${d.wr != null ? `<div class="lv-sub">${esc(t("Ensemble :"))} <b class="${cls}">${pct(d.wr, 1)}</b> ${esc(t("de victoires sur {0} parties · {1} par rapport à la moyenne de {2} (Émeraude+)", int(d.n), signed(d.delta, 1), d.me_name))}</div>`
        : `<div class="lv-sub">${esc(t("Trop peu de parties ensemble pour chiffrer ce duo."))}</div>`}</div>
  </section>`;
}

function splitBar(sp) {
  if (!sp) return `<span class="t-muted">—</span>`;
  return `<div class="lv-split"><i class="ad" style="width:${sp.physical}%"></i><i class="ap" style="width:${sp.magic}%"></i><i class="tr" style="width:${sp.true}%"></i></div>
    <span class="lv-sub">${esc(t("{0} % AD · {1} % AP", sp.physical, sp.magic))}${sp.true ? " · " + esc(t("{0} % brut", sp.true)) : ""}</span>`;
}

function profiles(v) {
  const a = v.profiles.allies, e = v.profiles.enemies;
  const line = (label, pa, pe) => `<div class="lv-row"><span class="lv-k">${label}</span><span>${pa}</span><span>${pe}</span></div>`;
  const names = (l) => (l && l.length ? esc(l.join(", ")) : `<span class="t-muted">${esc(t("aucun"))}</span>`);
  return `<section class="card lv-prof"><h3 class="card-title">${esc(t("Les deux compos"))}</h3>
    <div class="lv-row head"><span></span><span>${esc(t("Ton équipe"))}</span><span>${esc(t("Eux"))}</span></div>
    ${line(esc(t("Dégâts")), splitBar(a.split), splitBar(e.split))}
    ${line(esc(t("Frontline")), names(a.front), names(e.front))}
    ${line(esc(t("Soigneurs")), names(a.healers), names(e.healers))}
    ${line("CC", a.n ? `${a.control} / ${3 * a.n}` : "—", e.n ? `${e.control} / ${3 * e.n}` : "—")}
    ${e.tips.length ? `<ul class="lv-tips">${e.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
  </section>`;
}

function counters(v) {
  if (!v.combo) return "";
  const list = v.counters || [];
  return `<section class="card lv-counter"><h3 class="card-title">${esc(t("Objets contre leur compo"))}</h3>
    ${list.length ? list.map((o) => `<div class="lv-item"><img src="/img/items/${o.id}.png" alt=""><div><b>${esc(o.name)}</b><span class="lv-sub">${esc(o.label)} · ${esc(o.why)}${o.in_core ? " · " + esc(t("déjà dans le build")) : ""}</span></div></div>`).join("")
      : `<p class="t-muted small">${esc(v.enemies.some((x) => x.key) ? t("Rien de particulier.") : t("En attente de leurs champions."))}</p>`}
  </section>`;
}
