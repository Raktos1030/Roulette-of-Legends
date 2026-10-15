"""
Chaos mode: any champion in any role (jungle Yuumi, jungle Swain...).

These combos have no written guide (too few games to write an honest one). A chaos guide is assembled from
real data only:
  - the champion's REAL build, skill order and matchups in that role (lolalytics, on demand, cached for the patch)
    when there are enough games;
  - otherwise the build of the closest guide (role affinity x guide popularity), with the role's requirements:
    Smite and a jungle pet, support item;
  - the texts of the closest guide, labeled as such.
"""

import os
import time

from core import DATA, ROLE_LABEL, read_json, write_json

# how close each role is to the others (picks the guide whose advice and build are reused)
AFFINITY = {
    "jgl": {"top": 1.0, "mid": 0.7, "sup": 0.4, "adc": 0.3},     # solo lane, farms camps, often a bruiser or tank
    "top": {"jgl": 0.9, "mid": 0.8, "adc": 0.4, "sup": 0.3},
    "mid": {"top": 0.8, "adc": 0.7, "jgl": 0.6, "sup": 0.5},
    "adc": {"mid": 0.8, "top": 0.5, "sup": 0.4, "jgl": 0.3},     # farming carry that scales
    "sup": {"mid": 0.6, "adc": 0.5, "top": 0.4, "jgl": 0.3},
}
SMITE, FLASH, POTION = 11, 4, 2003
JUNGLE_PET, SUPPORT_ITEM = 1102, 3865      # Gustwalker Hatchling, World Atlas
SPELL_FOR = {"top": 12, "mid": 14, "adc": 7, "sup": 3}   # replaces Smite outside the jungle: TP, Ignite, Heal, Exhaust
MIN_REAL = 150          # minimum games to use the champion's real data in that role
TTL = 3 * 86400
CACHE = os.path.join(DATA, "cache", "chaos")

# role game rules (not advice), shown on chaos guides
RULES = {
    "jgl": "Jungle : Châtiment et un compagnon de jungle au départ (il évolue en tuant des monstres). Ton expérience "
           "vient des camps de la jungle, pas des vagues de sbires.",
    "sup": "Support : l'Atlas te rapporte de l'or quand tu touches les ennemis et évolue au fil de la partie. "
           "Laisse les sbires à ton ADC, l'expérience de la lane est partagée.",
}


def nearest(data, key, role):
    """Closest guide for a champion in a role it has none for: role affinity x guide popularity."""
    roles = data.champs[key]["roles"]
    if role in roles:
        return data.combo_key(key, role)
    best = max(roles, key=lambda r: AFFINITY[role].get(r, 0.2) * (0.6 + 0.4 * data.combos[data.combo_key(key, r)]["share"] / 100.0))
    return data.combo_key(key, best)


def level(share):
    """Chaos level from the share of the champion's games played in that role."""
    s = share or 0.0
    if s < 0.5:
        return "Pick de l'enfer", "bad2"
    if s < 2:
        return "Très rare", "bad"
    if s < 8:
        return "Rare", "warn"
    return "Jouable", "good"


def _adapt_build(b, role):
    """Build of another guide with the role's requirements; its numbers no longer apply and are dropped."""
    b = dict(b)
    sums = list((b.get("sums") or {}).get("ids") or [])
    if role == "jgl":
        sums = [FLASH, SMITE]
        b["start"] = {"ids": [JUNGLE_PET, POTION], "counts": [1, 1]}
    else:
        sums = [SPELL_FOR[role] if x == SMITE else x for x in sums]
        if role == "sup":
            b["start"] = {"ids": [SUPPORT_ITEM, POTION], "counts": [1, 2]}
    b["sums"] = {"ids": sums}
    b["runes"] = dict(b.get("runes") or {}, games=None, wr=None)
    for part in ("start", "core"):
        if b.get(part):
            b[part] = {k: v for k, v in b[part].items() if k not in ("games", "wr")}
    b["opts"] = [[{"id": o["id"]} for o in col] for col in b.get("opts") or []]
    if isinstance(b.get("skills"), dict):
        b["skills"] = {k: v for k, v in b["skills"].items() if k not in ("games", "wr", "m", "w")}
    b["label"] = "Adapté · %s" % b.get("label", "")
    b["games"] = b["wr"] = None
    b["src"] = "adapted"
    return b


def _names(data):
    by_id = data.all_champs.get("by_id") or {}
    return {int(c): v["name"] for c, v in by_id.items()}, {int(c): v["key"] for c, v in by_id.items()}


def build(data, key, role, raw=None):
    """Chaos combo (same shape as a stats combo) from the lolalytics response, or without one."""
    import updater
    near = nearest(data, key, role)
    nc = data.combos[near]
    ch = data.champs[key]
    lane = updater.LANE[role]
    share = (((raw or {}).get("nav") or {}).get("lanes") or {}).get(lane)
    games = ((raw or {}).get("header") or {}).get("n", 0) or 0
    pc = {"name": ch["name"], "name_en": ch.get("name_en", ch["name"]), "key": key, "cid": ch["cid"], "role": role,
          "share": round(share, 2) if share is not None else 0.0, "patch": data.meta.get("patch"), "t": time.time()}
    real = False
    if raw and "header" in raw and games >= MIN_REAL:
        try:
            rb = updater.runes_build(raw)
            items = updater.items_build(raw)
            if rb.get("runes") and items:
                names, keys = _names(data)
                pc.update({"month": updater.header(raw), "skills": updater.skills(raw), "items": items,
                           "runes": rb["runes"], "sums": rb.get("sums"), "builds": [], "bench": updater.bench(raw)})
                try:
                    pc["matchups"] = updater.matchups(role, raw, None, None, names, keys)
                except Exception:
                    pc["matchups"] = None
                real = True
        except Exception:
            real = False
    if not real:
        pc.update({"month": None, "skills": nc.get("skills"), "items": dict(nc.get("items") or {}),
                   "runes": nc.get("runes"), "sums": list(nc.get("sums") or []), "matchups": None,
                   "builds": [_adapt_build(b, role) for b in nc.get("builds") or []]})
        # fallback build (lolalytics) of the closest guide: same requirements
        if role == "jgl":
            pc["sums"] = [FLASH, SMITE]
            pc["items"]["start"] = [[JUNGLE_PET, 1], [POTION, 1]]
        elif role == "sup":
            pc["items"]["start"] = [[SUPPORT_ITEM, 1], [POTION, 2]]
        if role != "jgl":
            pc["sums"] = [SPELL_FOR[role] if x == SMITE else x for x in pc["sums"]]
    lv, tone = level(share)
    pc["chaos"] = {"from": near, "from_label": "%s %s" % (nc["name"], ROLE_LABEL[nc["role"]]), "real": real,
                   "games": games, "share": share, "level": lv, "tone": tone, "rule": RULES.get(role)}
    return pc


def _path(key, role):
    return os.path.join(CACHE, "%s_%s.json" % (key, role))


def cached(data, key, role):
    pc = read_json(_path(key, role))
    if pc and pc.get("patch") == data.meta.get("patch") and time.time() - pc.get("t", 0) < TTL:
        return pc
    return None


def fetch(data, key, role):
    """Real data for the champion in that role (one lolalytics request, about a second), cached."""
    import updater
    slug = "wukong" if key == "MonkeyKing" else key.lower()
    try:
        raw = updater.fetch(updater.LOLA % ("30", slug, updater.LANE[role], "emerald_plus"), tries=2, timeout=20)
    except Exception:
        raw = None
    pc = build(data, key, role, raw)
    if raw:   # no cache on a failed download, so it is retried
        try:
            os.makedirs(CACHE, exist_ok=True)
            write_json(_path(key, role), pc, compact=True)
        except OSError:
            pass
    return pc
