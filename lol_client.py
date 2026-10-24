"""
League client link.

The client exposes a local API (LCU) protected by a token stored in the install folder's lockfile.
This module finds that token (or reads it from the LeagueClientUx.exe command line), then reads the game flow
phase, champ select and match history.

It never acts on the game: no pick, ban, lock or chat. The only writes (imports.py, when enabled) are the rune
page, summoner spells and an item set, once the champion is locked.

RollHistory tracks rolls through their lifecycle:
  pending -> in_game -> played | remake
  pending -> cancelled   (rerolled before playing, autofill, champion banned or taken)
  pending -> to_check    (rerolled while the client was offline; resolved later from the match history)
"""

import base64
import json
import os
import queue
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request


# LCU positions -> app roles
POSITION_TO_ROLE = {"top": "top", "jungle": "jgl", "middle": "mid", "bottom": "adc", "utility": "sup"}

QUEUE_NAMES = {
    400: "Normale (draft)", 420: "Classée solo/duo", 430: "Normale (aveugle)", 440: "Classée flexible",
    450: "ARAM", 480: "Partie rapide", 490: "Partie rapide", 700: "Clash", 900: "ARURF", 1700: "Arena",
    1900: "URF", 2400: "ARAM Mayhem",
}

GAME_PHASES = ("InProgress", "Reconnect", "WaitingForStats", "PreEndOfGame", "EndOfGame")
# Summoner's Rift queues (ranked, normal, quickplay, Clash, co-op vs AI)
SR_QUEUES = {400, 420, 430, 440, 480, 490, 700, 830, 840, 850, 870, 880, 890}
BOT_QUEUES = {830, 840, 850, 870, 880, 890}   # co-op vs AI: never counts for a roll


def roulette_game(queue_id=None, mode=None, custom=False):
    """Only Summoner's Rift games against players can count for a roll (no ARAM, Arena, URF, co-op vs AI, practice
    tool or custom games)."""
    if custom or queue_id in BOT_QUEUES:
        return False
    if mode:
        return str(mode).upper() == "CLASSIC"
    return queue_id in SR_QUEUES
REMAKE_SECONDS = 300

# Ranked queues and LP ladder
RANKED_QUEUES = {420: "RANKED_SOLO_5x5", 440: "RANKED_FLEX_SR"}
RANKED_LABEL = {"RANKED_SOLO_5x5": "Solo/duo", "RANKED_FLEX_SR": "Flexible"}
TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND"]
APEX_TIERS = ("MASTER", "GRANDMASTER", "CHALLENGER")
TIER_LABEL = {"IRON": "Fer", "BRONZE": "Bronze", "SILVER": "Argent", "GOLD": "Or", "PLATINUM": "Platine",
           "EMERALD": "Émeraude", "DIAMOND": "Diamant", "MASTER": "Maître", "GRANDMASTER": "Grand maître",
           "CHALLENGER": "Challenger"}
DIVISIONS = ["IV", "III", "II", "I"]
LP_TIMEOUT = 360      # no rank change 6 min after a ranked game: it didn't count


# replaced by core.T at startup (this module doesn't depend on core)
T = lambda text: text   # noqa: E731


def queue_name(qid):
    return T(QUEUE_NAMES.get(qid, "File %s" % qid)) if qid else ""


def parse_ranked(data):
    """Current rank per ranked queue: tier, division, LP, wins, losses."""
    if not isinstance(data, dict):
        return {}
    qm = data.get("queueMap") or {}
    if not qm and isinstance(data.get("queues"), list):
        qm = {q.get("queueType"): q for q in data["queues"] if isinstance(q, dict)}
    out = {}
    for qt in RANKED_QUEUES.values():
        q = qm.get(qt)
        if not isinstance(q, dict):
            continue
        out[qt] = {
            "tier": (q.get("tier") or "").upper(), "division": (q.get("division") or "").upper(),
            "lp": int(q.get("leaguePoints") or 0), "wins": int(q.get("wins") or 0), "losses": int(q.get("losses") or 0),
            "provisional": bool(q.get("isProvisional")), "prov_left": q.get("provisionalGamesRemaining") or 0,
        }
    return out


def is_placement(q):
    return not q or q.get("provisional") or q.get("tier") not in TIERS + list(APEX_TIERS)


def abs_lp(q):
    """Absolute ladder position (Iron IV 0 LP = 0), so LP gains work across divisions."""
    if q["tier"] in APEX_TIERS:
        return len(TIERS) * 400 + q["lp"]
    div = DIVISIONS.index(q["division"]) if q["division"] in DIVISIONS else 0
    return TIERS.index(q["tier"]) * 400 + div * 100 + q["lp"]


def rank_label(q):
    if not q:
        return ""
    if is_placement(q):
        return T("en placement")
    tier = T(TIER_LABEL.get(q["tier"], q["tier"].title()))
    if q["tier"] in APEX_TIERS:
        return "%s %d LP" % (tier, q["lp"])
    return "%s %s · %d LP" % (tier, q["division"], q["lp"])


LIVE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"
ACTIVE_URL = LIVE_URL.replace("allgamedata", "activeplayer")
LIVE_POSITIONS = {"TOP": "top", "JUNGLE": "jgl", "MIDDLE": "mid", "MID": "mid", "BOTTOM": "adc", "BOT": "adc",
                  "UTILITY": "sup", "SUPPORT": "sup"}


def fetch_live_game(timeout=2.0, url=None):
    """Live Client Data API (local, read-only). None outside a game.
    url: a sub-endpoint (ACTIVE_URL returns the active player only, much lighter)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE   # self-signed certificate, 127.0.0.1 only
    try:
        with urllib.request.urlopen(urllib.request.Request(url or LIVE_URL, headers={"Accept": "application/json"}),
                                    context=ctx, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def parse_live_roster(data):
    """Game roster only (champions, teams, positions), i.e. what the loading screen shows."""
    if not isinstance(data, dict):
        return None
    players = []
    for p in data.get("allPlayers") or []:
        raw = p.get("rawChampionName") or ""
        players.append({
            "key": raw.split("displayname_")[-1] if "displayname_" in raw else "",
            "name": p.get("championName") or "",
            "team": p.get("team") or "",
            "role": LIVE_POSITIONS.get((p.get("position") or "").upper()),
            "ids": {p.get("riotId"), p.get("summonerName"), p.get("riotIdGameName")} - {None, ""},
        })
    if not players:
        return None
    ap = data.get("activePlayer") or {}
    mine = {ap.get("riotId"), ap.get("summonerName"), ap.get("riotIdGameName")} - {None, ""}
    me = next((i for i, p in enumerate(players) if p["ids"] & mine), None)
    for p in players:
        p.pop("ids")
    return {"me": me, "players": players}


def parse_lp_notification(n):
    """LP change notification from the client, if any (undocumented payload)."""
    if not isinstance(n, dict):
        return None
    gid, delta = n.get("gameId"), n.get("leaguePointsDelta")
    if gid and isinstance(delta, (int, float)) and not isinstance(delta, bool):
        return {"gameId": gid, "delta": int(delta)}
    return None


# ----------------------------------------------------------------------------
# Client connection
# ----------------------------------------------------------------------------

def riot_install_dir():
    """League install folder recorded by the Riot Client (wherever the player installed it), or None."""
    root = "/Users/Shared" if sys.platform == "darwin" else (os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
    path = os.path.join(root, "Riot Games", "Metadata", "league_of_legends.live",
                        "league_of_legends.live.product_settings.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            m = re.search(r'^product_install_full_path:\s*"?([^"\r\n]+)"?\s*$', f.read(), re.M)
    except OSError:
        return None
    return os.path.normpath(m.group(1)) if m else None


class LolClient:
    """HTTP access to the LCU (reads; writes are limited to imports.py)."""

    def __init__(self, app_dir, custom_dir=None):
        self.app_dir = app_dir
        self.custom_dir = custom_dir
        self.port = None
        self.auth = None
        self.connected = False
        self._ctx = ssl.create_default_context()
        # self-signed certificate, 127.0.0.1 only
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def candidate_dirs(self):
        dirs = []
        if self.custom_dir:
            dirs.append(self.custom_dir)
        installed = riot_install_dir()
        if installed:
            dirs.append(installed)
        # the app is often installed in "Riot Games", next to League of Legends
        dirs.append(os.path.join(os.path.dirname(self.app_dir), "League of Legends"))
        if sys.platform == "win32":
            for drive in "CDEFGHIJ":
                dirs.append("%s:\\Riot Games\\League of Legends" % drive)
        else:
            dirs.append("/Applications/League of Legends.app")
        # macOS: the client files (lockfile) sit inside the app bundle
        return [os.path.join(d, "Contents", "LoL") if d.rstrip("/").endswith(".app") else d for d in dirs]

    def _from_lockfile(self):
        for d in self.candidate_dirs():
            path = os.path.join(d, "lockfile")
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        parts = f.read().strip().split(":")
                    if len(parts) >= 4:
                        return parts[2], parts[3]
                except OSError:
                    continue
        return None

    def _from_process(self):
        if sys.platform == "win32":
            cmd = ["powershell", "-NoProfile", "-Command",
                   "(Get-CimInstance Win32_Process -Filter \"name='LeagueClientUx.exe'\").CommandLine"]
        elif sys.platform == "darwin":
            cmd = ["ps", "-A", "-o", "args="]
        else:
            return None
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        out = "\n".join(line for line in (out or "").splitlines() if "LeagueClientUx" in line)
        port = re.search(r"--app-port=(\d+)", out or "")
        token = re.search(r"--remoting-auth-token=([\w-]+)", out or "")
        if port and token:
            return port.group(1), token.group(1)
        return None

    def connect(self, use_process=False):
        creds = self._from_lockfile() or (self._from_process() if use_process else None)
        if not creds:
            self.connected = False
            return False
        self.port = creds[0]
        self.auth = "Basic " + base64.b64encode(("riot:" + creds[1]).encode()).decode()
        try:
            self.get("/lol-gameflow/v1/gameflow-phase")
            self.connected = True
        except OSError:
            self.connected = False
        return self.connected

    def get(self, path):
        """Read-only GET. Returns the JSON body (None on 404). Raises OSError when the client doesn't answer."""
        req = urllib.request.Request("https://127.0.0.1:%s%s" % (self.port, path),
                                     headers={"Authorization": self.auth, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=4) as r:
                body = r.read().decode("utf-8")
                return json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                return None
            raise OSError("HTTP %s" % e.code)
        except urllib.error.URLError as e:
            raise OSError(str(e))

    def send(self, method, path, body=None):
        """POST / PUT / PATCH / DELETE (rune, spell and item set imports only).
        Returns the JSON body; raises OSError with the client's message on refusal."""
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request("https://127.0.0.1:%s%s" % (self.port, path), data=data, method=method,
                                     headers={"Authorization": self.auth, "Accept": "application/json",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=6) as r:
                out = r.read().decode("utf-8")
                return json.loads(out) if out else None
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("message") or ""
            except (OSError, ValueError, AttributeError):
                msg = ""
            raise OSError("HTTP %s %s" % (e.code, msg))
        except urllib.error.URLError as e:
            raise OSError(str(e))


# ----------------------------------------------------------------------------
# Client data parsing
# ----------------------------------------------------------------------------

def parse_champ_select(session):
    """Champ select summary for the local player."""
    if not session:
        return None
    local = session.get("localPlayerCellId")
    me = next((p for p in session.get("myTeam", []) if p.get("cellId") == local), {}) or {}
    bans, locked = set(), False
    for group in session.get("actions", []) or []:
        for a in group:
            if a.get("type") == "ban" and a.get("completed") and a.get("championId"):
                bans.add(a["championId"])
            if a.get("type") == "pick" and a.get("actorCellId") == local and a.get("completed"):
                locked = True
    b = session.get("bans") or {}
    bans.update(c for c in (b.get("myTeamBans") or []) + (b.get("theirTeamBans") or []) if c)
    taken = set()
    for p in (session.get("myTeam") or []) + (session.get("theirTeam") or []):
        if p.get("cellId") != local and p.get("championId"):
            taken.add(p["championId"])
    return {
        "assigned": POSITION_TO_ROLE.get((me.get("assignedPosition") or "").lower()),
        "my_champ": me.get("championId") or me.get("championPickIntent") or 0,
        "locked": locked,
        "bans": sorted(bans),
        "taken": sorted(taken),
        "spells": [me.get("spell1Id") or 0, me.get("spell2Id") or 0],
        "session": session.get("gameId") or session.get("id") or 0,
        "team": [_cs_player(p, local) for p in session.get("myTeam") or []],
        "enemies": [p["championId"] for p in session.get("theirTeam") or [] if p.get("championId")],
    }


def _cs_player(p, local):
    """Ally in champ select. Names are hidden by Riot in ranked solo/duo and are not looked up."""
    visible = (p.get("nameVisibilityType") or "VISIBLE").upper() != "HIDDEN" and bool(p.get("gameName"))
    return {"me": p.get("cellId") == local, "champ": p.get("championId") or p.get("championPickIntent") or 0,
            "locked": bool(p.get("championId")),
            "role": POSITION_TO_ROLE.get((p.get("assignedPosition") or "").lower()),
            "puuid": p.get("puuid") if visible else None,
            "name": ("%s#%s" % (p.get("gameName"), p.get("tagLine") or "")).strip("#") if visible else None}


def parse_game_teams(gd, my_puuid=None):
    """The 10 players of the game (loading screen and in game): champion, position, name, puuid."""
    picks = {}
    for x in gd.get("playerChampionSelections") or []:
        if x.get("puuid"):
            picks[x["puuid"]] = x.get("championId") or 0
    out = []
    for key, side in (("teamOne", 100), ("teamTwo", 200)):
        for p in gd.get(key) or []:
            puuid = p.get("puuid") or None
            name = ("%s#%s" % (p.get("gameName") or "", p.get("tagLine") or "")).strip("#") or p.get("summonerName") or None
            out.append({"side": side, "puuid": puuid, "name": name,
                        "champ": p.get("championId") or picks.get(puuid) or 0,
                        "role": POSITION_TO_ROLE.get((p.get("selectedPosition") or "").lower()),
                        "me": bool(puuid and puuid == my_puuid)})
    return out


LOBBY_POS = {"TOP": "top", "JUNGLE": "jgl", "MIDDLE": "mid", "BOTTOM": "adc", "UTILITY": "sup"}


def parse_lobby(lb, names, my_puuid=None):
    """Lobby members: Riot IDs and position preferences. names: {puuid: "name#tag"} already known."""
    out = []
    for m in (lb or {}).get("members") or []:
        if m.get("isBot") or not m.get("puuid"):
            continue
        out.append({"puuid": m["puuid"], "name": names.get(m["puuid"]) or m.get("summonerName") or "",
                    "me": m["puuid"] == my_puuid, "leader": bool(m.get("isLeader")),
                    "pos1": LOBBY_POS.get(m.get("firstPositionPreference")),
                    "pos2": LOBBY_POS.get(m.get("secondPositionPreference"))})
    out.sort(key=lambda x: (not x["me"], not x["leader"]))
    return out


def lane_role(lane, role):
    lane = (lane or "").upper()
    role = (role or "").upper()
    if lane == "TOP":
        return "top"
    if lane == "JUNGLE":
        return "jgl"
    if lane in ("MIDDLE", "MID"):
        return "mid"
    if lane in ("BOTTOM", "BOT"):
        return "sup" if "SUPPORT" in role else "adc"
    return None


def parse_game_detail(g, my_puuid=None):
    """Full match details (match history): the 10 players and team objectives."""
    if not g or not g.get("participants"):
        return None
    ids = {pi.get("participantId"): (pi.get("player") or {}) for pi in g.get("participantIdentities") or []}
    players = []
    for p in g["participants"]:
        s = p.get("stats") or {}
        pl = ids.get(p.get("participantId"), {})
        tl = p.get("timeline") or {}
        players.append({
            "teamId": p.get("teamId"), "championId": p.get("championId"),
            "name": pl.get("gameName") or pl.get("summonerName") or "", "tag": pl.get("tagLine") or "",
            "level": s.get("champLevel"), "k": s.get("kills", 0), "d": s.get("deaths", 0), "a": s.get("assists", 0),
            "cs": (s.get("totalMinionsKilled") or 0) + (s.get("neutralMinionsKilled") or 0),
            "gold": s.get("goldEarned", 0), "dmg": s.get("totalDamageDealtToChampions", 0), "penta": s.get("pentaKills", 0),
            "taken": s.get("totalDamageTaken", 0), "vision": s.get("visionScore", 0),
            "wards": s.get("wardsPlaced", 0), "wardsKilled": s.get("wardsKilled", 0),
            "pinks": s.get("visionWardsBoughtInGame", 0), "win": bool(s.get("win")),
            "role": lane_role(tl.get("lane"), tl.get("role")),
            "isMe": bool(my_puuid) and pl.get("puuid") == my_puuid,
        })
    teams = []
    for t in g.get("teams") or []:
        teams.append({
            "teamId": t.get("teamId"), "win": str(t.get("win", "")).lower() in ("win", "true"),
            "towers": t.get("towerKills"), "inhibs": t.get("inhibitorKills"), "barons": t.get("baronKills"),
            "dragons": t.get("dragonKills"), "heralds": t.get("riftHeraldKills"), "grubs": t.get("hordeKills"),
        })
    return {
        "source": "history", "gameId": g.get("gameId"), "puuid": my_puuid, "creation": (g.get("gameCreation") or 0) / 1000.0,
        "duration": g.get("gameDuration") or 0, "queueId": g.get("queueId"), "mode": g.get("gameMode"),
        "teams": teams, "players": players,
    }


def _stat(d, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return 0


def parse_eog(e, my_puuid=None):
    """End of game screen: immediate result (and team details when available)."""
    if not e:
        return None
    lp = e.get("localPlayer") or {}
    my_team = lp.get("teamId")
    teams_raw = e.get("teams") or []
    win = None
    for t in teams_raw:
        if (my_team is not None and t.get("teamId") == my_team) or t.get("isPlayerTeam"):
            win = bool(t.get("isWinningTeam"))
            break
    st = lp.get("stats") or {}
    if win is None:
        win = bool(_stat(st, "WIN"))
    result = {
        "championId": lp.get("championId"), "win": win, "k": _stat(st, "CHAMPIONS_KILLED"),
        "d": _stat(st, "NUM_DEATHS"), "a": _stat(st, "ASSISTS"), "duration": e.get("gameLength") or 0,
        "queueId": None,
    }
    players, teams = [], []
    for t in teams_raw:
        tw = bool(t.get("isWinningTeam"))
        teams.append({"teamId": t.get("teamId"), "win": tw})
        for p in t.get("players") or []:
            s = p.get("stats") or {}
            me = (my_puuid and p.get("puuid") == my_puuid) or (
                p.get("summonerId") and p.get("summonerId") == lp.get("summonerId"))
            players.append({
                "teamId": t.get("teamId"), "championId": p.get("championId"),
                "name": p.get("riotIdGameName") or p.get("gameName") or p.get("summonerName") or "",
                "tag": p.get("riotIdTagLine") or p.get("tagLine") or "",
                "level": _stat(s, "LEVEL"), "k": _stat(s, "CHAMPIONS_KILLED"), "d": _stat(s, "NUM_DEATHS"),
                "a": _stat(s, "ASSISTS"),
                "cs": _stat(s, "MINIONS_KILLED") + _stat(s, "NEUTRAL_MINIONS_KILLED"),
                "gold": _stat(s, "GOLD_EARNED"), "dmg": _stat(s, "TOTAL_DAMAGE_DEALT_TO_CHAMPIONS"), "penta": _stat(s, "PENTA_KILLS"),
                "taken": _stat(s, "TOTAL_DAMAGE_TAKEN"), "vision": _stat(s, "VISION_SCORE"),
                "wards": _stat(s, "WARD_PLACED"), "wardsKilled": _stat(s, "WARD_KILLED"),
                "pinks": _stat(s, "VISION_WARDS_BOUGHT_IN_GAME"), "win": tw, "role": None, "isMe": bool(me),
            })
    detail = None
    if players:
        detail = {"source": "eog", "gameId": e.get("gameId"), "creation": time.time(),
                  "duration": e.get("gameLength") or 0, "queueId": None, "mode": e.get("gameMode"),
                  "teams": teams, "players": players}
    return {"result": result, "detail": detail}


def detail_path(folder, game_id):
    return os.path.join(folder, "%s.json" % game_id)


def save_detail(folder, detail):
    if not detail or not detail.get("gameId"):
        return False
    try:
        os.makedirs(folder, exist_ok=True)
        with open(detail_path(folder, detail["gameId"]), "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False)
        return True
    except OSError:
        return False


def load_detail(folder, game_id):
    try:
        with open(detail_path(folder, game_id), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def parse_history(data):
    games = []
    for g in ((data or {}).get("games") or {}).get("games") or []:
        parts = g.get("participants") or []
        if not parts:
            continue
        p = parts[0]
        s = p.get("stats") or {}
        games.append({
            "gameId": g.get("gameId"), "championId": p.get("championId"), "win": bool(s.get("win")),
            "k": s.get("kills", 0), "d": s.get("deaths", 0), "a": s.get("assists", 0),
            "queueId": g.get("queueId"), "creation": (g.get("gameCreation") or 0) / 1000.0,
            "duration": g.get("gameDuration") or 0, "type": g.get("gameType"), "mode": g.get("gameMode"),
        })
    return games


class LolWatcher(threading.Thread):
    """Polls the client every ~2 s and pushes events to a queue.

    Events:
      {"type": "state", ...}                         client state (phase, champ select, game)
      {"type": "history", "games": [...], "puuid"}   match history (last 20 games, client limit)
      {"type": "eog", "gameId", "result", "detail"}  end of game screen (immediate result)
      {"type": "game", "gameId", "detail"}           full details of a requested game
      {"type": "ranked", "queues", "notif"}          current rank (sent when it changes)
      {"type": "roster", "gameId", "me", "players"}  current game roster (overlay)
    """

    AWAIT_EVERY = 8      # seconds between history reads after a game
    AWAIT_FOR = 900      # max wait for the game to show up in the history
    RANKED_EVERY = 60    # rank refresh outside of post-game
    LP_EVERY = 5         # rank refresh right after a game
    LP_FOR = 480         # duration of the post-game rank watch

    def __init__(self, events, app_dir, custom_dir=None, interval=2.0):
        super().__init__(daemon=True)
        self.events = events
        self.client = LolClient(app_dir, custom_dir)
        self.interval = interval
        self.stop_evt = threading.Event()
        self.history_evt = threading.Event()
        self.requests = queue.Queue()
        self._last_state = None
        self._last_try = 0.0
        self._tries = 0
        self._summoner = ""
        self._puuid = None
        self.summoner_id = None
        self._prev_phase = None
        self._game_id = None
        self._eog_done = set()
        self._await = None   # [gameId, deadline, last read]
        self._ranked_sig = None
        self._ranked_next = 0.0
        self._lp_until = 0.0
        self._roster_for = None
        self._roster_next = 0.0
        self._names = {}        # puuid -> "name#tag" (lobby members)

    def _fetch_roster(self, now):
        """Current game roster (one successful read per game)."""
        if self._roster_for == self._game_id or now < self._roster_next:
            return
        self._roster_next = now + 3
        roster = parse_live_roster(fetch_live_game())
        if roster and roster.get("me") is not None:
            self._roster_for = self._game_id
            self.events.put(dict(roster, type="roster", gameId=self._game_id))

    def _fetch_ranked(self, now, force=False):
        """Refreshes the rank (every 60 s, every 5 s right after a game)."""
        watching = now < self._lp_until
        if not force and now < self._ranked_next:
            return
        self._ranked_next = now + (self.LP_EVERY if watching else self.RANKED_EVERY)
        try:
            queues = parse_ranked(self.client.get("/lol-ranked/v1/current-ranked-stats"))
            notif = parse_lp_notification(self.client.get("/lol-ranked/v1/current-lp-change-notification")) \
                if watching else None
        except OSError:
            return
        if not queues:
            return
        sig = json.dumps([queues, notif], sort_keys=True)
        if sig != self._ranked_sig:
            if self._ranked_sig is not None and watching:
                self._lp_until = now + 20   # rank changed: a few more reads, then stop
            self._ranked_sig = sig
            self.events.put({"type": "ranked", "queues": queues, "notif": notif})

    def request_game(self, game_id):
        """Requests full game details (answered with a "game" event)."""
        if game_id:
            self.requests.put(game_id)

    def set_custom_dir(self, path):
        self.client.custom_dir = path
        self.client.connected = False
        self._last_try = 0.0

    def request_history(self):
        self.history_evt.set()

    def stop(self):
        self.stop_evt.set()

    def _push(self, ev):
        if ev.get("type") == "state":
            sig = json.dumps(ev, sort_keys=True)
            if sig == self._last_state:
                return
            self._last_state = sig
        self.events.put(ev)

    def _disconnected(self):
        self.client.connected = False
        self._prev_phase = None
        self._push({"type": "state", "connected": False})

    def run(self):
        while not self.stop_evt.is_set():
            try:
                self._tick()
            except OSError:
                self._disconnected()
            except Exception as e:  # never let the watcher die
                self._push({"type": "state", "connected": False, "error": str(e)})
            self.stop_evt.wait(self.interval)

    def _tick(self):
        c = self.client
        if not c.connected:
            now = time.time()
            if now - self._last_try < 5:
                return
            self._last_try = now
            self._tries += 1
            # querying the process is slow: only every 6th attempt
            if not c.connect(use_process=(self._tries % 6 == 1)):
                self._push({"type": "state", "connected": False})
                return
            me = c.get("/lol-summoner/v1/current-summoner") or {}
            self._summoner = ("%s#%s" % (me.get("gameName", ""), me.get("tagLine", ""))).strip("#")
            self._puuid = me.get("puuid")
            self.summoner_id = me.get("summonerId")
            self.history_evt.set()

        now = time.time()
        phase = c.get("/lol-gameflow/v1/gameflow-phase") or "None"
        state = {"type": "state", "connected": True, "phase": phase, "summoner": self._summoner}
        if phase == "ChampSelect":
            state["cs"] = parse_champ_select(c.get("/lol-champ-select/v1/session"))
            if state["cs"] is not None:
                gd = (c.get("/lol-gameflow/v1/session") or {}).get("gameData") or {}
                state["cs"]["queue"] = (gd.get("queue") or {}).get("id")
                state["cs"]["map"] = (gd.get("queue") or {}).get("mapId")
        if phase in ("Lobby", "Matchmaking", "ReadyCheck"):   # lobby members (group roulette), queue picked
            lb = c.get("/lol-lobby/v2/lobby")
            gc = (lb or {}).get("gameConfig") or {}
            state["lobby_queue"] = {"id": gc.get("queueId"), "map": gc.get("mapId"), "custom": bool(gc.get("isCustom"))}
            for m in (lb or {}).get("members") or []:
                pu = m.get("puuid")
                if pu and pu not in self._names and not m.get("isBot"):
                    try:
                        sm = c.get("/lol-summoner/v2/summoners/puuid/%s" % pu) or {}
                        self._names[pu] = ("%s#%s" % (sm.get("gameName", ""), sm.get("tagLine", ""))).strip("#")
                    except OSError:
                        pass
            state["lobby"] = [{k: v for k, v in x.items() if k != "puuid"} for x in parse_lobby(lb, self._names, self._puuid)]
        if phase in GAME_PHASES or phase == "GameStart":
            gs = c.get("/lol-gameflow/v1/session") or {}
            gd = gs.get("gameData") or {}
            if phase in ("GameStart", "InProgress", "Reconnect"):   # live game: the 10 players
                state["teams"] = parse_game_teams(gd, self._puuid)
                state["queue"] = (gd.get("queue") or {}).get("id")
            if phase in GAME_PHASES:
                qid = (gd.get("queue") or {}).get("id")
                state["game"] = {"gameId": gd.get("gameId"), "queueId": qid, "mode": (gd.get("queue") or {}).get("gameMode"),
                                 "custom": bool(gd.get("isCustomGame")) or qid in (None, -1, 0, 3140)}
                if gd.get("gameId"):
                    self._game_id = gd["gameId"]
        # rank re-read on every phase change (pre-game rank = LP baseline)
        self._fetch_ranked(now, force=(phase != self._prev_phase))
        self._push(state)
        if phase in ("InProgress", "Reconnect") and self._game_id:
            self._fetch_roster(now)

        # end of game screen: immediate result, without waiting for the history
        if phase in ("WaitingForStats", "PreEndOfGame", "EndOfGame") and self._game_id \
                and self._game_id not in self._eog_done:
            eog = c.get("/lol-end-of-game/v1/eog-stats-block")
            parsed = parse_eog(eog, self._puuid)
            if parsed and (not eog.get("gameId") or eog.get("gameId") == self._game_id):
                self._eog_done.add(self._game_id)
                self.events.put({"type": "eog", "gameId": self._game_id, "result": parsed["result"],
                                 "detail": parsed["detail"]})

        # after a game: re-read the history every 8 s until the game shows up
        if self._prev_phase in GAME_PHASES and phase not in ("InProgress", "Reconnect") and self._game_id:
            if not self._await or self._await[0] != self._game_id:
                self._await = [self._game_id, now + self.AWAIT_FOR, 0.0]
                self._lp_until = now + self.LP_FOR
                self._ranked_next = now
        self._prev_phase = phase
        fetch = self.history_evt.is_set()
        if self._await and now - self._await[2] >= self.AWAIT_EVERY:
            fetch = True
        if fetch:
            self.history_evt.clear()
            data = c.get("/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=20")
            games = parse_history(data)
            self.events.put({"type": "history", "games": games, "puuid": self._puuid})
            if self._await:
                self._await[2] = now
                if any(g["gameId"] == self._await[0] for g in games) or now > self._await[1]:
                    if any(g["gameId"] == self._await[0] for g in games):
                        self.requests.put(self._await[0])
                    self._await = None

        # game details requested by the app
        for _ in range(3):
            try:
                gid = self.requests.get_nowait()
            except queue.Empty:
                break
            g = c.get("/lol-match-history/v1/games/%s" % gid)
            self.events.put({"type": "game", "gameId": gid, "detail": parse_game_detail(g, self._puuid)})


# ----------------------------------------------------------------------------
# Roll history
# ----------------------------------------------------------------------------

LEGACY_STATUS = {"en attente": "pending", "en partie": "in_game", "jouée": "played", "annulé": "cancelled",
                 "à vérifier": "to_check"}
LEGACY_REASON = {"champion pris": "champion_taken", "champion banni": "champion_banned",
                 "relancé avant de jouer": "rerolled", "relancé sans client LoL connecté": "rerolled_offline",
                 "partie hors Faille": "not_rift", "relancé (groupe)": "group_reroll"}
LEGACY_ROLE = {"Top": "top", "Jungle": "jgl", "Mid": "mid", "ADC": "adc", "Support": "sup"}


class RollHistory:
    """Persistent roll history, matched against the games actually played.

    Games played without a roll are stored too ("free"), whether tracked live or caught up from the client's
    match history on the next connection (the client only keeps the last 20). Custom games and practice tool
    are excluded."""

    def __init__(self, path, cid_to_key):
        self.path = path
        self.cid_to_key = cid_to_key
        self.entries = []
        self.account = None   # current LoL account: each one has its own rolls (pending roll, matching)
        self.load()

    # --- storage ---
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.entries = data if isinstance(data, list) else []
        except (OSError, ValueError):
            self.entries = []
        if self._upgrade_legacy():
            self.save()

    def _upgrade_legacy(self):
        """Older versions stored French status and reason texts."""
        changed = False
        for e in self.entries:
            status = LEGACY_STATUS.get(e.get("status"))
            if status:
                e["status"] = status
                changed = True
            reason = e.get("reason")
            if isinstance(e.get("favs"), list):
                favs = ["roles" if f == "rôles" else f for f in e["favs"]]
                if favs != e["favs"]:
                    e["favs"] = favs
                    changed = True
            if isinstance(reason, str) and reason:
                code = LEGACY_REASON.get(reason)
                if code is None and reason.startswith("autofill (") and reason.endswith(")"):
                    label = reason[len("autofill ("):-1]
                    code = "autofill:" + LEGACY_ROLE.get(label, label.lower())
                if code:
                    e["reason"] = code
                    changed = True
        return changed

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def clear(self):
        self.entries = []
        self.save()

    def fix_off_rift(self):
        """Fixes rolls wrongly matched to a non-Rift game (ARAM, Arena, practice tool...): the game becomes a free game,
        the latest roll goes back to pending and older ones are cancelled."""
        changed = False
        rolls = self.rolls()
        for e in rolls:
            if e.get("status") not in ("played", "remake") or not e.get("queue") or e["queue"] in SR_QUEUES:
                continue
            if e["queue"] not in (3140, -1, 0):   # real game (ARAM...): kept as a free game
                # the game started shortly after the roll (the stored end time isn't reliable for these old entries)
                g = self._free_entry(e["game_id"], e["created"] + 60, e.get("played"), e.get("puuid"))
                for k in ("queue", "win", "kda", "duration", "ended", "status"):
                    if k in e:
                        g[k] = e[k]
                g.pop("role", None)
                g["role"] = None
                self._insert(g)
            for k in ("game_id", "queue", "played", "win", "kda", "duration", "ended", "lp_before", "lp", "lp_protected",
                      "rank_ref", "src", "puuid"):
                e.pop(k, None)
            if e is rolls[-1]:
                e["status"] = "pending"
                e.pop("reason", None)
            else:
                e["status"] = "cancelled"
                e["reason"] = "not_rift"
            changed = True
        if changed:
            self.save()
        return changed

    # --- rolls ---
    def mine(self, e):
        """Entry of the current LoL account (entries recorded without one, by older versions, belong to all)."""
        owner = e.get("account") or e.get("puuid")
        return not (self.account and owner and owner != self.account)

    def rolls(self):
        return [e for e in self.entries if not e.get("free") and self.mine(e)]

    def last_roll(self):
        return next((e for e in reversed(self.entries) if not e.get("free") and self.mine(e)), None)

    def pending(self):
        e = self.last_roll()
        return e if e and e.get("status") == "pending" else None

    def _insert(self, entry):
        """Inserts a game in chronological order (caught-up games can be older)."""
        i = len(self.entries)
        while i > 0 and self.entries[i - 1].get("created", 0) > entry["created"]:
            i -= 1
        self.entries.insert(i, entry)

    def _free_entry(self, game_id, created, champ_key, puuid=None):
        return {"id": int(created * 1000) + (game_id or 0) % 1000, "created": created, "free": True,
                "date": time.strftime("%d/%m %H:%M", time.localtime(created)), "key": champ_key, "played": champ_key,
                "role": None, "game_id": game_id, "puuid": puuid}

    def add_roll(self, key, role, tracking, reason=None, now=None, mode=None, favs=None, group=None, full=None,
                 official=None, day=None):
        """mode: "both" (random role + champion), "role" (random role, picked champion),
        "champ" (random champion, picked role). favs: favorite filters active for the roll.
        full: role and champion both drawn. official: made on the official roulette, it fills the binder
        (collection.py). day: the roulette day it belongs to (core.Core._day)."""
        now = now or time.time()
        prev = self.pending()
        if prev:
            if tracking:
                prev["status"] = "cancelled"
                prev["reason"] = reason or "rerolled"
            else:
                prev["status"] = "to_check"
                prev["reason"] = reason or "rerolled_offline"
            prev["closed"] = now
        entry = {"id": int(now * 1000), "created": now, "date": time.strftime("%d/%m %H:%M", time.localtime(now)),
                 "key": key, "role": role, "status": "pending"}
        if self.account:
            entry["account"] = self.account
        if mode:
            entry["mode"] = mode
        if full is not None:
            entry["full"] = bool(full)
        if official is not None:
            entry["official"] = bool(official)
        if favs:
            entry["favs"] = favs
        if group:
            entry["group"] = group
        if day:
            entry["day"] = day
        self.entries.append(entry)
        self.save()
        return entry

    def move_role(self, e, role):
        """Autofill on a role the rolled champion plays too: the roll keeps its champion and moves to that role."""
        e.setdefault("rolled_role", e["role"])
        e["role"] = role
        self.save()

    def on_result(self, game_id, res):
        """Immediate result (end of game screen) for the roll matched to that game."""
        for e in reversed(self.entries):
            if e.get("game_id") == game_id and e.get("status") == "in_game":
                g = {"gameId": game_id, "queueId": e.get("queue"), "championId": res.get("championId"),
                     "win": res.get("win"), "k": res.get("k", 0), "d": res.get("d", 0), "a": res.get("a", 0),
                     "duration": res.get("duration", 0)}
                self._apply(e, g)
                e["src"] = "eog"   # confirmed later by the match history
                self.save()
                return True
        return False

    # --- games ---
    def _used_games(self):
        return {e.get("game_id") for e in self.entries if e.get("game_id")}

    def on_game_start(self, game_id, queue_id, played_cid, started_at=None, ranked=None, role=None, puuid=None,
                      custom=False, mode=None, paused=False):
        """A game just started: matched to the pending roll (created before it), otherwise stored as a free game.
        ranked: current rank, the LP baseline for this game. Returns "roll", "free" or None."""
        started_at = started_at or time.time()
        if not game_id or game_id in self._used_games():
            return None
        e = self.pending()
        kind = "roll"
        if not e or e["created"] > started_at or paused or not roulette_game(queue_id, mode, custom):
            if custom:
                return None   # custom / practice game without a roll: not stored
            e = self._free_entry(game_id, started_at, self.cid_to_key.get(played_cid), puuid)
            e["role"] = role
            self._insert(e)
            kind = "free"
        if puuid:
            e["puuid"] = puuid
        e["status"] = "in_game"
        e["game_id"] = game_id
        e["queue"] = queue_id
        if played_cid:
            e["played"] = self.cid_to_key.get(played_cid)
        qt = RANKED_QUEUES.get(queue_id)
        if qt and ranked and ranked.get(qt):
            e["lp_before"] = dict(ranked[qt], queue=qt)
        elif ranked and ranked.get("RANKED_SOLO_5x5"):   # elo of a game outside ranked (binder cards): the solo/duo rank
            r = ranked["RANKED_SOLO_5x5"]
            e["rank_ref"] = {"tier": r.get("tier"), "division": r.get("division"), "provisional": r.get("provisional"),
                             "queue": "RANKED_SOLO_5x5"}
        self.save()
        return kind

    # --- LP ---
    @staticmethod
    def _rank_tuple(q):
        return (q.get("wins"), q.get("losses"), q.get("tier"), q.get("division"), q.get("lp"))

    def on_ranked(self, queues, notif=None):
        """New rank received: computes LP for the games waiting for it. Returns True on change."""
        changed = False
        recent = self.entries[-40:]
        for i, e in enumerate(recent):
            before = e.get("lp_before")
            lp = e.get("lp")
            if not before or (lp is not None and not lp.get("timeout")):
                continue
            if e.get("status") not in ("in_game", "played", "remake"):
                continue
            # if a later ranked game in the same queue started, the rank stored at its start is this game's "after"
            nxt = next((x["lp_before"] for x in recent[i + 1:]
                        if x.get("lp_before") and x["lp_before"]["queue"] == before["queue"]), None)
            after = nxt or queues.get(before["queue"])
            if not after or self._rank_tuple(after) == self._rank_tuple(before):
                continue   # rank not updated yet (or game not counted)
            games = (after["wins"] + after["losses"]) - (before["wins"] + before["losses"])
            result = "win" if after["wins"] > before["wins"] else "loss" if after["losses"] > before["losses"] else None
            placement = is_placement(before) or is_placement(after)
            if games > 1 or games < 0:
                delta = None   # several ranked games played since: LP can't be attributed
            else:
                delta = None if placement else abs_lp(after) - abs_lp(before)
            if notif and notif.get("gameId") == e.get("game_id"):
                delta = notif["delta"]   # the client's own number wins
            e["lp"] = {"delta": delta, "queue": before["queue"], "tier": after["tier"], "division": after["division"],
                       "lp": after["lp"], "provisional": after.get("provisional"), "prov_left": after.get("prov_left"),
                       "counted": games == 1, "result": result, "placement": placement, "multi": games > 1}
            e["lp_protected"] = bool(result == "loss" and delta == 0)
            changed = True
        if changed:
            self.save()
        return changed

    def check_lp_timeout(self, queues, now=None, delay=LP_TIMEOUT):
        """Ranked game ended long ago without any rank change: it didn't count (e.g. loss forgiven by the client)."""
        now = now or time.time()
        changed = False
        recent = self.entries[-40:]
        for i, e in enumerate(recent):
            before = e.get("lp_before")
            if not before or e.get("lp") is not None or e.get("status") != "played":
                continue
            nxt = next((x["lp_before"] for x in recent[i + 1:]
                        if x.get("lp_before") and x["lp_before"]["queue"] == before["queue"]), None)
            # a later ranked game already started with the same rank: no need to wait
            if not nxt and now - e.get("ended", now) < delay:
                continue
            after = nxt or queues.get(before["queue"])
            if not after or self._rank_tuple(after) != self._rank_tuple(before):
                continue
            e["lp"] = {"delta": 0, "queue": before["queue"], "tier": after["tier"], "division": after["division"],
                       "lp": after["lp"], "provisional": after.get("provisional"), "prov_left": after.get("prov_left"),
                       "counted": False, "result": None, "placement": is_placement(after), "timeout": True}
            e["lp_protected"] = not e.get("win")
            changed = True
        if changed:
            self.save()
        return changed

    def _apply(self, e, g):
        e["game_id"] = g["gameId"]
        e["queue"] = g.get("queueId") or e.get("queue")
        e["played"] = self.cid_to_key.get(g.get("championId"))
        if e.get("free") and e["played"]:
            e["key"] = e["played"]
        e["win"] = g.get("win")
        e["kda"] = [g.get("k", 0), g.get("d", 0), g.get("a", 0)]
        e["duration"] = g.get("duration", 0)
        e["status"] = "remake" if g.get("duration", 0) and g["duration"] < REMAKE_SECONDS else "played"
        e.setdefault("ended", time.time())
        e.pop("reason", None)

    def on_history(self, games, puuid=None, paused=False):
        """Syncs with the client's match history (last 20 games): rolls matched to their game, then every other
        matchmade game added as a free game. Returns True on change."""
        if not games:
            return False
        changed = False
        by_id = {g["gameId"]: g for g in games}
        used = self._used_games()
        oldest = min(g["creation"] for g in games)
        ordered = sorted(games, key=lambda g: g["creation"])
        rolls = self.rolls()
        for i, e in enumerate(rolls):
            st = e.get("status")
            if (st == "in_game" or e.get("src") == "eog") and e.get("game_id") in by_id:
                self._apply(e, by_id[e["game_id"]])
                e.pop("src", None)
                changed = True
            elif st in ("to_check", "pending"):
                start = e["created"]
                end = rolls[i + 1]["created"] if i + 1 < len(rolls) else float("inf")
                g = None if (paused and st == "pending") else next(
                    (g for g in ordered if start < g["creation"] < end and g["gameId"] not in used
                     and roulette_game(g.get("queueId"), g.get("mode"), g.get("type") == "CUSTOM_GAME")), None)
                if g:
                    self._apply(e, g)
                    used.add(g["gameId"])
                    changed = True
                elif st == "to_check" and oldest < start:
                    e["status"] = "cancelled"
                    e["reason"] = "rerolled"
                    changed = True
        for e in self.entries:   # free games tracked live
            if e.get("free") and (e.get("status") == "in_game" or e.get("src") == "eog") and e.get("game_id") in by_id:
                self._apply(e, by_id[e["game_id"]])
                e.pop("src", None)
                changed = True
        for g in ordered:        # games played while the app was closed
            if g["gameId"] in used or g.get("type") not in (None, "MATCHED_GAME"):
                continue
            e = self._free_entry(g["gameId"], g["creation"], self.cid_to_key.get(g.get("championId")), puuid)
            self._apply(e, g)
            e["ended"] = g["creation"] + (g.get("duration") or 0)
            self._insert(e)
            used.add(g["gameId"])
            changed = True
        if changed:
            self.save()
        return changed

    # --- display ---
    def summary(self, entries=None):
        entries = self.entries if entries is None else entries
        games = [e for e in entries if e.get("status") == "played"]
        kdas = [e["kda"] for e in games if e.get("kda")]
        n = max(1, len(kdas))
        measured = [e for e in games if isinstance((e.get("lp") or {}).get("delta"), int)]
        everything = {
            "games": len(games), "games_wins": sum(1 for e in games if e.get("win")),
            "games_protected": sum(1 for e in games if e.get("lp_protected")),
            "roll_games": sum(1 for e in games if not e.get("free")),
            "kda": [round(sum(k[i] for k in kdas) / n, 1) for i in range(3)] if kdas else None,
            "lp_total": sum(e["lp"]["delta"] for e in measured), "lp_games": len(measured),
            "protected": sum(1 for e in games if e.get("lp_protected")),
        }
        entries = [e for e in entries if not e.get("free")]
        played = [e for e in entries if e.get("status") == "played"]
        wins = sum(1 for e in played if e.get("win"))
        respected = [e for e in played if e.get("played") == e.get("key")]
        out = {
            "total": len(entries),
            "played": len(played),
            "respected": len(respected),
            "respected_wins": sum(1 for e in respected if e.get("win")),
            # losses without LP loss: still losses, excluded from the displayed win rate
            "respected_protected": sum(1 for e in respected if e.get("lp_protected")),
            "wins": wins,
            "cancelled": sum(1 for e in entries if e.get("status") == "cancelled"),
        }
        out.update(everything)
        return out


def make_event_queue():
    return queue.Queue()
