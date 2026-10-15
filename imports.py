"""
Champ select import, like u.gg: rune page, summoner spells and shop item set.

Source: the build picked in the guide (Build tab: u.gg's recommended build or a variant, Emerald+, current patch;
otherwise the most played one on lolalytics) for the locked champion in its role. Runs once per champ select,
after the lock, and only for the options enabled in the settings.

These are the app's only writes to the client:
  - runes: the "RoL · ..." page is replaced. Without one and with no free slot, a page made by another tool
    (u.gg, op.gg...) is replaced, otherwise the selected page only if allowed (else the banner offers it);
  - summoner spells: Flash stays on its key;
  - item set: a single "RoL · ..." set at a time. Another tool's set for the same champion (u.gg...) is replaced
    so the shop shows ours; if the client rejects the list as too long, the oldest tool sets are removed.
    The player's own sets are never touched.
"""

import json
import time
import uuid

PREFIX = "RoL · "
OURS = ("RoL · ", "Roulette · ")   # our pages and sets ("Roulette · " is the app's former name)
TOOL_PAGES = ("U.GG", "OP.GG", "BLITZ", "MOBALYTICS", "POROFESSOR", "LOLALYTICS")   # pages and sets of other tools
MAX_BODY = 60000   # max item set list size sent to the client (it rejects about 64 KB and more)


# replaced by core.T at startup (this module doesn't depend on core)
T = lambda text: text   # noqa: E731


def page_name(combo_name, role_label):
    return (PREFIX + "%s %s" % (combo_name, role_label))[:25]


def rune_page(build):
    """(primary style, secondary style, 9 perks in client order) or None."""
    r = (build or {}).get("runes") or {}
    perks, shards = list(r.get("perks") or []), list(r.get("shards") or [])
    if len(perks) != 6 or len(shards) != 3 or not r.get("pri") or not r.get("sec") or r["pri"] == r["sec"]:
        return None
    return r["pri"], r["sec"], perks + shards


def import_runes(client, build, name, replace_current=False):
    """Creates (or replaces) the "RoL · ..." page. Returns (state, message); state: ok, full, error."""
    built = rune_page(build)
    if not built:
        return "error", T("pas de page de runes connue pour ce champion")
    ps, ss, perks = built
    body = {"name": name, "primaryStyleId": ps, "subStyleId": ss, "selectedPerkIds": perks, "current": True}
    pages = client.get("/lol-perks/v1/pages") or []
    ours = [p for p in pages if (p.get("name") or "").startswith(OURS) and p.get("isDeletable", True)]
    for p in ours:
        client.send("DELETE", "/lol-perks/v1/pages/%s" % p["id"])
    note = ""
    if not ours and (client.get("/lol-perks/v1/inventory") or {}).get("canAddCustomPage") is False:
        # no free slot: another tool's page first, the selected page only if allowed
        tool = next((p for p in pages if p.get("isDeletable") and (p.get("name") or "").strip().upper().startswith(TOOL_PAGES)), None)
        victim = tool
        if not victim and replace_current:
            cur = client.get("/lol-perks/v1/currentpage") or {}
            victim = cur if cur.get("id") and cur.get("isDeletable") else None
            if not victim:
                return "error", T("la page sélectionnée ne peut pas être remplacée")
        if not victim:
            return "full", T("plus de place pour une nouvelle page de runes")
        client.send("DELETE", "/lol-perks/v1/pages/%s" % victim["id"])
        note = T(" (page « %s » remplacée)") % (victim.get("name") or "").strip()
    page = client.send("POST", "/lol-perks/v1/pages", body)
    if page and page.get("id"):
        try:
            client.send("PUT", "/lol-perks/v1/currentpage", page["id"])
        except OSError:
            pass
    return "ok", T("runes importées") + note


def import_spells(client, build, current):
    """Summoner spells of the build; Flash keeps its key (D or F)."""
    sums = list(((build or {}).get("sums") or {}).get("ids") or [])
    if len(sums) != 2:
        return "error", T("pas de sorts connus pour ce champion")
    current = list(current or [0, 0])
    if sorted(sums) == sorted(current):
        return "ok", T("sorts déjà en place")
    # a spell already equipped (usually Flash) keeps its key
    if current[0] in sums and sums[0] != current[0]:
        sums = sums[::-1]
    elif current[1] in sums and sums[1] != current[1]:
        sums = sums[::-1]
    client.send("PATCH", "/lol-champ-select/v1/session/my-selection", {"spell1Id": sums[0], "spell2Id": sums[1]})
    return "ok", T("sorts importés")


def import_itemset(client, combo, build, summoner_id, title, counters=None):
    """"RoL · ..." item set (one at a time), shown in the shop during the game."""
    b = build or {}
    if not b.get("core") or not summoner_id:
        return "error", T("pas de build connu")
    path = "/lol-item-sets/v1/item-sets/%s/sets" % summoner_id
    cur = client.get(path)
    if not isinstance(cur, dict) or "itemSets" not in cur:
        return "error", T("sets d'objets illisibles")   # never write without reading the existing sets first
    def tool(s):
        return (s.get("title") or "").strip().upper().startswith(TOOL_PAGES)
    removed = 0
    sets = []
    for s in cur.get("itemSets") or []:
        if (s.get("title") or "").startswith(OURS):
            continue
        if tool(s) and combo["cid"] in (s.get("associatedChampions") or []):
            removed += 1   # another tool's set for this champion: replaced by ours
            continue
        sets.append(s)

    def block(label, ids):
        items = []
        for it in ids:
            iid, cnt = (it if isinstance(it, (list, tuple)) else (it, 1))
            items.append({"id": str(iid), "count": int(cnt or 1)})
        return {"type": label, "items": items}

    st = b.get("start") or {}
    blocks = [block(T("Départ"), list(zip(st.get("ids") or [], st.get("counts") or [1] * 9))),
              block(T("Build recommandé") if b.get("id", "reco") == "reco" else "Build " + T(b.get("label", "")),
                    b["core"].get("ids") or [])]
    extra = [o for o in counters or [] if not o.get("in_core")]
    if extra:   # items against the enemy comp (known at the end of champ select)
        blocks.append(block(T("Contre leur compo : ") + " · ".join(o["label"].lower() for o in extra)[:60],
                            [o["id"] for o in extra]))
    for label, opts in zip((T("4e objet (au choix)"), T("5e objet (au choix)"), T("6e objet (au choix)")), b.get("opts") or []):
        if opts:
            blocks.append(block(label, [o["id"] for o in opts]))
    ours = {"title": title, "associatedChampions": [combo["cid"]], "associatedMaps": [11], "blocks": blocks,
            "map": "any", "mode": "any", "preferredItemSlots": [], "sortrank": 0, "startedFrom": "blank",
            "type": "custom", "uid": str(uuid.uuid4())}
    # the client rejects lists that are too long (~64 KB): drop the oldest tool sets
    def size(lst):
        return len(json.dumps({"accountId": cur.get("accountId"), "itemSets": lst, "timestamp": 0},
                              separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    while size([ours] + sets) > MAX_BODY:
        i = next((i for i, s in enumerate(sets) if tool(s)), None)
        if i is None:
            return "error", T("trop de sets d'objets dans le client pour en ajouter un")
        sets.pop(i)
        removed += 1
    body = dict(cur)
    body["itemSets"] = [ours] + sets   # first, so the shop suggests it
    body["timestamp"] = int(time.time() * 1000)
    client.send("PUT", path, body)
    return "ok", T("set d'objets importé") + ((T(" (%d sets d'autres outils remplacés)") if removed > 1
                                               else T(" (%d set d'un autre outil remplacé)")) % removed if removed else "")
