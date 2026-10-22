"""
Collection binder: one card per champion and role (865 cards), filled by the games played on a roll, read from the
local history of the LoL account.

Card levels, from the best game of that champion in that role:
  0 locked      never played on a roll
  1 played      the rolled champion was played (game completed)
  2 rare        a win outside ranked, on a roll whose role was picked
  3 epic        a ranked win on a roll whose role was picked, or a win outside ranked on a full random roll
  4 legendary   a ranked win (solo/duo or flex) on a full random roll: what the master set asks for
A champion is mastered when its five roles are legendary; roles without a guide (chaos) belong to the master set too.

Full random: role and champion both drawn (roulette, chaos, group with nothing picked). A champ select reroll (ban,
champion taken, autofill) keeps the randomness of the roll it replaces. A roll whose champion was picked by the player
fills nothing.
"""

RANKED = {420, 440}
CS_REROLLS = ("champion_banned", "champion_taken", "autofill")   # reasons of a champ select reroll
LEVELS = ("locked", "played", "rare", "epic", "legendary")
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


def roll_full(mode, reason, replaced, entries):
    """For a roll being saved: full random, given what it replaces (champ select reroll)."""
    if mode in ("both", "chaos"):
        return True
    if mode == "champ" and replaced is not None and str(reason or "").startswith(CS_REROLLS):
        return is_full(entries, entries.index(replaced))
    return False


def level_of(entry, full):
    if not entry.get("win"):
        return 1
    ranked = entry.get("queue") in RANKED
    if ranked and full:
        return LEGENDARY
    return 3 if ranked or full else 2


def cards(entries, account=None):
    """{"Key|role": {"level", "games", "wins", "at", "queue", "full"}} for the account's games (entries without an
    account, from older versions, count for everyone)."""
    out = {}
    for i, e in enumerate(entries):
        if e.get("free") or e.get("status") != "played" or e.get("mode") == "role":
            continue
        if account and e.get("puuid") and e["puuid"] != account:
            continue
        if e.get("played") and e["played"] != e["key"]:
            continue   # another champion was played
        full = is_full(entries, i)
        level = level_of(e, full)
        c = out.setdefault("%s|%s" % (e["key"], e["role"]), {"level": 0, "games": 0, "wins": 0})
        c["games"] += 1
        c["wins"] += bool(e.get("win"))
        if level > c["level"]:
            c.update(level=level, at=e.get("date"), queue=e.get("queue"), full=full)
    return out
