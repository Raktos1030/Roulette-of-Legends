// Ambient motion: the background rings turn very slowly. Off via the setting or when Windows reduces animations.
export function setAmbient(on) {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.body.classList.toggle("ambient", on && !reduce);
}
