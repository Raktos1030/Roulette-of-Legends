// Full app promotion, shown by the Lite only: roll card panel, home card, About section and a details modal.
import { esc, t, img, ICONS } from "./util.js";
import { store, openModal, toast, isMac } from "./ctx.js";
import { call } from "./api.js";

const BUILD_SVG = '<svg viewBox="0 0 24 24"><path d="M12 3l7 4v5c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V7z"/><path d="M9 12l2 2 4-4"/></svg>';
const OVERLAY_SVG = '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/><path d="M14 7.5h4v4h-4z"/></svg>';

function features() {
  const b = store.boot;
  return [
    [ICONS.guide, t("Fiches de jeu"), t("Une fiche pour chaque champion à chaque poste ({0}) : plan de lane, matchups, mid & late, condition de victoire.", b.meta.combos)],
    [BUILD_SVG, t("Build importé"), t("Runes, sorts d'invocateur et set d'objets du patch envoyés dans LoL dès que tu verrouilles ton champion.")],
    [OVERLAY_SVG, t("Overlay en jeu"), t("En maintenant Tab : ta fiche, tes stats, l'écart d'or. Le sort à monter s'allume sur ton HUD.")],
    [ICONS.live, t("Page Partie"), t("Les deux équipes face à face, les classements et ce que chaque adversaire veut faire.")],
  ];
}

const downloadButton = (cls = "btn-gold") => store.boot.download
  ? `<button class="${cls}" data-download>${esc(t("Télécharger la version complète"))}</button>`
  : `<button class="${cls}" disabled>${esc(t("Bientôt disponible"))}</button>`;

export function openPromo() {
  const b = store.boot;
  const hero = (store.roll && store.roll.key) || b.hero;
  const { box } = openModal(`
    <div class="promo-modal">
      <div class="pm-head">
        <div class="pm-art" style="background-image:url('${img.splash(hero)}')"></div><div class="pm-shade"></div>
        <div class="kicker">${esc(t("Version complète"))}</div>
        <h2 class="w-brand">Roulette<small>of</small>Legends</h2>
        <p class="w-text">${esc(t("La même roulette, avec tout ce qu'il faut pour jouer ton tirage : la fiche du champion, son build et un overlay en partie."))}</p>
      </div>
      <div class="pm-feats">${features().map(([icon, title, text]) => `
        <div class="pm-feat"><span class="pm-ic">${icon}</span><div><b>${esc(title)}</b><span>${esc(text)}</span></div></div>`).join("")}
      </div>
      <div class="pm-foot">
        <p class="muted">${esc(isMac() ? t("Gratuite, sur Windows pour l'instant. Elle s'installe à côté de la Lite : tu peux garder les deux.")
          : t("Gratuite, pour Windows. Elle s'installe à côté de la Lite : tu peux garder les deux."))}</p>
        ${downloadButton()}
      </div>
    </div>`);
  box.classList.add("promo-box");
  wireDownload(box);
}

function wireDownload(box) {
  box.querySelectorAll("[data-download]").forEach((b) => (b.onclick = async () => {
    const r = await call("open_download");
    if (r.error) toast(r.error, "bad");
  }));
}

export function wirePromo(box) {
  box.querySelectorAll("[data-promo]").forEach((b) => (b.onclick = (e) => {
    e.stopPropagation();
    openPromo();
  }));
  wireDownload(box);
}

// panel on the roll card: the guide of the rolled champion is in the full app
export function rollPromo(roll) {
  return `<div class="sr-promo">
    <div class="kicker">${esc(t("Version complète"))}</div>
    <p>${esc(t("La fiche {0} {1} t'attend dans la version complète : plan de lane, matchups et build importé dans LoL.", roll.name, roll.role_label))}</p>
    <button class="more-link" data-promo>${esc(t("Découvrir →"))}</button>
  </div>`;
}

// home card under the welcome hero
export function homePromo() {
  return `<section class="card promo-card">
    <div class="pc-text">
      <div class="kicker">${esc(t("Envie d'aller plus loin ?"))}</div>
      <h3>${esc(t("Roulette of Legends, la version complète"))}</h3>
      <p class="muted">${esc(t("Ton tirage arrive avec sa fiche de jeu et son build, et un overlay t'accompagne en partie."))}</p>
    </div>
    <div class="pc-feats">${features().map(([icon, title]) => `<span class="pc-feat">${icon}${esc(title)}</span>`).join("")}</div>
    <button class="btn-gold" data-promo>${esc(t("Découvrir"))}</button>
  </section>`;
}

// row of the About section
export function aboutPromo() {
  return `<div class="about-promo">
    <div><b>${esc(t("Roulette of Legends, la version complète"))}</b>
      <span>${esc(t("Fiches de jeu, build importé, overlay en jeu et page Partie."))}</span></div>
    <button class="btn sm" data-promo>${esc(t("Découvrir"))}</button>
  </div>`;
}
