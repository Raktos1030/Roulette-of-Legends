"""
Team comp analysis (champ select, live game, overlay, imported item set).

  team_profile   team profile: AD / AP damage, frontline, healers, CC, divers, engage, poke
  matchup_vs     win rate against a champion (lolalytics, 30 days, Emerald+)
  counter_items  items to plan against the enemy comp
  guess_roles    likely roles of a team (champ select, games without positions)
  countered_by   champions that beat a champion the most in its role

Counter items don't come from a hand-written list: for each need (MR against mostly AP, armor against mostly AD,
anti-heal against healers, anti-tank against several tanks, boots), the pick is the item of that category the
champion buys most often (lolalytics, Emerald+). Categories come from Data Dragon item stats and descriptions;
heals and damage taken per game come from lolalytics.
"""

import math
import re
from itertools import permutations

ROLES = ["top", "jgl", "mid", "adc", "sup"]
FRONTLINE = {"TANK", "VANGUARD", "WARDEN"}
DIVERS = {"ASSASSIN", "DIVER", "SKIRMISHER"}
ENGAGE = {"VANGUARD", "CATCHER"}
MERCURY, STEELCAPS = 3111, 3047
# replaced by core at startup (this module doesn't depend on core)
T = lambda text: text   # noqa: E731
lang = lambda: "fr"     # noqa: E731


def heal_threshold(data, role):
    """Heals per game above which a champion counts as a healer: top quartile of its role (jungle camps inflate every
    jungler's heals, hence the per-role threshold)."""
    cache = getattr(data, "_heal_t", None)
    if cache is None:
        cache = {}
        for r in ("top", "jgl", "mid", "adc", "sup"):
            vals = sorted(c["heal"] for c in data.combos.values() if c["role"] == r and c.get("heal") is not None)
            cache[r] = vals[int(len(vals) * 0.75)] if vals else None
        data._heal_t = cache
    return cache.get(role)


def is_healer(data, key, role):
    """Healer in that role (or, role unknown, in its most played role)."""
    c = data.combos.get(data.combo_key(key, role)) if role else None
    if not c:
        cands = [x for k, x in data.combos.items() if k.startswith(key + "|")]
        c = max(cands, key=lambda x: x.get("share") or 0) if cands else None
    if not c or c.get("heal") is None:
        return False
    t = heal_threshold(data, c["role"])
    return t is not None and c["heal"] >= t


def team_profile(data, team):
    """team: [(key, role)] from the loading screen."""
    compo = data.compo or {}
    profiles = compo.get("profiles") or {}
    damage = compo.get("damage") or {}
    phys = magic = true_ = 0.0
    front, divers, engage, poke, enchant, healers = [], [], [], [], [], []
    control = 0
    for key, role in team:
        name = data.champ_name(key)
        dm = damage.get("%s|%s" % (key, role)) if role else None
        if not dm:
            cands = [v for k, v in damage.items() if k.startswith(key + "|")]
            if cands:
                dm = {t: sum(c[t] for c in cands) / len(cands) for t in ("physical", "magic", "true")}
        p = profiles.get(key) or {}
        if not dm and p:
            dm = {"physical": 100, "magic": 0, "true": 0} if p.get("adaptive") != "magic" else \
                 {"physical": 0, "magic": 100, "true": 0}
        if dm:
            phys += dm["physical"]
            magic += dm["magic"]
            true_ += dm["true"]
        classes = set(p.get("classes") or [])
        control += p.get("control", 2)
        if p.get("toughness") == 3 or classes & FRONTLINE:
            front.append(name)
        if classes & DIVERS:
            divers.append(name)
        if classes & ENGAGE:
            engage.append(name)
        if "ARTILLERY" in classes:
            poke.append(name)
        if "ENCHANTER" in classes:
            enchant.append(name)
        if is_healer(data, key, role):
            healers.append(name)
    tot = phys + magic + true_
    split = {"physical": round(100 * phys / tot), "magic": round(100 * magic / tot),
             "true": round(100 * true_ / tot)} if tot else None
    n = len(team)
    tips = []
    if n and control >= 2.2 * n:
        tips.append(T("Beaucoup de CC (%d/%d) : un seul CC peut coûter le fight, garde ton Flash ou ton dash "
                      "et ne te montre pas en premier.") % (control, 3 * n))
    elif n and control <= 1.4 * n:
        tips.append(T("Peu de CC (%d/%d) : ils ont peu de moyens de te lock.") % (control, 3 * n))
    if len(divers) >= 2:
        tips.append(T("Divers et assassins (%s) : reste près de ta frontline, ils vont chercher les carries.")
                    % ", ".join(divers))
    if not front:
        tips.append(T("Aucun vrai tank : leurs carries sont exposés dès que le fight commence."))
    elif len(front) >= 2:
        tips.append(T("Frontline solide (%s) : ne dépense pas tout sur les tanks, vise leurs carries.") % ", ".join(front))
    if len(engage) >= 2:
        tips.append(T("Beaucoup d'engage (%s) : reste hors de portée de leurs engages.") % ", ".join(engage))
    if poke:
        tips.append(T("Poke à longue portée (%s) : ne reste pas à portée avant les objectifs sans pouvoir engager.")
                    % ", ".join(poke))
    if len(healers) >= 2:
        tips.append(T("Beaucoup de soins (%s) : l'anti-soin fait une vraie différence.") % ", ".join(healers))
    elif enchant:
        tips.append(T("Heals et shields (%s) : les fights courts et le burst passent mieux que les fights longs.")
                    % ", ".join(enchant))
    return {"split": split, "front": front, "divers": divers, "engage": engage, "poke": poke,
            "enchant": enchant, "healers": healers, "control": control, "n": n, "tips": tips}


def matchup_vs(data, combo_key, enemy_key, enemy_role=None):
    """Win rate against an enemy champion in its role: (win rate, games, delta to the champion's average)."""
    compo = data.compo or {}
    mine = (compo.get("vs") or {}).get(combo_key)
    cid = next((c for c, k in data.cid_to_key.items() if k == enemy_key), None)
    if not mine or cid is None:
        return None
    cid = str(cid)
    lanes = mine["vs"]
    if enemy_role and cid in lanes.get(enemy_role, {}):
        wr, n = lanes[enemy_role][cid]
    else:
        best = max(((l[cid], r) for r, l in lanes.items() if cid in l), key=lambda x: x[0][1], default=None)
        if not best:
            return None
        wr, n = best[0]
    return wr, n, wr - mine["avg"]


def counter_items(data, combo, enemies):
    """Items to plan against the enemy comp: [{"id", "cat", "label", "why"}], most important first."""
    b = (combo or {}).get("items") or {}
    pool = b.get("pool") or []
    if not pool or not enemies:
        return []
    cats = data.item_cats
    prof = team_profile(data, enemies)
    sp = prof["split"] or {"physical": 0, "magic": 0, "true": 0}
    n = prof["n"] or 1
    out = []
    used = set()

    def best(cat):
        cands = [(pr, i) for i, pr in pool if cat in cats.get(str(i), ()) and pr >= 1.0 and i not in used]
        return max(cands)[1] if cands else None

    def add(cat, label, why):
        i = best(cat)
        if i:
            used.add(i)
            out.append({"id": i, "cat": cat, "label": label, "why": why})

    if len(prof["healers"]) >= 2:
        add("antiheal", T("Anti-soin"), T("soins : %s") % ", ".join(prof["healers"]))
    if sp["magic"] >= 60:
        add("mr", T("Résistance magique"), T("%d %% de leurs dégâts sont magiques") % sp["magic"])
    if sp["physical"] >= 65:
        add("armor", T("Armure"), T("%d %% de leurs dégâts sont physiques") % sp["physical"])
    if len(prof["front"]) >= 2:
        add("antitank", T("Anti-tank"), T("tanks : %s") % ", ".join(prof["front"]))
    boots = {i: pr for i, pr in b.get("boots") or []}
    if (sp["magic"] >= 55 or prof["control"] >= 2.2 * n) and boots.get(MERCURY, 0) >= 3:
        out.append({"id": MERCURY, "cat": "boots", "label": T("Bottes"),
                    "why": T("beaucoup de CC") if prof["control"] >= 2.2 * n else T("%d %% de dégâts magiques") % sp["magic"]})
    elif sp["physical"] >= 60 and boots.get(STEELCAPS, 0) >= 3:
        out.append({"id": STEELCAPS, "cat": "boots", "label": T("Bottes"), "why": T("%d %% de dégâts physiques") % sp["physical"]})
    core = set(b.get("core") or [])
    for o in out:
        o["in_core"] = o["id"] in core
    return out


def strip_goal(text):
    for prefix in ("Pour gagner cette partie, tu veux ", "To win this game, you want to "):
        if text.startswith(prefix) and len(text) > len(prefix):
            return text[len(prefix)].upper() + text[len(prefix) + 1:]
    return text


_THIRD = [(r"\bà te (?=\w)", "à le "), (r"\bton\b", "son"), (r"\bta\b", "sa"), (r"\btes\b", "ses"),
          (r"\btoi\b", "soi"), (r"\bte\b", "se"), (r"(?<![\w])t'(?=\w)", "s'")]


_THIRD_EN = [(r"\byourself\b", "themselves"), (r"\byours\b", "theirs"), (r"\byour\b", "their"), (r"\bYour\b", "Their"),
             (r"\byou're\b", "they're"), (r"\byou've\b", "they've"), (r"\byou'll\b", "they'll"), (r"\byou\b", "they"),
             (r"\bYou\b", "They")]


def third_person(text):
    """Guide text written in the second person -> describes an opponent ("ton ultime" -> "son ultime")."""
    for pat, rep in (_THIRD_EN if lang() == "en" else _THIRD):
        text = re.sub(pat, rep, text)
    return text


def role_share(data, key, role):
    """Share of a champion's games in a role (lolalytics); 1 % when the role has no guide (< 20 %)."""
    c = data.combos.get(data.combo_key(key, role)) if key else None
    return (c or {}).get("share") or 1.0


def guess_roles(data, keys, known=None):
    """Most likely role assignment: each champion gets its most played role, without duplicates (as u.gg does before
    the game reveals the real positions). keys: champion keys (None = not picked yet); known: {index: role}."""
    known = dict(known or {})
    free = [r for r in ROLES if r not in known.values()]
    idx = [i for i, k in enumerate(keys) if i not in known]
    best, best_score = None, -1e9
    if len(idx) <= len(free):
        for perm in permutations(free, len(idx)):
            sc = sum(math.log(role_share(data, keys[i], r) + 0.5) for i, r in zip(idx, perm) if keys[i])
            if sc > best_score:
                best, best_score = perm, sc
    out = [known.get(i) for i in range(len(keys))]
    for i, r in zip(idx, best or []):
        out[i] = r
    return out


def countered_by(data, key, role, n=3):
    """The n champions this champion wins the least against in its role (worst matchups, lolalytics)."""
    c = data.combos.get(data.combo_key(key, role)) if key and role else None
    if not c:
        return []
    m = c.get("matchups") or {}
    return [{"key": e["key"], "name": e["name"], "wr": e["wr"], "n": e["n"]}
            for e in (m.get("bad") or [])[:n] if e.get("key")]
