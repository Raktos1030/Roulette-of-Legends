// Core access: POST /api/<name> calls and the event stream (Server-Sent Events).

const params = new URLSearchParams(location.search);
let token = params.get("t");
try {
  if (token) sessionStorage.setItem("rl-token", token);
  else token = sessionStorage.getItem("rl-token");
} catch (e) { /* storage unavailable: the URL token is enough */ }

export async function call(name, body = {}) {
  const r = await fetch(`/api/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Token": token || "" },
    body: JSON.stringify(body),
  });
  let data = {};
  try {
    data = await r.json();
  } catch (e) {
    data = { error: `Réponse illisible (${r.status})` };
  }
  if (!r.ok && !data.error) data.error = `Erreur ${r.status}`;
  return data;
}

export function listen(onMessage, onState) {
  let es = null;
  const open = () => {
    es = new EventSource(`/api/events?t=${encodeURIComponent(token || "")}`);
    es.onopen = () => onState && onState(true);
    es.onmessage = (ev) => {
      try {
        onMessage(JSON.parse(ev.data));
      } catch (e) {
        console.error(e);
      }
    };
    es.onerror = () => onState && onState(false);
  };
  open();
  return () => es && es.close();
}
