"""
Automatic stats update.

Sources (the same ones the guides were written from):
  - Data Dragon (Riot): patch number, French names and ability descriptions, icons;
  - lolalytics: last 30 days and current patch, Emerald+, all regions (win rates, matchups, skill order, most
    played runes, summoner spells and items, for the overlay and the champ select import);
  - u.gg: last two patches, Emerald+, world (matchup cross-check, gold diff at 15 min); current patch builds
    (recommended and AD, AP, crit, lethality, on-hit, tank variants) for the guides' Build tab.

When: at startup, then every 6 hours, the app checks whether an update is needed:
  - a new patch has enough games (about 3 days of data);
  - or the stats are older than 7 days (the 30-day window moves).
Everything runs in the background; new files only replace the old ones once complete and checked.
Only the numbers change: the guide texts stay the same.
"""

import gzip
import hashlib
import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.request

from core import DATA, LITE, STATS_FILES, T, log_error, read_json, write_json

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
DD = "https://ddragon.leagueoflegends.com"
LOLA = "https://a1.lolalytics.com/mega/?ep=build-full&v=1&patch=%s&c=%s&lane=%s&tier=%s&queue=ranked&region=all"
LOLA_TEAM = LOLA.replace("ep=build-full", "ep=build-team")   # teammates (synergies), per role
DUO_LANE = {"adc": "support", "sup": "bottom"}   # bot lane partner: lolalytics lane
UGG = "https://stats2.u.gg/lol/1.5/%s/%s/ranked_solo_5x5/%d/1.5.0.json"
LANE = {"top": "top", "jgl": "jungle", "mid": "middle", "adc": "bottom", "sup": "support"}
UROLE = {"top": "4", "jgl": "1", "mid": "5", "adc": "3", "sup": "2"}
EVOLVE_CHAMPS = {"Khazix", "Viktor", "Kaisa"}    # champions with evolving abilities (order given by u.gg)
SK = "QWER"
K_SHRINK = 500
STATE_PATH = os.path.join(DATA, "update.json")
CACHE = os.path.join(DATA, "cache")
CHECK_EVERY = 6 * 3600
REFRESH_DAYS = 7
MIN_PATCH_SHARE = 0.10   # the new patch must hold >= 10 % of the 30-day games (about 3 days)
# stats published by .github/workflows/stats.yml on the repository's "stats" branch: the apps download them instead
# of querying lolalytics and u.gg themselves (one update a day for everyone)
STATS_URL = "https://raw.githubusercontent.com/Raktos1030/Roulette-of-Legends/stats/"
STATS_FORMAT = 1
CENTRAL_MAX_AGE = 14   # days; older published stats mean the workflow stopped, and the app updates on its own
LATEST_RELEASE = "https://github.com/Raktos1030/Roulette-of-Legends/releases/latest"   # redirects to .../tag/vX.Y.Z


def fetch(url, tries=3, binary=False, timeout=45):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            return body if binary else json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                return None
        except (OSError, ValueError) as e:
            last = e
        time.sleep(2 + 3 * i)
    raise IOError("%s: %s" % (url.split("?")[0], last))


def latest_app_version():
    """Version of the latest published release ("2.3"), read from the redirect of the releases page, or None."""
    req = urllib.request.Request(LATEST_RELEASE, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            final = r.geturl()
    except (OSError, ValueError):
        return None
    tag = final.rstrip("/").rsplit("/", 1)[-1]
    return tag[1:] if tag.startswith("v") and all(p.isdigit() for p in tag[1:].split(".")) else None


def newer(version, than):
    as_tuple = lambda v: tuple(int(p) for p in v.split("."))   # noqa: E731
    return as_tuple(version) > as_tuple(than)


def display_patch(ver):
    """"16.19.1" (internal version) -> "26.19" (official patch name)."""
    major, minor = ver.split(".")[:2]
    return "%d.%s" % (int(major) + 10, minor)


def lola_patch(ver):
    return ".".join(ver.split(".")[:2])


def ugg_patch(ver):
    return "_".join(ver.split(".")[:2])


# ----------------------------------------------------------------------------
# Calculations (same as the ones used to write the guides)
# ----------------------------------------------------------------------------

def header(d):
    h = d["header"]
    return {"wr": float(h["wr"]), "pr": float(h["pr"]), "br": float(h["br"]), "games": h["n"],
            "tier": h.get("tier"), "rank": h.get("rank"), "rank_total": h.get("rankTotal")}


def skills(d):
    def letters(code):
        return "".join(SK[int(ch) - 1] for ch in str(code) if ch in "1234")
    s6 = d.get("skill6") or []
    paths = [{"path": letters(x[0]), "pct": round(x[2], 1)} for x in s6[:3] if x[2] >= 10]
    so = (d.get("skillOrder") or [[None, 0, 0, 0]])[0]
    order15 = ((d.get("summary") or {}).get("pick") or {}).get("skillorder", {}).get("id", "")
    return {"paths": paths, "prio": so[0], "prio_pct": so[2], "order15": letters(order15)}


def items_build(d):
    """Most common items (lolalytics): starting items, core trio, then options for items 4 to 6."""
    it = (((d or {}).get("summary") or {}).get("pick") or {}).get("items") or {}
    st, core_ = it.get("start") or {}, it.get("core") or {}
    if not st and not core_:
        return None
    start = [[i, c] for i, c in zip(st.get("setUnique") or [], st.get("count") or [])] or         [[i, 1] for i in st.get("set") or []]
    return {"start": start, "core": core_.get("set") or [], "core_n": core_.get("n"),
            "opts": [[o["id"] for o in (it.get(k) or [])[:3] if o.get("id")] for k in ("item4", "item5", "item6")],
            # completed items and boots bought by this champion (pick rate %): picked against the enemy comp
            "pool": [[x[0], round(x[2], 2)] for x in (d.get("popularItem") or []) if len(x) > 2 and x[2] >= 0.5][:30],
            "boots": [[x[0], round(x[2], 2)] for x in (d.get("boots") or []) if len(x) > 2 and x[2] >= 1
                      and x[0] not in (1001, 9999)]}


def item_cats(v):
    """Categories that matter against a comp: magic resist, armor, anti-heal, anti-tank, tenacity."""
    import re
    st = v.get("stats") or {}
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", v.get("description") or ""))
    out = []
    if st.get("FlatSpellBlockMod"):
        out.append("mr")
    if st.get("FlatArmorMod"):
        out.append("armor")
    if re.search(r"hémorragie|blessures graves", text, re.I):
        out.append("antiheal")
    if re.search(r"\d+\s?% de pénétration|réduit (leur |son |l')armure|réduit (leur |sa |la )résistance magique|"
                 r"de leurs PV max|PV max(imum)? de|PV actuels|en fonction de leurs PV bonus", text, re.I):
        out.append("antitank")
    if "Tenacity" in (v.get("tags") or []):
        out.append("tenacity")
    return out


def runes_build(d):
    """Most common rune page and summoner spells (lolalytics)."""
    pick = ((d or {}).get("summary") or {}).get("pick") or {}
    rs = (pick.get("runes") or {}).get("set") or {}
    out = {}
    if len(rs.get("pri") or []) == 4 and len(rs.get("sec") or []) == 2 and len(rs.get("mod") or []) == 3:
        out["runes"] = {"pri": rs["pri"], "sec": rs["sec"], "mod": rs["mod"]}
    sums = (pick.get("sums") or {}).get("ids") or []
    if len(sums) == 2:
        out["sums"] = sums
    return out


# build variants published by u.gg (file, id, display name)
UGG_BUILDS = [("overview", "reco", "Recommandé"), ("ad-overview", "ad", "AD"), ("ap-overview", "ap", "AP"),
              ("crit-overview", "crit", "Crit"), ("lethality-overview", "lethality", "Létalité"),
              ("onhit-overview", "onhit", "On-hit"), ("tank-overview", "tank", "Tank")]
SHARDS = {5008: ("Force adaptative", "StatModsAdaptiveForceIcon"), 5005: ("Vitesse d'attaque", "StatModsAttackSpeedIcon"),
          5007: ("Accélération de compétence", "StatModsCDRScalingIcon"), 5010: ("Vitesse de déplacement", "StatModsMovementSpeedIcon"),
          5011: ("PV", "StatModsHealthPlusIcon"), 5013: ("Ténacité et résistance aux ralentissements", "StatModsTenacityIcon"),
          5001: ("PV selon le niveau", "StatModsHealthScalingIcon")}
SHARD_ROWS = [[5008, 5005, 5007], [5008, 5010, 5001], [5011, 5013, 5001]]


def ugg_build(b):
    """A u.gg "overview" row -> app build (None if incomplete)."""
    def rate(m, w):
        return {"games": int(m or 0), "wr": round(100.0 * w / m, 2) if m else None}
    try:
        runes, spells, start, core_, sk, opts, total = b[0], b[1], b[2], b[3], b[4], b[5], b[6]
        shards = b[8] if len(b) > 8 else None
        out = {"games": int(total[1] or 0), "wr": round(100.0 * total[0] / total[1], 2) if total[1] else None}
        if len(runes) >= 5 and len(runes[4]) == 6:
            out["runes"] = dict(rate(runes[0], runes[1]), pri=runes[2], sec=runes[3], perks=list(runes[4]),
                                shards=[int(x) for x in (shards[2] if shards and len(shards) > 2 else [])])
        if len(spells) >= 3 and len(spells[2]) == 2:
            out["sums"] = dict(rate(spells[0], spells[1]), ids=list(spells[2]))
        if len(start) >= 3 and start[2]:
            out["start"] = dict(rate(start[0], start[1]), ids=[i for i in start[2] if i])
        if len(core_) >= 3 and core_[2] and all(core_[2]):
            out["core"] = dict(rate(core_[0], core_[1]), ids=list(core_[2]))
        out["opts"] = [[{"id": o[0], "wr": round(100.0 * o[1] / o[2], 2) if o[2] else None, "games": o[2]}
                        for o in col[:3] if len(o) >= 3 and o[0]] for col in (opts or [])[:3]]
        if len(sk) >= 4 and sk[2]:
            out["skills"] = dict(rate(sk[0], sk[1]), path="".join(x for x in sk[2] if x in "QWER"), prio=sk[3])
        # evolution order (Kha'Zix, Viktor, Kai'Sa: the only champions u.gg fills this block for)
        ev = b[9] if len(b) > 9 else None
        if isinstance(ev, list) and len(ev) >= 3 and isinstance(ev[2], str) and ev[2]:
            out["evolve"] = dict(rate(ev[0], ev[1]), order="".join(x for x in ev[2] if x in "QWER"))
    except (IndexError, TypeError, ZeroDivisionError):
        return None
    return out if out.get("runes") and out.get("core") else None


def pick_builds(variants):
    """The recommended build, then variants that really differ and are played enough (3 at most)."""
    reco = variants.get("reco")
    if not reco:
        return []
    out = [dict(reco, id="reco", label="Recommandé")]

    def sig(b):
        return (b["runes"]["perks"] and sorted(b["runes"]["perks"])[0], b["runes"]["pri"], tuple(sorted(b["core"]["ids"])))
    seen = {sig(reco)}
    cands = [(v["games"], vid) for vid, v in variants.items() if vid != "reco"]
    for games, vid in sorted(cands, reverse=True):
        v = variants[vid]
        if games < max(400, 0.05 * reco["games"]) or sig(v) in seen:
            continue
        seen.add(sig(v))
        out.append(dict(v, id=vid, label=dict((x[1], x[2]) for x in UGG_BUILDS)[vid]))
        if len(out) >= 4:
            break
    return out


def matchups(role, d_e, d_all, mu_role, names, keys):
    lane = LANE[role]
    h = d_e["header"]
    total = h["n"]
    min_n = 400 if total >= 60000 else 250 if total >= 25000 else 150
    min_pr = 0.5
    allrows = (d_e.get("enemy") or {}).get(lane, [])
    rows = [r for r in allrows if r[5] >= min_n and r[4] >= min_pr]
    if len(rows) < 12:
        min_pr = 0.3
        rows = [r for r in allrows if r[5] >= min_n and r[4] >= min_pr]
    tier_used = "emerald_plus"
    if len(rows) < 10 and d_all:
        h_all = d_all["header"]
        min_n = 300 if h_all["n"] >= 60000 else 150
        rows = [r for r in (d_all.get("enemy") or {}).get(lane, []) if r[5] >= min_n and r[4] >= min_pr]
        tier_used = "all"
        h = h_all
    base = float(h["wr"])
    tw = sum(a[0] for a in (mu_role or {}).values())
    tn = sum(a[1] for a in (mu_role or {}).values())
    ugg_base = 100.0 * tw / tn if tn else None

    def entry(r):
        o, wr, _, _, _, n = r[:6]
        e = {"cid": o, "name": names.get(o, str(o)), "key": keys.get(o), "wr": round(wr, 2), "n": n,
             "shr": round((wr * n + base * K_SHRINK) / (n + K_SHRINK), 2)}
        u = (mu_role or {}).get(o)
        if u and u[1] >= 150:
            e["ugg_wr"] = round(100 * u[0] / u[1], 2)
            e["ugg_n"] = u[1]
            e["gd15"] = round(u[2] / u[1])
            dl, du = wr - base, e["ugg_wr"] - ugg_base
            if abs(du) < 1 or abs(dl) < 1:
                e["check"] = "neutral"
            elif dl * du > 0:
                e["check"] = "ok"
            else:
                e["check"] = "contradiction"
        else:
            e["check"] = "absent"
        e["rel"] = "solid" if n >= 3000 else "fair" if n >= 1000 else "limited"
        return e

    ents = [entry(r) for r in rows]
    good = [e for e in sorted(ents, key=lambda e: -e["shr"]) if e["wr"] >= 51.0][:6]
    bad = [e for e in sorted(ents, key=lambda e: e["shr"]) if e["wr"] <= 49.0][:6]
    good_clear, bad_clear = bool(good), bool(bad)
    if not good:
        good = sorted(ents, key=lambda e: -e["shr"])[:3]
    if not bad:
        bad = sorted(ents, key=lambda e: e["shr"])[:3]
    freq = sorted(ents, key=lambda e: -e["n"])[:6]
    return {"base": base, "ugg_base": round(ugg_base, 2) if ugg_base else None, "tier_used": tier_used,
            "min_n": min_n, "min_pr": min_pr, "n_opps": len(ents), "good": good, "bad": bad,
            "good_clear": good_clear, "bad_clear": bad_clear, "frequent": freq,
            "all": sorted(ents, key=lambda e: -e["n"])}


# lolalytics game length buckets ("sidebar.time"): <15, 15-20, 20-25, 25-30, 30-35, 35-40, 40+ min;
# the middle of each bucket is used for the average length
TIME_MID = {"1": 13.0, "2": 17.5, "3": 22.5, "4": 27.5, "5": 32.5, "6": 37.5, "7": 43.0}


def bench(d):
    """Emerald+ benchmarks for the champion in that role (per-game averages): CS (minions + monsters), kills,
    deaths, assists and average game length. {} when lolalytics doesn't provide them."""
    sb = (d or {}).get("sidebar") or {}
    st = {r[0]: r[2] for r in (sb.get("stats") or {}).get("stats") or [] if isinstance(r, list) and len(r) > 2}
    tm = {k: v for k, v in ((sb.get("time") or {}).get("time") or {}).items() if k in TIME_MID}
    n = sum(tm.values())
    if not n or st.get("minions") is None or st.get("deaths") is None:
        return {}
    dur = sum(TIME_MID[k] * v for k, v in tm.items()) / n
    return {"dur": round(dur, 2), "cs": round(st["minions"] + (st.get("jungleCS") or 0), 2),
            "k": st.get("kills", 0), "d": st["deaths"], "a": st.get("assists", 0), "n": n}


def duos(role, d_team, base, names, keys):
    """Bot lane partners: which supports an ADC wins the most with (and the other way around). Same rules as
    matchups: enough games, played enough, win rate shrunk toward the champion's average (a duo over 300 games
    doesn't rank above a duo over 5,000)."""
    lane = DUO_LANE.get(role)
    allrows = [r for r in (((d_team or {}).get("team") or {}).get(lane) or []) if isinstance(r, list) and len(r) >= 6]
    if not allrows:
        return None
    total = sum(r[5] for r in allrows)
    min_n = 400 if total >= 60000 else 250 if total >= 25000 else 150
    min_pr = 0.5
    rows = [r for r in allrows if r[5] >= min_n and r[4] >= min_pr]
    if len(rows) < 10:
        min_pr = 0.3
        rows = [r for r in allrows if r[5] >= min_n and r[4] >= min_pr]
    ents = []
    for r in rows:
        o, wr, _d1, d2, pr, n = r[:6]
        ents.append({"cid": o, "name": names.get(o, str(o)), "key": keys.get(o), "wr": round(wr, 2), "n": n,
                     "pr": round(pr, 2), "syn": round(d2, 2),
                     "shr": round((wr * n + base * K_SHRINK) / (n + K_SHRINK), 2),
                     "rel": "solide" if n >= 3000 else "correct" if n >= 1000 else "limite"})
    if not ents:
        return None
    good = sorted(ents, key=lambda e: -e["shr"])[:6]
    bad = [e for e in sorted(ents, key=lambda e: e["shr"]) if e not in good][:4]
    return {"partner": "sup" if role == "adc" else "adc", "base": base, "min_n": min_n, "min_pr": min_pr,
            "n_partners": len(ents), "total": total, "good": good, "bad": bad,
            "frequent": sorted(ents, key=lambda e: -e["n"])[:6],
            # every pair with at least 100 games, so the in-game duo is found even outside the lists
            "all": [[r[0], keys.get(r[0]), round(r[1], 2), r[5]] for r in allrows if r[5] >= 100]}


def clean_html(t):
    """Data Dragon description -> text: HTML line breaks become spaces ("HP. After")."""
    import re
    t = re.sub(r"<br\s*/?>", " ", t or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t).replace("\n", " ")
    return re.sub(r"\s{2,}", " ", t).strip()


# ----------------------------------------------------------------------------
# Update
# ----------------------------------------------------------------------------

class Cancelled(Exception):
    pass


class Updater:
    def __init__(self, core):
        self.core = core
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._force = False
        self.busy = False
        self.state = read_json(STATE_PATH, {}) or {}
        last = self.state.get("last_check_txt")
        self._status({"state": "idle", "text": "", "last_check": last})

    def start(self):
        threading.Thread(target=self._loop, name="updater", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def request(self, force=False):
        if self.busy:   # an update is already running
            return
        self._force = self._force or force
        self._wake.set()

    def _status(self, st):
        st.setdefault("last_check", self.state.get("last_check_txt"))
        self.core.set_update_status(st)

    def _save_state(self):
        try:
            write_json(STATE_PATH, self.state)
        except OSError:
            pass

    def _loop(self):
        self._wake.wait(45)   # let the app start quietly
        while not self._stop.is_set():
            force, self._force = self._force, False
            self._wake.clear()
            from core import APP_VERSION
            latest = latest_app_version()
            if latest and newer(latest, APP_VERSION):
                self.core.set_app_update(latest)
            if force or self.core.profile.get("auto_update", True):
                try:
                    self.run(force=force)
                except Cancelled:
                    return
                except Exception as e:
                    import traceback
                    log_error("update: " + traceback.format_exc())
                    self._status({"state": "error", "text": T("La mise à jour a échoué (%s). Nouvel essai plus tard.") % e})
            self._wake.wait(CHECK_EVERY)

    def _check_stop(self):
        if self._stop.is_set():
            raise Cancelled()

    # --- decision ---
    def run(self, force=False, local=False):
        """local: compute the stats here (lolalytics, u.gg) instead of downloading the published ones."""
        self.busy = True
        try:
            self._status({"state": "checking"})
            if not local:
                try:
                    published = self._published(force)
                except (IOError, ValueError, KeyError):
                    published = None
                if published is not None:
                    return published
            versions = fetch(DD + "/api/versions.json")
            latest = versions[0]
            prev = next(v for v in versions if lola_patch(v) != lola_patch(latest))
            prev2 = next(v for v in versions if lola_patch(v) not in (lola_patch(latest), lola_patch(prev)))
            meta = self.core.data.meta
            now = time.time()
            self.state["last_check"] = now
            self.state["last_check_txt"] = time.strftime("%d/%m/%Y %H:%M", time.localtime(now))
            self._save_state()
            # does the new patch have enough games? (probe on a very popular combo)
            probe = max(self.core.data.combos.values(), key=lambda c: c["month"]["games"])
            slug = "wukong" if probe["key"] == "MonkeyKing" else probe["key"].lower()
            d30 = fetch(LOLA % ("30", slug, LANE[probe["role"]], "emerald_plus"))
            dnew = fetch(LOLA % (lola_patch(latest), slug, LANE[probe["role"]], "emerald_plus"))
            share = (dnew or {}).get("header", {}).get("n", 0) / max(1, (d30 or {}).get("header", {}).get("n", 1))
            if share >= MIN_PATCH_SHARE:
                cur, before = latest, prev
            else:
                cur, before = prev, prev2
            age_days = self._age_days(meta.get("generated"))
            new_patch = display_patch(cur) != meta.get("patch")
            # data from an older version (no runes or items): complete it right away
            incomplete = any(not c.get("runes") or not (c.get("items") or {}).get("pool") or "heal" not in c
                             or "builds" not in c for c in self.core.data.combos.values())
            if not force and not new_patch and age_days < REFRESH_DAYS and not incomplete:
                if any(c["role"] in DUO_LANE and "all" not in (c.get("duo") or {}) for c in self.core.data.combos.values()):
                    self.fill_duos()
                if any("bench" not in c for c in self.core.data.combos.values()):
                    self.fill_bench()
                if any(c["key"] in EVOLVE_CHAMPS and "evolve" not in c for c in self.core.data.combos.values()):
                    self.fill_evolve()
                txt = T("Statistiques à jour (patch %s).") % meta.get("patch")
                if lola_patch(latest) != lola_patch(cur):
                    txt += T(" Le patch %s vient de sortir : ses statistiques arriveront dès qu'il aura assez de parties.") \
                           % display_patch(latest)
                self._status({"state": "uptodate", "text": txt})
                return False
            self.build(latest, cur, before)
            return True
        finally:
            self.busy = False

    def _published(self, force=False):
        """Downloads the stats published by the repository when they are newer than the local ones.
        Returns True (installed), False (already up to date), or None when unavailable or stale."""
        try:
            manifest = fetch(STATS_URL + "manifest.json", tries=2, timeout=20)
        except IOError:
            return None
        if not isinstance(manifest, dict) or manifest.get("format") != STATS_FORMAT or \
                self._age_days(manifest.get("generated")) > CENTRAL_MAX_AGE:
            return None
        meta = self.core.data.meta
        now = time.time()
        self.state["last_check"] = now
        self.state["last_check_txt"] = time.strftime("%d/%m/%Y %H:%M", time.localtime(now))
        self._save_state()
        if not force and (manifest.get("generated") or "") <= (meta.get("generated") or ""):
            self._status({"state": "uptodate", "text": T("Statistiques à jour (patch %s).") % meta.get("patch")})
            return False
        files = {}
        names = [n for n in STATS_FILES if not (LITE and n == "compo.json")]
        for i, name in enumerate(names):
            self._check_stop()
            self._progress(i, len(names), T("Téléchargement des statistiques du patch %s…") % manifest.get("patch"))
            info = (manifest.get("files") or {}).get(name) or {}
            body = fetch(STATS_URL + name, binary=True, tries=2, timeout=60)
            if not body or hashlib.sha256(body).hexdigest() != info.get("sha256"):
                return None
            files[name] = body
        stats = json.loads(files["stats.json"].decode("utf-8"))
        if len(stats.get("combos") or {}) < 0.95 * len(self.core.data.combos):
            return None
        dd_ver = stats["meta"].get("ddragon")
        if dd_ver and dd_ver != meta.get("ddragon"):   # new patch: images of new champions, items and runes
            self._status({"state": "building", "progress": 1.0, "text": T("Calcul des nouvelles statistiques…")})
            full_fr = fetch("%s/cdn/%s/data/fr_FR/championFull.json" % (DD, dd_ver))["data"]
            en = fetch("%s/cdn/%s/data/en_US/champion.json" % (DD, dd_ver))["data"]
            runes_fr = fetch("%s/cdn/%s/data/fr_FR/runesReforged.json" % (DD, dd_ver))
            runes = json.loads(files["runes.json"].decode("utf-8"))
            self._download_assets(dd_ver, stats["combos"], runes.get("sums") or {}, full_fr, en, runes_fr)
        os.makedirs(CACHE, exist_ok=True)
        for name in ("stats.json", "compo.json", "champions.json"):
            src = os.path.join(DATA, name)
            if name in files and os.path.exists(src):
                shutil.copy2(src, os.path.join(CACHE, name.replace(".json", "_previous.json")))
        for name, body in files.items():
            path = os.path.join(DATA, name)
            with open(path + ".tmp", "wb") as f:
                f.write(body)
            os.replace(path + ".tmp", path)
        self.state["last_ok"] = time.time()
        self._save_state()
        self.core.reload_data()
        self._status({"state": "done", "text": T("Statistiques mises à jour : patch %s, données du %s.") % (
            stats["meta"].get("patch"), time.strftime("%d/%m/%Y", time.strptime(stats["meta"]["generated"], "%Y-%m-%d")))})
        return True

    def fill_duos(self):
        """Bot lane duos for stats that don't have them yet (one request per ADC and support guide, about a minute),
        without a full update."""
        data = self.core.data
        path = os.path.join(DATA, "stats.json")
        st = read_json(path)
        if not st:
            return
        by_id = (data.all_champs.get("by_id") or {})
        names = {int(cid): c["name"] for cid, c in by_id.items()}
        keys = {int(cid): c["key"] for cid, c in by_id.items()}
        todo = [k for k, c in st["combos"].items() if c["role"] in DUO_LANE and "all" not in (c.get("duo") or {})]
        for i, k in enumerate(todo):
            self._check_stop()
            c = st["combos"][k]
            self._progress(i, len(todo), T("Duos de la botlane : %s…") % c["name"])
            slug = "wukong" if c["key"] == "MonkeyKing" else c["key"].lower()
            try:
                dteam = fetch(LOLA_TEAM % ("30", slug, LANE[c["role"]], "emerald_plus"))
                time.sleep(0.2)
            except IOError:
                continue
            duo = duos(c["role"], dteam, c["month"]["wr"], names, keys)
            if duo:
                c["duo"] = duo
        write_json(path, st, compact=True)
        self.core.reload_data()

    def fill_evolve(self):
        """Evolution order for stats that don't have it yet (one u.gg file per affected champion, a few seconds)."""
        path = os.path.join(DATA, "stats.json")
        st = read_json(path)
        if not st:
            return
        ver = st["meta"].get("ddragon") or ""
        todo = [k for k, c in st["combos"].items() if c["key"] in EVOLVE_CHAMPS and "evolve" not in c]
        for i, k in enumerate(todo):
            self._check_stop()
            c = st["combos"][k]
            self._progress(i, len(todo), T("Évolutions : %s…") % c["name"])
            try:
                ov = fetch(UGG % ("overview", ugg_patch(ver), c["cid"]), tries=2, timeout=30)
            except IOError:
                continue
            row = (((ov or {}).get("12") or {}).get("17") or {}).get(UROLE[c["role"]])
            b = ugg_build(row[0]) if isinstance(row, list) and row and isinstance(row[0], list) else None
            c["evolve"] = (b or {}).get("evolve")
        write_json(path, st, compact=True)
        self.core.reload_data()

    def fill_bench(self):
        """Emerald+ benchmarks (CS, KDA, game length) for stats that don't have them yet (one request per guide,
        a few minutes), without a full update."""
        path = os.path.join(DATA, "stats.json")
        st = read_json(path)
        if not st:
            return
        todo = [k for k, c in st["combos"].items() if "bench" not in c]
        for i, k in enumerate(todo):
            self._check_stop()
            c = st["combos"][k]
            self._progress(i, len(todo), T("Repères Émeraude+ : %s…") % c["name"])
            slug = "wukong" if c["key"] == "MonkeyKing" else c["key"].lower()
            try:
                d30 = fetch(LOLA % ("30", slug, LANE[c["role"]], "emerald_plus"))
                time.sleep(0.2)
            except IOError:
                continue
            c["bench"] = bench(d30)
        write_json(path, st, compact=True)
        self.core.reload_data()

    @staticmethod
    def _age_days(iso):
        try:
            t = time.mktime(time.strptime(iso, "%Y-%m-%d"))
            return (time.time() - t) / 86400.0
        except (TypeError, ValueError):
            return 999

    # --- build ---
    def _progress(self, done, total, text):
        self._status({"state": "downloading", "progress": done / max(1, total), "text": text})

    def build(self, dd_ver, cur, before):
        core = self.core
        combos_old = core.data.combos
        pool = [{"key": c["key"], "cid": c["cid"], "role": c["role"], "name": c["name"], "name_en": c.get("name_en")}
                for c in combos_old.values()]
        os.makedirs(os.path.join(CACHE, "ugg"), exist_ok=True)

        # 1. Data Dragon: French names, abilities, champion list
        self._progress(0, 1, T("Données officielles de Riot (patch %s)…") % display_patch(dd_ver))
        full_fr = fetch("%s/cdn/%s/data/fr_FR/championFull.json" % (DD, dd_ver))["data"]
        en = fetch("%s/cdn/%s/data/en_US/champion.json" % (DD, dd_ver))["data"]
        id2key = {int(c["key"]): k for k, c in en.items()}
        id2fr = {int(c["key"]): full_fr[k]["name"] for k, c in en.items() if k in full_fr}

        # 2. u.gg: matchups for both patches (the finished patch is cached), current patch ranking
        cids = sorted({c["cid"] for c in pool})
        total = len(cids) + len(pool)
        done = 0
        ugg_mu, ugg_rk, ugg_builds = {}, {}, {}
        for cid in cids:
            self._check_stop()
            done += 1
            self._progress(done, total, T("Recoupement u.gg : champion %d sur %d…") % (done, len(cids)))
            mu = {}
            for ver in (cur, before):
                lines = self._ugg_matchups(cid, ugg_patch(ver), final=(ver != cur))
                for role, rows in lines.items():
                    agg = mu.setdefault(role, {})
                    for o, w, n, g in rows:
                        a = agg.setdefault(o, [0, 0, 0])
                        a[0] += w
                        a[1] += n
                        a[2] += g
            ugg_mu[cid] = mu
            rk = fetch(UGG % ("rankings", ugg_patch(cur), cid))
            ugg_rk[cid] = ((rk or {}).get("12") or {}).get("17") or {}
            time.sleep(0.15)
            ugg_builds[cid] = self._ugg_builds(cid, cur, before)

        # 3. lolalytics: 30 days, current patch, and all ranks when the Emerald+ sample is too small
        combos, vs, damage = {}, {}, {}
        failures = []
        for c in pool:
            self._check_stop()
            done += 1
            self._progress(done, total, T("Statistiques lolalytics : %s %s…") % (c["name"], {"jgl": "Jungle", "sup": "Support",
                           "adc": "ADC", "mid": "Mid", "top": "Top"}[c["role"]]))
            slug = "wukong" if c["key"] == "MonkeyKing" else c["key"].lower()
            lane = LANE[c["role"]]
            try:
                d30 = fetch(LOLA % ("30", slug, lane, "emerald_plus"))
                time.sleep(0.2)
                dcur = fetch(LOLA % (lola_patch(cur), slug, lane, "emerald_plus"))
                time.sleep(0.2)
                if not d30 or "header" not in d30:
                    raise IOError("empty response")
                dall = None
                rows = [r for r in (d30.get("enemy") or {}).get(lane, []) if r[5] >= 150]
                if len(rows) < 10:
                    dall = fetch(LOLA % ("30", slug, lane, "all"))
                    time.sleep(0.2)
            except IOError as e:
                failures.append("%s|%s : %s" % (c["key"], c["role"], e))
                continue
            # current form: if the champion has too few games on the current patch (brand new patch or rarely played
            # champion), use the previous patch and flag it
            month = header(d30)
            pstats = header(dcur) if dcur and "header" in dcur else None
            if pstats:
                pstats["label"] = display_patch(cur)
            if not pstats or pstats["games"] < max(1000, 0.05 * month["games"]):
                try:
                    dprev = fetch(LOLA % (lola_patch(before), slug, lane, "emerald_plus"))
                    time.sleep(0.2)
                except IOError:
                    dprev = None
                if dprev and "header" in dprev and dprev["header"].get("n", 0) > (pstats or {}).get("games", 0):
                    pstats = header(dprev)
                    pstats["label"] = display_patch(before)
                    pstats["thin"] = display_patch(cur)
            ur = UROLE[c["role"]]
            rk = ugg_rk.get(c["cid"], {}).get(ur)
            ugg_cur = None
            if rk and rk[1]:
                ugg_cur = {"wr": round(100.0 * rk[0] / rk[1], 2), "games": rk[1],
                           "rank": rk[2] if isinstance(rk[2], int) else None,
                           "rank_total": rk[3] if isinstance(rk[3], int) else None}
            key = "%s|%s" % (c["key"], c["role"])
            share = ((d30.get("nav") or {}).get("lanes") or {}).get(lane)
            # items: the current patch's when it has enough games (items change with patches)
            items = None
            if dcur and "header" in dcur and dcur["header"].get("n", 0) >= max(1000, 0.05 * month["games"]):
                items = items_build(dcur)
                if items:
                    items["src"] = display_patch(cur)
            if not items:
                items = items_build(d30)
                if items:
                    items["src"] = "30d"
            rb = {}
            if items and items["src"] != "30d":
                rb = runes_build(dcur)
            if not rb.get("runes"):
                rb = runes_build(d30)
            combos[key] = {
                "name": id2fr.get(c["cid"], c["name"]), "name_en": en.get(c["key"], {}).get("name", c["name_en"]),
                "key": c["key"], "cid": c["cid"], "role": c["role"],
                "share": round(share, 2) if share is not None else combos_old[key]["share"],
                "month": month, "patch": pstats, "ugg": ugg_cur,
                "skills": skills(d30), "items": items, "runes": rb.get("runes"), "sums": rb.get("sums"),
                "builds": ugg_builds.get(c["cid"], {}).get(UROLE[c["role"]]) or [],
                "evolve": next((b["evolve"] for b in ugg_builds.get(c["cid"], {}).get(UROLE[c["role"]]) or []
                                if b.get("evolve")), None),
                "matchups": matchups(c["role"], d30, dall, ugg_mu.get(c["cid"], {}).get(ur), id2fr, id2key),
            }
            # average heals and damage taken per game (spots healers and frontline in a comp)
            sb = {r[0]: r[2] for r in ((d30.get("sidebar") or {}).get("stats") or {}).get("stats") or []
                  if isinstance(r, list) and len(r) > 2}
            if sb.get("heal") is not None:
                combos[key]["heal"] = round(sb["heal"])
            if sb.get("damageTaken") is not None:
                combos[key]["taken"] = round(sb["damageTaken"])
            combos[key]["bench"] = bench(d30)
            if c["role"] in DUO_LANE:   # bot lane: partners this champion wins with
                try:
                    dteam = fetch(LOLA_TEAM % ("30", slug, lane, "emerald_plus"))
                    time.sleep(0.2)
                    duo = duos(c["role"], dteam, month["wr"], id2fr, id2key)
                    if duo:
                        combos[key]["duo"] = duo
                except IOError:
                    pass
            hd = d30["header"]
            dm = hd.get("damage") or {}
            tot = sum(dm.values())
            if tot:
                damage[key] = {k: round(100.0 * dm.get(k, 0) / tot) for k in ("physical", "magic", "true")}
            lanes = {}
            rev = {v: k for k, v in LANE.items()}
            for ln, rows in (d30.get("enemy") or {}).items():
                role = rev.get(ln)
                if role:
                    lanes[role] = {str(r[0]): [round(r[1], 1), r[5]] for r in rows if len(r) >= 6 and r[5] >= 150}
            vs[key] = {"avg": hd["wr"], "vs": lanes}

        # 4. checks before replacing
        if len(combos) < 0.95 * len(pool):
            raise IOError("%d of %d combos fetched (%s)" % (len(combos), len(pool), "; ".join(failures[:3])))
        for key, c in combos_old.items():   # missing combo: keep the old one rather than losing it
            combos.setdefault(key, c)
        self._status({"state": "building", "progress": 1.0, "text": T("Calcul des nouvelles statistiques…")})
        kits = {}
        for k in sorted({c["key"] for c in pool}):
            f = full_fr.get(k)
            if not f:
                kits[k] = core.data.kits.get(k, {})
                continue
            out = {"P": {"name": f["passive"]["name"], "desc": clean_html(f["passive"]["description"])}}
            for s, spell in zip(SK, f["spells"]):
                out[s] = {"name": spell["name"], "desc": clean_html(spell["description"]),
                          "cd": spell.get("cooldownBurn"), "range": spell.get("rangeBurn")}
            kits[k] = out
        patch_name = display_patch(cur)
        today = time.strftime("%Y-%m-%d")
        stats = {
            "meta": {
                "patch": patch_name, "generated": today, "ddragon": dd_ver,
                "sources": {
                    "lolalytics": "lolalytics.com — 30 derniers jours, Émeraude+, toutes régions",
                    "lolalytics_patch": "lolalytics.com — patch %s uniquement, Émeraude+ (forme actuelle)" % patch_name,
                    "ugg": "u.gg — patchs %s + %s cumulés, Émeraude+, monde (recoupement des matchups, écart d'or à 15 min)"
                           % (display_patch(before), patch_name),
                },
            },
            "kits": kits,
            "combos": combos,
        }
        old_compo = core.data.compo or {}
        profiles = dict(old_compo.get("profiles") or {})
        new_champs = [k for k in full_fr if k not in profiles]
        if new_champs:
            profiles.update(self._profiles_for(new_champs, full_fr))
        compo = {"meta": {"source_vs": "lolalytics.com, 30 jours, Émeraude+, toutes régions (>= 150 parties)",
                          "source_profiles": (old_compo.get("meta") or {}).get("source_profiles", "Meraki Analytics")},
                 "vs": vs, "damage": damage, "profiles": profiles}
        champs = {"version": dd_ver, "by_id": {str(cid): {"key": id2key[cid], "name": id2fr.get(cid, id2key[cid])}
                                                for cid in id2key}}

        items_fr = fetch("%s/cdn/%s/data/fr_FR/item.json" % (DD, dd_ver))["data"]
        item_list = {"version": dd_ver, "items": {
            i: {"name": v.get("name", ""), "gold": (v.get("gold") or {}).get("total", 0), "cat": item_cats(v)}
            for i, v in items_fr.items() if (v.get("maps") or {}).get("11")}}
        # runes (trees, French names) and summoner spells: champ select import and display
        runes_fr = fetch("%s/cdn/%s/data/fr_FR/runesReforged.json" % (DD, dd_ver))
        sums_fr = fetch("%s/cdn/%s/data/fr_FR/summoner.json" % (DD, dd_ver))["data"]
        rune_list = {"version": dd_ver, "trees": {}, "runes": {}, "sums": {}}
        for tree in runes_fr:
            rune_list["trees"][str(tree["id"])] = {"name": tree["name"], "slots": [[r["id"] for r in sl["runes"]] for sl in tree["slots"]]}
            for sl in tree["slots"]:
                for r in sl["runes"]:
                    rune_list["runes"][str(r["id"])] = {"name": r["name"], "tree": tree["id"]}
        for v in sums_fr.values():
            rune_list["sums"][str(v["key"])] = {"name": v["name"], "image": v["image"]["full"]}
        rune_list["shards"] = {str(k): v[0] for k, v in SHARDS.items()}
        rune_list["shard_rows"] = SHARD_ROWS

        # 5. missing images (new champions, ability and suggested item icons)
        self._download_assets(dd_ver, combos, rune_list["sums"], full_fr, en, runes_fr)

        # 6. replace (previous version kept in data/cache)
        for name in ("stats.json", "compo.json", "champions.json"):
            src = os.path.join(DATA, name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(CACHE, name.replace(".json", "_previous.json")))
        write_json(os.path.join(DATA, "stats.json"), stats, compact=True)
        write_json(os.path.join(DATA, "compo.json"), compo, compact=True)
        write_json(os.path.join(DATA, "champions.json"), champs, compact=True)
        write_json(os.path.join(DATA, "items.json"), item_list, compact=True)
        write_json(os.path.join(DATA, "runes.json"), rune_list, compact=True)
        self.state["last_ok"] = time.time()
        self._save_state()
        core.reload_data()
        txt = T("Statistiques mises à jour : patch %s, données du %s.") % (patch_name, time.strftime("%d/%m/%Y"))
        if failures:
            txt += T(" (%d combinaison(s) gardée(s) de la version précédente)") % len(failures)
        self._status({"state": "done", "text": txt})
        if new_champs:
            log_error("update: new champions without a guide: %s" % ", ".join(new_champs))

    def _ugg_builds(self, cid, cur, before):
        """u.gg builds of a champion per u.gg role: {"4": [recommended, variants...], ...}. Current patch; previous
        patch if the recommended build still has too few games (brand new patch)."""
        from concurrent.futures import ThreadPoolExecutor
        out = {}
        for ver in (cur, before):
            self._check_stop()
            per_role = {}

            def get(kind):
                try:
                    return fetch(UGG % (kind, ugg_patch(ver), cid), tries=2, timeout=30)
                except IOError:
                    return None
            with ThreadPoolExecutor(max_workers=len(UGG_BUILDS)) as ex:   # all 7 files at once
                files = list(ex.map(get, [k for k, _, _ in UGG_BUILDS]))
            for (kind, vid, _), data in zip(UGG_BUILDS, files):
                region = ((data or {}).get("12") or {}).get("17") or {}
                for role, row in region.items():
                    b = ugg_build(row[0]) if isinstance(row, list) and row and isinstance(row[0], list) else None
                    if b:
                        per_role.setdefault(role, {})[vid] = b
            for role, variants in per_role.items():
                if role not in out and variants.get("reco") and variants["reco"]["games"] >= 1500:
                    out[role] = pick_builds(variants)
                    out[role][0]["patch"] = display_patch(ver)
            if out:
                break
        return out

    def _ugg_matchups(self, cid, upatch, final):
        """u.gg matchups of a champion for a patch, summarized (the raw file is close to 1 MB compressed)."""
        path = os.path.join(CACHE, "ugg", "%s_%d.json" % (upatch, cid))
        if final and os.path.exists(path):
            cached = read_json(path)
            if cached is not None:
                return {r: [tuple(x) for x in rows] for r, rows in cached.items()}
        data = fetch(UGG % ("matchups", upatch, cid))
        out = {}
        region = ((data or {}).get("12") or {}).get("17") or {}
        for role in ("1", "2", "3", "4", "5"):
            rows = (region.get(role) or [[]])[0] or []
            out[role] = [(x[0], x[2] - x[1], x[2], -x[4]) for x in rows if len(x) > 4 and x[2] >= 15]
        if final:   # only a finished patch is cached: its numbers won't change anymore
            try:
                write_json(path, out, compact=True)
            except OSError:
                pass
        time.sleep(0.15)
        return out

    def _profiles_for(self, keys, full_fr):
        """Profile (classes, control, toughness, mobility) of champions released since the last version."""
        out = {}
        try:
            meraki = fetch("https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions.json", timeout=90)
        except IOError:
            meraki = {}
        by_key = {v.get("key"): v for v in (meraki or {}).values()}
        for k in keys:
            ch = full_fr.get(k, {})
            m = by_key.get(k)
            info = ch.get("info") or {}
            adaptive = "magic" if info.get("magic", 0) > info.get("attack", 0) else "physical"
            if m:
                ar = m.get("attributeRatings") or {}
                out[k] = {"classes": m.get("roles") or [], "control": ar.get("control", 2),
                          "toughness": ar.get("toughness", 2), "mobility": ar.get("mobility", 2),
                          "adaptive": "magic" if m.get("adaptiveType") == "MAGIC_DAMAGE" else "physical"}
            else:
                out[k] = {"classes": [t.upper() for t in ch.get("tags") or []], "control": 2,
                          "toughness": 3 if info.get("defense", 0) >= 7 else 2 if info.get("defense", 0) >= 4 else 1,
                          "mobility": 2, "adaptive": adaptive, "source": "ddragon"}
        return out

    def _download_assets(self, dd_ver, combos, sums, full_fr, en, runes_fr):
        """Missing images for these stats: champions, abilities, items of the builds, runes, summoner spells."""
        used = set()
        for c in combos.values():
            b = c.get("items") or {}
            used.update(x[0] for x in b.get("start") or [])
            used.update(b.get("core") or [])
            for o in b.get("opts") or []:
                used.update(o)
            used.update(x[0] for x in b.get("pool") or [])
            used.update(x[0] for x in b.get("boots") or [])
            for bd in c.get("builds") or []:
                used.update(bd.get("start", {}).get("ids") or [])
                used.update(bd.get("core", {}).get("ids") or [])
                for col in bd.get("opts") or []:
                    used.update(o["id"] for o in col)
        icons = []
        for tree in runes_fr:
            icons.append((str(tree["id"]), tree["icon"]))
            for sl in tree["slots"]:
                icons += [(str(r["id"]), r["icon"]) for r in sl["runes"]]
        icons += [(str(k), "perk-images/StatMods/%s.png" % v[1]) for k, v in SHARDS.items()]
        self._assets(dd_ver, full_fr, en, [c["key"] for c in combos.values()], sorted(str(i) for i in used), icons,
                     [(k, v["image"]) for k, v in sums.items()])

    def _assets(self, dd_ver, full_fr, en, pool_keys, item_ids=(), rune_icons=(), sum_icons=()):
        img = os.path.join(DATA, "img")
        jobs = [(os.path.join(img, "items", i + ".png"), "%s/cdn/%s/img/item/%s.png" % (DD, dd_ver, i)) for i in item_ids]
        jobs += [(os.path.join(img, "runes", i + ".png"), "%s/cdn/img/%s" % (DD, path)) for i, path in rune_icons]
        jobs += [(os.path.join(img, "sums", i + ".png"), "%s/cdn/%s/img/spell/%s" % (DD, dd_ver, f)) for i, f in sum_icons]
        for k in en:
            jobs.append((os.path.join(img, "icons", k + ".png"), "%s/cdn/%s/img/champion/%s.png" % (DD, dd_ver, k)))
            jobs.append((os.path.join(img, "loading", k + ".jpg"), "%s/cdn/img/champion/loading/%s_0.jpg" % (DD, k)))
            jobs.append((os.path.join(img, "splash", k + ".jpg"), "%s/cdn/img/champion/splash/%s_0.jpg" % (DD, k)))
        for k in sorted(set(pool_keys)):
            f = full_fr.get(k)
            if not f:
                continue
            jobs.append((os.path.join(img, "spells", k + "_P.png"),
                         "%s/cdn/%s/img/passive/%s" % (DD, dd_ver, f["passive"]["image"]["full"])))
            for s, spell in zip(SK, f["spells"]):
                jobs.append((os.path.join(img, "spells", "%s_%s.png" % (k, s)),
                             "%s/cdn/%s/img/spell/%s" % (DD, dd_ver, spell["image"]["full"])))
        missing = list(dict((p, u) for p, u in jobs if not os.path.exists(p)).items())
        for i, (path, url) in enumerate(missing):
            self._check_stop()
            if i % 20 == 0:
                self._status({"state": "building", "progress": 1.0, "text": T("Images : %d sur %d…") % (i, len(missing))})
            try:
                body = fetch(url, binary=True, tries=2)
                if body:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path + ".tmp", "wb") as f:
                        f.write(body)
                    os.replace(path + ".tmp", path)
            except IOError:
                pass


# ----------------------------------------------------------------------------
# Publishing (repository workflow): python updater.py --publish DIR [--force]
# ----------------------------------------------------------------------------

class _Headless:
    """Minimal core for running the updater outside the app."""

    def __init__(self):
        from core import Data
        self._data_cls = Data
        self.data = Data()
        self.profile = {"auto_update": True}

    def set_update_status(self, st):
        if st.get("text") and st.get("state") != "downloading":
            print(st["text"], flush=True)

    def reload_data(self):
        self.data = self._data_cls()


def publish(out, force=False):
    """Updates data/ from the previously published stats (out/), computes new stats when due, then writes the
    published set back to out/: the stats files, the u.gg cache of finished patches and manifest.json."""
    ugg_out, ugg_local = os.path.join(out, "cache", "ugg"), os.path.join(CACHE, "ugg")
    for name in STATS_FILES:
        if os.path.exists(os.path.join(out, name)):
            shutil.copy2(os.path.join(out, name), os.path.join(DATA, name))
    if os.path.isdir(ugg_out):
        shutil.copytree(ugg_out, ugg_local, dirs_exist_ok=True)
    updater = Updater(_Headless())
    try:
        updater.run(force=force, local=True)
    except Exception as e:   # keep publishing the current stats; the workflow shows the error
        print("::warning title=Stats update failed::%s" % " ".join(str(e).split()), flush=True)
    files = {}
    for name in STATS_FILES:
        with open(os.path.join(DATA, name), "rb") as f:
            body = f.read()
        with open(os.path.join(out, name), "wb") as f:
            f.write(body)
        files[name] = {"sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}
    if os.path.isdir(ugg_local):
        shutil.copytree(ugg_local, ugg_out, dirs_exist_ok=True)
    meta = read_json(os.path.join(DATA, "stats.json"))["meta"]
    write_json(os.path.join(out, "manifest.json"), {"format": STATS_FORMAT, "patch": meta.get("patch"),
                                                    "generated": meta.get("generated"),
                                                    "ddragon": meta.get("ddragon"), "files": files})
    print("Published: patch %s, data of %s" % (meta.get("patch"), meta.get("generated")))


if __name__ == "__main__":
    import sys
    if "--publish" in sys.argv:
        publish(os.path.abspath(sys.argv[sys.argv.index("--publish") + 1]), force="--force" in sys.argv)
