// Roulette of Legends, web edition: just the roulette (solo, group, chaos), favorites and recent rolls.
// No link with the LoL client. Everything stays in the browser (localStorage); rolls follow the same logic as the
// desktop app (core.py: api_roll, api_group_roll), ported to JavaScript.
(function () {
  "use strict";

  const D = window.ROL_DATA;
  const EN = window.ROL_EN || {};
  const ROLES = ["top", "jgl", "mid", "adc", "sup"];
  const ROLE_ICON = { top: "top", jgl: "jungle", mid: "middle", adc: "bottom", sup: "utility", random: "fill" };
  const UGG_ROLE = { top: "top", jgl: "jungle", mid: "mid", adc: "adc", sup: "support" };
  const DD = "https://ddragon.leagueoflegends.com/cdn/";

  // --- storage: the browser keeps favorites and rolls (nothing is sent anywhere) ------------------------------
  const mem = {};
  const ls = {
    get(k, d) {
      try {
        const v = localStorage.getItem("rol_" + k);
        return v == null ? d : JSON.parse(v);
      } catch (e) {
        return k in mem ? mem[k] : d;
      }
    },
    set(k, v) {
      mem[k] = v;
      try {
        localStorage.setItem("rol_" + k, JSON.stringify(v));
      } catch (e) { /* storage unavailable (private browsing…): kept for this visit only */ }
    },
  };

  // --- language: French text is the key, en.js provides the English ------------------------------------------
  // each language has its own page: / (French) and /en/ (English); ROOT leads back to the site's root
  const ROOT = document.documentElement.dataset.root || "";
  const LANG = document.documentElement.lang === "en" ? "en" : "fr";
  const otherLang = (lang) => ROOT + (lang === "en" ? "en/" : "") + location.hash;
  if (ls.get("lang", null) && ls.get("lang", null) !== LANG) location.replace(otherLang(ls.get("lang", null)));
  function t(fr, ...args) {
    let s = LANG === "en" ? EN[fr] ?? fr : fr;
    if (args.length) s = s.replace(/\{(\d)\}/g, (m, i) => (args[+i] ?? ""));
    return s;
  }
  function esc(s) {
    const out = String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    return LANG === "en" ? out : out.replace(/ ([:;!?»])/g, " $1").replace(/« /g, "« ");
  }
  const roleLabel = (r) => (r === "random" ? t("Aléatoire") : { top: "Top", jgl: "Jungle", mid: "Mid", adc: "ADC", sup: "Support" }[r] || r);
  const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  const pct = (x) => Math.round(x) + (LANG === "en" ? "%" : " %");

  // --- images: Data Dragon, Riot's official CDN --------------------------------------------------------------
  const img = {
    icon: (k) => `${DD}${D.ddragon}/img/champion/${encodeURIComponent(k)}.png`,
    tall: (k) => `${DD}img/champion/loading/${encodeURIComponent(k)}_0.jpg`,
    splash: (k) => `${DD}img/champion/splash/${encodeURIComponent(k)}_0.jpg`,
  };
  // absolute URL: inside a CSS variable a relative URL is resolved against the stylesheet using it, not the page
  const ROLE_ICONS = new URL(ROOT + "img/roles/", location.href).href;
  const roleIcon = (r) => `<i class="ri" style="--m:url('${ROLE_ICONS}${ROLE_ICON[r] || "fill"}.png')"></i>`;
  const ugg = (key, role) => `https://u.gg/lol/champions/${String(key).toLowerCase()}/build${UGG_ROLE[role] ? "/" + UGG_ROLE[role] : ""}`;
  const CHAOS_ICON = `<svg class="chaos-ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5c.6 3.3 3.9 4.6 3.9 8.5a3.9 3.9 0 0 1-7.8 0c0-1.5.6-2.6 1.4-3.5.2 1.6 1 2.5 2 2.5-1.1-2.6-.4-5.5.5-7.5z"/><path d="M6.4 9.6C5.2 11 4.5 12.8 4.5 14.7A7.5 7.5 0 0 0 12 22.2a7.5 7.5 0 0 0 7.5-7.5c0-2-.8-3.9-2.1-5.3"/></svg>`;
  const SOLO_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c.6-4 3.6-6.5 7.5-6.5s6.9 2.5 7.5 6.5"/></svg>`;
  const GROUP_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8.5" r="3.4"/><circle cx="16.6" cy="9.4" r="2.7"/><path d="M2.8 20c.5-3.5 3-5.6 6.2-5.6s5.7 2.1 6.2 5.6"/><path d="M15.4 14.6c2.9-.3 5.2 1.6 5.8 4.9"/></svg>`;
  const COPY_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2.5"/><path d="M15.5 8.5V6a2.5 2.5 0 0 0-2.5-2.5H6A2.5 2.5 0 0 0 3.5 6v7A2.5 2.5 0 0 0 6 15.5h2.5"/></svg>`;
  const UGG_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/></svg>`;
  const STAR_SVG = `<svg class="star" viewBox="0 0 24 24"><path d="M12 3.2l2.7 5.5 6 .9-4.4 4.2 1 6-5.3-2.8-5.3 2.8 1-6-4.4-4.2 6-.9z"/></svg>`;
  // release downloads (github.com/<owner>/<repo>/releases/latest/download/<file>); empty until published
  const RELEASE = "https://github.com/Raktos1030/Roulette-of-Legends/releases/latest/download/";
  const DOWNLOADS = { lite_win: RELEASE + "Roulette-of-Legends-Lite-windows.zip", lite_mac: RELEASE + "Roulette-of-Legends-Lite-mac.zip",
    full_win: RELEASE + "Roulette-of-Legends-windows.zip" };
  const DOWNLOAD_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/></svg>';

  const NAV_ICONS = {
    roulette: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><path d="M12 3v6M12 15v6M3 12h6M15 12h6M5.6 5.6l4.3 4.3M14.1 14.1l4.3 4.3M18.4 5.6l-4.3 4.3M9.9 14.1l-4.3 4.3"/></svg>',
    favorites: '<svg viewBox="0 0 24 24"><path d="M12 3.2l2.7 5.5 6 .9-4.4 4.2 1 6-5.3-2.8-5.3 2.8 1-6-4.4-4.2 6-.9z"/></svg>',
    rolls: '<svg viewBox="0 0 24 24"><path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3 4v4.5h4.5"/><path d="M12 7.5V12l3 2"/></svg>',
    app: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/><path d="M12 7v5M9.5 9.5L12 12l2.5-2.5"/></svg>',
  };

  // --- champions ------------------------------------------------------------------------------------------
  const CHAMPS = D.champions.map((c) => ({ key: c.key, fr: c.name, en: c.name_en, roles: c.roles.map(([role, share]) => ({ role, share })) }));
  const BY_KEY = Object.fromEntries(CHAMPS.map((c) => [c.key, c]));
  const nameOf = (k) => (BY_KEY[k] ? BY_KEY[k][LANG === "en" ? "en" : "fr"] : k);
  const hasRole = (k, r) => !!BY_KEY[k] && BY_KEY[k].roles.some((x) => x.role === r);
  const sortedChamps = () => [...CHAMPS].sort((a, b) => norm(nameOf(a.key)).localeCompare(norm(nameOf(b.key))));
  function findChampion(text) {
    const q = norm(text);
    if (!q) return null;
    return CHAMPS.find((c) => norm(c.fr) === q || norm(c.en) === q || norm(c.key) === q)
      || CHAMPS.find((c) => norm(c.fr).startsWith(q) || norm(c.en).startsWith(q)) || null;
  }

  // --- profile (favorites, filters) and recent rolls ----------------------------------------------------------
  const profile = Object.assign({ favRoles: [], favChamps: [], onlyFavRoles: false, onlyFavChamps: false, noRepeat: true }, ls.get("profile", {}));
  const saveProfile = () => ls.set("profile", profile);
  let recent = ls.get("recent", []);   // [{key, role, mode, at, group:[{name, key, role}]}]
  const saveRecent = () => ls.set("recent", recent.slice(0, 100));
  const drawn = new Set();             // "no repeat this session": champion + role already rolled
  function addRecent(e) {
    recent.unshift(Object.assign({ at: Date.now() }, e));
    saveRecent();
  }
  // group player label: their nickname, otherwise "Player 2" in the current language
  const playerLabel = (p, i) => String((p && p.name) || "").trim() || t("Joueur {0}", (p && p.i != null ? p.i : i) + 1);
  const MODE_LABEL = () => ({ both: t("Rôle + champion"), role: t("Rôle aléatoire"), champ: t("Champion aléatoire"), group: t("Groupe"), chaos: "Chaos" });

  // =============================================================================================================
  // Rolls: everything is decided here at once; the animation only reveals the result
  // =============================================================================================================
  function roleStep(roles, winner = pick(roles), n = 34, idx = 28) {
    const seq = Array.from({ length: n }, () => pick(roles));
    seq[idx] = winner;
    return [winner, { type: "role", seq, index: idx, pool: roles.length }];
  }
  function champStep(keys, role, winner = pick(keys), n = keys.length > 1 ? 60 : 12, idx = n - 7) {
    const seq = Array.from({ length: n }, () => pick(keys));
    seq[idx] = winner;
    return [winner, { type: "champ", seq, index: idx, pool: keys.length, role }];
  }
  function champPool(role) {
    const keys = CHAMPS.filter((c) => hasRole(c.key, role)).map((c) => c.key);
    return profile.onlyFavChamps ? keys.filter((k) => profile.favChamps.includes(k)) : keys;
  }
  function noRepeat(keys, role, notes) {
    if (!profile.noRepeat) return keys;
    const left = keys.filter((k) => !drawn.has(k + "|" + role));
    if (left.length) return left;
    keys.forEach((k) => drawn.delete(k + "|" + role));
    notes.push(t("Tous les champions de ce tirage sont sortis : on remet tout en jeu."));
    return keys;
  }

  function soloRoll(role, champText) {
    const text = (champText || "").trim();
    const c = text ? findChampion(text) : null;
    if (text && !c) return { error: t("Champion introuvable : « {0} ». Choisis-le dans la liste.", text) };
    const notes = [], steps = [];
    if (role === "chaos") {   // a random role, then any champion (or the chosen one)
      const [r, rs] = roleStep(ROLES);
      const [w, cs] = champStep(c ? [c.key] : CHAMPS.map((x) => x.key), r, undefined, 60, 53);
      return { steps: [rs, cs], result: { key: w, role: r }, mode: "chaos", notes };
    }
    if (c) {
      if (ROLES.includes(role)) return { error: t("Choisis un rôle OU un champion : la roulette tire l'autre au hasard.") };
      const roles = c.roles.map((x) => x.role);
      let cand = roles;
      if (profile.onlyFavRoles) {
        cand = roles.filter((r) => profile.favRoles.includes(r));
        if (!cand.length) {
          cand = roles;
          notes.push(t("Aucun rôle de {0} n'est dans tes favoris : tous ses rôles sont en jeu.", nameOf(c.key)));
        }
      }
      if (cand.length === 1) {
        notes.push(t("{0} : un seul rôle possible ({1}).", nameOf(c.key), roleLabel(cand[0])));
        const [, st] = champStep([c.key], cand[0]);
        return { steps: [st], result: { key: c.key, role: cand[0] }, mode: "role", notes };
      }
      const [r, st] = roleStep(cand);
      return { steps: [st], result: { key: c.key, role: r }, mode: "role", notes };
    }
    if (ROLES.includes(role)) {
      const keys = champPool(role);
      if (!keys.length) return { error: t("Aucun champion favori jouable en {0}. Ajoute-en dans les favoris ou désactive « Champions favoris seulement ».", roleLabel(role)) };
      const [w, st] = champStep(noRepeat(keys, role, notes), role);
      return { steps: [st], result: { key: w, role }, mode: "champ", notes };
    }
    let roles = ROLES;
    if (profile.onlyFavRoles) {
      if (profile.favRoles.length) roles = ROLES.filter((r) => profile.favRoles.includes(r));
      else notes.push(t("Aucun rôle favori coché : tous les rôles sont en jeu."));
    }
    roles = roles.filter((r) => champPool(r).length);
    if (!roles.length) return { error: t("Aucun champion favori dans ces rôles. Ajoute des favoris ou désactive un filtre.") };
    let r = roles[0];
    if (roles.length > 1) {
      let st;
      [r, st] = roleStep(roles);
      steps.push(st);
    }
    const [w, cs] = champStep(noRepeat(champPool(r), r, notes), r);
    steps.push(cs);
    return { steps, result: { key: w, role: r }, mode: "both", notes };
  }

  // group roulette: a different role and champion for everyone, no duplicates
  function groupRoll(players, chaos) {
    const ps = players.map((p, i) => ({ name: String(p.name || "").trim().slice(0, 24), role: ROLES.includes(p.role) ? p.role : "random", champ: String(p.champ || "").trim() }));
    if (ps.length < 2 || ps.length > 5) return { error: t("La roulette de groupe se joue de 2 à 5 joueurs.") };
    const fixed = ps.filter((p) => p.role !== "random").map((p) => p.role);
    const dup = fixed.find((r, i) => fixed.indexOf(r) !== i);
    if (dup) return { error: t("Deux joueurs ont le même poste ({0}) : un seul par poste.", roleLabel(dup)) };
    const chosen = {};
    for (let i = 0; i < ps.length; i++) {
      const p = ps[i];
      if (!p.champ) continue;
      const ch = findChampion(p.champ);
      if (!ch) return { error: t("{0} : champion introuvable (« {1} »).", playerLabel(p, i), p.champ) };
      if (p.role !== "random" && !hasRole(ch.key, p.role) && !chaos) return { error: t("{0} : {1} n'est pas joué {2}.", playerLabel(p, i), nameOf(ch.key), roleLabel(p.role)) };
      chosen[i] = ch;
    }
    if (new Set(Object.values(chosen).map((c) => c.key)).size < Object.keys(chosen).length) return { error: t("Deux joueurs ont choisi le même champion.") };
    const takenRoles = new Set(fixed), takenChamps = new Set(Object.values(chosen).map((c) => c.key));
    const out = new Array(ps.length);
    // most constrained players first: chosen champion, then chosen role, then fully random
    const order = ps.map((p, i) => i).sort((a, b) => ((a in chosen ? 0 : 2) + (ps[a].role !== "random" ? 0 : 1)) - ((b in chosen ? 0 : 2) + (ps[b].role !== "random" ? 0 : 1)));
    for (const i of order) {
      const p = ps[i], steps = [];
      let role = p.role;
      if (role === "random") {
        const base = i in chosen && !chaos ? chosen[i].roles.map((x) => x.role) : ROLES;
        const cand = base.filter((r) => !takenRoles.has(r));
        if (!cand.length) return { error: t("{0} : plus de poste libre pour {1}.", playerLabel(p, i), i in chosen ? nameOf(chosen[i].key) : t("lui")) };
        let st;
        [role, st] = roleStep(cand, pick(cand), 30, 24);
        steps.push(st);
        takenRoles.add(role);
      }
      const every = chaos ? CHAMPS.map((c) => c.key) : CHAMPS.filter((c) => hasRole(c.key, role)).map((c) => c.key);
      let key;
      if (i in chosen) {
        key = chosen[i].key;
        steps.push(champStep(every, role, key, every.length > 1 ? 48 : 10, (every.length > 1 ? 48 : 10) - 6)[1]);
      } else {
        const pool = every.filter((k) => !takenChamps.has(k));
        key = pick(pool);
        steps.push(champStep(pool, role, key, pool.length > 1 ? 48 : 10, (pool.length > 1 ? 48 : 10) - 6)[1]);
      }
      takenChamps.add(key);
      out[i] = { i, name: p.name, role, key, steps, randomRole: p.role === "random" };
    }
    return { players: out, chaos: !!chaos };
  }

  function groupReroll(g, i) {
    const p = g.players[i];
    const others = new Set(g.players.filter((q, j) => j !== i).map((q) => q.key));
    const every = g.chaos ? CHAMPS.map((c) => c.key) : CHAMPS.filter((c) => hasRole(c.key, p.role)).map((c) => c.key);
    const pool = every.filter((k) => !others.has(k) && k !== p.key);
    if (!pool.length) return { error: t("Plus aucun autre champion disponible pour ce poste.") };
    const key = pick(pool);
    return { player: Object.assign({}, p, { key, steps: [champStep(pool, p.role, key, 48, 42)[1]], randomRole: false }) };
  }

  // =============================================================================================================
  // Small UI services
  // =============================================================================================================
  function toast(text, tone = "gold", ms = 4600) {
    const box = document.getElementById("toasts");
    const el = document.createElement("div");
    el.className = `toast t-${tone}`;
    el.innerHTML = `<span>${esc(text)}</span>`;
    box.appendChild(el);
    while (box.children.length > 4) box.firstElementChild.remove();
    setTimeout(() => {
      el.classList.add("out");
      setTimeout(() => el.remove(), 320);
    }, ms);
  }
  let status = { text: "", tone: "muted" };
  function setStatus(text, tone = "muted") {
    status = { text, tone };
    const s = document.querySelector("#status");
    if (s) {
      s.textContent = text;
      s.className = `status-line t-${tone}`;
    }
  }
  function confirmBox(text, okLabel) {
    return new Promise((resolve) => {
      const m = document.getElementById("modal");
      m.innerHTML = `<div class="modal-box" style="width:auto;max-width:520px"><div style="padding:34px 36px 28px">
        <div class="card-title">${esc(t("Confirmation"))}</div><p class="prose">${esc(text)}</p>
        <div class="row" style="justify-content:flex-end;margin-top:22px;gap:10px"><button class="btn" data-a="no">${esc(t("Annuler"))}</button><button class="btn-gold" data-a="yes">${esc(okLabel)}</button></div></div></div>`;
      m.hidden = false;
      const close = (v) => {
        m.hidden = true;
        m.innerHTML = "";
        resolve(v);
      };
      m.onclick = (e) => e.target === m && close(false);
      m.querySelector('[data-a="no"]').onclick = () => close(false);
      m.querySelector('[data-a="yes"]').onclick = () => close(true);
    });
  }

  // logo: the wheel spins like a real roulette (momentum, slowdown, stops in the middle of a slot)
  let logoAngle = 0, logoAnim = null;
  function spinLogo(turns = 1.2) {
    const wheel = document.querySelector("#top .l-wheel");
    const ptr = document.querySelector("#top .l-ptr");
    if (!wheel) return;
    const want = turns * 360;
    if (logoAnim && logoAnim.end - logoAngle >= want) return;
    const start = logoAngle;
    let end = start + want + Math.random() * 360 * Math.min(1, turns);
    end = end - (end % 36) + 18;
    const dur = 1100 + ((end - start) / 360) * 650;
    const t0 = performance.now();
    const anim = { end };
    logoAnim = anim;
    let seg = Math.floor(start / 36);
    const frame = (now) => {
      if (logoAnim !== anim) return;
      const k = Math.min(1, (now - t0) / dur);
      logoAngle = start + (end - start) * (1 - Math.pow(1 - k, 3));
      wheel.style.transform = `rotate(${logoAngle.toFixed(2)}deg)`;
      const s = Math.floor(logoAngle / 36);
      if (s !== seg && ptr) {
        seg = s;
        ptr.classList.remove("tick");
        void ptr.offsetWidth;
        ptr.classList.add("tick");
      }
      if (k < 1) requestAnimationFrame(frame);
      else logoAnim = null;
    };
    requestAnimationFrame(frame);
  }

  // hextech background mechanism: kick on launch, then the role ring stops on the rolled role
  const mechAngles = { m1: 0, m2: 0, m3: 0, m4: 0 };
  function mechTurn(cls, deg, ms, set = false) {
    const im = document.querySelector(`.bg-mech .${cls} img`);
    if (!im) return;
    mechAngles[cls] = set ? deg : mechAngles[cls] + deg;
    im.style.transition = ms ? `transform ${ms}ms cubic-bezier(.12,.72,.18,1)` : "none";
    im.style.transform = `rotate(${mechAngles[cls].toFixed(1)}deg)`;
  }
  function mechKick() {
    mechTurn("m1", 110 + Math.random() * 60, 5200);
    mechTurn("m2", -(150 + Math.random() * 80), 4600);
    mechTurn("m4", 200 + Math.random() * 90, 3800);
    mechTurn("m3", 540 + Math.random() * 180, 6000);
  }
  function mechRole(role) {
    const i = ROLES.indexOf(role);
    if (i < 0) return;
    let target = 180 - i * 72;
    while (target < mechAngles.m3 + 200) target += 360;
    mechTurn("m3", target, 2600, true);
  }

  // background: blurred art of the champion on screen
  let bdIndex = 0, bdKey = null;
  function backdrop(key) {
    if (!key || key === bdKey) return;
    bdKey = key;
    const layers = document.querySelectorAll("#backdrop .bd-layer");
    const next = layers[bdIndex % 2], prev = layers[(bdIndex + 1) % 2];
    const im = new Image();
    im.onload = () => {
      next.style.backgroundImage = `url("${img.splash(key)}")`;
      next.classList.add("on");
      prev.classList.remove("on");
      bdIndex++;
    };
    im.src = img.splash(key);
  }

  function preload(urls) {
    return Promise.all([...new Set(urls)].map((u) => new Promise((res) => {
      const im = new Image();
      im.onload = im.onerror = res;
      im.src = u;
    })));
  }
  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }
  const easeOut = (x) => 1 - Math.pow(1 - x, 4);

  // =============================================================================================================
  // Roulette page
  // =============================================================================================================
  let root = null;
  let role = "random";
  let champ = null;
  let spinning = false;
  let mode = ls.get("mode", "solo") === "group" ? "group" : "solo";
  let lastRoll = ls.get("last", null);   // last solo roll: shown by the idle strip
  let gPlayers = ls.get("group_players", null) || [{ name: "", role: "random", champ: "" }, { name: "", role: "random", champ: "" }];
  let gResult = null;
  let gChaos = false;
  const CARD_W = 124, GAP = 12, STEP = CARD_W + GAP;
  const GCARD = 92, GSTEP = GCARD + 8;

  function renderRoulette(page) {
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
        <button class="btn-gold launch" id="launch"><span class="lt">${esc(t("Lancer"))}</span></button>
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
    setStatus(status.text, status.tone);
    page.querySelector("#launch").onclick = () => launch();
    page.querySelectorAll(".mode-tab").forEach((b) => (b.onclick = () => {
      if (spinning) return;
      mode = b.dataset.mode;
      ls.set("mode", mode);
      paintMode();
    }));
    paintMode();
    renderWelcome(page.querySelector("#stage"));
  }

  function paintRoles() {
    const box = root.querySelector("#roles");
    box.innerHTML = [...ROLES, "random", "chaos"].map((r) => `
      <button class="role-btn${r === role ? " on" : ""}${r === "chaos" ? " chaos" : ""}" data-r="${r}" title="${esc(r === "random" ? t("Rôle au hasard (touche 0)") : r === "chaos" ? t("Chaos : n'importe quel champion à n'importe quel poste (Yuumi jungle…).") : t("{0} (touche {1})", roleLabel(r), ROLES.indexOf(r) + 1))}">
        ${r === "chaos" ? CHAOS_ICON : roleIcon(r)}<span>${r === "chaos" ? "Chaos" : esc(roleLabel(r))}</span>${profile.favRoles.includes(r) ? `<i class="fav-dot" title="${esc(t("Rôle favori"))}"></i>` : ""}
      </button>`).join("");
    box.querySelectorAll(".role-btn").forEach((b) => (b.onclick = () => {
      role = b.dataset.r;
      paintRoles();
    }));
  }

  function paintFilters() {
    const chips = [
      ["onlyFavRoles", `${esc(t("Rôles favoris seulement"))} <span class="n">${profile.favRoles.length}</span>`],
      ["onlyFavChamps", `${esc(t("Champions favoris seulement"))} <span class="n">${profile.favChamps.length}</span>`],
      ["noRepeat", esc(t("Pas de doublon dans la session"))],
    ];
    const box = root.querySelector("#filters");
    box.innerHTML = `<span class="ctl-label" style="margin:0 6px 0 2px">${esc(t("Filtres"))}</span>` +
      chips.map(([k, l]) => `<button class="chip${profile[k] ? " on" : ""}" data-k="${k}"><span class="ck"></span>${l}</button>`).join("");
    box.querySelectorAll(".chip").forEach((c) => (c.onclick = () => {
      profile[c.dataset.k] = !profile[c.dataset.k];
      saveProfile();
      paintFilters();
    }));
  }

  function setupChampField() {
    const input = root.querySelector("#cf-input"), dd = root.querySelector("#cf-dd"), clear = root.querySelector("#cf-clear");
    let act = 0, items = [];
    if (champ) {
      input.value = nameOf(champ.key);
      showChampInfo();
    }
    const render = () => {
      const q = norm(input.value);
      if (!q) return (dd.hidden = true);
      const all = sortedChamps();
      const starts = all.filter((c) => norm(c.fr).startsWith(q) || norm(c.en).startsWith(q));
      const contains = all.filter((c) => !starts.includes(c) && (norm(c.fr).includes(q) || norm(c.en).includes(q)));
      items = [...starts, ...contains].slice(0, 12);
      if (!items.length) {
        dd.innerHTML = `<div class="dd-item muted">${esc(t("Aucun champion ne correspond."))}</div>`;
        dd.hidden = false;
        return;
      }
      act = Math.min(act, items.length - 1);
      dd.innerHTML = items.map((c, i) => `
        <div class="dd-item${i === act ? " act" : ""}" data-i="${i}"><img src="${img.icon(c.key)}" alt=""><span>${esc(nameOf(c.key))}</span>
          <span class="dd-roles">${c.roles.map((r) => roleIcon(r.role)).join("")}</span></div>`).join("");
      dd.hidden = false;
      dd.querySelectorAll(".dd-item[data-i]").forEach((it) => (it.onmousedown = (e) => {
        e.preventDefault();
        pickChamp(items[+it.dataset.i]);
      }));
    };
    const pickChamp = (c) => {
      champ = c;
      input.value = nameOf(c.key);
      dd.hidden = true;
      showChampInfo();
    };
    input.oninput = () => {
      act = 0;
      champ = null;
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
        if (!dd.hidden && items[act]) pickChamp(items[act]);
        else launch();
      } else if (e.key === "Escape") dd.hidden = true;
    };
    input.onblur = () => setTimeout(() => (dd.hidden = true), 120);
    input.onfocus = () => input.value && !champ && render();
    clear.onclick = () => {
      input.value = "";
      champ = null;
      showChampInfo();
      input.focus();
    };
  }

  function showChampInfo() {
    const info = root.querySelector("#cf-info"), icon = root.querySelector("#cf-icon"), input = root.querySelector("#cf-input");
    root.querySelector("#cf-clear").hidden = !input.value;
    if (champ) {
      info.innerHTML = champ.roles.map((r) => `${esc(roleLabel(r.role))}${profile.favChamps.includes(champ.key) ? " ★" : ""} ${pct(r.share)}`).join(" · ");
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

  // --- roulette strip ---------------------------------------------------------------------------------------
  const champCard = (key) => `<div class="scard" style="background-image:url('${img.tall(key)}')"><b>${esc(nameOf(key))}</b></div>`;
  const roleCard = (r) => `<div class="scard role">${roleIcon(r)}<b>${esc(roleLabel(r).toUpperCase())}</b></div>`;

  function idleStrip() {
    const strip = root.querySelector("#strip"), track = root.querySelector("#track");
    const favs = CHAMPS.filter((c) => profile.favChamps.includes(c.key));
    const pool = shuffle([...(favs.length >= 12 ? favs : CHAMPS)]).slice(0, 22);
    const cards = pool.map((c) => champCard(c.key)).join("");
    track.style.transform = "";
    track.innerHTML = cards + cards;
    strip.className = "strip idle";
    paintStripRoll();
  }

  // last roll: the idle strip becomes its card (splash, name, role) with "View on u.gg"
  function paintStripRoll() {
    const strip = root && root.querySelector("#strip");
    if (!strip || !strip.classList.contains("idle")) return;
    strip.classList.toggle("has-roll", !!lastRoll);
    let box = strip.querySelector(".strip-roll");
    if (!lastRoll) {
      if (box) box.remove();
      return;
    }
    if (!box) {
      box = document.createElement("div");
      box.className = "strip-roll";
      strip.appendChild(box);
    }
    const r = lastRoll;
    box.innerHTML = `
      <div class="sr-art" style="background-image:url('${img.splash(r.key)}')"></div><div class="sr-shade"></div>
      <div class="sr-body">
        <div class="sr-card" style="background-image:url('${img.tall(r.key)}')"></div>
        <div class="sr-info">
          <div class="sr-kick">${esc(t("Ton tirage"))}</div>
          <div class="sr-name">${esc(nameOf(r.key))}</div>
          <div class="sr-role">${roleIcon(r.role)}<span>${esc(roleLabel(r.role))}</span>${r.mode ? `<em>${esc(MODE_LABEL()[r.mode] || "")}</em>` : ""}</div>
          <div class="sr-sub">${esc(t("Bonne partie ! Le build du moment est sur u.gg."))}</div>
          <div class="sr-act"><a class="btn-gold sr-guide" data-ugg href="${ugg(r.key, r.role)}" target="_blank" rel="noopener">${UGG_SVG}${esc(t("Voir sur u.gg"))}</a></div>
        </div>
      </div>
      <div class="sr-promo">
        <div class="kicker">${esc(t("Dans l'appli"))}</div>
        <p>${esc(t("Ce tirage serait suivi dans LoL jusqu'au résultat : autofill, ban, victoire et LP, tout part dans ton historique."))}</p>
        <a class="sr-promo-link" href="#/app">${esc(t("Découvrir l'appli →"))}</a>
      </div>`;
  }

  function spinStep(step, duration) {
    const strip = root.querySelector("#strip"), track = root.querySelector("#track");
    const isRole = step.type === "role";
    track.innerHTML = step.seq.map((x) => (isRole ? roleCard(x) : champCard(x))).join("");
    strip.className = "strip spinning";
    const W = strip.clientWidth;
    const start = W / 2 - CARD_W / 2 - STEP * 2;
    const jitter = (Math.random() - 0.5) * CARD_W * 0.64;
    const end = W / 2 - (step.index * STEP + CARD_W / 2) + jitter;
    track.style.transform = `translate3d(${start}px,0,0)`;
    return new Promise((resolve) => {
      const t0 = performance.now();
      const frame = (now) => {
        const k = Math.min(1, (now - t0) / duration);
        track.style.transform = `translate3d(${start + (end - start) * easeOut(k)}px,0,0)`;
        if (k < 1) return requestAnimationFrame(frame);
        const centered = W / 2 - (step.index * STEP + CARD_W / 2);
        track.style.transition = "transform .35s cubic-bezier(.2,.8,.2,1)";
        track.style.transform = `translate3d(${centered}px,0,0)`;
        setTimeout(() => (track.style.transition = ""), 380);
        track.children[step.index].classList.add("win");
        strip.className = "strip done";
        celebrate(strip);
        setTimeout(resolve, 420);
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
    spinning = on;
    const b = root.querySelector("#launch");
    if (b) b.disabled = on;
    root.querySelectorAll(".role-btn, .chip, #cf-input, .gp-row input, .gp-role, .gp-add, .gp-del, .mode-tab, [data-reroll]").forEach((x) => (x.disabled = on));
  }

  async function launch() {
    if (spinning || !root) return;
    if (mode === "group") return launchGroup();
    const r = soloRoll(role, champ ? nameOf(champ.key) : root.querySelector("#cf-input").value || "");
    if (r.error) {
      setStatus(r.error, "warn");
      toast(r.error, "warn");
      return;
    }
    lock(true);
    spinLogo(3.5);
    mechKick();
    if (!r.steps.some((s) => s.type === "role")) setTimeout(() => mechRole(r.result.role), 1800);
    try {
      const urls = [];
      for (const s of r.steps) if (s.type === "champ") s.seq.forEach((k) => urls.push(img.tall(k)));
      await Promise.race([preload(urls), sleep(4000)]);
      for (const n of r.notes) setStatus(n, "warn");
      for (const step of r.steps) {
        if (step.type === "role") {
          const roles = ROLES.filter((x) => step.seq.includes(x)).map(roleLabel);
          if (!r.notes.length) setStatus(t("Roulette du rôle… ({0})", roles.join(", ")), "gold");
          await spinStep(step, 2600);
          mechRole(step.seq[step.index]);
          setStatus(t("Rôle : {0}", roleLabel(step.seq[step.index])), "gold");
          await sleep(520);
        } else {
          const fav = profile.onlyFavChamps ? t(" parmi tes favoris") : "";
          setStatus(step.pool > 1 ? t("Roulette {0}… ({1} champions en jeu{2})", roleLabel(step.role), step.pool, fav)
            : t("Roulette {0}… ({1} champion en jeu{2})", roleLabel(step.role), step.pool, fav), "gold");
          await spinStep(step, step.pool > 1 ? 4200 : 1600);
        }
      }
      const res = Object.assign({ mode: r.mode }, r.result);
      drawn.add(res.key + "|" + res.role);
      addRecent(res);
      lastRoll = res;
      ls.set("last", res);
      backdrop(res.key);
      await sleep(1300);
      if (!root || !document.body.contains(root)) return;
      idleStrip();
      renderWelcome(root.querySelector("#stage"));
      setStatus(t("Ton tirage : {0} {1}. Bonne partie !", nameOf(res.key), roleLabel(res.role)), "gold");
    } finally {
      lock(false);
    }
  }

  // --- group roulette ---------------------------------------------------------------------------------------
  const initial = (p, i) => (String(p.name || "").trim().charAt(0) || String(i + 1)).toUpperCase();
  const playerName = (p, i) => String(p.name || "").trim() || t("Joueur {0}", i + 1);
  const saveGroup = () => ls.set("group_players", gPlayers);

  function paintMode() {
    root.querySelectorAll(".mode-tab").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
    const group = mode === "group";
    root.querySelector(".controls").classList.toggle("group", group);
    root.querySelector("#strip").hidden = group;
    root.querySelector("#gstrips").hidden = !group;
    root.querySelector("#gresult").hidden = !group;
    if (group) {
      paintGroupPanel();
      paintGroupStrips();
      if (gResult) paintGroupResult();
    }
  }

  function paintGroupPanel() {
    const box = root.querySelector("#gpanel");
    const taken = (i) => new Set(gPlayers.filter((p, j) => j !== i && p.role !== "random").map((p) => p.role));
    box.innerHTML = `
      <div class="gp-head"><span class="ctl-label">${esc(t("Joueurs · {0} / 5", gPlayers.length))}</span><span class="gp-src"><span class="gp-hint">${esc(t("Chacun reçoit un poste et un champion différents."))}</span></span>
        <button class="chip chaos${gChaos ? " on" : ""}" data-gchaos title="${esc(t("N'importe quel champion à n'importe quel poste, pour tout le groupe"))}">${CHAOS_ICON}Chaos</button></div>
      <div class="gp-rows">${gPlayers.map((p, i) => {
        const tk = taken(i);
        return `<div class="gp-row" data-i="${i}">
          <span class="gp-av">${esc(initial(p, i))}</span>
          <input class="input gp-name" value="${esc(p.name)}" placeholder="${esc(t("Pseudo du joueur {0}", i + 1))}" maxlength="24" spellcheck="false">
          <div class="gp-roles">${["random", ...ROLES].map((r) => `<button class="gp-role${p.role === r ? " on" : ""}" data-role="${r}" ${r !== "random" && tk.has(r) ? "disabled" : ""} title="${esc(r === "random" ? t("Poste au hasard") : roleLabel(r))}">${roleIcon(r)}</button>`).join("")}</div>
          <input class="input gp-champ" list="gp-champs" value="${esc(p.champ)}" placeholder="${esc(t("Champion au hasard"))}" spellcheck="false">
          ${gPlayers.length > 2 ? `<button class="gp-del" title="${esc(t("Retirer ce joueur"))}">×</button>` : `<span class="gp-me"></span>`}
        </div>`;
      }).join("")}</div>
      ${gPlayers.length < 5 ? `<button class="gp-add">${esc(t("+ Ajouter un joueur"))}</button>` : ""}
      <datalist id="gp-champs">${sortedChamps().map((c) => `<option value="${esc(nameOf(c.key))}">`).join("")}</datalist>`;
    box.querySelector("[data-gchaos]").onclick = () => {
      gChaos = !gChaos;
      paintGroupPanel();
    };
    box.querySelectorAll(".gp-row").forEach((row) => {
      const i = +row.dataset.i, p = gPlayers[i];
      const nm = row.querySelector(".gp-name");
      nm.oninput = () => {
        p.name = nm.value;
        saveGroup();
        row.querySelector(".gp-av").textContent = initial(p, i);
        const g = root.querySelector(`.gs-row[data-i="${i}"] .gs-id b`);
        if (g) g.textContent = playerName(p, i);
      };
      row.querySelectorAll(".gp-role").forEach((b) => (b.onclick = () => {
        p.role = b.dataset.role;
        saveGroup();
        paintGroupPanel();
        paintGroupStrips();
      }));
      const ch = row.querySelector(".gp-champ");
      ch.oninput = () => {
        p.champ = ch.value;
        saveGroup();
      };
      const del = row.querySelector(".gp-del");
      if (del) del.onclick = () => {
        gPlayers.splice(i, 1);
        saveGroup();
        paintGroupPanel();
        paintGroupStrips();
      };
    });
    const add = box.querySelector(".gp-add");
    if (add) add.onclick = () => {
      gPlayers.push({ name: "", role: "random", champ: "" });
      saveGroup();
      paintGroupPanel();
      paintGroupStrips();
      const inputs = box.querySelectorAll(".gp-name");
      inputs[inputs.length - 1].focus();
    };
  }

  const gCard = (key) => `<div class="gcard" style="background-image:url('${img.tall(key)}')"><b>${esc(nameOf(key))}</b></div>`;
  const roleChip = (p) => (p.role && p.role !== "random" ? `${roleIcon(p.role)}<span>${esc(roleLabel(p.role))}</span>` : `<i class="gs-q">?</i><span>${esc(t("poste au hasard"))}</span>`);

  function paintGroupStrips() {
    const box = root.querySelector("#gstrips");
    box.innerHTML = gPlayers.map((p, i) => {
      const cards = shuffle([...CHAMPS]).slice(0, 16).map((c) => gCard(c.key)).join("");
      return `<div class="gs-row idle" data-i="${i}">
        <div class="gs-who"><span class="gs-av">${esc(initial(p, i))}</span>
          <div class="gs-id"><b>${esc(playerName(p, i))}</b><span class="gs-role">${roleChip(p)}</span></div></div>
        <div class="gs-strip"><div class="gs-track">${cards}${cards}</div><i class="gs-mark"></i></div>
      </div>`;
    }).join("");
  }

  function spinRow(row, pl, duration) {
    const strip = row.querySelector(".gs-strip"), track = row.querySelector(".gs-track");
    const step = pl.steps[pl.steps.length - 1];
    track.innerHTML = step.seq.map((k) => gCard(k)).join("");
    row.className = "gs-row spinning";
    if (pl.randomRole) row.querySelector(".gs-role").innerHTML = `<i class="gs-q spin">?</i><span>${esc(t("poste au hasard…"))}</span>`;
    const W = strip.clientWidth;
    const start = W / 2 - GCARD / 2 - GSTEP * 2;
    const jitter = (Math.random() - 0.5) * GCARD * 0.6;
    const end = W / 2 - (step.index * GSTEP + GCARD / 2) + jitter;
    track.style.transition = "";
    track.style.transform = `translate3d(${start}px,0,0)`;
    return new Promise((resolve) => {
      const t0 = performance.now();
      const frame = (now) => {
        const k = Math.min(1, (now - t0) / duration);
        track.style.transform = `translate3d(${start + (end - start) * easeOut(k)}px,0,0)`;
        if (k < 1) return requestAnimationFrame(frame);
        const centered = W / 2 - (step.index * GSTEP + GCARD / 2);
        track.style.transition = "transform .35s cubic-bezier(.2,.8,.2,1)";
        track.style.transform = `translate3d(${centered}px,0,0)`;
        track.children[step.index].classList.add("win");
        row.className = "gs-row done";
        row.querySelector(".gs-role").innerHTML = `${roleIcon(pl.role)}<span>${esc(roleLabel(pl.role))}</span>`;
        setTimeout(resolve, 380);
      };
      requestAnimationFrame(frame);
    });
  }

  async function launchGroup() {
    const r = groupRoll(gPlayers, gChaos);
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
      r.players.forEach((pl) => pl.steps[pl.steps.length - 1].seq.forEach((k) => urls.push(img.tall(k))));
      await Promise.race([preload(urls), sleep(5000)]);
      root.querySelector("#gresult").innerHTML = "";
      paintGroupStrips();
      const rows = [...root.querySelectorAll(".gs-row")];
      await Promise.all(r.players.map((pl, i) => spinRow(rows[i], pl, 2300 + i * 750)));
      gResult = r;
      addRecent({ key: r.players[0].key, role: r.players[0].role, mode: "group", group: r.players.map((p) => ({ name: p.name, i: p.i, key: p.key, role: p.role })) });
      setStatus(t("Tirage du groupe enregistré."), "gold");
      paintGroupResult();
      renderWelcome(root.querySelector("#stage"));
    } finally {
      lock(false);
    }
  }

  function paintGroupResult() {
    const box = root.querySelector("#gresult");
    if (!gResult) return (box.innerHTML = "");
    box.innerHTML = `<section class="card gres page-enter">
      <h3 class="card-title">${esc(t("Le tirage du groupe"))}<span class="aside"><button class="gr-copy" data-copy>${COPY_SVG}${esc(t("Copier"))}</button></span></h3>
      <div class="gres-row">${gResult.players.map((p) => `
        <div class="gres-card" style="--art:url('${img.tall(p.key)}')">
          <span class="gr-who">${esc(playerLabel(p))}</span>
          <div class="gr-foot">
            <b>${esc(nameOf(p.key))}</b>
            <span class="gr-role">${roleIcon(p.role)}${esc(roleLabel(p.role))}</span>
            <div class="gr-act"><a class="btn sm" href="${ugg(p.key, p.role)}" target="_blank" rel="noopener" title="${esc(t("Ouvre la page u.gg de ce champion à ce poste dans ton navigateur"))}">u.gg</a><button class="btn sm" data-reroll="${p.i}" title="${esc(t("Nouveau champion au même poste (banni, déjà pris…)"))}">${esc(t("Relancer"))}</button></div>
          </div>
        </div>`).join("")}</div>
    </section>`;
    box.querySelectorAll("[data-reroll]").forEach((b) => (b.onclick = () => rerollOne(+b.dataset.reroll)));
    box.querySelector("[data-copy]").onclick = copyGroup;
  }

  async function rerollOne(i) {
    if (spinning || !gResult) return;
    const r = groupReroll(gResult, i);
    if (r.error) return toast(r.error, "warn");
    lock(true);
    try {
      await Promise.race([preload(r.player.steps[0].seq.map((k) => img.tall(k))), sleep(4000)]);
      const row = root.querySelector(`.gs-row[data-i="${i}"]`);
      if (row) await spinRow(row, r.player, 1900);
      gResult.players[i] = r.player;
      paintGroupResult();
      setStatus(t("{0} : {1} {2}.", playerLabel(r.player), nameOf(r.player.key), roleLabel(r.player.role)), "gold");
    } finally {
      lock(false);
    }
  }

  async function copyGroup() {
    const lines = [t("🎲 Roulette of Legends · tirage du groupe"), ...gResult.players.map((p) => t("• {0} : {1} ({2})", playerLabel(p), nameOf(p.key), roleLabel(p.role)))];
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

  // --- home: introduction and recent rolls --------------------------------------------------------------------
  function recentSub(e) {
    const when = new Date(e.at).toLocaleDateString(LANG === "en" ? "en-US" : "fr-FR", { day: "numeric", month: "short" });
    return `${roleLabel(e.role)} · ${MODE_LABEL()[e.mode] || ""} · ${when}`;
  }
  function renderWelcome(stage) {
    const hero = (lastRoll && lastRoll.key) || heroKey;
    backdrop(hero);
    stage.innerHTML = `
    <div class="welcome page-enter">
      <section class="card w-hero">
        <div class="w-art" style="background-image:url('${img.splash(hero)}')"></div><div class="w-shade"></div>
        <div class="kicker">${esc(t("La Faille décide pour toi"))}</div>
        <h1 class="w-brand">Roulette<small>of</small>Legends</h1>
        <p class="w-text">${esc(t("Choisis un rôle, un champion, ou laisse la roulette tout décider. Seul, ou avec tes potes grâce à la roulette de groupe."))}</p>
        <div class="w-feats">
          <div class="w-feat"><b>${esc(t("Groupe"))}</b><span>${esc(t("Jusqu'à 5 joueurs : postes et champions différents pour tout le monde, prêts à copier sur Discord."))}</span></div>
          <div class="w-feat"><b>${esc(t("Chaos"))}</b><span>${esc(t("N'importe quel champion à n'importe quel poste. Yuumi jungle, quelqu'un ?"))}</span></div>
          <div class="w-feat"><b>u.gg</b><span>${esc(t("Après le tirage, un clic ouvre la page u.gg du champion à ce poste."))}</span></div>
        </div>
      </section>
      <section class="card">
        <h3 class="card-title">${esc(t("Derniers tirages"))}<span class="aside"><a href="#/rolls" class="t-gold">${esc(t("Tous tes tirages →"))}</a></span></h3>
        ${recent.length ? `<div class="recent-list scroll">${recent.slice(0, 12).map((e) => `
          <a class="recent-item" href="${ugg(e.key, e.role)}" target="_blank" rel="noopener" title="${esc(t("Voir sur u.gg"))}"><img src="${img.icon(e.key)}" alt="">
            <div><div class="ri-name">${esc(nameOf(e.key))}${e.group ? ` <span class="t-muted">+${e.group.length - 1}</span>` : ""}</div><div class="ri-sub">${esc(recentSub(e))}</div></div>
            <span class="ri-glyph t-gold">↗</span></a>`).join("")}</div>`
          : `<div class="empty">${esc(t("Aucun tirage pour l'instant."))}<br>${esc(t("Appuie sur « Lancer » !"))}</div>`}
      </section>
      <section class="card promo-card">
        <div class="pc-text">
          <div class="kicker">${esc(t("Plus utile sur ton PC"))}</div>
          <h3>${esc(t("Installe l'appli"))}</h3>
          <p class="muted">${esc(t("La même roulette, reliée à LoL : tes tirages suivis jusqu'au résultat, ton historique et tes LP. La version complète ajoute les fiches de jeu, le build importé et un overlay en partie."))}</p>
        </div>
        <div class="pc-feats">${[t("Suivi dans LoL"), t("Historique et LP"), t("Fiches de jeu"), t("Overlay en jeu")].map((x) => `<span class="pc-feat">${esc(x)}</span>`).join("")}</div>
        <a class="btn-gold" href="#/app">${esc(t("Voir les applis"))}</a>
      </section>
    </div>`;
  }

  // =============================================================================================================
  // Apps page: the Lite and the full desktop app
  // =============================================================================================================
  function downloadButton(which, label, cls = "btn-gold") {
    return DOWNLOADS[which]
      ? `<a class="${cls} dl" href="${esc(DOWNLOADS[which])}" rel="noopener" data-track="${which}">${DOWNLOAD_SVG}${esc(label)}</a>`
      : `<button class="${cls}" disabled title="${esc(t("Bientôt disponible"))}">${esc(label)}</button>`;
  }
  function renderApps(page) {
    root = page;
    backdrop(heroKey);
    const list = (items) => `<ul class="app-list">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    const rows = [
      [t("Roulette solo et de groupe, chaos"), 1, 1, 1],
      [t("Favoris"), 1, 1, 1],
      [t("Tirage suivi dans le client LoL (autofill, ban, champion pris)"), 0, 1, 1],
      [t("Historique, résultats et LP"), 0, 1, 1],
      [t("Fiches de jeu pour chaque champion à chaque poste"), 0, 0, 1],
      [t("Runes, sorts et set d'objets importés dans LoL"), 0, 0, 1],
      [t("Overlay en jeu"), 0, 0, 1],
      [t("Page Partie : les deux équipes et leurs classements"), 0, 0, 1],
    ];
    const mark = (on) => `<td class="${on ? "yes" : "no"}">${on ? "✓" : "—"}</td>`;
    const guides = D.champions.reduce((n, c) => n + c.roles.length, 0);
    page.innerHTML = `
    <div class="page-enter">
      <header class="page-head"><div>
        <div class="kicker">${esc(t("Sur ton PC"))}</div>
        <h1 class="page-title">${esc(t("App"))}</h1>
        <p class="page-sub muted">${esc(t("Le site, c'est la roulette. L'appli la relie à League of Legends : elle suit chaque tirage jusqu'au bout et remplit ton historique toute seule."))}</p>
      </div></header>
      <div class="apps">
        <section class="card app-card">
          <div class="kicker">Lite</div>
          <h2>Roulette of Legends Lite</h2>
          <p class="app-tag">${esc(t("La roulette, reliée à LoL"))}</p>
          ${list([
            t("Ton tirage est suivi dans le client : autofill, ban ou champion pris détectés, relance en un clic."),
            t("Résultat, KDA et LP ajoutés à ton historique, même pour les parties jouées sans la roulette."),
            t("Roulette de groupe avec les pseudos de ton salon LoL."),
            t("Discrète : elle attend près de l'horloge et peut se lancer avec Windows."),
          ])}
          <div class="app-dl">${downloadButton("lite_win", t("Windows"), "btn")}${downloadButton("lite_mac", t("Mac"), "btn")}</div>
          <p class="app-note">${esc(DOWNLOADS.lite_win ? t("Mac (Apple Silicon) : au premier lancement, ouvre Réglages Système › Confidentialité et sécurité, puis « Ouvrir quand même ».")
            : t("Bientôt disponible."))}</p>
        </section>
        <section class="card app-card full">
          <div class="kicker">${esc(t("Pour aller plus loin"))}</div>
          <h2>Roulette of Legends</h2>
          <p class="app-tag">${esc(t("Tout pour jouer ton tirage"))}</p>
          <p class="app-plus">${esc(t("Tout ce que fait la Lite, plus :"))}</p>
          ${list([
            t("Une fiche pour chaque champion à chaque poste ({0}) : plan de lane, matchups, mid & late.", guides),
            t("Runes, sorts d'invocateur et set d'objets importés dans LoL dès que tu verrouilles."),
            t("Overlay en jeu (Tab) : ta fiche, tes stats, l'écart d'or, le sort à monter sur ton HUD."),
            t("Page Partie : les deux équipes, leurs classements et ce que veut chaque adversaire."),
          ])}
          <div class="app-dl">${downloadButton("full_win", t("Windows"))}</div>
          <p class="app-note">${esc(t("Windows 10 et 11. L'overlay en jeu n'existe pas encore sur Mac."))}</p>
        </section>
      </div>
      <section class="card cmp-card">
        <h3 class="card-title">${esc(t("Comparer"))}</h3>
        <table class="cmp">
          <thead><tr><th></th><th>${esc(t("Site"))}</th><th>Lite</th><th>${esc(t("Complète"))}</th></tr></thead>
          <tbody>${rows.map(([label, a, b, c]) => `<tr><th>${esc(label)}</th>${mark(a)}${mark(b)}${mark(c)}</tr>`).join("")}</tbody>
        </table>
        <p class="muted cmp-note">${esc(t("Gratuites et sans compte. Les applis lisent le client LoL sans jamais jouer à ta place : aucun pick, ban ou verrouillage."))}</p>
      </section>
    </div>`;
  }

  // =============================================================================================================
  // Favorites page
  // =============================================================================================================
  const favState = { q: "", role: "all", only: false };
  function renderFavorites(page) {
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
    paintFavRoles();
    paintFavTools();
    paintFavGrid();
  }
  function paintFavRoles() {
    const box = root.querySelector("#f-roles");
    box.innerHTML = ROLES.map((r) => `<button class="role-btn${profile.favRoles.includes(r) ? " on" : ""}" data-r="${r}">${roleIcon(r)}<span>${esc(roleLabel(r))}</span></button>`).join("");
    box.querySelectorAll(".role-btn").forEach((b) => (b.onclick = () => {
      const r = b.dataset.r;
      profile.favRoles = profile.favRoles.includes(r) ? profile.favRoles.filter((x) => x !== r) : [...profile.favRoles, r];
      saveProfile();
      paintFavRoles();
      paintFavCount();
    }));
  }
  function paintFavTools() {
    const box = root.querySelector("#f-tools");
    box.innerHTML = `
      <input class="input" id="f-q" placeholder="${esc(t("Rechercher un champion…"))}" value="${esc(favState.q)}" spellcheck="false">
      ${["all", ...ROLES].map((r) => `<button class="chip${favState.role === r ? " on" : ""}" data-role="${r}">${r === "all" ? esc(t("Tous")) : roleIcon(r) + esc(roleLabel(r))}</button>`).join("")}
      <button class="chip${favState.only ? " on" : ""}" data-only><span class="ck"></span>${esc(t("Favoris uniquement"))}</button>
      <span class="grow"></span>
      <span class="t-teal small" id="f-count"></span>
      <button class="btn sm danger" id="f-clear">${esc(t("Tout retirer"))}</button>`;
    const q = box.querySelector("#f-q");
    q.oninput = () => {
      favState.q = q.value;
      paintFavGrid();
    };
    box.querySelectorAll("[data-role]").forEach((c) => (c.onclick = () => {
      favState.role = c.dataset.role;
      paintFavTools();
      paintFavGrid();
    }));
    box.querySelector("[data-only]").onclick = () => {
      favState.only = !favState.only;
      paintFavTools();
      paintFavGrid();
    };
    box.querySelector("#f-clear").onclick = async () => {
      if (!(await confirmBox(t("Retirer tous tes champions et rôles favoris ?"), t("Tout retirer")))) return;
      profile.favChamps = [];
      profile.favRoles = [];
      saveProfile();
      paintFavRoles();
      paintFavGrid();
      paintFavCount();
    };
    paintFavCount();
  }
  function paintFavCount() {
    const c = root.querySelector("#f-count");
    const nc = profile.favChamps.length, nr = profile.favRoles.length;
    if (c) c.textContent = (nc > 1 ? t("{0} champions favoris", nc) : t("{0} champion favori", nc)) + " · " + (nr > 1 ? t("{0} rôles favoris", nr) : t("{0} rôle favori", nr));
  }
  function paintFavGrid() {
    const q = norm(favState.q);
    const list = sortedChamps().filter((c) => {
      if (q && !norm(c.fr).includes(q) && !norm(c.en).includes(q)) return false;
      if (favState.role !== "all" && !hasRole(c.key, favState.role)) return false;
      return !favState.only || profile.favChamps.includes(c.key);
    });
    const box = root.querySelector("#f-grid");
    box.innerHTML = list.length ? list.map((c) => {
      const on = profile.favChamps.includes(c.key);
      return `<div class="ftile${on ? " full" : ""}" data-k="${esc(c.key)}" title="${esc(nameOf(c.key))} — ${esc(c.roles.map((r) => roleLabel(r.role)).join(", "))}">
        ${on ? STAR_SVG : ""}<img src="${img.icon(c.key)}" alt="" loading="lazy"><span class="nm">${esc(nameOf(c.key))}</span></div>`;
    }).join("") : `<div class="card empty">${esc(t("Aucun champion ne correspond."))}</div>`;
    box.querySelectorAll(".ftile").forEach((el) => (el.onclick = () => {
      const k = el.dataset.k;
      profile.favChamps = profile.favChamps.includes(k) ? profile.favChamps.filter((x) => x !== k) : [...profile.favChamps, k];
      saveProfile();
      paintFavGrid();
      paintFavCount();
    }));
  }

  // =============================================================================================================
  // Rolls page: everything rolled in this browser
  // =============================================================================================================
  function renderRolls(page) {
    root = page;
    const rows = recent;
    const counts = {};
    rows.forEach((e) => (counts[e.role] = (counts[e.role] || 0) + 1));
    const top = ROLES.filter((r) => counts[r]).sort((a, b) => counts[b] - counts[a])[0];
    page.innerHTML = `
    <div class="page-enter">
      <header class="page-head"><div>
        <div class="kicker">${esc(t("Sur ce navigateur"))}</div>
        <h1 class="page-title">${esc(t("Tes tirages"))}</h1>
      </div></header>
      <div class="sums">
        <div class="sum"><div class="l">${esc(t("Tirages"))}</div><div class="v num">${rows.length}</div></div>
        <div class="sum"><div class="l">${esc(t("En groupe"))}</div><div class="v num">${rows.filter((e) => e.mode === "group").length}</div></div>
        <div class="sum"><div class="l">${esc(t("Chaos"))}</div><div class="v num">${rows.filter((e) => e.mode === "chaos").length}</div></div>
        <div class="sum"><div class="l">${esc(t("Rôle le plus tiré"))}</div><div class="v">${top ? `${roleIcon(top)} ${esc(roleLabel(top))}` : "—"}</div></div>
      </div>
      <section class="card">
        <h3 class="card-title">${esc(t("Historique des tirages"))}<span class="aside">${rows.length ? `<button class="btn sm danger" id="r-clear">${esc(t("Effacer"))}</button>` : ""}</span></h3>
        ${rows.length ? `<div class="rlist">${rows.map((e) => `
          <a class="rrow" href="${ugg(e.key, e.role)}" target="_blank" rel="noopener" title="${esc(t("Voir sur u.gg"))}">
            <img src="${img.icon(e.key)}" alt="">
            <div class="rr-main"><b>${esc(nameOf(e.key))}</b><span>${roleIcon(e.role)}${esc(roleLabel(e.role))}</span></div>
            <div class="rr-mode">${esc(MODE_LABEL()[e.mode] || "")}</div>
            <div class="rr-group">${e.group ? e.group.map((m) => `<span title="${esc(playerLabel(m))} : ${esc(nameOf(m.key))} ${esc(roleLabel(m.role))}"><img src="${img.icon(m.key)}" alt=""></span>`).join("") : ""}</div>
            <div class="rr-date num">${esc(new Date(e.at).toLocaleString(LANG === "en" ? "en-US" : "fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }))}</div>
            <span class="rr-go">u.gg ↗</span>
          </a>`).join("")}</div>` : `<div class="empty">${esc(t("Aucun tirage pour l'instant."))}<br><a class="t-gold" href="#/">${esc(t("Lancer la roulette →"))}</a></div>`}
        <p class="tiny muted" style="margin:14px 2px 0">${esc(t("Tes tirages et tes favoris restent dans ce navigateur : rien n'est envoyé nulle part."))}</p>
      </section>
    </div>`;
    const clr = page.querySelector("#r-clear");
    if (clr) clr.onclick = async () => {
      if (!(await confirmBox(t("Effacer tous tes tirages ?"), t("Effacer")))) return;
      recent = [];
      lastRoll = null;
      saveRecent();
      ls.set("last", null);
      renderRolls(page);
    };
  }

  // =============================================================================================================
  // Navigation, language, footer
  // =============================================================================================================
  const PAGES = {
    "": { label: "Roulette", icon: NAV_ICONS.roulette, render: renderRoulette },
    favorites: { label: "Favoris", icon: NAV_ICONS.favorites, render: renderFavorites },
    rolls: { label: "Tirages", icon: NAV_ICONS.rolls, render: renderRolls },
    app: { label: "App", icon: NAV_ICONS.app, render: renderApps },
  };
  let heroKey = pick(CHAMPS).key;

  function buildChrome() {
    document.documentElement.lang = LANG;
    document.getElementById("top-nav").innerHTML = Object.entries(PAGES).map(([id, p]) =>
      `<a class="top-item" href="#/${id}" data-p="${id}">${p.icon}<span>${esc(t(p.label))}</span></a>`).join("");
    document.querySelectorAll("#top-lang button").forEach((b) => {
      b.classList.toggle("on", b.dataset.lang === LANG);
      b.onclick = () => {
        if (b.dataset.lang === LANG || spinning) return;
        ls.set("lang", b.dataset.lang);
        location.href = otherLang(b.dataset.lang);
      };
    });
    document.getElementById("foot").innerHTML = `
      <div class="foot-row"><span>${esc(t("Statistiques du patch {0} : rôles joués par chaque champion (Émeraude+).", D.patch))}</span>
        <a href="#/app" class="t-gold">${esc(t("Télécharger l'appli →"))}</a>
        <span>${esc(t("Illustrations : Riot Games (Data Dragon)."))}</span>
        <span>${esc(t("Mesure d'audience anonyme, sans cookies (GoatCounter)."))}</span></div>
      <p class="legal">${esc(t("Roulette of Legends n'est pas approuvée par Riot Games et ne reflète pas les opinions de Riot Games ni de quiconque officiellement impliqué dans la production ou la gestion des propriétés de Riot Games. Riot Games et toutes les propriétés associées sont des marques commerciales ou déposées de Riot Games, Inc."))}</p>`;
    document.querySelector("#top .top-brand").onmouseenter = () => spinLogo(1.2);
  }

  // anonymous visit count (GoatCounter, no cookies): one hit per page shown, and download clicks as events
  const counted = [];
  function track(vars) {
    const gc = window.goatcounter;
    if (gc && gc.count) gc.count(vars);
    else counted.push(vars);
  }
  const counter = document.querySelector("script[data-goatcounter]");
  if (counter) counter.addEventListener("load", () => counted.splice(0).forEach((v) => window.goatcounter.count(v)));
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-track]");
    if (a) track({ path: "download/" + a.dataset.track, title: a.textContent.trim(), event: true });
  });

  function route() {
    const id = location.hash.replace(/^#\/?/, "").split("/")[0];
    const key = PAGES[id] ? id : "";
    track({ path: (LANG === "en" ? "/en/" : "/") + (key ? "#/" + key : ""), title: document.title });
    document.querySelectorAll(".top-item").forEach((a) => a.classList.toggle("on", a.dataset.p === key));
    document.getElementById("about").hidden = key !== "";   // presentation text: home page only
    root = null;
    const page = document.getElementById("page");
    window.scrollTo(0, 0);
    PAGES[key].render(page);
    spinLogo(0.7);
  }

  document.addEventListener("keydown", (e) => {
    if (location.hash.replace(/^#\/?/, "") !== "" || spinning || !root) return;
    const tg = e.target;
    const typing = tg && (tg.tagName === "INPUT" || tg.tagName === "TEXTAREA");
    if (!typing && !e.ctrlKey && !e.altKey && /^[0-5]$/.test(e.key) && mode === "solo") {
      role = e.key === "0" ? "random" : ROLES[+e.key - 1];
      paintRoles();
    } else if (e.key === "Enter" && !typing && !(tg && (tg.tagName === "BUTTON" || tg.tagName === "A"))) {
      e.preventDefault();
      launch();
    }
  });
  window.addEventListener("hashchange", route);
  buildChrome();
  route();
})();
