"""
Collection binder: one card per champion and role (865 cards), filled only by the official roulette, read from the
local history of the LoL account.

Official roulette: role and champion both drawn (chaos or not, solo or group), no favorite filter. A champ select
reroll (ban, champion taken, autofill) keeps the status of the roll it replaces. The personal roulette (picked role or
champion, favorites) fills nothing.

Card levels, from the best game of that champion in the role played (autofill on a role the champion plays: the roll
moves there):
  0 locked      never drawn
  1 known       drawn but not played (rerolled, Joker, banned...), or played with another champion: not a card, the
                champion shows greyed
  2 rare        a game played with it
  3 epic        a win outside ranked (normal, quick play), on the Rift
  4 legendary   a ranked win (solo/duo or flex): what the master set asks for
A champion is mastered when its five roles are legendary; roles without a guide (chaos) belong to the master set too.
"""

RANKED = {420, 440}
TIERS = ("IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER")
DIVISIONS = ("IV", "III", "II", "I")
CS_REROLLS = ("champion_banned", "champion_taken", "autofill")   # reasons of a champ select reroll
LEVELS = ("locked", "known", "rare", "epic", "legendary")
KNOWN = 1
CARD = 2        # first level that is a card (rare); a known champion only shows greyed
EPIC = 3
LEGENDARY = 4


def _replaced(entries, i):
    """The roll cancelled right before entry i, when i was a champ select reroll of it."""
    e = entries[i]
    for j in range(i - 1, max(-1, i - 4), -1):
        prev = entries[j]
        if prev.get("free"):
            continue
        if prev.get("status") in ("cancelled", "to_check") and str(prev.get("reason") or "").startswith(CS_REROLLS) \
                and e["created"] - prev.get("closed", prev["created"]) < 900:
            return j
        return None
    return None


def is_full(entries, i, depth=0):
    """Whether the roll of entry i drew both the role and the champion."""
    e = entries[i]
    if "full" in e:
        return bool(e["full"])
    mode = e.get("mode")
    if mode in ("both", "chaos", "group"):
        return True
    if mode == "champ" and depth < 5:
        j = _replaced(entries, i)
        return j is not None and is_full(entries, j, depth + 1)
    return False


def is_official(entries, i):
    """Whether the roll of entry i counts for the binder. Rolls saved before 2.6 have no flag: read from what they
    were (full random, no favorite filter)."""
    e = entries[i]
    if "official" in e:
        return bool(e["official"])
    return not e.get("free") and is_full(entries, i) and not e.get("favs")


def roll_full(mode, reason, replaced, entries):
    """For a roll being saved: full random, given what it replaces (champ select reroll)."""
    if mode in ("both", "chaos"):
        return True
    if mode == "champ" and replaced is not None and str(reason or "").startswith(CS_REROLLS):
        return is_full(entries, entries.index(replaced))
    return False


def rank_of(e):
    """Elo of a game: the rank of its queue at the start for a ranked game, the solo/duo rank otherwise (recorded since
    2.6); None when unranked or still in placements."""
    r = e.get("lp_before") or e.get("rank_ref")
    if not r or r.get("provisional") or r.get("tier") not in TIERS:
        return None
    apex = TIERS.index(r["tier"]) >= 7
    return {"tier": r["tier"], "division": "" if apex else r.get("division") or "", "queue": r.get("queue"),
            "ranked": bool(e.get("lp_before"))}


def rank_value(r):
    return TIERS.index(r["tier"]) * 4 + (DIVISIONS.index(r["division"]) if r["division"] in DIVISIONS else 0)


def level_of(entry):
    """Level of a game played with the rolled champion."""
    if not entry.get("win"):
        return CARD
    return LEGENDARY if entry.get("queue") in RANKED else EPIC


def cards(entries, account=None):
    """{"Key|role": {"level", "games", "wins", "at", "queue", "elo"}} from the account's official rolls (entries without
    an account, from older versions, count for everyone)."""
    out = {}
    for i, e in enumerate(entries):
        if e.get("free") or not e.get("key") or e.get("role") not in ("top", "jgl", "mid", "adc", "sup") \
                or not is_official(entries, i):
            continue
        if account and e.get("puuid") and e["puuid"] != account:
            continue
        c = out.setdefault("%s|%s" % (e["key"], e["role"]), {"level": 0, "games": 0, "wins": 0})
        if e.get("status") != "played" or (e.get("played") and e["played"] != e["key"]):
            c["level"] = max(c["level"], KNOWN)   # not played, or another champion was: known only
            continue
        level = level_of(e)
        c["games"] += 1
        c["wins"] += bool(e.get("win"))
        if level > c["level"]:
            c.update(level=level, at=e.get("date"), queue=e.get("queue"))
        rank = rank_of(e) if e.get("win") else None
        if rank and (not c.get("elo") or rank_value(rank) >= rank_value(c["elo"])):   # the best win (the latest on a tie)
            c["elo"] = dict(rank, date=e.get("date"), game_queue=e.get("queue"))
    return out


# card backs: the first one from the start, the others unlocked by milestones of the binder
BACKS = (
    ("hextech", "Hextech", None, 0),
    ("void", "Néant", "cards", 25),
    ("infernal", "Infernal", "chaos", 10),
    ("prism", "Prismatique", "legendary", 25),
    ("crown", "Royal", "masters", 1),
)


def milestones(got, guide_keys, champions, roles):
    """Counts the backs are unlocked by: cards collected, chaos role cards, legendaries, mastered champions."""
    return {
        "cards": sum(1 for c in got.values() if c["level"] >= CARD),
        "chaos": sum(1 for k, c in got.items() if c["level"] >= CARD and k not in guide_keys),
        "legendary": sum(1 for c in got.values() if c["level"] == LEGENDARY),
        "masters": sum(1 for key in champions
                       if all((got.get("%s|%s" % (key, r)) or {}).get("level") == LEGENDARY for r in roles)),
    }


def backs(counts):
    return [{"id": i, "label": label, "need": need, "goal": goal, "have": counts.get(need, 0) if need else 0,
             "unlocked": not need or counts.get(need, 0) >= goal} for i, label, need, goal in BACKS]
