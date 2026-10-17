// Roulette page (home): role and champion pick, animated strip, recent rolls.
// The result opens in the Guides page.
import { esc, pct, img, roleIcon, norm, ROLES, ROLE_LABEL, sleep, fmtDate, CHAOS_ICON, t } from "./util.js";
import { store, on, setStatus, toast, backdrop, spinLogo, mechKick, mechRole, confirmBox, isLite, openUgg, UGG_SVG } from "./ctx.js";
import { rollPromo, homePromo, wirePromo } from "./promo.js";
import { call } from "./api.js";
import { showGuide, openCombo } from "./guides.js";

let role = "random";
let champ = null;          // picked champion (boot.champions entry) or null
let root = null;
let unsub = null;

const CARD_W = 124, GAP = 12, STEP = CARD_W + GAP;

export function renderRoulette(page) {
  root = page;
  page.innerHTML = `
  <div class="page-enter">
    <nav class="mode-tabs" id="mode-tabs">
      <button class="mode-tab" data-mode="solo">${SOLO_SVG}<span>${esc(t("Solo"))}</span></button>
      <button class="mode-tab" data-mode="group">${GROUP_SVG}<span>${esc(t("Groupe"))}</span></button>
    </nav>
    <section class="card controls">
      <div class="gpanel" id="gpanel"></div>
      <div class="ctl-roles"><div class="ctl-label">${esc(t("Rôle"))}</div><div class="roles" id="roles"></div></div>
      <div class="ctl-champ"><div class="ctl-label">${esc(t("Champion"))}</div>
        <div class="champ-field">
          <span class="cf-icon" id="cf-icon">?</span>
          <input class="input" id="cf-input" placeholder="${esc(t("Aléatoire — ou tape un nom"))}" autocomplete="off" spellcheck="false">
          <button class="cf-clear" id="cf-clear" title="${esc(t("Effacer"))}" hidden>×</button>
          <div class="dropdown scroll" id="cf-dd" hidden></div>
          <div class="champ-info" id="cf-info"></div>
        </div>
      </div>
      <button class="btn-gold launch" id="launch" title="${esc(t("Raccourcis : 1 à 5 choisissent le rôle, 0 = aléatoire, Ctrl+F = chercher un champion"))}"><span class="lt">${esc(t("Lancer"))}</span></button>
      <div class="filters" id="filters"></div>
    </section>
    <section class="gstrips" id="gstrips" hidden></section>
    <div id="gresult"></div>
    <section class="strip idle" id="strip">
      <div class="strip-track" id="track"></div>
      <div class="strip-marker"><i class="top"></i><i class="bot"></i></div>
      <div class="strip-msg"><div><b>${esc(t("LA FAILLE DÉCIDE POUR TOI"))}</b><span>${esc(t("Choisis un rôle ou laisse tout au hasard, puis appuie sur Lancer"))}</span></div></div>
    </section>
    <div class="status-line" id="status"></div>
    <div id="stage"></div>
  </div>`;
  paintRoles();
  paintFilters();
  setupChampField();
  idleStrip();
  page.querySelector("#launch").onclick = () => launch();
  page.querySelectorAll(".mode-tab").forEach((b) => (b.onclick = () => {
    if (store.spinning) return;
    mode = b.dataset.mode;
    try { localStorage.setItem("rol_mode", mode); } catch (e) { /* storage unavailable: not important */ }
    paintMode();
  }));
  paintMode();
  paintStatus();
  const stage = page.querySelector("#stage");
  renderWelcome(stage);
  unsub && unsub();
  unsub = on((type) => {
    if (!root || !document.body.contains(root)) return;
    if (type === "status") paintStatus();
    if (type === "lol" && mode === "group") {
      if (!syncLobby() && synced() !== gSyncPainted) paintGroupPanel();
      else paintLobbyBtn();
      const mine = root.querySelector(".gp-row.me .gp-name");
      if (mine) mine.value = myName();
      const lab = root.querySelector(".gs-row[data-i] .gs-id b");
      const meIdx = gPlayers ? playing().findIndex((p) => p.me) : -1;
      const row = meIdx >= 0 && root.querySelector(`.gs-row[data-i="${meIdx}"] .gs-id b`);
      if (row && lab) row.textContent = myName();
    }
    if (type === "profile") {
      paintRoles();
      paintFilters();
      if (!store.spinning) paintStripRoll();
      if (champ) showChampInfo();
    }
    if ((type === "recent" || type === "roll") && !store.spinning) {
      renderWelcome(stage);
      paintStripRoll();
    }
  });
}

export function rouletteKey(e) {
  if (store.spinning) return false;
  const t = e.target;
  const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT");
  // shortcuts: 1 to 5 = role, 0 = random, Ctrl+F (Cmd+F on macOS) = search a champion
  if (!typing && !e.ctrlKey && !e.metaKey && !e.altKey && /^[0-5]$/.test(e.key)) {
    role = e.key === "0" ? "random" : ROLES[+e.key - 1];
    paintRoles();
    return true;
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
    const input = root && root.querySelector("#cf-input");
    if (input) {
      input.focus();
      input.select();
      return true;
    }
  }
  if (e.key !== "Enter") return false;
  if (t && t.id === "cf-input") return false;   // handled by the input itself
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.tagName === "BUTTON")) return false;
  launch();
  return true;
}

// ---------------------------------------------------------------------------------------------
function paintRoles() {
  const box = root.querySelector("#roles");
  const favRoles = store.profile.fav_roles || [];
  box.innerHTML = [...ROLES, "random", "chaos"].map((r) => `
    <button class="role-btn${r === role ? " on" : ""}${r === "chaos" ? " chaos" : ""}" data-r="${r}" title="${esc(r === "random" ? t("Rôle au hasard (touche 0)") : r === "chaos" ? (isLite() ? t("Chaos : n'importe quel champion à n'importe quel poste (Yuumi jungle…).") : t("Chaos : n'importe quel champion à n'importe quel poste (Yuumi jungle…). Les postes sans fiche ont une fiche chaos.")) : t("{0} (touche {1})", ROLE_LABEL[r], ROLES.indexOf(r) + 1))}">
      ${r === "chaos" ? CHAOS_ICON : roleIcon(r)}<span>${r === "chaos" ? "Chaos" : esc(ROLE_LABEL[r])}</span>${favRoles.includes(r) ? `<i class="fav-dot" title="${esc(t("Rôle favori"))}"></i>` : ""}
    </button>`).join("");
  box.querySelectorAll(".role-btn").forEach((b) => (b.onclick = () => {
    role = b.dataset.r;
    paintRoles();
  }));
}

function paintFilters() {
  const p = store.profile;
  const chips = [
    ["only_fav_roles", `${esc(t("Rôles favoris seulement"))} <span class="n">${(p.fav_roles || []).length}</span>`],
    ["only_fav_champs", `${esc(t("Champions favoris seulement"))} <span class="n">${p.fav_count || 0}</span>`],
    ["no_repeat", esc(t("Pas de doublon dans la session"))],
  ];
  const box = root.querySelector("#filters");
  box.innerHTML = `<span class="ctl-label" style="margin:0 6px 0 2px">${esc(t("Filtres"))}</span>` +
    chips.map(([k, l]) => `<button class="chip${p[k] ? " on" : ""}" data-k="${k}"><span class="ck"></span>${l}</button>`).join("");
  box.querySelectorAll(".chip").forEach((c) => (c.onclick = async () => {
    const k = c.dataset.k;
    const r = await call("set_pref", { key: k, value: !store.profile[k] });
    if (r.error) return toast(r.error, "bad");
    store.profile = r.profile;
    paintFilters();
  }));
}

function paintStatus() {
  const s = root && root.querySelector("#status");
  if (!s) return;
  s.textContent = store.status.text || "";
  s.className = `status-line t-${store.status.tone || "muted"}`;
}

// --- champion search field ----------------------------------------------------------------------
function setupChampField() {
  const input = root.querySelector("#cf-input");
  const dd = root.querySelector("#cf-dd");
  const clear = root.querySelector("#cf-clear");
  let act = 0, items = [];
  if (champ) {
    input.value = champ.name;
    showChampInfo();
  }
  const render = () => {
    const q = norm(input.value);
    if (!q) {
      dd.hidden = true;
      return;
    }
    const all = store.boot.champions;
    const starts = all.filter((c) => norm(c.name).startsWith(q) || norm(c.name_en).startsWith(q));
    const contains = all.filter((c) => !starts.includes(c) && (norm(c.name).includes(q) || norm(c.name_en).includes(q)));
    items = [...starts, ...contains].slice(0, 12);
    if (!items.length) {
      dd.innerHTML = `<div class="dd-item muted">${esc(t("Aucun champion ne correspond."))}</div>`;
      dd.hidden = false;
      return;
    }
    act = Math.min(act, items.length - 1);
    dd.innerHTML = items.map((c, i) => `
      <div class="dd-item${i === act ? " act" : ""}" data-i="${i}"><img src="${img.icon(c.key)}" alt=""><span>${esc(c.name)}</span>
        <span class="dd-roles">${c.roles.map((r) => roleIcon(r.role)).join("")}</span></div>`).join("");
    dd.hidden = false;
    dd.querySelectorAll(".dd-item[data-i]").forEach((it) => (it.onmousedown = (e) => {
      e.preventDefault();
      pick(items[+it.dataset.i]);
    }));
  };
  const pick = (c) => {
    champ = c;
    input.value = c.name;
    dd.hidden = true;
    showChampInfo();
  };
  input.oninput = () => {
    act = 0;
    champ = null;
    clear.hidden = !input.value;
    render();
    showChampInfo();
  };
  input.onkeydown = (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (dd.hidden) return render();
      act = (act + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      render();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (!dd.hidden && items[act]) pick(items[act]);
      else launch();
    } else if (e.key === "Escape") {
      dd.hidden = true;
    }
  };
  input.onblur = () => setTimeout(() => (dd.hidden = true), 120);
  input.onfocus = () => input.value && !champ && render();
  clear.onclick = () => {
    input.value = "";
    champ = null;
    clear.hidden = true;
    showChampInfo();
    input.focus();
  };
}

function showChampInfo() {
  const info = root.querySelector("#cf-info");
  const icon = root.querySelector("#cf-icon");
  const input = root.querySelector("#cf-input");
  root.querySelector("#cf-clear").hidden = !input.value;
  if (champ) {
    const p = store.profile;
    const fav = (r) => p.fav_champs.includes(champ.key) || p.fav_combos.includes(`${champ.key}|${r}`);
    info.innerHTML = champ.roles.map((r) => `${ROLE_LABEL[r.role]}${fav(r.role) ? " ★" : ""} ${pct(r.share, 0)}`).join(" · ");
    info.className = "champ-info ok";
    icon.innerHTML = `<img src="${img.icon(champ.key)}" alt="">`;
  } else if (input.value.trim()) {
    info.textContent = t("choisis dans la liste");
    info.className = "champ-info warn";
    icon.textContent = "?";
  } else {
    info.textContent = "";
    info.className = "champ-info";
    icon.textContent = "?";
  }
}

// --- roulette strip ------------------------------------------------------------------------------
function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function champCard(key, name) {
  return `<div class="scard" style="background-image:url('${img.tall(key)}')"><b>${esc(name)}</b></div>`;
}
function roleCard(r) {
  return `<div class="scard role">${roleIcon(r)}<b>${esc(ROLE_LABEL[r].toUpperCase())}</b></div>`;
}

function idleStrip() {
  const strip = root.querySelector("#strip");
  const track = root.querySelector("#track");
  const favs = store.boot.champions.filter((c) => store.profile.fav_champs.includes(c.key) || store.profile.fav_combos.some((x) => x.startsWith(c.key + "|")));
  const pool = shuffle([...(favs.length >= 12 ? favs : store.boot.champions)]).slice(0, 22);
  const cards = pool.map((c) => champCard(c.key, c.name)).join("");
  track.style.transform = "";
  track.innerHTML = cards + cards;   // twice: seamless continuous scroll
  strip.className = "strip idle";
  paintStripRoll();
}

const PAUSE_SVG = `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="2.5" width="3" height="11" rx="1"/><rect x="9.5" y="2.5" width="3" height="11" rx="1"/></svg>`;
const PLAY_SVG = `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.6v10.8c0 .5.5.8.9.5l8.2-5.4a.6.6 0 0 0 0-1L5.4 2.1c-.4-.3-.9 0-.9.5z"/></svg>`;

// Current roll: the idle strip becomes its card (splash, name, role), with the guide and pause buttons.
// While paused the card freezes: games don't count for the roulette and the roll waits.
function paintStripRoll() {
  const strip = root && root.querySelector("#strip");
  if (!strip || !strip.classList.contains("idle")) return;
  const roll = store.roll;
  const show = !!roll && (roll.status === "pending" || roll.status === "in_game");
  const inGame = show && roll.status === "in_game";
  const paused = show && !inGame && !!store.profile.roulette_paused;
  strip.classList.toggle("has-roll", show);
  strip.classList.toggle("paused", paused);
  let box = strip.querySelector(".strip-roll");
  if (!show) {
    if (box) box.remove();
    return;
  }
  if (!box) {
    box = document.createElement("div");
    box.className = "strip-roll";
    strip.appendChild(box);
  }
  const kicker = inGame ? t("Partie en cours") : paused ? t("Tirage en pause") : t("Ton tirage");
  const sub = inGame ? t("Le résultat et les LP s'ajoutent à ton historique à la fin de la partie.")
    : paused ? t("Tes parties ne comptent pas pour la roulette. Il t'attend, reprends quand tu veux.")
    : t("À jouer sur la Faille. L'ARAM et les autres modes ne le comptent jamais.");
  const tip = paused ? t("Tes prochaines parties sur la Faille compteront à nouveau pour ce tirage")
    : t("Pour une partie sans la roulette (classée avec des potes…) : elle ne comptera pas, ton tirage restera en attente");
  box.innerHTML = `
    <div class="sr-art" style="background-image:url('${img.splash(roll.key)}')"></div><div class="sr-shade"></div>
    <div class="sr-body">
      <div class="sr-card" style="background-image:url('${img.tall(roll.key)}')"></div>
      <div class="sr-info">
        <div class="sr-kick">${esc(kicker)}</div>
        <div class="sr-name">${esc(roll.name)}</div>
        <div class="sr-role">${roleIcon(roll.role)}<span>${esc(roll.role_label)}</span>${roll.mode ? `<em>${esc(roll.mode)}</em>` : ""}</div>
        <div class="sr-sub">${esc(sub)}</div>
        <div class="sr-act">
          ${isLite() ? `<button class="btn-gold sr-guide" data-ugg title="${esc(t("Ouvre la page u.gg de ce champion à ce poste dans ton navigateur"))}">${UGG_SVG}${esc(t("Voir sur u.gg"))}</button>`
            : `<button class="btn-gold sr-guide" data-guide>${esc(t("Voir la fiche"))}</button>`}
          ${inGame ? "" : `<button class="sr-pause${paused ? " on" : ""}" data-pause title="${esc(tip)}">${paused ? PLAY_SVG + esc(t("Reprendre")) : PAUSE_SVG + esc(t("Mettre en pause"))}</button>`}
        </div>
      </div>
    </div>
    ${paused ? `<div class="sr-frozen"><span class="sr-ring">${PAUSE_SVG}</span><b>${esc(t("En pause"))}</b></div>` : isLite() ? rollPromo(roll) : ""}`;
  wirePromo(box);
  const fb = box.querySelector("[data-guide]");
  if (fb) fb.onclick = () => openCombo(roll.combo);
  const ub = box.querySelector("[data-ugg]");
  if (ub) ub.onclick = () => openUgg(roll.key, roll.role);
  const pb = box.querySelector("[data-pause]");
  if (pb) pb.onclick = async () => {
    pb.disabled = true;
    const r = await call("set_pref", { key: "roulette_paused", value: !paused });
    if (r.error) return toast(r.error, "bad");
    store.profile = r.profile;
    paintStripRoll();
  };
}

function preload(urls) {
  return Promise.all([...new Set(urls)].map((u) => new Promise((res) => {
    const im = new Image();
    im.onload = im.onerror = res;
    im.src = u;
  })));
}

const easeOut = (t) => 1 - Math.pow(1 - t, 4);

function spinStep(step, duration) {
  const strip = root.querySelector("#strip");
  const track = root.querySelector("#track");
  const isRole = step.type === "role";
  track.innerHTML = step.seq.map((x) => (isRole ? roleCard(x) : champCard(x.key, x.name))).join("");
  strip.className = "strip spinning";
  const W = strip.clientWidth;
  const start = W / 2 - CARD_W / 2 - STEP * 2;
  const jitter = (Math.random() - 0.5) * CARD_W * 0.64;
  const end = W / 2 - (step.index * STEP + CARD_W / 2) + jitter;
  track.style.transform = `translate3d(${start}px,0,0)`;
  return new Promise((resolve) => {
    const t0 = performance.now();
    const frame = (now) => {
      const t = Math.min(1, (now - t0) / duration);
      const x = start + (end - start) * easeOut(t);
      track.style.transform = `translate3d(${x}px,0,0)`;
      if (t < 1) requestAnimationFrame(frame);
      else {
        // smooth recentering on the winning card
        const centered = W / 2 - (step.index * STEP + CARD_W / 2);
        track.style.transition = "transform .35s cubic-bezier(.2,.8,.2,1)";
        track.style.transform = `translate3d(${centered}px,0,0)`;
        setTimeout(() => (track.style.transition = ""), 380);
        const card = track.children[step.index];
        card.classList.add("win");
        strip.className = "strip done";
        celebrate(strip);
        setTimeout(resolve, 420);
      }
    };
    requestAnimationFrame(frame);
  });
}

function celebrate(strip) {
  const fl = document.createElement("div");
  fl.className = "flash";
  strip.appendChild(fl);
  setTimeout(() => fl.remove(), 900);
  const cx = strip.clientWidth / 2, cy = strip.clientHeight / 2;
  for (let i = 0; i < 26; i++) {
    const s = document.createElement("i");
    s.className = "spark";
    const a = Math.random() * Math.PI * 2, d = 80 + Math.random() * 150;
    s.style.left = cx + "px";
    s.style.top = cy + "px";
    s.style.setProperty("--dx", Math.cos(a) * d + "px");
    s.style.setProperty("--dy", Math.sin(a) * d * 0.7 + "px");
    s.style.animationDelay = Math.random() * 0.12 + "s";
    strip.appendChild(s);
    setTimeout(() => s.remove(), 1200);
  }
}

function lock(on) {
  store.spinning = on;
  const b = root.querySelector("#launch");
  if (b) b.disabled = on;
  root.querySelectorAll(".role-btn, .chip, #cf-input, .gp-row input, .gp-role, .gp-add, .gp-del, .gp-lobby, .gp-av, .gp-manual, .mode-tab, [data-reroll]")
    .forEach((x) => (x.disabled = on));
  // group list redrawn after a roll: lobby changes held during the spin, names and taken roles locked again
  if (!on && mode === "group" && gPlayers && !syncLobby()) paintGroupPanel();
}

export async function launch(opts = {}) {
  if (store.spinning || !root) return;
  if (mode === "group" && !opts.role) return launchGroup();
  // pending roll: rerolling cancels it, so confirm first (except champ select "Reroll" buttons
  // and guide lookups: champion and role both picked, that's not a roll)
  const pend = store.roll && store.roll.status === "pending" ? store.roll : null;
  if (pend && !opts.role && !(champ && role !== "random" && role !== "chaos")) {
    store.spinning = true;   // no second roll while asking
    const ok = await confirmBox(t("Tu as déjà un tirage en attente : {0} {1}. Si tu relances, il sera compté comme annulé dans ton historique (relancé avant de jouer).", pend.name, pend.role_label), t("Relancer quand même"));
    store.spinning = false;
    if (!ok || !root) return;
  }
  const body = opts.role ? { role: opts.role, reason: opts.reason || null } : { role, champ: champ ? champ.name : (root.querySelector("#cf-input").value || "") };
  const r = await call(opts.role ? "reroll" : "roll", body);
  if (r.error) {
    setStatus(r.error, "warn");
    toast(r.error, "warn");
    return;
  }
  if (r.direct) {
    showGuide(r.combo);
    return;
  }
  lock(true);
  spinLogo(3.5);   // the logo wheel spins with the roulette
  mechKick();
  // role already known (picked role): the mechanism settles on it; otherwise it waits for the role strip
  if (!r.steps.some((s) => s.type === "role")) setTimeout(() => mechRole(r.steps[0].role), 1800);
  try {
    const urls = [];
    for (const s of r.steps) if (s.type === "champ") s.seq.forEach((x) => urls.push(img.tall(x.key)));
    await preload(urls);
    for (const n of r.notes || []) setStatus(n, "warn");
    for (const step of r.steps) {
      if (step.type === "role") {
        const roles = ROLES.filter((x) => step.seq.includes(x)).map((x) => ROLE_LABEL[x]);
        if (!(r.notes || []).length) setStatus(t("Roulette du rôle… ({0})", roles.join(", ")), "gold");
        await spinStep(step, 2600);
        mechRole(step.seq[step.index]);
        setStatus(t("Rôle : {0}", ROLE_LABEL[step.seq[step.index]]), "gold");
        await sleep(520);
      } else {
        const fav = r.fav_filter ? t(" parmi tes favoris") : "";
        setStatus(step.pool > 1 ? t("Roulette {0}… ({1} champions en jeu{2})", ROLE_LABEL[step.role], step.pool, fav)
          : t("Roulette {0}… ({1} champion en jeu{2})", ROLE_LABEL[step.role], step.pool, fav), "gold");
        await spinStep(step, step.pool > 1 ? 4200 : 1600);
      }
    }
    const c = await call("roll_commit", { id: r.id });
    if (c.error) {
      toast(c.error, "bad");
      return;
    }
    store.current = c.combo;
    if (isLite()) {
      // Lite: no guide, the strip becomes the roll card (with "See on u.gg")
      await sleep(1300);
      if (!root || !document.body.contains(root)) return;
      idleStrip();
      renderWelcome(root.querySelector("#stage"));
      setStatus(t("Ton tirage : {0} {1}. Bonne partie !", c.combo.champ.name, c.combo.role_label), "gold");
      return;
    }
    await sleep(750);   // time to see the winning card
    showGuide(c.combo);
  } finally {
    lock(false);
  }
}

// --- group roulette ------------------------------------------------------------------------------
// The server decides everything at once (different roles and champions, no duplicates); the strips here only
// reveal the results, one after the other.
const SOLO_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c.6-4 3.6-6.5 7.5-6.5s6.9 2.5 7.5 6.5"/></svg>`;
const GROUP_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8.5" r="3.4"/><circle cx="16.6" cy="9.4" r="2.7"/><path d="M2.8 20c.5-3.5 3-5.6 6.2-5.6s5.7 2.1 6.2 5.6"/><path d="M15.4 14.6c2.9-.3 5.2 1.6 5.8 4.9"/></svg>`;
const COPY_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2.5"/><path d="M15.5 8.5V6a2.5 2.5 0 0 0-2.5-2.5H6A2.5 2.5 0 0 0 3.5 6v7A2.5 2.5 0 0 0 6 15.5h2.5"/></svg>`;
const GCARD = 92, GSTEP = GCARD + 8;
let mode = "solo";
try { mode = localStorage.getItem("rol_mode") === "group" ? "group" : "solo"; } catch (e) { /* storage unavailable */ }
let gPlayers = null;   // [{name, me, role, champ, out}]; out: in the lobby but not in this roll
let gResult = null;    // last group roll
let gChaos = false;    // chaos for the whole group: any champion in any role
let gManual = false;   // list edited by hand: the LoL lobby no longer fills it
const gKeep = {};      // each lobby player's choices (role, champion, sitting out), kept while the lobby changes
let gSyncPainted = null;

const lobby = () => (store.lol && store.lol.lobby) || [];
// the list follows the LoL lobby (players joining or leaving) unless edited by hand
const synced = () => !gManual && lobby().length >= 2;
const keyOf = (p) => (p.me ? "★" : p.name);
const remember = (p) => (gKeep[keyOf(p)] = { role: p.role, champ: p.champ, out: !!p.out });
const playing = () => gPlayers.filter((p) => !p.out);
const shortName = (n) => String(n || "").split("#")[0];
const initial = (p) => (p.me ? "★" : (shortName(p.name).trim().charAt(0) || "?").toUpperCase());
// local player's Riot ID (without the #tag) once the client is connected; "Toi" otherwise
const myName = () => shortName((store.lol && store.lol.summoner) || "").trim() || t("Toi");
const nameOf = (p, i) => (p.me ? myName() : p.name || t("Joueur {0}", i + 1));

function playersFromLobby() {
  const lb = lobby().slice(0, 5);
  const firsts = lb.map((m) => m.pos1).filter(Boolean);
  const distinct = new Set(firsts).size === firsts.length;   // lobby roles reused when they don't overlap
  return lb.map((m) => {
    const p = { name: m.me ? myName() : shortName(m.name), me: m.me, role: distinct && m.pos1 ? m.pos1 : "random", champ: "", out: false };
    return { ...p, ...gKeep[keyOf(p)] };
  });
}

// someone joined or left the lobby: the list follows (not during a roll)
function syncLobby() {
  if (!synced() || store.spinning || !gPlayers) return false;
  const next = playersFromLobby();
  if (next.map(keyOf).join("|") === gPlayers.map(keyOf).join("|")) return false;
  gPlayers = next;
  paintGroupPanel();
  paintGroupStrips();
  return true;
}

function paintMode() {
  root.querySelectorAll(".mode-tab").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  const group = mode === "group";
  root.querySelector(".controls").classList.toggle("group", group);
  root.querySelector("#strip").hidden = group;
  root.querySelector("#gstrips").hidden = !group;
  root.querySelector("#gresult").hidden = !group;
  if (group) {
    if (!gPlayers) gPlayers = lobby().length >= 2 ? playersFromLobby() : [
      { name: "", me: true, role: "random", champ: "" }, { name: "", me: false, role: "random", champ: "" }];
    else if (synced()) gPlayers = playersFromLobby();   // the lobby may have changed meanwhile
    paintGroupPanel();
    paintGroupStrips();
    if (gResult) paintGroupResult();
  }
}

function paintLobbyBtn() {
  const head = root && root.querySelector(".gp-head");
  if (!head) return;
  const lb = lobby();
  head.querySelector(".gp-src").innerHTML = synced()
    ? `<span class="gp-lobby gp-sync" title="${esc(t("Les joueurs de ton salon LoL, mis à jour tout seuls"))}">${GROUP_SVG}${esc(t("Groupe LoL · {0}", lb.length))}</span>
       <button class="gp-manual" data-manual title="${esc(t("Modifier la liste à la main"))}">✎</button>`
    : lb.length >= 2
      ? `<button class="gp-lobby" data-lobby title="${esc(t("Reprend les pseudos et les postes choisis dans ton salon LoL"))}">${GROUP_SVG}${esc(t("Reprendre mon groupe LoL · {0}", lb.length))}</button>`
      : `<span class="gp-hint">${esc(t("Groupe-toi dans le client LoL : vos pseudos se remplissent tout seuls."))}</span>`;
  const b = head.querySelector("[data-lobby]");
  if (b) b.onclick = () => {
    gManual = false;
    gPlayers = playersFromLobby();
    paintGroupPanel();
    paintGroupStrips();
  };
  const m = head.querySelector("[data-manual]");
  if (m) m.onclick = () => {
    gManual = true;
    paintGroupPanel();
  };
}

function paintGroupPanel() {
  const box = root.querySelector("#gpanel");
  const taken = (i) => new Set(gPlayers.filter((p, j) => j !== i && !p.out && p.role !== "random").map((p) => p.role));
  const auto = synced();
  gSyncPainted = auto;
  box.innerHTML = `
    <div class="gp-head"><span class="ctl-label">${esc(t("Joueurs · {0} / 5", gPlayers.length))}</span><span class="gp-src"></span>
      <button class="chip chaos${gChaos ? " on" : ""}" data-gchaos title="${esc(t("N'importe quel champion à n'importe quel poste, pour tout le groupe"))}">${CHAOS_ICON}Chaos</button></div>
    <div class="gp-rows">${gPlayers.map((p, i) => {
      const tk = taken(i);
      const av = p.me ? `<span class="gp-av">${esc(initial(p))}</span>`
        : `<button class="gp-av" data-out title="${esc(p.out ? t("Ne joue pas cette fois : clique pour l'ajouter au tirage") : t("Clique si ce joueur ne veut pas de tirage"))}">${esc(initial(p))}</button>`;
      return `<div class="gp-row${p.me ? " me" : ""}${p.out ? " out" : ""}" data-i="${i}">
        ${av}
        <input class="input gp-name" value="${esc(p.me ? myName() : p.name)}" placeholder="${esc(t("Pseudo du joueur {0}", i + 1))}" ${p.me ? `disabled title="${esc(t("Ton pseudo LoL"))}"` : auto ? `disabled title="${esc(t("Pseudo du salon LoL"))}"` : ""} maxlength="24" spellcheck="false">
        <div class="gp-roles">${["random", ...ROLES].map((r) => `<button class="gp-role${p.role === r ? " on" : ""}" data-role="${r}" ${p.out || (r !== "random" && tk.has(r)) ? "disabled" : ""} title="${esc(r === "random" ? t("Poste au hasard") : ROLE_LABEL[r])}">${roleIcon(r)}</button>`).join("")}</div>
        <input class="input gp-champ" list="gp-champs" value="${esc(p.out ? "" : p.champ)}" placeholder="${esc(p.out ? t("ne joue pas") : t("Champion au hasard"))}" ${p.out ? "disabled" : ""} spellcheck="false">
        ${p.me ? `<span class="gp-me" title="${esc(t("Ton tirage est suivi dans ton historique"))}">${esc(t("toi"))}</span>` : auto ? "<span></span>" : `<button class="gp-del" title="${esc(t("Retirer ce joueur"))}">×</button>`}
      </div>`;
    }).join("")}</div>
    ${gPlayers.length < 5 && !auto ? `<button class="gp-add">${esc(t("+ Ajouter un joueur"))}</button>` : ""}
    <datalist id="gp-champs">${store.boot.champions.map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist>`;
  paintLobbyBtn();
  box.querySelector("[data-gchaos]").onclick = () => {
    gChaos = !gChaos;
    paintGroupPanel();
  };
  box.querySelectorAll(".gp-row").forEach((row) => {
    const i = +row.dataset.i, p = gPlayers[i];
    const nm = row.querySelector(".gp-name");
    nm.oninput = () => {
      p.name = nm.value;
      row.querySelector(".gp-av").textContent = initial(p);
      const g = root.querySelector(`.gs-row[data-i="${playing().indexOf(p)}"] .gs-id b`);
      if (g) g.textContent = nm.value || t("Joueur {0}", i + 1);
    };
    row.querySelectorAll(".gp-role").forEach((b) => (b.onclick = () => {
      p.role = b.dataset.role;
      remember(p);
      paintGroupPanel();
      paintGroupStrips();
    }));
    const ch = row.querySelector(".gp-champ");
    ch.oninput = () => {
      p.champ = ch.value;
      remember(p);
    };
    const out = row.querySelector("[data-out]");
    if (out) out.onclick = () => {
      p.out = !p.out;
      remember(p);
      paintGroupPanel();
      paintGroupStrips();
    };
    const del = row.querySelector(".gp-del");
    if (del) del.onclick = () => {
      gPlayers.splice(i, 1);
      paintGroupPanel();
      paintGroupStrips();
    };
  });
  const add = box.querySelector(".gp-add");
  if (add) add.onclick = () => {
    gPlayers.push({ name: "", me: false, role: "random", champ: "" });
    paintGroupPanel();
    paintGroupStrips();
    const inputs = box.querySelectorAll(".gp-name");
    inputs[inputs.length - 1].focus();
  };
}

function gCard(key, name) {
  return `<div class="gcard" style="background-image:url('${img.tall(key)}')"><b>${esc(name)}</b></div>`;
}

function roleChip(p) {
  return p.role && p.role !== "random" ? `${roleIcon(p.role)}<span>${esc(ROLE_LABEL[p.role])}</span>` : `<i class="gs-q">?</i><span>${esc(t("poste au hasard"))}</span>`;
}

function paintGroupStrips() {
  const box = root.querySelector("#gstrips");
  const champs = store.boot.champions;
  box.innerHTML = playing().map((p, i) => {   // i: index in the roll (players sitting out have no strip)
    const pool = shuffle([...champs]).slice(0, 16);
    const cards = pool.map((c) => gCard(c.key, c.name)).join("");
    return `<div class="gs-row idle" data-i="${i}">
      <div class="gs-who"><span class="gs-av">${esc(initial(p))}</span>
        <div class="gs-id"><b>${esc(nameOf(p, gPlayers.indexOf(p)))}</b><span class="gs-role">${roleChip(p)}</span></div></div>
      <div class="gs-strip"><div class="gs-track">${cards}${cards}</div><i class="gs-mark"></i></div>
    </div>`;
  }).join("");
}

function spinRow(row, pl, duration) {
  const strip = row.querySelector(".gs-strip");
  const track = row.querySelector(".gs-track");
  const step = pl.steps[pl.steps.length - 1];
  track.innerHTML = step.seq.map((x) => gCard(x.key, x.name)).join("");
  row.className = "gs-row spinning";
  if (pl.random_role) row.querySelector(".gs-role").innerHTML = `<i class="gs-q spin">?</i><span>${esc(t("poste au hasard…"))}</span>`;
  const W = strip.clientWidth;
  const start = W / 2 - GCARD / 2 - GSTEP * 2;
  const jitter = (Math.random() - 0.5) * GCARD * 0.6;
  const end = W / 2 - (step.index * GSTEP + GCARD / 2) + jitter;
  track.style.transition = "";
  track.style.transform = `translate3d(${start}px,0,0)`;
  return new Promise((resolve) => {
    const t0 = performance.now();
    const frame = (now) => {
      const t = Math.min(1, (now - t0) / duration);
      track.style.transform = `translate3d(${start + (end - start) * easeOut(t)}px,0,0)`;
      if (t < 1) return requestAnimationFrame(frame);
      const centered = W / 2 - (step.index * GSTEP + GCARD / 2);
      track.style.transition = "transform .35s cubic-bezier(.2,.8,.2,1)";
      track.style.transform = `translate3d(${centered}px,0,0)`;
      track.children[step.index].classList.add("win");
      row.className = "gs-row done";
      row.querySelector(".gs-role").innerHTML = roleChip(pl);
      celebrate(strip);
      setTimeout(resolve, 380);
    };
    requestAnimationFrame(frame);
  });
}

async function launchGroup() {
  if (store.spinning || !root) return;
  const pend = store.roll && store.roll.status === "pending" ? store.roll : null;
  if (pend) {
    store.spinning = true;
    const ok = await confirmBox(t("Tu as déjà un tirage en attente : {0} {1}. Le tirage du groupe le remplacera, il sera compté comme annulé dans ton historique.", pend.name, pend.role_label), t("Lancer le groupe"));
    store.spinning = false;
    if (!ok || !root) return;
  }
  const r = await call("group_roll", { chaos: gChaos, players: playing().map((p) => ({ name: nameOf(p, gPlayers.indexOf(p)), me: p.me, role: p.role, champ: p.champ })) });
  if (r.error) {
    setStatus(r.error, "warn");
    toast(r.error, "warn");
    return;
  }
  lock(true);
  spinLogo(4.5);
  mechKick();
  setStatus(t("Roulette du groupe : {0} joueurs, aucun doublon possible…", r.players.length), "gold");
  try {
    const urls = [];
    r.players.forEach((pl) => pl.steps[pl.steps.length - 1].seq.forEach((x) => urls.push(img.tall(x.key))));
    await preload(urls);
    root.querySelector("#gresult").innerHTML = "";
    paintGroupStrips();
    const rows = [...root.querySelectorAll(".gs-row")];
    await Promise.all(r.players.map((pl, i) => spinRow(rows[i], pl, 2300 + i * 750)));
    const c = await call("group_commit", { id: r.id });
    if (c.error) return toast(c.error, "bad");
    gResult = c.players;
    const me = gResult.find((p) => p.me);
    setStatus(me ? t("Tirage du groupe enregistré : {0}, {1} {2}.", me.name, me.champ, me.role_label) : t("Tirage du groupe enregistré."), "gold");
    paintGroupResult();
  } finally {
    lock(false);
  }
}

function paintGroupResult() {
  const box = root.querySelector("#gresult");
  if (!gResult) return (box.innerHTML = "");
  box.innerHTML = `<section class="card gres page-enter">
    <h3 class="card-title">${esc(t("Le tirage du groupe"))}<span class="aside"><button class="gr-copy" data-copy>${COPY_SVG}${esc(t("Copier"))}</button></span></h3>
    <div class="gres-row">${gResult.map((p) => `
      <div class="gres-card${p.me ? " me" : ""}" style="--art:url('${img.tall(p.key)}')">
        <span class="gr-who">${esc(p.name)}${p.me ? `<i class="gr-me">${esc(t("toi"))}</i>` : ""}</span>
        <div class="gr-foot">
          <b>${esc(p.champ)}</b>
          <span class="gr-role">${roleIcon(p.role)}${esc(p.role_label)}</span>
          <div class="gr-act">${isLite() ? `<button class="btn sm" data-ugg="${esc(p.combo)}" title="${esc(t("Ouvre la page u.gg de ce champion à ce poste dans ton navigateur"))}">u.gg</button>` : `<button class="btn sm" data-guide="${esc(p.combo)}">${esc(t("Fiche"))}</button>`}<button class="btn sm" data-reroll="${p.i}" title="${esc(t("Nouveau champion au même poste (banni, déjà pris…)"))}">${esc(t("Relancer"))}</button></div>
        </div>
      </div>`).join("")}</div>
  </section>`;
  box.querySelectorAll("[data-guide]").forEach((b) => (b.onclick = () => openCombo(b.dataset.guide)));
  box.querySelectorAll("[data-ugg]").forEach((b) => (b.onclick = () => openUgg(...b.dataset.ugg.split("|"))));
  box.querySelectorAll("[data-reroll]").forEach((b) => (b.onclick = () => rerollOne(+b.dataset.reroll)));
  box.querySelector("[data-copy]").onclick = copyDiscord;
}

async function rerollOne(i) {
  if (store.spinning) return;
  const r = await call("group_reroll", { i });
  if (r.error) return toast(r.error, "warn");
  lock(true);
  try {
    await preload(r.player.steps[0].seq.map((x) => img.tall(x.key)));
    const row = root.querySelector(`.gs-row[data-i="${i}"]`);
    if (row) await spinRow(row, r.player, 1900);
    gResult[i] = r.player;
    paintGroupResult();
    setStatus(t("{0} : {1} {2}.", r.player.name, r.player.champ, r.player.role_label), "gold");
  } finally {
    lock(false);
  }
}

async function copyDiscord() {
  const lines = [t("🎲 Roulette of Legends · tirage du groupe"), ...gResult.map((p) => t("• {0} : {1} ({2})", p.name, p.champ, p.role_label))];
  const text = lines.join("\n");
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  toast(t("Tirage du groupe copié."), "teal");
}

// --- home --------------------------------------------------------------------------------------
function renderWelcome(stage) {
  const b = store.boot;
  const hero = b.hero;
  backdrop(hero);
  const recent = store.recent || [];
  const roll = store.roll;
  stage.innerHTML = `
  <div class="welcome page-enter">
    <section class="card w-hero">
      <div class="w-art" style="background-image:url('${img.splash(hero)}')"></div><div class="w-shade"></div>
      <div class="kicker">${esc(t("La Faille décide pour toi"))}</div>
      <h1 class="w-brand">Roulette<small>of</small>Legends</h1>
      ${isLite() ? `<p class="w-text">${esc(t("Choisis un rôle, un champion, ou laisse la roulette tout décider. Seul, ou avec tes potes grâce à la roulette de groupe."))}</p>
      <div class="w-feats">
        <div class="w-feat"><b>${esc(t("Relié à LoL"))}</b><span>${esc(t("Autofill, ban, résultat et LP : chaque tirage est suivi jusqu'au bout, et ton historique se remplit tout seul."))}</span></div>
        <div class="w-feat"><b>${esc(t("Chaos"))}</b><span>${esc(t("N'importe quel champion à n'importe quel poste. Yuumi jungle, quelqu'un ?"))}</span></div>
        <div class="w-feat"><b>u.gg</b><span>${esc(t("Après le tirage, un clic ouvre la page u.gg du champion à ce poste."))}</span></div>
      </div>` : `<p class="w-text">${esc(t("Choisis un rôle ou laisse la roulette tout décider. Chaque tirage arrive avec sa fiche de jeu et son build, sur les statistiques du patch {0}, mises à jour automatiquement.", b.meta.patch))}</p>
      <div class="w-feats">
        <div class="w-feat"><b>${esc(t("Relié à LoL"))}</b><span>${esc(t("Autofill, ban, résultat et LP : chaque tirage est suivi jusqu'au bout. Runes, sorts et objets importés dès que tu verrouilles."))}</span></div>
        <div class="w-feat"><b>${esc(t("Overlay en jeu"))}</b><span>${esc(t("Maintiens Tab en partie : ta fiche, ton build, tes stats et l'écart d'or. Le sort à monter s'allume sur ton HUD."))}</span></div>
        <div class="w-feat"><b>${esc(t("Lexique"))}</b><span>${esc(t("Survole un terme souligné dans une fiche pour sa définition."))}</span></div>
      </div>`}
    </section>
    <section class="card">
      <h3 class="card-title">${esc(t("Derniers tirages"))}<span class="aside"><a href="#/history" class="t-gold">${esc(t("Historique complet →"))}</a></span></h3>
      ${roll ? `<button class="roll-now" data-combo="${esc(roll.combo)}">
          <img src="${img.icon(roll.key)}" alt=""><span><small>${esc(roll.status === "in_game" ? t("Partie en cours") : store.profile.roulette_paused ? t("Tirage en pause") : t("Ton tirage en cours"))}</small><b>${esc(roll.name)} · ${esc(roll.role_label)}</b></span>
          <span class="rn-go">${esc(isLite() ? t("Voir sur u.gg →") : t("Voir la fiche →"))}</span></button>` : ""}
      ${recent.length ? `<div class="recent-list scroll">${recent.slice(0, 12).map((it) => `
        <div class="recent-item" data-combo="${esc(it.combo)}"><img src="${img.icon(it.key)}" alt="">
          <div><div class="ri-name">${esc(it.name)}</div><div class="ri-sub">${esc(it.sub)}</div></div>
          <span class="ri-glyph t-${it.tone}">${esc(it.glyph)}</span></div>`).join("")}</div>`
        : `<div class="empty">${esc(t("Aucun tirage pour l'instant."))}<br>${esc(t("Appuie sur « Lancer » !"))}</div>`}
    </section>
    ${isLite() ? homePromo() : ""}
  </div>`;
  wirePromo(stage);
  stage.querySelectorAll(".recent-item, .roll-now").forEach((it) => (it.onclick = () =>
    (isLite() ? openUgg(...it.dataset.combo.split("|")) : openCombo(it.dataset.combo))));
}
