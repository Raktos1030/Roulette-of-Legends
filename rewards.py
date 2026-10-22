"""
Rewards path of the binder: one ladder of milestones, from the first rolls to a mastered champion. Each step
unlocks its rewards: a card back, a title, a roulette skin, an interface theme, a booster opening or an exploit
stamp. Everything is read from the history of the LoL account; nothing is stored but the steps already shown.

Exploits, read from the games themselves (rolls only: the rolled champion, in its role, as for the cards):
  flawless    a win without dying
  domination  the most damage to champions of the ten players
  penta       a pentakill (games recorded since the app keeps that number)
Their stamp goes on that card.

The Joker, from the first step on: one in reserve, earned back 10 rolls played after the last one used. A roll
passed with it is closed as "joker" in the history, not counted as cancelled.
"""

from collection import CARD

STAMPS = ("flawless", "domination", "penta")
READY = {"title", "joker", "stamp", "back", "theme", "roulette", "opening"}   # reward kinds the app already gives
LOOKS = {"theme": "hextech", "roulette": "classic", "opening": "classic"}   # looks picked once unlocked: their default
JOKER_AT = 5        # rolls played to unlock the Joker (first step)
JOKER_EVERY = 10    # rolls played to get it back after using it

# (id, name, [(counter, goal)], [(kind, id, label)]); the 4 card backs keep their own unlocks (collection.BACKS)
LADDER = (
    ("recruit", "Recrue du destin", [("rolls", JOKER_AT)], [("title", "recruit", "Recrue du destin"), ("joker", "joker", "Le Joker")]),
    ("silver", "Le collectionneur", [("cards", 10)], [("opening", "silver", "Ouverture Éclat d'argent")]),
    ("flawless", "Sans faillir", [("flawless", 1)], [("stamp", "flawless", "Tampon Sans faillir")]),
    ("void", "La première galerie", [("cards", 25)], [("back", "void", "Dos Néant")]),
    ("chaos", "L'appel du chaos", [("chaos", 10)], [("back", "infernal", "Dos Infernal")]),
    ("arsenal", "L'arsenal", [("epics", 10)], [("roulette", "infernal", "Roulette infernale")]),
    ("domination", "Le prédateur", [("domination", 1)], [("stamp", "domination", "Tampon Domination")]),
    ("five", "La voie des cinq", [("roles", 10)], [("theme", "void", "Thème Néant")]),
    ("untouchable", "Intouchable", [("flawless", 5)], [("title", "untouchable", "Intouchable")]),
    ("finisher", "Le finisseur", [("penta", 1)], [("stamp", "penta", "Tampon Pentakill"), ("title", "finisher", "Le finisseur")]),
    ("gold", "La salle dorée", [("cards", 50), ("epics", 10)], [("theme", "gold", "Thème Or")]),
    ("prism", "Le panthéon", [("legendary", 25)], [("back", "prism", "Dos Prismatique")]),
    ("legend", "Légende vivante", [("legendary", 40)], [("roulette", "prism", "Roulette prismatique"), ("title", "legend", "Légende vivante")]),
    ("master", "Champion maître", [("masters", 1)], [("back", "crown", "Dos Royal"), ("title", "master", "Maître de {0}")]),
)


def counted(e):
    """A roll that fills the binder: played to the end with the rolled champion, role drawn (as collection.cards)."""
    return (not e.get("free") and e.get("status") == "played" and e.get("mode") != "role"
            and not (e.get("played") and e["played"] != e["key"]))


def exploits(entries, detail):
    """({card key: [stamps]}, {stamp: games}) from the rolls. detail(game_id): the recorded game, or None."""
    stamps, count = {}, {s: 0 for s in STAMPS}
    for e in entries:
        if not counted(e):
            continue
        got = set()
        kda = e.get("kda") or []
        if e.get("win") and len(kda) == 3 and kda[1] == 0:
            got.add("flawless")
        d = detail(e["game_id"]) if e.get("game_id") else None
        players = (d or {}).get("players") or []
        me = next((p for p in players if p.get("isMe")), None)
        if me and me.get("dmg") and me["dmg"] >= max(p.get("dmg") or 0 for p in players):
            got.add("domination")
        if me and me.get("penta"):
            got.add("penta")
        for s in got:
            count[s] += 1
            card = stamps.setdefault("%s|%s" % (e["key"], e["role"]), [])
            if s not in card:
                card.append(s)
    return {k: [s for s in STAMPS if s in v] for k, v in stamps.items()}, count


def counters(got, milestones, roles, entries, exploit_count):
    """Every counter the ladder reads. milestones: collection.milestones (cards, chaos, legendary, masters)."""
    c = dict(milestones)
    c["epics"] = sum(1 for x in got.values() if x["level"] >= 3)
    c["roles"] = min(sum(1 for k, x in got.items() if x["level"] >= CARD and k.endswith("|" + r)) for r in roles)
    c["rolls"] = sum(1 for e in entries if not e.get("free") and e.get("status") == "played")
    c.update(exploit_count)
    return c


def ladder(counts):
    out = []
    for sid, name, conds, rewards in LADDER:
        cs = [{"counter": k, "goal": g, "have": min(counts.get(k, 0), g)} for k, g in conds]
        out.append({"id": sid, "name": name, "conds": cs, "done": all(x["have"] >= x["goal"] for x in cs),
                     "rewards": [{"kind": k, "id": i, "label": label, "ready": k in READY} for k, i, label in rewards]})
    return out


def joker(entries):
    """{"unlocked", "available", "next_in"}: rolls played still needed before it comes back."""
    played = [e for e in entries if not e.get("free") and e.get("status") == "played"]
    unlocked = len(played) >= JOKER_AT
    used = [e.get("closed") or e["created"] for e in entries if e.get("reason") == "joker"]
    since = sum(1 for e in played if e["created"] > max(used)) if used else JOKER_EVERY
    available = unlocked and since >= JOKER_EVERY
    return {"unlocked": unlocked, "available": available, "next_in": 0 if available or not unlocked else JOKER_EVERY - since}


def looks(steps, picked):
    """{kind: {"current", "options": [{"id", "unlocked", "step"}]}} for the looks of LOOKS. picked: {kind: id}."""
    out = {}
    for kind, default in LOOKS.items():
        opts = [{"id": default, "unlocked": True, "step": None}] + [
            {"id": r["id"], "unlocked": s["done"], "step": i + 1}
            for i, s in enumerate(steps) for r in s["rewards"] if r["kind"] == kind]
        cur = picked.get(kind)
        out[kind] = {"current": cur if any(o["id"] == cur and o["unlocked"] for o in opts) else default, "options": opts}
    return out


def titles(steps, masters):
    """Titles won: those of the steps done, one "Master of" per mastered champion (names)."""
    out = []
    for st in steps:
        for r in st["rewards"]:
            if r["kind"] == "title" and st["done"]:
                if r["id"] == "master":
                    out += [{"id": "master:" + k, "label": r["label"], "arg": name} for k, name in masters]
                else:
                    out.append({"id": r["id"], "label": r["label"], "arg": None})
    return out
