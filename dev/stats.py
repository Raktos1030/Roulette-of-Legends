"""
Usage stats of Roulette of Legends, live in the browser: how many people have the app and how many are new since
November 1, 2026, then the players of the day, week and month, updates by version, downloads (GitHub releases) and site
visits (GoatCounter). The page follows the counts by itself while this window stays open.

The GoatCounter API key (permission: read statistics) is asked once and kept on this computer only
(%LOCALAPPDATA%/RoL stats/goatcounter.key), never in the project.

usage: python dev/stats.py [--reset-key]
"""

import datetime
import getpass
import html
import http.server
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

GOATCOUNTER = os.environ.get("ROL_STATS_API") or "https://rouletteoflegends.goatcounter.com/api/v0"
REPO = "Raktos1030/Roulette-of-Legends"
FETCH_FROM = datetime.date(2026, 10, 1)   # before the first release: every count is read from here
BASE = datetime.date(2026, 11, 1)         # "new since": the date the page counts from
COUNTED_FROM = "3.0.2"                    # first version that counts its players
READ_EVERY = 30                           # seconds between two readings of GoatCounter
KEY_FILE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "RoL stats", "goatcounter.key")
EDITIONS = {"full": "Complète", "lite": "Lite"}
SYSTEMS = {"windows": "Windows", "mac": "Mac"}
MONTHS = "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split()


class BadKey(Exception):
    pass


def read_key(reset):
    if reset and os.path.exists(KEY_FILE):
        os.remove(KEY_FILE)
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            key = f.read().strip()
            if key:
                return key
    except OSError:
        pass
    print("Clé GoatCounter : menu de ton compte en haut à droite › API › New API key, avec seulement « Read statistics ».")
    print("Colle-la ici puis appuie sur Entrée (elle ne s'affiche pas pendant la saisie).")
    key = getpass.getpass("Clé : ").strip()
    if not key:
        sys.exit("Pas de clé : rien à afficher.")
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    return key


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "rol-stats", **(headers or {})})
    for _ in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:   # 4 requests per second at most
                time.sleep(float(e.headers.get("X-Rate-Limit-Reset") or 1) + 0.2)
                continue
            if url.startswith(GOATCOUNTER) and e.code == 401:
                raise BadKey("Clé refusée par GoatCounter : copie-la en entier, ou crée-en une autre.")
            if url.startswith(GOATCOUNTER) and e.code == 403:
                raise BadKey("Cette clé n'a pas le droit « Read statistics » : crée-en une avec ce droit.")
            raise
    raise RuntimeError("GoatCounter : trop de requêtes, réessaie dans une minute.")


def goatcounter(key, path, params):
    """GET on the API; lists go comma-separated, or as repeated parameters if the API refuses that."""
    auth = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    csv = {k: (",".join(map(str, v)) if isinstance(v, list) else v) for k, v in params.items()}
    try:
        return get_json("%s/%s?%s" % (GOATCOUNTER, path, urllib.parse.urlencode(csv)), auth)
    except urllib.error.HTTPError as e:
        if e.code != 400 or not any(isinstance(v, list) for v in params.values()):
            raise
        return get_json("%s/%s?%s" % (GOATCOUNTER, path, urllib.parse.urlencode(params, doseq=True)), auth)


def hour(day):
    """Local midnight of a day, in UTC rounded to the hour (the API's range bounds)."""
    t = datetime.datetime.combine(day, datetime.time()).astimezone(datetime.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:00:00Z")


def all_hits(key, start, end):
    """Every path with its visitors per day: {path: {"title", "event", "id", "days": {date: n}}}."""
    out, seen = {}, []
    while True:
        params = {"start": hour(start), "end": hour(end + datetime.timedelta(days=1)), "limit": 100}
        if seen:
            params["exclude_paths"] = seen
        r = goatcounter(key, "stats/hits", params)
        for h in r.get("hits") or []:
            days = {}
            for s in h.get("stats") or []:
                if s.get("daily"):
                    days[datetime.date.fromisoformat(s["day"][:10])] = s["daily"]
            out[h["path"]] = {"title": h.get("title") or "", "event": bool(h.get("event")), "id": h["path_id"], "days": days}
            seen.append(h["path_id"])
        if not r.get("more") or not r.get("hits"):
            return out


def site_days(key, ids, start, end):
    """Site visitors per day (pages only, each visitor once a day even across pages)."""
    if not ids:
        return {}
    r = goatcounter(key, "stats/total", {"start": hour(start), "end": hour(end + datetime.timedelta(days=1)),
                                        "include_paths": ids})
    return {datetime.date.fromisoformat(s["day"][:10]): s.get("daily") or 0 for s in r.get("stats") or []}


_releases = {"next": 0.0, "data": None}


def releases():
    """[(tag, date, installers, zips)] from the GitHub releases, newest first, or None while GitHub hasn't answered.
    Read again every 15 minutes (GitHub answers 60 requests an hour without an account), 2 minutes after a failure."""
    if time.time() >= _releases["next"]:
        try:
            out = []
            for r in get_json("https://api.github.com/repos/%s/releases?per_page=100" % REPO):
                n = {"inst": 0, "zip": 0}
                for a in r.get("assets") or []:
                    if a["name"].endswith((".exe", ".dmg")):
                        n["inst"] += a["download_count"]
                    elif a["name"].endswith(".zip"):
                        n["zip"] += a["download_count"]
                out.append((r["tag_name"], (r.get("published_at") or "")[:10], n["inst"], n["zip"]))
            _releases.update(data=out, next=time.time() + 900)
        except (OSError, ValueError):
            _releases["next"] = time.time() + 120
    return _releases["data"]


# --- the numbers ---------------------------------------------------------------------------------------------
def total(series, days):
    return sum(series.get(d, 0) for d in days)


def merge(hits, pattern):
    """Visitors per day summed over the paths that match."""
    out = {}
    for path, h in hits.items():
        if re.match(pattern, path):
            for d, n in h["days"].items():
                out[d] = out.get(d, 0) + n
    return out


def days_from(first, last):
    return [first + datetime.timedelta(days=i) for i in range((last - first).days + 1)]


def compute(hits, site, rel, today):
    ever, since = days_from(FETCH_FROM, today), days_from(BASE, today)
    monday = today - datetime.timedelta(days=today.weekday())
    # charts: 30 days and 8 weeks, never before the base; the days still to come of the first month stay empty
    first_day = max(BASE, today - datetime.timedelta(days=29))
    chart_days = [first_day + datetime.timedelta(days=i) for i in range(30)]
    first_week = max(BASE - datetime.timedelta(days=BASE.weekday()), monday - datetime.timedelta(weeks=7))
    chart_weeks = [first_week + datetime.timedelta(weeks=i) for i in range(8)]
    upto = lambda d, v: v if d <= today else None
    new = merge(hits, r"^/app/new/")
    day, week, month = merge(hits, r"^/app/day/"), merge(hits, r"^/app/week/"), merge(hits, r"^/app/month/")
    s = {
        # each computer is a player once: a new install, its first update to the first counting version, or the
        # one-time count of a computer that had the app before the counts
        "players": total(new, ever) + total(merge(hits, r"^/app/update/\w+/%s$" % re.escape(COUNTED_FROM)), ever)
                   + total(merge(hits, r"^/app/known/"), ever),
        "new": total(new, since), "new_today": new.get(today, 0),
        "today": day.get(today, 0), "week": total(week, days_from(monday, today)),
        "month": total(month, days_from(today.replace(day=1), today)) if month else None,   # counted from 3.0.3
        "days": [(d, upto(d, day.get(d, 0)), new.get(d, 0)) for d in chart_days],
        "weeks": [(w, upto(w, total(week, days_from(w, w + datetime.timedelta(days=6))))) for w in chart_weeks],
        "site": total(site, since), "site_days": [(d, upto(d, site.get(d, 0))) for d in chart_days],
        "releases": rel,
    }
    by_edition = []
    for path, h in sorted(hits.items()):
        m = re.match(r"^/app/new/(\w+)/(\w+)$", path)
        if m and total(h["days"], since):
            by_edition.append(("%s · %s" % (EDITIONS.get(m[1], m[1]), SYSTEMS.get(m[2], m[2])),
                               h["days"].get(today, 0), total(h["days"], since)))
    s["editions"] = by_edition

    def versions(pattern, days):
        out = {}
        for path, h in hits.items():
            m = re.match(pattern, path)
            if m and total(h["days"], days):
                k = "%s %s" % (m["ver"], EDITIONS.get(m["ed"], m["ed"]))
                out[k] = out.get(k, 0) + total(h["days"], days)
        return sorted(out.items(), key=lambda kv: [int(x) for x in re.findall(r"\d+", kv[0])], reverse=True)
    s["updates"] = versions(r"^/app/update/(?P<ed>\w+)/(?P<ver>[\d.]+)$", ever)
    s["legacy"] = versions(r"^/app/(?P<ed>full|lite)/(?P<ver>[\d.]+)/\w+$", since)
    s["pages"] = sorted(((p, total(h["days"], since)) for p, h in hits.items()
                         if not h["event"] and not p.startswith("/app/") and total(h["days"], since)), key=lambda x: -x[1])
    s["clicks"] = sorted(((p.split("/", 1)[1], h["days"].get(today, 0), total(h["days"], since)) for p, h in hits.items()
                          if h["event"] and p.startswith("download/") and total(h["days"], since)), key=lambda x: -x[2])
    return s


# --- the page ------------------------------------------------------------------------------------------------
def day_label(d):
    return "%s %s" % ("1er" if d.day == 1 else d.day, MONTHS[d.month - 1])


def plural(n, one, many):
    return one if n <= 1 else many


def summary(s):
    return "%d %s · %d %s depuis le %s" % (s["players"], plural(s["players"], "personne a l'appli", "personnes ont l'appli"),
                                           s["new"], plural(s["new"], "nouveau joueur", "nouveaux joueurs"), day_label(BASE))


def bars(points, height=134):
    """Bar chart (inline SVG): points = [(label, value, accent value)], value None for a day still to come. The highest
    value is written above the bars, on a faint line."""
    n = len(points) or 1
    top = max([p[1] or 0 for p in points] + [1])
    area, floor = height - 36, height - 20
    w, gap = 100.0 / n, 100.0 / n * 0.22
    out = ['<line x1="0" x2="100%%" y1="%d" y2="%d" class="g"/><text x="0" y="10" class="t">%s</text>' % (floor - area, floor - area, top)]
    for i, (label, v, *rest) in enumerate(points):
        x = i * w + gap / 2
        if v is not None:
            h = v / top * area
            out.append('<rect x="%.2f%%" y="%.1f" width="%.2f%%" height="%.1f" rx="2" class="b"><title>%s : %s</title></rect>'
                       % (x, floor - h, w - gap, max(h, 0.6 if v else 0), html.escape(label), v))
            if rest and rest[0]:
                h2 = rest[0] / top * area
                out.append('<rect x="%.2f%%" y="%.1f" width="%.2f%%" height="%.1f" rx="2" class="b2"><title>%s : %s nouveau(x)</title></rect>'
                           % (x, floor - h2, w - gap, h2, html.escape(label), rest[0]))
        if n <= 8 or i % (n // 6) == 0 or i == n - 1:
            out.append('<text x="%.2f%%" y="%d" class="t" text-anchor="middle">%s</text>' % (x + (w - gap) / 2, height - 4, html.escape(label)))
    return '<svg class="chart" width="100%%" height="%d" role="img">%s</svg>' % (height, "".join(out))


def table(head, rows, empty):
    if not rows:
        return '<p class="muted">%s</p>' % html.escape(empty)
    th = "".join("<th>%s</th>" % html.escape(h) for h in head)
    tr = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % html.escape(str(c)) for c in r) for r in rows)
    return '<div class="wrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (th, tr)


def body_html(s):
    """Everything under the title; the open page swaps it when it changes."""
    fmt = lambda d: d.strftime("%d/%m")
    base = day_label(BASE)
    num = lambda name, v, shown=None: '<b data-n="%s" data-v="%d">%s</b>' % (name, v, v if shown is None else shown)
    item = lambda label, name, v: '<span>%s <em data-n="%s" data-v="%d">%d</em></span>' % (label, name, v, v)
    rel = s["releases"]
    hero = """<section class="hero">
  <div>%s<span>%s</span><small>chaque PC compté une fois</small></div>
  <div>%s<span>%s depuis le %s</span><small>dont %d aujourd'hui</small></div>
  <p class="active">Ont ouvert l'appli %s%s%s</p>
</section>""" % (
        num("players", s["players"]), plural(s["players"], "personne a l'appli", "personnes ont l'appli"),
        num("new", s["new"], ("+%d" % s["new"]) if s["new"] else 0), plural(s["new"], "nouveau joueur", "nouveaux joueurs"),
        base, s["new_today"],
        item("aujourd'hui", "today", s["today"]), item("cette semaine", "week", s["week"]),
        "" if s["month"] is None else item("ce mois-ci", "month", s["month"]))
    legacy = ('<section><h2>Anciennes versions · lancements depuis le %s</h2>%s</section>'
              % (base, table(["Version", "Lancements"], s["legacy"], ""))) if s["legacy"] else ""
    return hero + """
<section><h2>Joueurs par jour</h2>%(daily)s
  <div class="legend"><span><i style="background:var(--gold)"></i>joueurs du jour</span><span><i style="background:var(--teal)"></i>dont nouveaux</span></div></section>
<div class="two">
  <section><h2>Joueurs par semaine · du lundi</h2>%(weekly)s</section>
  <section><h2>Nouveaux joueurs par édition</h2>%(editions)s</section>
</div>
<div class="two">
  <section><h2>Mises à jour par version</h2>%(updates)s</section>
  <section><h2>Téléchargements GitHub%(downloads)s</h2>%(releases)s</section>
</div>
<section><h2>Site · visites par jour · %(site)d depuis le %(base)s</h2>%(site_chart)s</section>
<div class="two">
  <section><h2>Pages du site · depuis le %(base)s</h2>%(pages)s</section>
  <section><h2>Clics « Télécharger » sur le site</h2>%(clicks)s</section>
</div>
%(legacy)s
<footer><span>Une personne = un PC où l'appli a tourné, comptée une seule fois. Les joueurs d'avant la %(first)s comptent dès qu'ils mettent à jour.</span>
<span>Tes propres lancements comptent aussi : coupe les statistiques dans ton appli (Réglages › À propos › Confidentialité) pour ne pas te compter.</span>
<span>Les zips GitHub comptent aussi les mises à jour faites depuis l'appli.</span></footer>""" % {
        "daily": bars([(fmt(d), v, n) for d, v, n in s["days"]]),
        "weekly": bars([(fmt(w), v) for w, v in s["weeks"]]),
        "editions": table(["Édition", "Aujourd'hui", "Depuis le " + base], s["editions"], "Aucun nouveau joueur depuis le %s." % base),
        "updates": table(["Version", "Mises à jour"], s["updates"], "Aucune mise à jour comptée pour l'instant."),
        "downloads": "" if rel is None else " · %d installeurs, %d zips" % (sum(r[2] for r in rel), sum(r[3] for r in rel)),
        "releases": table(["Version", "Publiée", "Installeurs", "Zips"], rel or [],
                          "GitHub ne répond pas pour l'instant." if rel is None else "Aucune release."),
        "site": s["site"], "base": base, "site_chart": bars([(fmt(d), v) for d, v in s["site_days"]]),
        "pages": table(["Page", "Visites"], s["pages"], "Aucune visite depuis le %s." % base),
        "clicks": table(["Lien", "Aujourd'hui", "Depuis le " + base], s["clicks"], "Aucun clic depuis le %s." % base),
        "legacy": legacy, "first": COUNTED_FROM,
    }


STYLE = """
:root { --bg: #070c16; --panel: #0d1524; --line: rgba(255, 255, 255, .08); --text: #ebe6da; --muted: #8b909a;
  --gold: #c8aa6e; --gold-hi: #e8d09a; --teal: #19d3c4; --green: #45d38f; --warn: #e0a24f; --off: #e0725f;
  font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font-size: 14.5px; line-height: 1.5; }
main, #body { display: grid; gap: 22px; }
main { max-width: 1100px; margin: 0 auto; padding: 28px max(16px, 3vw) 48px; }
h1 { margin: 0; font: 600 26px/1.2 Georgia, serif; letter-spacing: .02em; color: var(--gold-hi); }
h2 { margin: 0 0 12px; font-size: 12px; letter-spacing: .14em; text-transform: uppercase; color: var(--gold); }
header { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 6px 18px; }
.muted { margin: 0; color: var(--muted); }
.live { display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--muted); }
.live i { width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px var(--green); }
.live.warn i { background: var(--warn); box-shadow: none; }
.live.off i { background: var(--off); box-shadow: none; }
section { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; min-width: 0; }
.hero { display: grid; grid-template-columns: 1fr 1fr; padding: 0; border-radius: 14px; overflow: hidden;
  border-color: rgba(200, 170, 110, .35); background: linear-gradient(160deg, rgba(200, 170, 110, .10), var(--panel) 60%); }
.hero > div { padding: 26px 30px 22px; min-width: 0; }
.hero > div + div { border-left: 1px solid var(--line); }
.hero b { display: block; font: 600 64px/1 Bahnschrift, "Segoe UI", sans-serif; color: var(--gold-hi); font-variant-numeric: tabular-nums; }
.hero > div > span { display: block; margin-top: 10px; font-size: 16px; }
.hero > div > small { display: block; margin-top: 2px; color: var(--muted); font-size: 12.5px; }
.active { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 6px 26px; margin: 0; padding: 13px 30px;
  border-top: 1px solid var(--line); color: var(--muted); }
.active em { margin-left: 4px; font-style: normal; font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
.bump { animation: bump 2.4s ease-out; }
@keyframes bump { from { color: #fff; text-shadow: 0 0 22px rgba(232, 208, 154, .9); } }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 22px; }
.chart { display: block; overflow: visible; }
.chart .b { fill: var(--gold); opacity: .85; }
.chart .b2 { fill: var(--teal); }
.chart .t { fill: var(--muted); font-size: 10px; }
.chart .g { stroke: var(--line); stroke-dasharray: 3 4; }
.legend { display: flex; gap: 14px; margin-top: 8px; font-size: 12px; color: var(--muted); }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--line); }
th { font-size: 12px; font-weight: 600; color: var(--muted); }
td:not(:first-child), th:not(:first-child) { text-align: right; }
.wrap { overflow-x: auto; }
footer { color: var(--muted); font-size: 12.5px; display: grid; gap: 4px; }
@media (max-width: 640px) {
  .hero { grid-template-columns: 1fr; }
  .hero > div + div { border-left: 0; border-top: 1px solid var(--line); }
  .hero b { font-size: 52px; }
}
@media (prefers-reduced-motion: reduce) { .bump { animation: none; } }
"""

# the open page asks this window every 10 seconds; a number that grew lights up, and the tab says how many new players
# arrived since it was opened
SCRIPT = """
const live = document.getElementById("live"), body = document.getElementById("body");
const values = () => Object.fromEntries([...body.querySelectorAll("[data-n]")].map(el => [el.dataset.n, +el.dataset.v]));
const opened = values().new;
async function poll() {
  let d;
  try {
    d = await (await fetch("/data", { cache: "no-store" })).json();
  } catch (e) {
    live.className = "live off";
    live.lastElementChild.textContent = "Fenêtre des stats fermée : relance stats.bat pour suivre";
    return;
  }
  live.className = d.error ? "live warn" : "live";
  live.lastElementChild.textContent = d.status;
  if (d.version === version) return;
  const before = values();
  version = d.version;
  body.innerHTML = d.html;
  for (const el of body.querySelectorAll("[data-n]"))
    if (+el.dataset.v > (before[el.dataset.n] ?? Infinity)) el.classList.add("bump");
  const more = values().new - opened;
  document.title = (more > 0 ? "(+" + more + ") " : "") + "Stats Roulette of Legends";
}
setInterval(poll, 10000);
"""

ICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='6' "
        "fill='none' stroke='%23c8aa6e' stroke-width='2.4'/%3E%3C/svg%3E")


def full_page(state):
    return ('<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Stats Roulette of Legends</title><link rel="icon" href="%s"><style>%s</style></head><body><main>'
            '<header><h1>Stats Roulette of Legends</h1><span id="live" class="live%s"><i></i><span>%s</span></span></header>'
            '<div id="body">%s</div></main><script>let version = %d;%s</script></body></html>'
            % (ICON, STYLE, " warn" if state["error"] else "", html.escape(state["status"]), state["html"], state["version"], SCRIPT))


# --- live ----------------------------------------------------------------------------------------------------
class Live:
    """The page's content, read again from GoatCounter every READ_EVERY seconds whether a page is open or not."""

    def __init__(self, key):
        self.key, self.lock = key, threading.Lock()
        self.html, self.version, self.at, self.error, self.summary = "", 0, None, None, None

    def read(self):
        today = datetime.date.today()
        hits = all_hits(self.key, FETCH_FROM, today)
        site_ids = [h["id"] for p, h in hits.items() if not h["event"] and not p.startswith("/app/")]
        s = compute(hits, site_days(self.key, site_ids, FETCH_FROM, today), releases(), today)
        page, line = body_html(s), summary(s)
        with self.lock:
            if page != self.html:
                self.html, self.version = page, self.version + 1
            self.at, self.error = datetime.datetime.now(), None
        if self.summary and line != self.summary:
            print("%s  %s" % (time.strftime("%H:%M"), line))
        self.summary = line

    def follow(self):
        while True:
            time.sleep(READ_EVERY)
            try:
                self.read()
            except Exception as e:   # the page stays up and says so; next try at the next turn
                reason = str(e) if isinstance(e, BadKey) else str(getattr(e, "reason", None) or e)
                if not self.error:
                    print("%s  lecture impossible (%s) : nouvel essai toutes les %d secondes" % (time.strftime("%H:%M"), reason, READ_EVERY))
                with self.lock:
                    self.error = reason

    def state(self):
        with self.lock:
            status = ("Lecture impossible (%s) · dernière à %s" % (self.error, self.at.strftime("%H:%M:%S")) if self.error
                      else "En direct · mis à jour à %s" % self.at.strftime("%H:%M:%S"))
            return {"version": self.version, "html": self.html, "status": status, "error": bool(self.error)}


class Server(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], ConnectionError):   # a tab closed while it was answered: nothing to say
            super().handle_error(request, client_address)


def serve(live):
    class Page(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                body, kind = full_page(live.state()), "text/html; charset=utf-8"
            elif path == "/data":
                body, kind = json.dumps(live.state()), "application/json"
            else:
                self.send_error(404)
                return
            body = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Server(("127.0.0.1", 0), Page)


def main():
    live = Live(read_key("--reset-key" in sys.argv))
    try:
        live.read()   # the first reading says here why it fails, before anything opens
    except BadKey as e:
        os.remove(KEY_FILE)
        sys.exit(str(e))
    except (OSError, RuntimeError) as e:
        sys.exit("GoatCounter injoignable (%s) : vérifie ta connexion." % (getattr(e, "reason", None) or e))
    threading.Thread(target=live.follow, daemon=True).start()
    server = serve(live)
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    print("Stats en direct : " + url)
    print(live.summary)
    print("Laisse cette fenêtre ouverte : la page se met à jour toute seule. Ferme-la pour arrêter.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
