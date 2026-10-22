"""
Random build, in the spirit of Ultimate Bravery: for the rolled champion and role, the parts the player picked are
drawn at random. The build stays one the game accepts:
  - runes: a random primary tree, its keystone and one rune per row; a different secondary tree, two runes from
    two different rows; one shard per row;
  - summoner spells: two different spells of the Rift; Smite in the jungle, never outside;
  - items, in buying order: a starting set seen in the guides of that role (so the jungle pet and the support
    item are there), tier 2 boots within the first three items (never for Cassiopeia), then legendary items, no
    two of a unique group. The jungle and support items take a slot: one item less;
  - skills: a random max order of Q, W and E, the ultimate at 6, 11 and 16, the game's rank limits.
Kept from the guide: Aphelios' points and Udyr's free ranks (no real skill order to draw).
"""

import random

from live import AUTO_FIRST, AUTO_R, FREE_RANKS, NO_SKILLS, can_level

PARTS = ("runes", "spells", "items", "skills")
SPELLS = (4, 14, 12, 7, 21, 3, 1, 6)   # Flash, Ignite, Teleport, Heal, Barrier, Exhaust, Cleanse, Ghost
SMITE = 11
NO_BOOTS = {"Cassiopeia"}
SLOT_ROLES = {"jgl", "sup"}   # their role item keeps a slot all game
ROLE_ITEMS = {"sup": {3865}, "jgl": {1101, 1102, 1103, 1105, 1106, 1107}}   # World Atlas, jungle pets
DEFAULT_START = {"sup": {"ids": [3865, 2003], "counts": [1, 2]}, "jgl": {"ids": [1101, 2003], "counts": [1, 1]}}
# legendary items sharing a unique passive: one at most per build
GROUPS = (
    {3003, 3004, 3119},          # Tear: Archangel's Staff, Manamune, Winter's Approach
    {3053, 3156, 6673},          # Lifeline: Sterak's Gage, Maw of Malmortius, Immortal Shieldbow
    {3074, 3748, 6698},          # Hydra: Ravenous, Titanic, Profane
    {3078, 3100, 6662, 3508},    # Spellblade: Trinity Force, Lich Bane, Iceborn Gauntlet, Essence Reaver
    {3036, 3033, 6694},          # Last Whisper: Lord Dominik's Regards, Mortal Reminder, Serylda's Grudge
    {3135, 3137},                # Blight: Void Staff, Cryptbloom
    {3102, 3814},                # Annul: Banshee's Veil, Edge of Night
    {3068, 6664},                # Immolate: Sunfire Aegis, Hollow Radiance
)


def draw_runes(runes, rng=random):
    """{"pri", "sec", "perks" (keystone, 3 primary, 2 secondary: client order), "shards"} or None."""
    trees = {int(k): v["slots"] for k, v in ((runes or {}).get("trees") or {}).items() if len(v.get("slots") or []) == 4}
    rows = (runes or {}).get("shard_rows") or []
    if len(trees) < 2 or len(rows) != 3:
        return None
    pri, sec = rng.sample(sorted(trees), 2)
    perks = [rng.choice(slot) for slot in trees[pri]]
    perks += [rng.choice(trees[sec][i]) for i in sorted(rng.sample((1, 2, 3), 2))]
    return {"pri": pri, "sec": sec, "perks": perks, "shards": [rng.choice(row) for row in rows]}


def draw_spells(role, rng=random):
    if role == "jgl":
        return [SMITE, rng.choice(SPELLS)]
    return rng.sample(SPELLS, 2)


def draw_items(items, role, key, starts, rng=random):
    """{"start": {"ids", "counts"}, "core": {"ids"}} or None. items: {id: {"kind"...}} (items.json);
    starts: the starting sets of that role's guides."""
    pool = {"boots": [], "legendary": []}
    for i, v in (items or {}).items():
        if v.get("kind") in pool:
            pool[v["kind"]].append(int(i))
    if len(pool["legendary"]) < 6 or not pool["boots"]:
        return None
    n = 5 if role in SLOT_ROLES else 6
    boots = None if key in NO_BOOTS else rng.choice(sorted(pool["boots"]))
    legend = []
    for i in rng.sample(sorted(pool["legendary"]), len(pool["legendary"])):
        if len(legend) == n - (1 if boots else 0):
            break
        if any(i in g and any(j in g for j in legend) for g in GROUPS):
            continue
        legend.append(i)
    core = list(legend)
    if boots:
        core.insert(rng.randrange(3), boots)
    starts = [s for s in starts or [] if role not in ROLE_ITEMS or ROLE_ITEMS[role] & set(s["ids"])]
    start = rng.choice(starts) if starts else DEFAULT_START.get(role, {"ids": [], "counts": []})
    return {"start": {"ids": list(start["ids"]), "counts": list(start.get("counts") or [1] * len(start["ids"]))},
            "core": {"ids": core}}


def draw_skills(key, rng=random):
    """{"order15", "prio"}: first three levels one skill each, then the max order (rank limits of the game), or None
    when the champion has no order to draw."""
    if key in NO_SKILLS or key in FREE_RANKS:
        return None
    prio = "".join(rng.sample("QWE", 3))
    first = list(rng.sample("QWE", 3))
    ranks = {c: 0 for c in "QWER"}
    out = []
    for lv in range(1, 16):
        if lv == 1 and AUTO_FIRST.get(key):
            c = AUTO_FIRST[key]
        elif key not in AUTO_R and can_level("R", ranks, lv, key):
            c = "R"
        else:
            c = next((x for x in first if ranks[x] == 0), None) if lv <= 3 else None
            c = c or next((x for x in prio if can_level(x, ranks, lv, key)), None)
        if not c:
            break
        out.append(c)
        ranks[c] += 1
    return {"order15": "".join(out), "prio": prio}


def draw(data, key, role, parts, starts, rng=random):
    """The drawn parts for that champion and role: {"parts", "runes"?, "sums"?, "start"?, "core"?, "skills"?}."""
    out = {"parts": [p for p in PARTS if p in parts]}
    if "runes" in parts:
        r = draw_runes(data.runes, rng)
        if r:
            r["perks"] = data.order_perks(r["perks"], r["pri"], r["sec"])
            out["runes"] = r
    if "spells" in parts:
        out["sums"] = {"ids": draw_spells(role, rng)}
    if "items" in parts:
        it = draw_items(data.items, role, key, starts, rng)
        if it:
            out.update(it)
    if "skills" in parts:
        sk = draw_skills(key, rng)
        if sk:
            out["skills"] = sk
    return out
