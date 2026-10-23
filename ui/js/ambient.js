// Animations: on, the background rings turn very slowly and every effect moves. Off (the setting, or Windows reducing
// animations), the app holds still: every animation and transition ends at once (class "still"); the roulette still
// spins, it is driven by script.
export function setAmbient(on) {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.body.classList.toggle("ambient", on && !reduce);
  document.body.classList.toggle("still", !on || reduce);
}
