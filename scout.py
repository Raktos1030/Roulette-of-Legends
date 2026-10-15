"""
Live game: rank and recent form of the players in the game, read from the League client (read-only), as on their
client profile.

For each visible player: solo/duo rank for the season, last 20 games (wins, current streak) and recent games on
the champion played. Riot's rule is respected: in ranked solo/duo champ select, ally names are hidden by the game
and the app doesn't try to find them (their info shows up on the loading screen, when the game shows it to everyone).
"""

import threading
import time

import lol_client as lol

TTL = 900   # a player already looked up is refreshed after 15 minutes only


def summarize(games, champ_id):
    """Summary of a player's recent games (most recent first)."""
    games = sorted(games, key=lambda g: -(g.get("creation") or 0))[:20]
    if not games:
        return None
    wins = sum(1 for g in games if g["win"])
    streak = 0
    for g in games:
        if g["win"] == games[0]["win"]:
            streak += 1
        else:
            break
    on = [g for g in games if champ_id and g["championId"] == champ_id]
    out = {"n": len(games), "wins": wins, "streak": streak if games[0]["win"] else -streak, "champ_n": len(on)}
    if on:
        k = sum(g["k"] for g in on)
        d = sum(g["d"] for g in on)
        a = sum(g["a"] for g in on)
        out["champ_wins"] = sum(1 for g in on if g["win"])
        out["champ_kda"] = round((k + a) / max(1, d), 2)
    tags = []
    if out["streak"] >= 3:
        tags.append(("good", lol.T("%d victoires d'affilée") % out["streak"]))
    elif out["streak"] <= -3:
        tags.append(("bad", lol.T("%d défaites d'affilée") % -out["streak"]))
    if champ_id and len(on) >= 10:
        tags.append(("warn", lol.T("spécialiste : %d de ses 20 dernières parties") % len(on)))
    elif champ_id and not on:
        tags.append(("muted", lol.T("aucune partie récente sur ce champion")))
    out["tags"] = tags
    return out


class Scout(threading.Thread):
    """Reads the requested players one by one, without blocking the rest of the app."""

    def __init__(self, client, on_change):
        super().__init__(name="live-game", daemon=True)
        self.client = client
        self.on_change = on_change
        self.cache = {}           # puuid -> {"at", "rank", "recent"}
        self.wanted = []          # [(puuid, champion)]
        self._wake = threading.Event()
        self._stop = threading.Event()

    def want(self, players):
        self.wanted = [(p["puuid"], p.get("champ") or 0) for p in players if p.get("puuid")]
        self._wake.set()

    def info(self, puuid, champ):
        c = self.cache.get(puuid)
        if not c:
            return None
        recent = summarize(c["games"], champ) if c.get("games") is not None else None
        return {"rank": c.get("rank"), "recent": recent}

    def stop(self):
        self._stop.set()
        self._wake.set()

    def run(self):
        while not self._stop.is_set():
            self._wake.wait(5)
            self._wake.clear()
            for puuid, champ in list(self.wanted):
                if self._stop.is_set():
                    return
                c = self.cache.get(puuid)
                if c and time.time() - c["at"] < TTL:
                    continue
                entry = {"at": time.time(), "rank": None, "games": None}
                try:
                    q = lol.parse_ranked(self.client.get("/lol-ranked/v1/ranked-stats/%s" % puuid))
                    entry["rank"] = q.get("RANKED_SOLO_5x5")
                    data = self.client.get("/lol-match-history/v1/products/lol/%s/matches?begIndex=0&endIndex=20" % puuid)
                    entry["games"] = lol.parse_history(data)
                except OSError:
                    entry["at"] = time.time() - TTL + 30   # client busy: retry in 30 s
                self.cache[puuid] = entry
                self.on_change()
                time.sleep(0.15)
