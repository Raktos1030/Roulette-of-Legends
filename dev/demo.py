"""
Demo of the full app with a made-up player, to try everything by hand: every reward step done (the four roulette
skins, the Silver Shine opening, titles, Joker), a mastered champion, a booster of cards to open (it ends on the
crowning) and a roll pending.

Its profile, history and games live in a folder of their own (%TEMP%/RoL-demo, made again at each start unless
--keep): the player's own data, the LoL client, the Windows startup entry and the stats are never touched.

usage: python dev/demo.py [--keep] [--lang en]
"""

import json
import os
import random
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["ROL_NO_COUNT"] = "1"   # no usage count

import core  # noqa: E402

combo_key = "{}|{}".format   # as core.Data.combo_key

DEMO = os.path.join(tempfile.gettempdir(), "RoL-demo")
ROLES = core.ROLES
RANKS = [("SILVER", "II"), ("SILVER", "I"), ("GOLD", "IV"), ("GOLD", "III"), ("GOLD", "II"), ("GOLD", "I"),
         ("PLATINUM", "IV"), ("PLATINUM", "III"), ("PLATINUM", "II")]
MASTER = "Yasuo"
PENDING = ("Garen", "top")


def build(lang):
    """The made-up player: history, recorded games and profile in DEMO."""
    rng = random.Random(7)
    stats = json.load(open(os.path.join(core.DATA, "stats.json"), encoding="utf-8"))
    guides = set(stats["combos"])
    champs = sorted(c["key"] for c in json.load(open(os.path.join(core.DATA, "champions.json"), encoding="utf-8"))["by_id"].values())
    os.makedirs(os.path.join(DEMO, "games"), exist_ok=True)
    clock = [time.time() - 30 * 86400]
    entries, seen, used = [], {}, set()

    def tick(minutes):
        clock[0] += minutes * 60
        return clock[0]

    def entry(key, role, status="played", queue=None, win=False, deaths=4, detail=None):
        t = tick(rng.randint(40, 300))
        e = {"id": int(t * 1000), "created": t, "date": time.strftime("%d/%m %H:%M", time.localtime(t)), "key": key,
             "role": role, "status": status, "mode": "both" if combo_key(key, role) in guides else "chaos",
             "full": True, "official": True}
        if status != "played":
            if status == "cancelled":
                e.update(reason="rerolled", closed=t + 120)
            entries.append(e)
            return e
        gid = 7000000000 + len(entries)
        n = len(entries) * len(RANKS) // 130
        tier, div = RANKS[min(n, len(RANKS) - 1)]
        e.update(game_id=gid, queue=queue, played=key, win=win, kda=[rng.randint(2, 14), deaths, rng.randint(3, 16)],
                 duration=rng.randint(1500, 2300), ended=t + 2000, closed=t + 2000)
        rank = {"tier": tier, "division": div, "lp": rng.randint(0, 90), "wins": 60, "losses": 55, "provisional": False}
        if queue in (420, 440):
            qt = "RANKED_SOLO_5x5" if queue == 420 else "RANKED_FLEX_SR"
            e["lp_before"] = dict(rank, queue=qt)
            delta = rng.randint(18, 26) if win else -rng.randint(14, 21)
            e["lp"] = {"delta": delta, "queue": qt, "tier": tier, "division": div, "lp": max(0, rank["lp"] + delta),
                       "counted": True, "result": "win" if win else "loss", "placement": False, "multi": False}
        else:
            e["rank_ref"] = dict(rank, queue="RANKED_SOLO_5x5")
        if detail:   # recorded game: the 10 players (domination, pentakill)
            players = [{"teamId": 100 if i < 5 else 200, "championId": 0, "name": "Joueur %d" % (i + 1), "tag": "DEMO",
                        "k": rng.randint(0, 10), "d": rng.randint(1, 9), "a": rng.randint(0, 15), "cs": rng.randint(30, 250),
                        "gold": rng.randint(7000, 15000), "dmg": rng.randint(8000, 24000), "penta": 0, "win": (i < 5) == win,
                        "role": ROLES[i % 5], "isMe": i == 0} for i in range(10)]
            players[0].update(detail)
            json.dump({"source": "history", "gameId": gid, "creation": t, "duration": e["duration"], "queueId": queue,
                       "mode": "CLASSIC", "teams": [], "players": players},
                      open(os.path.join(DEMO, "games", "%d.json" % gid), "w", encoding="utf-8"))
        level = 4 if win and queue in (420, 440) else 3 if win else 2
        k = combo_key(key, role)
        seen[k] = max(seen.get(k, 0), level)
        used.add(k)
        entries.append(e)
        return e

    # a mastered champion: its five roles won in ranked (chaos roles count too)
    for role in ROLES:
        entry(MASTER, role, queue=420, win=True, deaths=rng.randint(1, 6))
    # cards in every role: ranked wins (legendary), normal wins (epic), losses (rare)
    pool = [k for k in sorted(guides) if k.partition("|")[0] != MASTER and k != combo_key(*PENDING)]
    rng.shuffle(pool)
    by_role = {r: [k for k in pool if k.endswith("|" + r)] for r in ROLES}
    plan = [(420, True)] * 9 + [(440, True)] * 1 + [(400, True)] * 3 + [(490, True)] * 1 + [(420, False)] * 3 + [(400, False)] * 2
    for i, (queue, win) in enumerate(plan):
        for role in ROLES:
            key = by_role[role][i].partition("|")[0]
            flawless = win and i % 4 == 0
            detail = {"dmg": 41000} if (role, i) == ("mid", 2) else {"penta": 1, "k": 19} if (role, i) == ("adc", 5) else None
            entry(key, role, queue=queue, win=win, deaths=0 if flawless else rng.randint(1, 8), detail=detail)
    # chaos role cards: champions where they have no guide
    chaos = [(c, r) for c in champs for r in ROLES if combo_key(c, r) not in guides and c != MASTER]
    rng.shuffle(chaos)
    for key, role in chaos[:12]:
        entry(key, role, queue=rng.choice([400, 420, 490]), win=rng.random() < .5)
    # drawn but not played: known only
    for k in pool[-6:]:
        entry(*k.split("|"), status="cancelled")
    entry(*PENDING, status="pending")

    # the booster: a few cards still to open, the mastered champion's last
    keep = [k for k in used if k.partition("|")[0] != MASTER]
    rng.shuffle(keep)
    fresh = set()
    for lv, n in ((2, 2), (3, 2), (4, 3)):   # two rare, two epic, three legendary
        fresh |= set([k for k in keep if seen[k] == lv][:n])
    fresh |= {combo_key(MASTER, r) for r in ROLES}
    opened = {k: lv for k, lv in seen.items() if k not in fresh}
    json.dump(entries, open(os.path.join(DEMO, "history.json"), "w", encoding="utf-8"))
    profile = {"lang": lang, "binder_seen": {"-": opened}, "roulette_mode": "official", "usage_stats": False,
               "tray_hint_shown": True, "overlay_tab_seen": True, "app_update_seen": core.APP_VERSION, "auto_update": False}
    json.dump(profile, open(os.path.join(DEMO, "profile.json"), "w", encoding="utf-8"))
    print("demo: %d rolls, %d cards, %d to open -> %s" % (len(entries), len(seen), len(fresh), DEMO))


def main():
    args = sys.argv[1:]
    lang = args[args.index("--lang") + 1] if "--lang" in args else ""
    if "--keep" not in args or not os.path.isfile(os.path.join(DEMO, "history.json")):
        shutil.rmtree(DEMO, ignore_errors=True)
        os.makedirs(DEMO)
        build(lang)
    # everything the app writes for this player goes to the demo folder
    core.PROFILE_PATH = os.path.join(DEMO, "profile.json")
    core.HISTORY_PATH = os.path.join(DEMO, "history.json")
    core.GAMES_DIR = os.path.join(DEMO, "games")
    core.INSTANCE_PATH = os.path.join(DEMO, ".instance")   # runs beside the player's own app
    import system
    system.migrate_autostart = lambda: None   # the Windows startup entry stays the player's
    import roulette_lol
    start = roulette_lol.start_services
    roulette_lol.start_services = lambda c, **kw: start(c, **dict(kw, with_updater=False))   # stats left as they are
    sys.argv = [sys.argv[0], "--no-lol", "--no-tray"]
    roulette_lol.main()


if __name__ == "__main__":
    main()
