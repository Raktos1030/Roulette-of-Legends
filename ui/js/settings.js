// Settings page: in-game overlay, champ select import, stats, application and about.
import { esc, fmtDate, t, LANG } from "./util.js";
import { store, on, toast, isLite, isMac, wireBorderless } from "./ctx.js";
import { aboutPromo, wirePromo } from "./promo.js";
import { call } from "./api.js";
import * as sound from "./sound.js";

let root = null, unsub = null;

export function renderSettings(page) {
  root = page;
  page.innerHTML = `
  <div class="page-enter">
    <header class="page-head"><div>
      <div class="kicker">${esc(t("Configuration"))}</div>
      <h1 class="page-title">${esc(t("Réglages"))}</h1>
    </div></header>
    ${isLite() ? `<div class="set-grid">
      <section class="card" id="s-app"></section>
      <section class="card" id="s-data"></section>
      <section class="card" id="s-about"></section>
    </div>` : `<div class="set-grid">
      <section class="card" id="s-overlay"></section>
      <div class="set-col">
        <section class="card" id="s-import"></section>
        <section class="card" id="s-data"></section>
      </div>
      <section class="card" id="s-app"></section>
      <section class="card" id="s-about"></section>
    </div>`}
  </div>`;
  if (!isLite()) {
    paintOverlay();
    paintImport();
  }
  paintData();
  paintApp();
  paintAbout();
  unsub && unsub();
  unsub = on((type) => {
    if (!root || !document.body.contains(root)) return;
    if (type === "update") paintData();
    if (type === "app_update") paintAbout();
    if (type === "profile" && !isLite()) {
      paintOverlay();
      paintImport();
    }
    if (type === "lol") {
      paintApp();
      if (!isLite()) paintOverlay();
    }
    if (type === "data_reloaded") {
      paintData();
      paintAbout();
    }
  });
}

async function setPref(key, value) {
  const r = await call("set_pref", { key, value });
  if (r.error) return toast(r.error, "bad");
  store.profile = r.profile;
}

function paintOverlay() {
  const p = store.profile;
  const box = root.querySelector("#s-overlay");
  const mods = store.boot.overlay_modules || [];
  const cfg = p.overlay_modules || {};
  const placed = Object.keys(p.overlay_pos || {}).length;
  const off = p.overlay_mode === "never";
  box.innerHTML = `
    <h3 class="card-title">${esc(t("Overlay en jeu"))}</h3>
    <div class="set-row" title="${esc(t("Modules par-dessus la partie (LoL en plein écran sans bordure ou fenêtré). Tab ou en permanence ; Ctrl + la lettre du module le masque ou l'épingle."))}"><div class="txt"><b>${esc(t("Overlay"))}</b>
        ${(store.lol || {}).fullscreen ? `<span class="t-warn">${esc(t("LoL est en plein écran : l'overlay ne peut pas s'afficher. Passe-le en « Sans bordure » (le jeu remplit toujours tout l'écran)."))}</span>
        <button class="btn sm" data-borderless>${esc(t("Passer en Sans bordure"))}</button>` : `<span>${esc(t("Maintiens Tab en partie pour l'afficher."))}</span>`}</div>
      <label class="switch"><input type="checkbox" id="o-on" ${off ? "" : "checked"}><i></i></label></div>
    <div class="mods ${off ? "dim" : ""}">
      ${mods.map((m) => {
        const c = cfg[m.id] || { on: m.on !== false, mode: m.mode };
        return `<div class="mod-row ${c.on ? "" : "off"}" data-id="${m.id}" title="${esc(m.desc)}">
          <label class="switch"><input type="checkbox" class="m-on" ${c.on ? "checked" : ""}><i></i></label>
          <div class="txt"><b>${esc(m.label)} <kbd class="kc">Ctrl ${esc(m.key)}</kbd></b></div>
          <div class="seg sm">${[["tab", "Tab"], ["always", t("Toujours")]].map(([v, l]) => `<button data-mode="${v}" class="${c.mode === v ? "on" : ""}">${esc(l)}</button>`).join("")}</div>
        </div>`;
      }).join("")}
    </div>
    <div class="set-row" title="${esc(t("Glisse chaque module où tu veux : il s'aimante aux coins, aux bords et aux autres modules."))}"><div class="txt"><b>${esc(t("Position"))}</b></div>
      <div class="row"><button class="btn sm" id="o-place">${esc(t("Placer à l'écran"))}</button>${placed ? `<button class="btn sm" id="o-reset">${esc(t("Par défaut"))}</button>` : ""}</div></div>
    <div class="set-row"><div class="txt"><b>${esc(t("Taille"))}</b></div>
      <div class="range-row" style="width:300px"><span></span><input type="range" id="o-scale" min="0.8" max="1.3" step="0.05" value="${p.overlay_scale}"><span class="val" id="o-scale-v">${Math.round(p.overlay_scale * 100)}${LANG === "en" ? "" : " "}%</span></div></div>
    <div class="set-row"><div class="txt"><b>${esc(t("Opacité"))}</b></div>
      <div class="range-row" style="width:300px"><span></span><input type="range" id="o-op" min="0.6" max="1" step="0.05" value="${p.overlay_opacity}"><span class="val" id="o-op-v">${Math.round(p.overlay_opacity * 100)}${LANG === "en" ? "" : " "}%</span></div></div>
    <div class="set-row"><div class="txt"><b>${esc(t("Aperçu"))}</b></div>
      <button class="btn sm" id="o-prev">${esc(t("Aperçu"))}</button></div>`;
  box.querySelector("#o-on").onchange = (e) => setPref("overlay_mode", e.target.checked ? "tab" : "never");
  wireBorderless(box);
  box.querySelectorAll(".mod-row").forEach((row) => {
    const id = row.dataset.id;
    row.querySelector(".m-on").onchange = (e) => setModule(id, { on: e.target.checked });
    row.querySelectorAll(".seg button").forEach((b) => (b.onclick = () => setModule(id, { mode: b.dataset.mode })));
  });
  box.querySelector("#o-place").onclick = async () => {
    const r = await call("overlay", { action: "place" });
    if (r.error) toast(r.error, "bad");
  };
  const reset = box.querySelector("#o-reset");
  if (reset) reset.onclick = async () => {
    const r = await call("overlay", { action: "reset" });
    store.profile = r.profile;
    paintOverlay();
  };
  box.querySelector("#o-prev").onclick = () => call("overlay", { action: "preview" });
  const sc = box.querySelector("#o-scale");
  sc.oninput = () => (box.querySelector("#o-scale-v").textContent = Math.round(sc.value * 100) + (LANG === "en" ? "%" : " %"));
  sc.onchange = () => setPref("overlay_scale", +sc.value);
  const op = box.querySelector("#o-op");
  op.oninput = () => (box.querySelector("#o-op-v").textContent = Math.round(op.value * 100) + (LANG === "en" ? "%" : " %"));
  op.onchange = () => setPref("overlay_opacity", +op.value);
}

async function setModule(module, change) {
  const r = await call("overlay_module", { module, ...change });
  if (r.error) return toast(r.error, "bad");
  store.profile = r.profile;
  paintOverlay();
}

function paintImport() {
  const p = store.profile;
  const box = root.querySelector("#s-import");
  const sw = (id, key, title, text) => `
    <div class="set-row" title="${esc(t(text))}"><div class="txt"><b>${esc(t(title))}</b></div>
      <label class="switch"><input type="checkbox" id="${id}" ${p[key] ? "checked" : ""}><i></i></label></div>`;
  box.innerHTML = `
    <h3 class="card-title">${esc(t("Sélection des champions"))}</h3>
    ${sw("i-runes", "import_runes", "Runes", "Page « RoL · Champion Poste », remplacée à chaque partie.")}
    ${sw("i-spells", "import_spells", "Sorts d'invocateur", "Ton Flash reste sur la touche où tu l'avais mis.")}
    ${sw("i-items", "import_items", "Set d'objets", "Dans l'onglet des sets du magasin, en jeu. Un seul set « RoL » à la fois ; celui d'un autre outil (u.gg…) pour le même champion est remplacé, tes propres sets ne bougent pas.")}
    ${sw("i-replace", "import_replace", "Plus de place pour une page de runes ?", "Remplacer alors la page sélectionnée. Sinon, le bandeau de sélection te le propose.")}`;
  [["i-runes", "import_runes"], ["i-spells", "import_spells"], ["i-items", "import_items"], ["i-replace", "import_replace"]].forEach(
    ([id, key]) => (box.querySelector("#" + id).onchange = (e) => setPref(key, e.target.checked))
  );
}

function updateText(u) {
  if (!u) return "";
  switch (u.state) {
    case "checking": return t("Vérification d'un nouveau patch…");
    case "downloading": return u.text || t("Téléchargement des statistiques…");
    case "building": return t("Calcul des nouvelles statistiques…");
    case "done": return u.text || t("Statistiques à jour.");
    case "uptodate": return u.text || t("Les statistiques sont à jour.");
    case "waiting": return u.text || "";
    case "error": return u.text || t("La mise à jour a échoué : nouvel essai plus tard.");
    default: return u.text || "";
  }
}

function paintData() {
  const b = store.boot;
  const u = store.update || {};
  const busy = u.state === "downloading" || u.state === "building" || u.state === "checking";
  const box = root.querySelector("#s-data");
  box.innerHTML = `
    <h3 class="card-title">${esc(t("Statistiques"))}</h3>
    <dl class="kv">
      <dt>${esc(t("Patch"))}</dt><dd><b class="t-gold">${esc(b.meta.patch)}</b></dd>
      <dt>${esc(t("Données du"))}</dt><dd>${esc(fmtDate(b.meta.generated))}</dd>
      <dt>${esc(t("Sources"))}</dt><dd>${esc(t("lolalytics (30 jours et patch actuel, Émeraude+) · u.gg (recoupement)"))}</dd>
      ${u.last_check ? `<dt>${esc(t("Dernière vérification"))}</dt><dd>${esc(u.last_check)}</dd>` : ""}
    </dl>
    <div class="set-row" style="margin-top:8px" title="${esc(t("Dès qu'un nouveau patch a assez de parties (environ 3 jours), puis une fois par semaine, en arrière-plan."))}"><div class="txt"><b>${esc(t("Mise à jour automatique"))}</b></div>
      <label class="switch"><input type="checkbox" id="d-auto" ${store.profile.auto_update ? "checked" : ""}><i></i></label></div>
    <div class="set-row"><div class="txt"><b>${esc(t("Mettre à jour maintenant"))}</b><span class="${u.state === "error" ? "t-bad" : ""}">${esc(updateText(u))}</span>
        ${busy ? `<div class="progress"><i style="width:${Math.round((u.progress || 0) * 100)}%"></i></div>` : ""}</div>
      <button class="btn sm" id="d-now" ${busy ? "disabled" : ""}>${esc(busy ? t("En cours…") : t("Mettre à jour"))}</button></div>`;
  box.querySelector("#d-auto").onchange = (e) => setPref("auto_update", e.target.checked);
  box.querySelector("#d-now").onclick = async () => {
    const r = await call("update", { action: "now" });
    if (r.error) toast(r.error, "bad");
  };
}

function paintApp() {
  const a = store.boot.autostart || {};
  const l = store.lol || {};
  const box = root.querySelector("#s-app");
  box.innerHTML = `
    <h3 class="card-title">${esc(t("Application"))}</h3>
    <div class="set-row"><div class="txt"><b>${esc(t("Langue"))}</b></div>
      <div class="seg sm" id="a-lang">${[["fr", "Français"], ["en", "English"]].map(([v, l]) => `<button data-lang="${v}" class="${LANG === v ? "on" : ""}">${l}</button>`).join("")}</div></div>
    ${isMac() ? "" : `<div class="set-row" title="${esc(a.available ? t("Démarre discrètement dans la zone de notification.") : t("Disponible avec l'application .exe."))}"><div class="txt"><b>${esc(t("Lancer au démarrage de Windows"))}</b></div>
      <label class="switch"><input type="checkbox" id="a-auto" ${a.on ? "checked" : ""} ${a.available ? "" : "disabled"}><i></i></label></div>`}
    <div class="set-row"><div class="txt"><b>${esc(t("Client League of Legends"))}</b><span>${l.connected ? `${esc(t("Connecté"))}${l.summoner ? " — " + esc(l.summoner) : ""}${l.rank ? " · " + esc(t("Solo/duo {0}", l.rank)) : ""}` : esc(t("Non détecté"))}</span>
        ${store.profile.lol_dir ? `<span class="tiny">${esc(t("Dossier : {0}", store.profile.lol_dir))}</span>` : ""}</div>
      <button class="btn sm" id="a-dir">${esc(t("Choisir le dossier…"))}</button></div>
    <div class="set-row"><div class="txt"><b>${esc(t("Sons"))}</b><span>${esc(t("La roulette et les cartes du classeur."))}</span></div>
      <div class="snd-row"><input type="range" id="a-vol" min="0.1" max="1" step="0.05" value="${store.profile.sound_volume ?? 0.6}" ${store.profile.sounds === false ? "disabled" : ""}>
        <label class="switch"><input type="checkbox" id="a-snd" ${store.profile.sounds !== false ? "checked" : ""}><i></i></label></div></div>
    <div class="set-row"><div class="txt"><b>${esc(t("Animations"))}</b><span>${esc(t("Coupées, l'appli reste immobile : fond, cadres, effets des cartes, transitions. La roulette tourne toujours."))}</span></div>
      <label class="switch"><input type="checkbox" id="a-amb" ${store.profile.ambient !== false ? "checked" : ""}><i></i></label></div>
    <div class="set-row"><div class="txt"><b>${esc(t("Statistiques anonymes"))}</b><span>${esc(t("Compte les lancements de l'appli (version, Windows ou Mac). Rien d'autre n'est envoyé."))}</span></div>
      <label class="switch"><input type="checkbox" id="a-usage" ${store.profile.usage_stats !== false ? "checked" : ""}><i></i></label></div>`;
  const auto = box.querySelector("#a-auto");
  if (auto) auto.onchange = async (e) => {
    const r = await call("autostart", { on: e.target.checked });
    store.boot.autostart = r.autostart;
    paintApp();
  };
  box.querySelector("#a-amb").onchange = (e) => setPref("ambient", e.target.checked);
  box.querySelector("#a-snd").onchange = async (e) => {
    await setPref("sounds", e.target.checked);
    paintApp();
    sound.win(false);
  };
  box.querySelector("#a-vol").onchange = async (e) => {
    await setPref("sound_volume", +e.target.value);
    sound.win(false);   // hear the new volume
  };
  box.querySelector("#a-usage").onchange = (e) => setPref("usage_stats", e.target.checked);
  box.querySelectorAll("#a-lang button").forEach((b) => (b.onclick = async () => {
    if (b.dataset.lang === LANG) return;
    const r = await call("set_lang", { lang: b.dataset.lang });
    if (r.error) toast(r.error, "bad");   // otherwise the "lang" event reloads the UI
  }));
  box.querySelector("#a-dir").onclick = async () => {
    const r = await call("lol_dir");
    if (r.profile) store.profile = r.profile;
    paintApp();
  };
}

function paintAbout() {
  const b = store.boot;
  root.querySelector("#s-about").innerHTML = `
    <h3 class="card-title">${esc(t("À propos"))}</h3>
    <dl class="kv">
      <dt>${esc(t("Version"))}</dt><dd>${esc(b.app.name)} ${esc(b.app.version)}${b.app_update ? ` · <a href="#" class="t-gold" data-dl>${esc(t("version {0} disponible", b.app_update.version))}</a>` : ""}</dd>
      ${isLite() ? "" : `<dt>${esc(t("Fiches"))}</dt><dd>${esc(t("{0} combinaisons champion + rôle (runes et objets : import en sélection et overlay)", b.meta.guides))}</dd>`}
      <dt>${esc(t("Statistiques"))}</dt><dd>lolalytics.com, u.gg</dd>
      <dt>${esc(t("Profils de champions"))}</dt><dd>Meraki Analytics</dd>
      <dt>${esc(t("Illustrations"))}</dt><dd>Riot Games (Data Dragon)</dd>
      <dt>${esc(t("Sons"))}</dt><dd>ElevenLabs (elevenlabs.io), Kenney</dd>
      <dt>${esc(t("Police des titres"))}</dt><dd>${esc(t("Marcellus SC (licence OFL)"))}</dd>
    </dl>
    <p class="legal">${esc(isLite()
      ? t("Roulette of Legends n'est pas approuvée par Riot Games et ne reflète pas les opinions de Riot Games ni de quiconque officiellement impliqué dans la production ou la gestion des propriétés de Riot Games. Riot Games et toutes les propriétés associées sont des marques commerciales ou déposées de Riot Games, Inc. L'application ne choisit, ne bannit, ne verrouille et n'envoie jamais rien à ta place : elle lit seulement le client pour suivre tes tirages.")
      : t("Roulette of Legends n'est pas approuvée par Riot Games et ne reflète pas les opinions de Riot Games ni de quiconque officiellement impliqué dans la production ou la gestion des propriétés de Riot Games. Riot Games et toutes les propriétés associées sont des marques commerciales ou déposées de Riot Games, Inc. L'application ne choisit, ne bannit, ne verrouille et n'envoie jamais rien à ta place ; si tu l'actives, elle importe seulement ta page de runes, tes sorts d'invocateur et un set d'objets une fois ton champion verrouillé."))}</p>
    ${isLite() ? aboutPromo() : ""}`;
  wirePromo(root.querySelector("#s-about"));
  const dl = root.querySelector("#s-about [data-dl]");
  if (dl) dl.onclick = async (e) => {
    e.preventDefault();
    const r = await call("install_update");
    if (r.error) toast(r.error, "bad");
  };
}
