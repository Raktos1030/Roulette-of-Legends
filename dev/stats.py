"""
Usage stats of Roulette of Legends in one page, opened in the browser: new players, players of the day and of the week,
updates by version (the app's anonymous counts), downloads (GitHub releases) and site visits (GoatCounter).

The GoatCounter API key (permission: read statistics) is asked once and kept on this computer only
(%LOCALAPPDATA%/RoL stats/goatcounter.key), never in the project.

usage: python dev/stats.py [--reset-key]
"""

import datetime
import getpass
import html
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

GOATCOUNTER = os.environ.get("ROL_STATS_API") or "https://rouletteoflegends.goatcounter.com/api/v0"
REPO = "Raktos1030/Roulette-of-Legends"
SINCE = datetime.date(2026, 10, 1)   # before the first release: everything counted since
KEY_FILE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "RoL stats", "goatcounter.key")
EDITIONS = {"full": "Complète", "lite": "Lite"}
SYSTEMS = {"windows": "Windows", "mac": "Mac"}


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


def releases():
    """[(tag, date, installers, zips)] from the GitHub releases, newest first."""
    out = []
    for r in get_json("https://api.github.com/repos/%s/releases?per_page=100" % REPO):
        n = {"inst": 0, "zip": 0}
        for a in r.get("assets") or []:
            if a["name"].endswith((".exe", ".dmg")):
                n["inst"] += a["download_count"]
            elif a["name"].endswith(".zip"):
                n["zip"] += a["download_count"]
        out.append((r["tag_name"], (r.get("published_at") or "")[:10], n["inst"], n["zip"]))
    return out


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


def compute(hits, site, rel, today):
    span = lambda n: [today - datetime.timedelta(days=i) for i in range(n)]
    ever = [SINCE + datetime.timedelta(days=i) for i in range((today - SINCE).days + 1)]
    monday = today - datetime.timedelta(days=today.weekday())
    weeks = [monday - datetime.timedelta(weeks=i) for i in range(8)][::-1]
    new = merge(hits, r"^/app/new/")
    day = merge(hits, r"^/app/day/")
    week = merge(hits, r"^/app/week/")
    s = {
        "today": today, "span7": span(7), "span30": span(30), "ever": ever,
        "new": {"7": total(new, span(7)), "30": total(new, span(30)), "all": total(new, ever)},
        "day": {"today": day.get(today, 0), "avg7": total(day, span(7)) / 7},
        "week": [(w, total(week, [w + datetime.timedelta(days=i) for i in range(7)])) for w in weeks],
        "day_series": [(d, day.get(d, 0), new.get(d, 0)) for d in span(30)[::-1]],
        "site": {"7": total(site, span(7)), "30": total(site, span(30)), "all": total(site, ever)},
        "site_series": [(d, site.get(d, 0)) for d in span(30)[::-1]],
        "releases": rel,
    }
    by_edition = []
    for path, h in sorted(hits.items()):
        m = re.match(r"^/app/new/(\w+)/(\w+)$", path)
        if m:
            by_edition.append(("%s · %s" % (EDITIONS.get(m[1], m[1]), SYSTEMS.get(m[2], m[2])),
                               total(h["days"], span(7)), total(h["days"], span(30)), total(h["days"], ever)))
    s["by_edition"] = by_edition

    def versions(pattern):
        out = {}
        for path, h in hits.items():
            m = re.match(pattern, path)
            if m:
                k = "%s %s" % (m["ver"], EDITIONS.get(m["ed"], m["ed"]))
                out[k] = out.get(k, 0) + total(h["days"], ever)
        return sorted(out.items(), key=lambda kv: [int(x) for x in re.findall(r"\d+", kv[0])], reverse=True)
    s["updates"] = versions(r"^/app/update/(?P<ed>\w+)/(?P<ver>[\d.]+)$")
    s["legacy"] = versions(r"^/app/(?P<ed>full|lite)/(?P<ver>[\d.]+)/\w+$")
    s["pages"] = sorted(((p, h["title"], total(h["days"], span(30))) for p, h in hits.items()
                         if not h["event"] and not p.startswith("/app/")), key=lambda x: -x[2])
    s["clicks"] = sorted(((p.split("/", 1)[1], total(h["days"], span(30)), total(h["days"], ever)) for p, h in hits.items()
                          if h["event"] and p.startswith("download/")), key=lambda x: -x[2])
    return s


# --- the page ------------------------------------------------------------------------------------------------
def bars(points, height=120):
    """Bar chart (inline SVG): points = [(label, value, accent value or None)], labels every few bars."""
    n = len(points) or 1
    top = max([v for _, v, *_ in points] + [1])
    w, gap = 100.0 / n, 100.0 / n * 0.22
    out = []
    for i, (label, v, *rest) in enumerate(points):
        h = v / top * (height - 22)
        x = i * w + gap / 2
        out.append('<rect x="%.2f%%" y="%.1f" width="%.2f%%" height="%.1f" rx="2" class="b"><title>%s : %s</title></rect>'
                   % (x, height - 18 - h, w - gap, max(h, 0.6 if v else 0), html.escape(label), v))
        if rest and rest[0]:
            h2 = rest[0] / top * (height - 22)
            out.append('<rect x="%.2f%%" y="%.1f" width="%.2f%%" height="%.1f" rx="2" class="b2"><title>%s : %s nouveau(x)</title></rect>'
                       % (x, height - 18 - h2, w - gap, h2, html.escape(label), rest[0]))
        if n <= 8 or i % (n // 6) == 0 or i == n - 1:
            out.append('<text x="%.2f%%" y="%d" class="t" text-anchor="middle">%s</text>' % (x + (w - gap) / 2, height - 4, html.escape(label)))
    out.append('<text x="0" y="10" class="t">%s</text>' % top)
    return '<svg class="chart" width="100%%" height="%d" role="img">%s</svg>' % (height, "".join(out))


def table(head, rows, empty):
    if not rows:
        return '<p class="muted">%s</p>' % html.escape(empty)
    th = "".join("<th>%s</th>" % html.escape(h) for h in head)
    tr = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % html.escape(str(c)) for c in r) for r in rows)
    return "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (th, tr)


TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stats Roulette of Legends</title>
<style>
:root { --bg: #070c16; --panel: #0d1524; --line: rgba(255, 255, 255, .08); --text: #ebe6da; --muted: #8b909a;
  --gold: #c8aa6e; --gold-hi: #e8d09a; --teal: #19d3c4; font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font-size: 14.5px; line-height: 1.5; }
main { max-width: 1100px; margin: 0 auto; padding: 28px max(16px, 3vw) 48px; display: grid; gap: 22px; }
h1 { margin: 0; font: 600 26px/1.2 Georgia, serif; letter-spacing: .02em; color: var(--gold-hi); }
h2 { margin: 0 0 12px; font-size: 12px; letter-spacing: .14em; text-transform: uppercase; color: var(--gold); }
header p, .muted { margin: 4px 0 0; color: var(--muted); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
.tile, section { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; min-width: 0; }
.tile span { font-size: 12px; color: var(--muted); }
.tile b { display: block; margin: 4px 0 2px; font: 600 34px/1.1 Bahnschrift, "Segoe UI", sans-serif; color: var(--text); font-variant-numeric: tabular-nums; }
.tile small { color: var(--muted); font-size: 12px; }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 22px; }
.chart { display: block; overflow: visible; }
.chart .b { fill: var(--gold); opacity: .85; }
.chart .b2 { fill: var(--teal); }
.chart .t { fill: var(--muted); font-size: 10px; }
.legend { display: flex; gap: 14px; margin-top: 8px; font-size: 12px; color: var(--muted); }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--line); }
th { font-size: 12px; font-weight: 600; color: var(--muted); }
td:not(:first-child), th:not(:first-child) { text-align: right; }
.wrap { overflow-x: auto; }
footer { color: var(--muted); font-size: 12.5px; display: grid; gap: 4px; }
</style></head><body><main>
<header><h1>Stats Roulette of Legends</h1><p>Le {{date}} à {{time}} · appli : comptages anonymes · site : GoatCounter · téléchargements : GitHub</p></header>
<div class="tiles">{{tiles}}</div>
<section><h2>Joueurs par jour · 30 jours</h2>{{daily}}
  <div class="legend"><span><i style="background:var(--gold)"></i>joueurs du jour</span><span><i style="background:var(--teal)"></i>dont nouveaux</span></div></section>
<div class="two">
  <section><h2>Joueurs par semaine · du lundi</h2>{{weekly}}</section>
  <section><h2>Nouveaux joueurs par édition</h2><div class="wrap">{{editions}}</div></section>
</div>
<div class="two">
  <section><h2>Mises à jour par version</h2><div class="wrap">{{updates}}</div></section>
  <section><h2>Téléchargements GitHub</h2><div class="wrap">{{releases}}</div></section>
</div>
<section><h2>Site · visites par jour · 30 jours</h2>{{site}}</section>
<div class="two">
  <section><h2>Pages du site · 30 jours</h2><div class="wrap">{{pages}}</div></section>
  <section><h2>Clics « Télécharger » sur le site</h2><div class="wrap">{{clicks}}</div></section>
</div>
{{legacy}}
<footer><span>Tes propres lancements comptent aussi : coupe « Statistiques anonymes » dans les Réglages de ton appli pour ne pas te compter.</span>
<span>Les zips GitHub comptent aussi les mises à jour faites depuis l'appli. Les comptages nouveaux joueurs / joueurs du jour existent depuis la 3.0.2.</span></footer>
</main></body></html>"""


def page(s, generated):
    fmt = lambda d: d.strftime("%d/%m")
    week_now, week_prev = s["week"][-1][1], s["week"][-2][1]
    inst = sum(r[2] for r in s["releases"])
    zips = sum(r[3] for r in s["releases"])
    tile = lambda label, big, sub: '<div class="tile"><span>%s</span><b>%s</b><small>%s</small></div>' % (
        html.escape(label), big, html.escape(sub))
    tiles = "".join([
        tile("Nouveaux joueurs · 7 jours", s["new"]["7"], "30 jours : %d · depuis le début : %d" % (s["new"]["30"], s["new"]["all"])),
        tile("Joueurs cette semaine", week_now, "semaine d'avant : %d" % week_prev),
        tile("Joueurs aujourd'hui", s["day"]["today"], "moyenne sur 7 jours : %.1f" % s["day"]["avg7"]),
        tile("Visites du site · 7 jours", s["site"]["7"], "30 jours : %d · depuis le début : %d" % (s["site"]["30"], s["site"]["all"])),
        tile("Installeurs téléchargés", inst, "et %d zips (mises à jour depuis l'appli)" % zips),
    ])
    daily = bars([(fmt(d), v, n) for d, v, n in s["day_series"]])
    weekly = bars([(fmt(w), v) for w, v in s["week"]])   # each week by its Monday
    site = bars([(fmt(d), v) for d, v in s["site_series"]])
    fill = {
        "date": generated.strftime("%d/%m/%Y"), "time": generated.strftime("%H:%M"), "tiles": tiles, "daily": daily,
        "weekly": weekly, "site": site,
        "editions": table(["Édition", "7 jours", "30 jours", "Total"], s["by_edition"], "Aucun nouveau joueur compté pour l'instant."),
        "updates": table(["Version", "Mises à jour"], s["updates"], "Aucune mise à jour comptée pour l'instant."),
        "releases": table(["Version", "Publiée", "Installeurs", "Zips"], s["releases"], "Aucune release."),
        "pages": table(["Page", "Titre", "Visites"], s["pages"], "Aucune visite."),
        "clicks": table(["Lien", "30 jours", "Total"], s["clicks"], "Aucun clic."),
        "legacy": ('<section><h2>Avant la 3.0.2 · lancements par version</h2><div class="wrap">%s</div></section>'
                   % table(["Version", "Lancements"], s["legacy"], "")) if s["legacy"] else "",
    }
    out = TEMPLATE
    for k, v in fill.items():
        out = out.replace("{{%s}}" % k, str(v))
    return out


def main():
    key = read_key("--reset-key" in sys.argv)
    today = datetime.date.today()
    try:
        hits = all_hits(key, SINCE, today)
        site_ids = [h["id"] for p, h in hits.items() if not h["event"] and not p.startswith("/app/")]
        site = site_days(key, site_ids, SINCE, today)
    except BadKey as e:
        os.remove(KEY_FILE)
        sys.exit(str(e))
    except urllib.error.URLError as e:
        sys.exit("GoatCounter injoignable (%s) : vérifie ta connexion." % getattr(e, "reason", e))
    try:
        rel = releases()
    except urllib.error.URLError:
        rel = []
    path = os.path.join(tempfile.gettempdir(), "rol-stats.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page(compute(hits, site, rel, today), datetime.datetime.now()))
    print("Stats : " + path)
    webbrowser.open("file:///" + path.replace("\\", "/"))


if __name__ == "__main__":
    main()
