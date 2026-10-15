"""
Current game data for the overlay (the game's official Live Client Data API, 127.0.0.1:2999, read-only; nothing
is sent to the game).

What the overlay uses, and nothing else:
  - the player's level and skill ranks: recommended skill order (same as in the guide);
  - the scoreboard (what Tab shows to everyone): CS, vision score, kills, assists, levels and items per player;
  - objectives announced to the whole game (drakes, Baron, Herald, inhibitors): their respawn timers;
  - the game clock: shows the guide section matching the moment of the game.
Forbidden by Riot, hence absent: enemy ability, ultimate or summoner spell tracking, power spike alerts, "go gank"
style instructions. The overlay displays; it never tells the player what to do now.
"""

import glob
import json
import os
import threading
import time

from lol_client import ACTIVE_URL, fetch_live_game

# minion waves spawn at 0:30 and reach lane around 1:00 (jungle camps: 1:00); nobody farms before that,
# so CS per minute is counted from there (otherwise it is skewed early on)
FARM_START = 1.0

POSITIONS = {"TOP": "top", "JUNGLE": "jgl", "MIDDLE": "mid", "MID": "mid", "BOTTOM": "adc", "BOT": "adc",
             "UTILITY": "sup", "SUPPORT": "sup"}
ROW_ORDER = {"top": 0, "jgl": 1, "mid": 2, "adc": 3, "sup": 4}

# objective timers (game seconds), from the official wiki, unchanged in 2026 (Baron respawns at 20:00)
DRAKE_FIRST, DRAKE_RESPAWN, ELDER_DELAY = 300, 300, 360
BARON_FIRST, BARON_RESPAWN = 1200, 360
HERALD_SPAWN, HERALD_GONE = 900, 1185
INHIB_RESPAWN = 300

# in-game guide phases: early (before 3:00), laning (until 14:00, end of plates), then mid & late
PHASE_LANE, PHASE_LATE = 180, 840

# ultimates that level on their own (no skill point); Aphelios doesn't level his abilities
AUTO_R = {"Jayce", "Elise", "Nidalee", "Karma"}
NO_SKILLS = {"Aphelios"}
MAX_RANK = {"Q": 5, "W": 5, "E": 5, "R": 3}
ELIXIR_SKILL = 2150     # Elixir of Skill (Triple Tonic rune): one extra skill point WITHOUT a level up
FREE_RANKS = {"Udyr"}   # no ultimate at 6/11/16: follow the guide as is
AUTO_FIRST = {"Zeri": "Q"}      # skill already at rank 1 on level 1, no choice: missing from published orders
EVOLVE_CHAMPS = {"Khazix", "Viktor", "Kaisa"}   # evolving abilities: the stats also count the evolutions


def champ_key(p):
    raw = p.get("rawChampionName") or ""
    return raw.split("displayname_")[-1] if "displayname_" in raw else ""


def parse(data):
    """Useful snapshot of the game (None while the game doesn't answer yet)."""
    if not isinstance(data, dict):
        return None
    gd = data.get("gameData") or {}
    ap = data.get("activePlayer") or {}
    mine = {ap.get("riotId"), ap.get("summonerName"), ap.get("riotIdGameName")} - {None, ""}
    players = []
    me = None
    for i, p in enumerate(data.get("allPlayers") or []):
        sc = p.get("scores") or {}
        ids = {p.get("riotId"), p.get("summonerName"), p.get("riotIdGameName")} - {None, ""}
        if ids & mine and me is None:
            me = i
        players.append({
            "key": champ_key(p), "name": p.get("championName") or "", "team": p.get("team") or "",
            "role": POSITIONS.get((p.get("position") or "").upper()), "level": p.get("level") or 1,
            "cs": sc.get("creepScore") or 0, "k": sc.get("kills") or 0, "d": sc.get("deaths") or 0,
            "a": sc.get("assists") or 0, "ward": float(sc.get("wardScore") or 0),
            "items": [[it.get("itemID"), it.get("count") or 1, it.get("price") or 0] for it in p.get("items") or []
                      if it.get("itemID")],
            "ids": sorted(ids),
        })
    if not players or me is None:
        return None
    ab = ap.get("abilities") or {}
    events = []
    for e in (data.get("events") or {}).get("Events") or []:
        name = e.get("EventName")
        if name in ("DragonKill", "BaronKill", "HeraldKill", "InhibKilled", "InhibRespawned"):
            events.append({"name": name, "t": float(e.get("EventTime") or 0), "killer": e.get("KillerName") or "",
                           "type": e.get("DragonType") or "", "inhib": e.get("InhibKilled") or e.get("InhibRespawned") or ""})
    return {
        "t": float(gd.get("gameTime") or 0), "mode": gd.get("gameMode") or "", "map": gd.get("mapNumber"),
        "level": ap.get("level") or players[me]["level"], "gold": float(ap.get("currentGold") or 0),
        "abilities": {s: int((ab.get(s) or {}).get("abilityLevel") or 0) for s in "QWER"},
        "players": players, "me": me, "events": events,
    }


class LivePoller(threading.Thread):
    """Reads the current game every second during a game (every 5 s otherwise; the local call fails immediately
    outside a game). The latest snapshot is stored in core.live."""

    def __init__(self, core):
        super().__init__(name="live-game", daemon=True)
        self.core = core
        self._stop = threading.Event()
        self._last_ok = 0.0

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            st = self.core.lol_state or {}
            in_game = st.get("phase") in ("InProgress", "Reconnect")
            recent = time.time() - self._last_ok < 15
            snap = None
            if in_game or recent or not st.get("connected"):
                try:
                    snap = parse(fetch_live_game(timeout=1.5))
                except Exception:
                    snap = None
            if snap:
                self._last_ok = time.time()
            self.core.live = snap
            if snap:
                self._fast_until(snap, time.time() + 1.0)
            else:
                self._stop.wait(1.0 if in_game else 5.0)

    def _fast_until(self, snap, end):
        """Between full reads, level and skills are re-read 4 times per second (small request), so the level-up halo
        lights up as soon as a level is gained."""
        while not self._stop.is_set():
            left = end - time.time()
            if left <= 0:
                return
            self._stop.wait(min(0.25, left))
            try:
                ap = fetch_live_game(timeout=0.5, url=ACTIVE_URL)
            except Exception:
                ap = None
            if not isinstance(ap, dict) or not ap.get("level"):
                continue
            ab = ap.get("abilities") or {}
            abilities = {s: int((ab.get(s) or {}).get("abilityLevel") or 0) for s in "QWER"}
            if ap["level"] != snap["level"] or abilities != snap["abilities"]:
                snap = dict(snap, level=ap["level"], abilities=abilities)
                self.core.live = snap


# ----------------------------------------------------------------------------
# Calculations (pure functions, tested outside of games)
# ----------------------------------------------------------------------------

def mmss(sec):
    sec = max(0, int(round(sec)))
    return "%d:%02d" % (sec // 60, sec % 60)


def guide_phase(t):
    return "early" if t < PHASE_LANE else "matchup" if t < PHASE_LATE else "late"


def me_of(snap):
    return snap["players"][snap["me"]]


def sides(snap):
    """(allies, enemies), each in scoreboard row order (top, jungle, mid, ADC, support)."""
    me = me_of(snap)
    allies = [p for p in snap["players"] if p["team"] == me["team"]]
    enemies = [p for p in snap["players"] if p["team"] != me["team"]]
    if all(p["role"] for p in snap["players"]):
        allies.sort(key=lambda p: ROW_ORDER.get(p["role"], 9))
        enemies.sort(key=lambda p: ROW_ORDER.get(p["role"], 9))
    return allies, enemies


def lane_opponent(snap):
    me = me_of(snap)
    allies, enemies = sides(snap)
    if me["role"]:
        opp = next((p for p in enemies if p["role"] == me["role"]), None)
        if opp:
            return opp
    i = allies.index(me)
    return enemies[i] if i < len(enemies) else None


def rank_max(c, key="", order=""):
    """Max rank of a skill: 5 (ultimate: 3); 6 for the basic abilities of auto-ult champions (Jayce, Elise,
    Nidalee, Karma); at least what the most played order shows (Yuumi: Q at rank 6)."""
    base = 6 if key in AUTO_R and c != "R" else MAX_RANK[c]
    return max(base, order.count(c)) if order and key not in EVOLVE_CHAMPS else base


def can_level(c, ranks, lvl, key="", order=""):
    """Can this skill take one more rank at this champion level? Basic abilities: rank 1 at level 1, 2 at level 3,
    3 at 5...; ultimate at levels 6, 11 and 16."""
    if key in FREE_RANKS:
        return True
    if ranks.get(c, 0) >= rank_max(c, key, order):
        return False
    if c == "R":
        return ranks.get("R", 0) < sum(1 for t in (6, 11, 16) if lvl >= t)
    return ranks.get(c, 0) < (lvl + 1) // 2


def clean_order(key, order):
    """Published order -> playable order. Zeri: Q is already rank 1 at level 1 (missing from the stats, everything
    was shifted by one level). Kha'Zix, Viktor, Kai'Sa: the stats count evolutions as skill ups (impossible ranks,
    shifted ultimate), so the order is replayed with the game rules, ultimate at 6, 11 and 16."""
    if not order:
        return order
    first = AUTO_FIRST.get(key)
    if first and order[0] != first:
        order = first + order
    if key not in EVOLVE_CHAMPS:
        return order
    queue, out = list(order), []
    ranks = {c: 0 for c in "QWER"}
    for lv in range(1, len(order) + 1):
        if "R" in queue and can_level("R", ranks, lv, key):
            c = "R"
        else:
            c = next((x for x in queue if x != "R" and can_level(x, ranks, lv, key)), None)
        if not c:
            break
        queue.remove(c)
        out.append(c)
        ranks[c] += 1
    return "".join(out)


def skill_plan(order15, have, level, key, prio="", bonus=0):
    """Next skills to level per the most played order. The n-th point spent follows the n-th step of the guide: if
    another skill was leveled, just move to the next step, except for the ultimate or a never learned skill (caught
    up first). A skill that can't level yet (max rank for the level) gives up its turn.
    bonus = points on top of the level (Elixir of Skill). avail = skill points to spend."""
    if not order15 or key in NO_SKILLS:
        return None
    auto_r = key in AUTO_R
    letters = "QWE" if auto_r else "QWER"
    seq = [c for c in order15 if c in letters]
    counts = {c: 0 for c in "QWER"}
    for c in seq:
        counts[c] += 1
    # past level 15: ultimate at 16, then the remaining skills by priority
    for lv in range(len(seq) + 1, 19):
        if not auto_r and lv >= 16 and counts["R"] < MAX_RANK["R"]:
            c = "R"
        else:
            c = next((x for x in (prio or "QWE") + "QWE" if x in "QWE" and counts[x] < rank_max(x, key, order15)), None)
        if not c:
            break
        seq.append(c)
        counts[c] += 1
    spent = sum(have.get(c, 0) for c in letters)
    points = min(level + bonus, 18)    # no points past 18, even with the elixir
    ranks = {c: have.get(c, 0) for c in "QWER"}
    nxt = []
    for step in range(5):
        n = spent + step                  # guide step of this point (0 = level 1)
        lvl = max(level, n + 1 - bonus)   # champion level when this point is spent
        # caught up first: the ultimate, or a never learned skill the guide would already have taken at this step
        due = seq[:n + 1]
        catch = [x for x in "RQWE" if x in letters and ranks[x] < due.count(x) and (x == "R" or ranks[x] == 0)]
        order = catch + seq[n:] + [c for c in (prio or "QWE") + "QWER" if c in letters]
        c = next((x for x in order if x in letters and can_level(x, ranks, lvl, key, order15)), None)
        if not c:
            break
        nxt.append(c)
        ranks[c] += 1
    return {"avail": max(0, points - spent), "next": nxt, "first_level": max(1, spent + 1 - bonus), "level": level}


def item_value(p, prices):
    """Value of the items in inventory ("realized gold", as on the scoreboard)."""
    tot = 0
    for iid, count, price in p["items"]:
        tot += (prices.get(str(iid)) or price or 0) * (count or 1)
    return tot


def gold_diff(snap, prices):
    allies, enemies = sides(snap)
    me = me_of(snap)
    rows = []
    for i in range(max(len(allies), len(enemies))):
        a = allies[i] if i < len(allies) else None
        e = enemies[i] if i < len(enemies) else None
        va = item_value(a, prices) if a else 0
        ve = item_value(e, prices) if e else 0
        rows.append({"a": a["key"] if a else None, "e": e["key"] if e else None, "diff": va - ve, "mine": a is me})
    total = sum(item_value(p, prices) for p in allies) - sum(item_value(p, prices) for p in enemies)
    return {"rows": rows, "total": total}


def bench_refs(bench):
    """Emerald+ benchmarks for the champion in that role (lolalytics per-game averages) -> CS per minute, KDA."""
    if not bench or not bench.get("dur"):
        return {}
    return {"cs": bench["cs"] / (bench["dur"] - FARM_START),
            "kda": (bench["k"] + bench["a"]) / max(1.0, bench["d"])}


def quick_stats(snap, prices, avgs=None, bench=None):
    """Player stats: CS per minute and KDA against Emerald+ players on the same champion and role (or the player's
    own average without a benchmark); kill participation and vision against the player's average in that role."""
    t = snap["t"]
    mins = max(t, 1) / 60.0
    me = me_of(snap)
    allies, _ = sides(snap)
    team_kills = sum(p["k"] for p in allies)
    opp = lane_opponent(snap)
    vals = {
        "cs": me["cs"] / max(0.5, mins - FARM_START),
        "kda": (me["k"] + me["a"]) / max(1, me["d"]),
        "kp": (me["k"] + me["a"]) / team_kills if team_kills else None,
        "vision": me["ward"] / mins,
    }
    elo = bench_refs(bench)
    out = []
    for k in ("cs", "kda", "kp", "vision"):
        v = vals[k]
        src = "elo" if k in elo else "toi"
        ref = elo.get(k) if src == "elo" else (avgs or {}).get(k)
        # no verdict before 5 min, nor on a KDA with fewer than 3 events (0/1/0 says nothing)
        early = t < 300 or (k == "kda" and me["k"] + me["d"] + me["a"] < 3)
        out.append({"id": k, "value": v, "ref": ref, "src": src, "cmp": None if (v is None or ref is None or early)
                    else (1 if v >= ref * 1.05 else -1 if v <= ref * 0.95 else 0)})
    return {"rows": out, "level": me["level"], "opp_level": opp["level"] if opp else None,
            "cs": me["cs"], "opp_cs": opp["cs"] if opp else None, "opp": opp["key"] if opp else None,
            "avg_n": (avgs or {}).get("n", 0), "avg_scope": (avgs or {}).get("scope"), "elo": bool(elo)}


def _side_of(snap, killer):
    me = me_of(snap)
    for p in snap["players"]:
        if killer and (killer in p["ids"] or killer == p["name"]):
            return "ally" if p["team"] == me["team"] else "enemy"
    return None


INHIB_LANES = {"L1": "top", "C1": "mid", "R1": "bot"}


def objectives(snap):
    """Next objective spawns, from the game's announcements (visible to everyone)."""
    t = snap["t"]
    me = me_of(snap)
    drakes = {"ally": 0, "enemy": 0}
    last_drake = last_elder = last_baron = None
    herald = None
    inhibs = {}
    for e in snap["events"]:
        side = _side_of(snap, e["killer"])
        if e["name"] == "DragonKill":
            if e["type"] == "Elder":
                last_elder = e["t"]
            else:
                drakes[side or "?"] = drakes.get(side or "?", 0) + 1
                last_drake = e["t"]
        elif e["name"] == "BaronKill":
            last_baron = (e["t"], side)
        elif e["name"] == "HeraldKill":
            herald = side or "?"
        elif e["name"] == "InhibKilled":
            inhibs[e["inhib"]] = e["t"]
        elif e["name"] == "InhibRespawned":
            inhibs.pop(e["inhib"], None)
    rows = []
    soul = max(drakes.get("ally", 0), drakes.get("enemy", 0)) >= 4
    if soul:
        nxt = (last_elder + ELDER_DELAY) if last_elder is not None and last_elder > (last_drake or 0) else \
            (last_drake or 0) + ELDER_DELAY
        rows.append({"id": "elder", "label": "Elder", "at": nxt})
    else:
        nxt = (last_drake + DRAKE_RESPAWN) if last_drake is not None else DRAKE_FIRST
        rows.append({"id": "drake", "label": "Drake", "at": nxt})
    rows.append({"id": "baron", "label": "Nashor", "at": (last_baron[0] + BARON_RESPAWN) if last_baron else BARON_FIRST})
    if herald:
        rows.append({"id": "herald", "label": "Héraut", "taken": herald})
    elif t < HERALD_GONE:
        rows.append({"id": "herald", "label": "Héraut", "at": HERALD_SPAWN, "until": HERALD_GONE})
    for name, kt in sorted(inhibs.items(), key=lambda x: x[1]):
        back = kt + INHIB_RESPAWN
        if back <= t:
            continue
        # Barracks_T1_L1: T1 = blue team inhibitor (ORDER), T2 = red (CHAOS); L1/C1/R1 = top/mid/bot
        parts = name.split("_")
        team = "ORDER" if "T1" in parts else "CHAOS" if "T2" in parts else ""
        lane = next((INHIB_LANES[p] for p in parts if p in INHIB_LANES), "")
        rows.append({"id": "inhib", "label": "Inhib %s" % lane, "at": back,
                     "own": "ally" if team == me["team"] else "enemy"})
    for r in rows:
        if "at" in r:
            r["in"] = r["at"] - t
    return {"rows": rows, "drakes": {"ally": drakes.get("ally", 0), "enemy": drakes.get("enemy", 0)}, "t": t}


# ----------------------------------------------------------------------------
# Player averages (games recorded by the app)
# ----------------------------------------------------------------------------

def own_averages(folder, role=None, limit=20):
    """Per-minute averages over the player's recent Rift games (same role when there are at least 3)."""
    rows = []
    for fn in glob.glob(os.path.join(folder, "*.json")):
        try:
            with open(fn, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if d.get("mode") != "CLASSIC" or (d.get("duration") or 0) < 900:
            continue
        players = d.get("players") or []
        me = next((p for p in players if p.get("isMe")), None)
        if not me:
            continue
        mins = d["duration"] / 60.0
        tk = sum(p.get("k", 0) for p in players if p.get("teamId") == me.get("teamId"))
        rows.append((d.get("creation") or 0, me.get("role"), {
            "cs": me.get("cs", 0) / (mins - FARM_START), "kda": (me.get("k", 0) + me.get("a", 0)) / max(1, me.get("d", 0)),
            "vision": me.get("vision", 0) / mins, "kp": (me.get("k", 0) + me.get("a", 0)) / tk if tk else None}))
    rows.sort(key=lambda r: -r[0])
    pick = [r for r in rows if role and r[1] == role][:limit]
    scope = "role"
    if len(pick) < 3:
        pick, scope = rows[:limit], "all"
    if len(pick) < 3:
        return None
    out = {"n": len(pick), "scope": scope}
    for k in ("cs", "kda", "vision", "kp"):
        vals = [r[2][k] for r in pick if r[2][k] is not None]
        out[k] = sum(vals) / len(vals) if vals else None
    return out


# ----------------------------------------------------------------------------
# Keyboard layout (AZERTY: A Z E R) so the overlay shows the same letters as the game
# ----------------------------------------------------------------------------

def spell_keys():
    out = {s: s for s in "QWER"}
    try:
        import ctypes
        u = ctypes.windll.user32
        hkl = u.GetKeyboardLayout(0)
        for s, sc in zip("QWER", (0x10, 0x11, 0x12, 0x13)):   # physical key positions of Q W E R
            vk = u.MapVirtualKeyExW(sc, 1, hkl)
            if 0x41 <= vk <= 0x5A:
                out[s] = chr(vk)
    except (AttributeError, OSError):
        pass
    return out


# ----------------------------------------------------------------------------
# Sample game (overlay preview and placement outside of games)
# ----------------------------------------------------------------------------

def demo_snapshot(data, combo_key, t=754.0):
    """A plausible game at 12:34 around the shown guide, to preview every module outside of a game."""
    c = data.combos[combo_key]
    roles = ["top", "jgl", "mid", "adc", "sup"]
    freq = c["matchups"].get("frequent") or []
    opp = freq[0]["key"] if freq else None

    def popular(role, exclude):
        ks = sorted(data.by_role[role], key=lambda k: -data.combos[k]["month"]["pr"])
        return next(data.combos[k]["key"] for k in ks if data.combos[k]["key"] not in exclude)

    used = {c["key"]}
    if opp:
        used.add(opp)

    def build_items(key, role, n_core):
        b = (data.combos.get(data.combo_key(key, role)) or {}).get("items") or {}
        items = [[i, cnt, 0] for i, cnt in (b.get("start") or [])[:1]]
        items += [[i, 1, 0] for i in (b.get("core") or [])[:n_core]]
        return items

    stats = {   # level, CS, kills, deaths, assists, vision, completed items
        "top": (9, 92, 2, 1, 1, 9.0, 1), "jgl": (8, 70, 3, 2, 4, 14.0, 1), "mid": (9, 88, 1, 1, 3, 10.0, 1),
        "adc": (8, 81, 2, 2, 2, 8.0, 1), "sup": (7, 12, 0, 2, 5, 22.0, 1)}
    players = []
    for team in ("ORDER", "CHAOS"):
        for r in roles:
            if team == "ORDER":
                key = c["key"] if r == c["role"] else popular(r, used)
            else:
                key = opp if (r == c["role"] and opp) else popular(r, used)
            used.add(key)
            lv, cs, k, d, a, w, n_core = stats[r]
            if team == "CHAOS":
                lv, cs, k, d, a = lv - (1 if r == "top" else 0), cs - 8, d, k, a
            if team == "ORDER" and r == c["role"]:
                lv, cs, k, d, a, w = 8, 74, 2, 1, 3, 7.0
            players.append({"key": key, "name": data.champ_name(key), "team": team, "role": r, "level": lv,
                            "cs": cs, "k": k, "d": d, "a": a, "ward": w,
                            "items": build_items(key, r, n_core if team == "ORDER" else (0 if r == "mid" else n_core)),
                            "ids": ["%s#%d" % (key, len(players))]})
    me = roles.index(c["role"])
    order = (c.get("skills") or {}).get("order15") or ""
    have = {s: 0 for s in "QWER"}
    for ch in order[:7]:   # level 8 with a point to spend
        have[ch] += 1
    killer_ally = players[1]["ids"][0]
    killer_enemy = players[6]["ids"][0]
    return {
        "t": t, "mode": "CLASSIC", "map": 11, "level": 8, "gold": 640.0, "abilities": have,
        "players": players, "me": me, "demo": True,
        "events": [
            {"name": "DragonKill", "t": 371.0, "killer": killer_ally, "type": "Fire", "inhib": ""},
            {"name": "DragonKill", "t": 688.0, "killer": killer_enemy, "type": "Water", "inhib": ""},
        ],
    }
