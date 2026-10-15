"""
Roulette of Legends core: data, profile, rolls, history and the League client link (no UI).

The UI (ui/ folder, shown in a WebView2 window) talks to this core through the local server in webserver.py;
the in-game overlay (overlay.py) reads it directly. Every public method takes the lock, so any thread can call it.
"""

import glob
import json
import os
import queue
import random
import shutil
import sys
import threading
import time
import unicodedata

import lol_client as lol
import lolassets


def find_base():
    """Folder holding data/: the script's folder, or for the .exe its own folder (or a parent when the exe sits in
    a subfolder of the project)."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        up = os.path.dirname(exe_dir)
        for d in (exe_dir, up, os.path.dirname(up)):
            if os.path.isfile(os.path.join(d, "data", "stats.json")):
                return d
        return exe_dir
    return os.path.dirname(os.path.abspath(__file__))


# Lite edition: a separate app built with lite/rol_lite.py. Roulette (solo, group, chaos), favorites and history
# only; no guides, overlay, imports or Game page.
try:
    import rol_lite  # noqa: F401
    LITE = True
except ImportError:
    LITE = False
MAC = sys.platform == "darwin"
APP_NAME = "Roulette of Legends Lite" if LITE else "Roulette of Legends"
APP_ID = "RouletteOfLegends.Lite" if LITE else "RouletteOfLegends.App"   # taskbar identity (AppUserModelID)
APP_SHORT = "RoL"
# download page of both apps (release page), shown by the Lite to promote the full app; empty until published
DOWNLOAD_URL = "https://github.com/Raktos1030/Roulette-of-Legends/releases/latest"
OLD_NAMES = () if LITE else ("Roulette LoL",)   # former app names (Windows startup entry to migrate)
APP_VERSION = "2.2.1"
# macOS app: data/ and ui/ are bundled read-only; data/ is copied to a writable folder of the user's Library
RESOURCES = getattr(sys, "_MEIPASS", None) if MAC and getattr(sys, "frozen", False) else None
BASE = os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_NAME) if RESOURCES else find_base()
DATA = os.path.join(BASE, "data")
UI_DIR = os.path.join(RESOURCES or BASE, "ui")
BACKUP_DIR = os.path.join(BASE, "backups")
PROFILE_PATH = os.environ.get("ROL_PROFILE") or os.path.join(DATA, "profile.json")   # alternate profile for tests
HISTORY_PATH = os.path.join(DATA, "history.json")
GAMES_DIR = os.path.join(DATA, "games")
LOG_PATH = os.path.join(DATA, "errors.log")
INSTANCE_PATH = os.path.join(DATA, ".instance")

# files renamed in 2.1, moved on first launch (old path, new path)
LEGACY_PATHS = [
    (os.path.join(DATA, "profil.json"), os.path.join(DATA, "profile.json")),
    (os.path.join(DATA, "historique.json"), HISTORY_PATH),
    (os.path.join(DATA, "parties"), GAMES_DIR),
    (os.path.join(DATA, "erreurs.log"), LOG_PATH),
    (os.path.join(DATA, "maj.json"), os.path.join(DATA, "update.json")),
    (os.path.join(DATA, "lexique.json"), os.path.join(DATA, "glossary.json")),
    (os.path.join(DATA, "lexique_en.json"), os.path.join(DATA, "glossary_en.json")),
    (os.path.join(DATA, "objets.json"), os.path.join(DATA, "items.json")),
    (os.path.join(DATA, "en", "noms.json"), os.path.join(DATA, "en", "names.json")),
    (os.path.join(DATA, "img", "ui", "or.png"), os.path.join(DATA, "img", "ui", "gold.png")),
    (os.path.join(BASE, "sauvegardes"), BACKUP_DIR),
] + [(os.path.join(DATA, "cache", name + "_precedent.json"), os.path.join(DATA, "cache", name + "_previous.json"))
     for name in ("stats", "champions", "compo", "items", "runes")]


def seed_data_dir():
    """macOS app: copies the bundled data to the user folder on first launch, and again when it ships newer stats."""
    if not RESOURCES:
        return
    src = os.path.join(RESOURCES, "data")

    def generated(folder):
        return ((read_json(os.path.join(folder, "stats.json"), {}) or {}).get("meta") or {}).get("generated") or ""
    newer = generated(src) > generated(DATA)
    for base, _dirs, files in os.walk(src):
        rel = os.path.relpath(base, src)
        dest = DATA if rel == "." else os.path.join(DATA, rel)
        os.makedirs(dest, exist_ok=True)
        for f in files:
            target = os.path.join(dest, f)
            if newer or not os.path.exists(target):
                shutil.copy2(os.path.join(base, f), target)


def migrate_legacy_paths():
    for old, new in LEGACY_PATHS:
        if os.path.exists(old) and not os.path.exists(new):
            try:
                os.rename(old, new)
            except OSError:
                pass

ROLES = ["top", "jgl", "mid", "adc", "sup"]
ROLE_LABEL = {"top": "Top", "jgl": "Jungle", "mid": "Mid", "adc": "ADC", "sup": "Support", "random": "Aléatoire"}
ROLE_LONG = {"top": "TOP", "jgl": "JUNGLE", "mid": "MID", "adc": "ADC", "sup": "SUPPORT"}
ROLE_ICON = {"top": "top", "jgl": "jungle", "mid": "middle", "adc": "bottom", "sup": "utility", "random": "fill"}
MODE_LABEL = {"both": "Rôle + champion", "role": "Rôle aléatoire", "champ": "Champion aléatoire", "group": "Groupe",
              "chaos": "Chaos"}
SPELL_KEYS = ["P", "Q", "W", "E", "R"]
_LABELS = [(ROLE_LABEL, dict(ROLE_LABEL)), (MODE_LABEL, dict(MODE_LABEL))]
GUIDE_FIELDS = [
    "identity", "playstyle", "early_game", "level_1", "level_2", "level_3", "level_6",
    "power_spikes", "lane_plan", "trading", "threats", "mistakes", "matchup_notes",
    "mid_game", "late_game", "ahead", "behind", "win_condition", "final_tip",
]
PHASE_TEXT = {
    "None": "Connecté", "Lobby": "Dans le salon", "Matchmaking": "Recherche de partie",
    "ReadyCheck": "Partie trouvée", "ChampSelect": "Sélection des champions", "GameStart": "Lancement de la partie",
    "InProgress": "Partie en cours", "Reconnect": "Reconnexion", "WaitingForStats": "Fin de partie",
    "PreEndOfGame": "Fin de partie", "EndOfGame": "Fin de partie",
}
_LABELS.append((PHASE_TEXT, dict(PHASE_TEXT)))
OVERLAY_MODES = [("tab", "Activé"), ("never", "Désactivé")]
OVERLAY_PAGES = [("early", "Début"), ("matchup", "Matchup"), ("late", "Mid & late"), ("team", "Équipe")]
# overlay modules: default display ("tab" = while holding Tab), Ctrl + letter shortcut, default position
OVERLAY_MODULES = [
    {"id": "guide", "label": "Fiche", "mode": "tab", "key": "O", "pos": {"fx": 1.0, "fy": 0.34},
     "desc": "Ta fiche résumée. La page suit le chrono : début, phase de lane, puis mid & late."},
    {"id": "skills", "label": "Ordre des sorts", "mode": "tab", "key": "L", "pos": {"fx": 0.74, "fy": 1.0},
     "desc": "Quand tu as un point à dépenser, le sort à monter s'allume en bleu directement sur ton HUD (il suit la taille du HUD, même changée en pleine partie). Avec Tab : les prochains sorts."},
    {"id": "stats", "label": "Tes stats", "mode": "tab", "key": "U", "pos": {"fx": 1.0, "fy": 0.08},
     "desc": "CS par minute et KDA comparés aux joueurs Émeraude+ sur ton champion à ce poste ; participation aux kills et vision comparées à ta moyenne ; niveau et CS face à ton vis-à-vis."},
    {"id": "items", "label": "Objets", "mode": "tab", "key": "K", "pos": {"fx": 0.0, "fy": 1.0},
     "desc": "Build le plus joué : départ, trio central, options des objets 4 à 6 (encadré vert : déjà acheté)."},
    {"id": "gold", "label": "Écart d'or", "mode": "tab", "key": "G", "pos": {"fx": 0.5, "fy": 0.0},
     "desc": "Valeur des objets ligne par ligne du tableau des scores, et l'écart de toute l'équipe."},
    {"id": "objectives", "label": "Objectifs", "mode": "tab", "key": "J", "pos": {"fx": 0.0, "fy": 0.1}, "on": False,
     "desc": "Chronos de réapparition : quand reviennent le prochain drake, le Nashor, le Héraut et les inhibiteurs (d'après les annonces de la partie). Désactivé par défaut."},
]
MODULE_DEFAULT = {m["id"]: m for m in OVERLAY_MODULES}
LEGACY_MODULE = {"fiche": "guide", "sorts": "skills", "objets": "items", "or": "gold", "objectifs": "objectives"}
LEGACY_PAGE = {"debut": "early", "equipe": "team"}
_OVERLAY_MODES_FR = list(OVERLAY_MODES)
_OVERLAY_PAGES_FR = list(OVERLAY_PAGES)
_OVERLAY_MODULES_FR = [(m["label"], m["desc"]) for m in OVERLAY_MODULES]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def log_error(text):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%d/%m/%Y %H:%M:%S"), text))
    except OSError:
        pass


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


# ----------------------------------------------------------------------------
# UI language: French by default. In English, UI text comes from ui/i18n/en.json (French text is the key),
# game names from Riot's official data (data/en/names.json), guides from data/guides_en
# ----------------------------------------------------------------------------
LANGS = ("fr", "en")
_I18N = {"lang": "fr", "en": None}


def system_lang():
    """French when the system UI is French, English otherwise."""
    if MAC:
        import subprocess
        try:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True,
                                 timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return "fr"
        first = next((x.strip(' ",') for x in out.splitlines() if x.strip(' ",()')), "fr")
        return "fr" if first.lower().startswith("fr") else "en"
    try:
        import ctypes
        return "fr" if (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x0C else "en"
    except (AttributeError, OSError):
        return "fr"


def lang():
    return _I18N["lang"]


def T(text):
    """UI text in the current language: T("Copier"). Templates are translated before the "%"."""
    if _I18N["lang"] == "fr" or not text:
        return text
    if _I18N["en"] is None:
        _I18N["en"] = read_json(os.path.join(UI_DIR, "i18n", "en.json"), {}) or {}
    en = _I18N["en"]
    return en.get(text) or en.get(text.replace(" ", " ").replace(" ", " "), text)


# modules that don't depend on core use the same function for their text
lol.T = T
import analysis as _analysis   # noqa: E402
import imports as _imports   # noqa: E402
_analysis.T, _analysis.lang = T, lang
_imports.T = T


def build_label(label):
    if (label or "").startswith("Adapté · "):
        return T("Adapté · %s") % T(label[len("Adapté · "):])
    return T(label or "")


def set_lang(code):
    """Switches the language: texts, number format and the labels kept in the constants above."""
    _I18N["lang"] = code if code in LANGS else "fr"
    _I18N["en"] = None
    for table, orig in _LABELS:
        for k, v in orig.items():
            table[k] = T(v)
    OVERLAY_MODES[:] = [(k, T(v)) for k, v in _OVERLAY_MODES_FR]
    OVERLAY_PAGES[:] = [(k, T(v)) for k, v in _OVERLAY_PAGES_FR]
    for m, orig in zip(OVERLAY_MODULES, _OVERLAY_MODULES_FR):
        m["label"], m["desc"] = T(orig[0]), T(orig[1])


def fmt_num(x, digits=1):
    out = ("%." + str(digits) + "f") % x
    return out if _I18N["lang"] == "en" else out.replace(".", ",")


def fmt_pct(x, digits=1):
    return (fmt_num(x, digits) + ("%" if _I18N["lang"] == "en" else " %")) if x is not None else "?"


def fmt_int(n):
    return ("{:,}".format(int(n)) if _I18N["lang"] == "en" else "{:,}".format(int(n)).replace(",", " ")) \
        if n is not None else "?"


def fmt_k(n):
    return fmt_num(n / 1000.0, 1) + ("k" if _I18N["lang"] == "en" else " k") if n and n >= 1000 else fmt_int(n or 0)


def signed(n):
    return ("+%d" % n) if n > 0 else ("−%d" % -n) if n < 0 else "0"


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data, compact=False):
    """Atomic write (temp file, then replace)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ----------------------------------------------------------------------------
# Profile (favorites and settings)
# ----------------------------------------------------------------------------

class Profile:
    DEFAULT = {
        "fav_champs": [], "fav_combos": [], "fav_roles": [], "only_fav_roles": False,
        "only_fav_champs": False, "no_repeat": True, "lol_dir": None, "tray_hint_shown": False,
        "overlay_mode": "tab", "overlay_side": "right", "overlay_page": "early",
        "overlay_pos": None, "overlay_scale": 1.0, "overlay_opacity": 0.95, "overlay_modules": {},
        "auto_update": True, "seen_update": None, "glossary_hints": True, "ambient": True,
        "lang": "",              # "fr", "en"; empty = the Windows language
        "import_runes": True, "import_spells": True, "import_items": True, "import_replace": False,
        "build_pick": {},   # build variant picked per guide (Build tab), imported in champ select
        "account_puuid": None,   # last connected LoL account: the history shows its games
        "board_geom": None,      # scoreboard grid (Tab), measured once for the resolution and HUD scale
        "roulette_paused": False,   # games don't count for the roulette, the current roll stays pending
    }

    def __init__(self, path):
        self.path = path
        self.data = json.loads(json.dumps(self.DEFAULT))
        loaded = read_json(path, {})
        if isinstance(loaded, dict):
            self.data.update({k: v for k, v in loaded.items() if k in self.DEFAULT})
        # old settings: a single overlay window (position, "always visible")
        pos = self.data["overlay_pos"]
        if pos is None and self.data["overlay_side"] == "left":
            pos = {"fx": 0.0, "fy": 0.12}
        if isinstance(pos, dict) and "fx" in pos:
            pos = {"guide": pos}
        self.data["overlay_pos"] = pos if isinstance(pos, dict) else {}
        if not isinstance(self.data["overlay_modules"], dict):
            self.data["overlay_modules"] = {}
        legacy = self.data["overlay_page"] in LEGACY_PAGE or any(
            m in LEGACY_MODULE for k in ("overlay_pos", "overlay_modules") for m in self.data[k])
        for k in ("overlay_pos", "overlay_modules"):
            self.data[k] = {LEGACY_MODULE.get(m, m): v for m, v in self.data[k].items()}
        self.data["overlay_page"] = LEGACY_PAGE.get(self.data["overlay_page"], self.data["overlay_page"])
        if self.data["overlay_mode"] == "always":
            self.data["overlay_modules"].setdefault("guide", {})["mode"] = "always"
        if self.data["overlay_mode"] not in dict(OVERLAY_MODES):
            self.data["overlay_mode"] = "tab"
        if legacy:
            self.save()

    def module_cfg(self, mid):
        """Overlay module setting: shown or not, and when (while holding Tab or always)."""
        c = (self.data.get("overlay_modules") or {}).get(mid) or {}
        mode = c.get("mode") if c.get("mode") in ("tab", "always") else MODULE_DEFAULT[mid]["mode"]
        return {"on": bool(c.get("on", MODULE_DEFAULT[mid].get("on", True))), "mode": mode}

    def save(self):
        try:
            write_json(self.path, self.data)
        except OSError:
            pass

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v
        self.save()

    def get(self, k, default=None):
        return self.data.get(k, default)

    # a champion can be a favorite for all its roles (global) or for some roles only
    def fav_roles_of(self, key, roles):
        if key in self.data["fav_champs"]:
            return set(roles)
        return {r for r in roles if "%s|%s" % (key, r) in self.data["fav_combos"]}

    def is_combo_fav(self, key, role):
        return key in self.data["fav_champs"] or "%s|%s" % (key, role) in self.data["fav_combos"]

    def is_any_fav(self, key):
        return key in self.data["fav_champs"] or any(c.startswith(key + "|") for c in self.data["fav_combos"])

    def set_fav_roles(self, key, roles_all, selected):
        self.data["fav_champs"] = [k for k in self.data["fav_champs"] if k != key]
        self.data["fav_combos"] = [c for c in self.data["fav_combos"] if not c.startswith(key + "|")]
        selected = set(selected)
        if selected and selected >= set(roles_all):
            self.data["fav_champs"].append(key)
        elif selected:
            self.data["fav_combos"].extend("%s|%s" % (key, r) for r in roles_all if r in selected)
        self.save()

    def toggle_global(self, key, roles_all):
        if key in self.data["fav_champs"]:
            self.set_fav_roles(key, roles_all, [])
            return False
        self.set_fav_roles(key, roles_all, roles_all)
        return True

    def toggle_combo(self, key, role, roles_all):
        cur = self.fav_roles_of(key, roles_all)
        cur ^= {role}
        self.set_fav_roles(key, roles_all, cur)
        return role in cur

    def fav_champ_count(self):
        return len(set(self.data["fav_champs"]) | {c.split("|")[0] for c in self.data["fav_combos"]})

    def toggle_role(self, role):
        roles = self.data["fav_roles"]
        if role in roles:
            roles.remove(role)
        else:
            roles.append(role)
        self.save()
        return role in roles


# ----------------------------------------------------------------------------
# Data (stats, guides, team comps, glossary)
# ----------------------------------------------------------------------------

def clean_skills(c):
    """Published skill orders made playable (Zeri, evolving champions: see live.clean_order)."""
    import live
    key = c.get("key")
    sk = c.get("skills") or {}
    if sk.get("order15"):
        o = live.clean_order(key, sk["order15"])
        # impossible ranks removed (evolutions): the end of the order follows the skill priority
        ranks = {x: o.count(x) for x in "QWER"}
        while len(o) < 15:
            x = next((x for x in (sk.get("prio") or "") + "QWE" if x in "QWE" and live.can_level(x, ranks, len(o) + 1, key)), None)
            if not x:
                break
            o += x
            ranks[x] += 1
        sk["order15"] = o
    first = live.AUTO_FIRST.get(key)
    for p in sk.get("paths") or []:
        if first and p.get("path") and p["path"][0] != first:
            p["path"] = (first + p["path"])[:len(p["path"])]
    for b in c.get("builds") or []:
        bs = b.get("skills") or {}
        if bs.get("path"):
            bs["path"] = live.clean_order(key, bs["path"])


class Data:
    def _english(self):
        """English UI: Riot's official names (champions, spells, items, runes), English guides and glossary.
        A guide not translated yet stays in French."""
        en = read_json(os.path.join(DATA, "en", "names.json"), {}) or {}
        names = en.get("champions") or {}
        for c in self.combos.values():
            c["name"] = names.get(c["key"]) or c.get("name_en") or c["name"]
        for c in (self.all_champs.get("by_id") or {}).values():
            c["name"] = names.get(c["key"], c["name"])
        for k, kit in (en.get("kits") or {}).items():
            for slot, sp in kit.items():
                if k in self.kits and slot in self.kits[k]:
                    self.kits[k][slot] = dict(self.kits[k][slot], name=sp["name"], desc=sp["desc"])
        self.item_names.update(en.get("items") or {})
        for part in ("trees", "runes", "sums"):
            for i, name in (en.get(part) or {}).items():
                if i in (self.runes.get(part) or {}):
                    self.runes[part][i]["name"] = name
        self.runes["shards"] = {i: T(v) for i, v in (self.runes.get("shards") or {}).items()}
        for fn in sorted(glob.glob(os.path.join(DATA, "guides_en", "*.json"))):
            try:
                with open(fn, encoding="utf-8") as f:
                    self.guides.update(json.load(f))
            except (OSError, ValueError) as e:
                self.guide_errors.append("%s : %s" % (os.path.basename(fn), e))
        self.glossary = read_json(os.path.join(DATA, "glossary_en.json"), None) or self.glossary

    def __init__(self):
        st = read_json(os.path.join(DATA, "stats.json"))
        if not st:
            raise RuntimeError("data/stats.json is missing or unreadable")
        self.meta = st["meta"]
        self.kits = st["kits"]
        self.combos = st["combos"]
        for c in self.combos.values():
            clean_skills(c)
        self.chaos_combos = {}   # chaos mode: a champion in a role without a guide (chaos.py), built on demand

        self.guides = {}
        self.guide_errors = []
        for fn in sorted(glob.glob(os.path.join(DATA, "guides", "*.json"))):
            try:
                with open(fn, encoding="utf-8") as f:
                    self.guides.update(json.load(f))
            except (OSError, ValueError) as e:
                self.guide_errors.append("%s : %s" % (os.path.basename(fn), e))
        # team comp data (overlay: stats against each opponent, champion profiles)
        self.compo = read_json(os.path.join(DATA, "compo.json"), {}) or {}
        self.glossary = read_json(os.path.join(DATA, "glossary.json"), {}) or {}
        # every champion in the game, to recognize opponents without a guide
        self.all_champs = read_json(os.path.join(DATA, "champions.json"), {}) or {}
        # items (total price, name) and runes (trees): overlay and champ select import
        items = (read_json(os.path.join(DATA, "items.json"), {}) or {}).get("items") or {}
        self.item_prices = {k: v.get("gold", 0) for k, v in items.items()}
        self.item_names = {k: v.get("name", "") for k, v in items.items()}
        self.item_cats = {k: v.get("cat") or [] for k, v in items.items()}
        self.runes = read_json(os.path.join(DATA, "runes.json"), {}) or {}
        if lang() == "en":
            self._english()

        self.by_role = {r: [] for r in ROLES}
        self.champs = {}
        self.cid_to_key = {}
        for cid, c in (self.all_champs.get("by_id") or {}).items():
            self.cid_to_key[int(cid)] = c["key"]
        for key, c in self.combos.items():
            self.by_role[c["role"]].append(key)
            self.cid_to_key[c["cid"]] = c["key"]
            ch = self.champs.setdefault(c["key"], {
                "key": c["key"], "cid": c["cid"], "name": c["name"], "name_en": c.get("name_en", c["name"]),
                "roles": [],
            })
            ch["roles"].append(c["role"])
        for ch in self.champs.values():
            ch["roles"].sort(key=lambda r: ROLES.index(r))
        for r in ROLES:
            self.by_role[r].sort(key=lambda k: norm(self.combos[k]["name"]))
        self.names = sorted((c["name"] for c in self.champs.values()), key=norm)
        self.sorted_champs = sorted(self.champs.values(), key=lambda c: norm(c["name"]))
        self._name_index = {}
        for c in (self.all_champs.get("by_id") or {}).values():
            self._name_index[norm(c["name"])] = c["key"]
            self._name_index[norm(c["key"])] = c["key"]

    def combo_key(self, champ_key, role):
        return "%s|%s" % (champ_key, role)

    # --- builds (Build tab, champ select import, overlay Items module) ---
    def order_perks(self, perks, pri, sec):
        """Runes in client order: keystone and 3 runes of the primary tree, then the 2 of the secondary."""
        trees = (self.runes or {}).get("trees") or {}

        def slot(tree, r):
            for i, sl in enumerate((trees.get(str(tree)) or {}).get("slots") or []):
                if r in sl:
                    return i
            return None
        p = sorted((r for r in perks if slot(pri, r) is not None), key=lambda r: slot(pri, r))
        s2 = sorted((r for r in perks if r not in p and slot(sec, r) is not None), key=lambda r: slot(sec, r))
        return p + s2 if len(p) == 4 and len(s2) == 2 else list(perks)

    def combo_any(self, key):
        """Guide, or chaos combo already built."""
        return self.combos.get(key) or self.chaos_combos.get(key)

    def is_chaos_key(self, key):
        champ, _, role = (key or "").partition("|")
        return key not in self.combos and champ in self.champs and role in ROLES

    def builds(self, combo_key):
        """Builds of a guide: u.gg's (recommended + variants), otherwise the most played one on lolalytics."""
        c = self.combo_any(combo_key) or {}
        out = []
        for b in c.get("builds") or []:
            b = dict(b)
            r = dict(b["runes"])
            r["perks"] = self.order_perks(r["perks"], r["pri"], r["sec"])
            b["runes"] = r
            b["src"] = "u.gg"
            out.append(b)
        if out:
            # starting items: u.gg repeats an item bought twice (potions); otherwise lolalytics quantities
            counts = {i: n for i, n in ((c.get("items") or {}).get("start") or [])}
            for b in out:
                st = dict(b["start"])
                uniq, n = [], {}
                for i in st["ids"]:
                    if i not in n:
                        uniq.append(i)
                    n[i] = n.get(i, 0) + 1
                st["ids"] = uniq
                st["counts"] = [n[i] if n[i] > 1 else counts.get(i, 1) for i in uniq]
                b["start"] = st
            return out
        it, ru = c.get("items") or {}, c.get("runes") or {}
        if not it or not ru:
            return []
        tree_of = {int(k): v["tree"] for k, v in ((self.runes or {}).get("runes") or {}).items()}
        pri, sec = tree_of.get(ru["pri"][0]), tree_of.get(ru["sec"][0])
        sk = c.get("skills") or {}
        return [{"id": "reco", "label": "Le plus joué", "src": "lolalytics", "games": None, "wr": None,
                 "runes": {"pri": pri, "sec": sec, "perks": list(ru["pri"]) + list(ru["sec"]), "shards": list(ru["mod"])},
                 "sums": {"ids": list(c.get("sums") or [])},
                 "start": {"ids": [x[0] for x in it.get("start") or []], "counts": [x[1] for x in it.get("start") or []]},
                 "core": {"ids": list(it.get("core") or [])},
                 "opts": [[{"id": i} for i in col] for col in it.get("opts") or []],
                 "skills": {"path": sk.get("order15", ""), "prio": sk.get("prio", "")}}]

    def build_for(self, combo_key, pick=None):
        bl = self.builds(combo_key)
        return next((b for b in bl if b["id"] == pick), bl[0] if bl else None)

    def champ_name(self, key):
        c = self.champs.get(key)
        if c:
            return c["name"]
        for x in (self.all_champs.get("by_id") or {}).values():
            if x["key"] == key:
                return x["name"]
        return key or "?"

    def find_champion(self, text):
        q = norm(text)
        if not q:
            return None
        champs = list(self.champs.values())
        for c in champs:
            if q in (norm(c["name"]), norm(c["key"]), norm(c["name_en"])):
                return c
        pref = [c for c in champs if norm(c["name"]).startswith(q) or norm(c["name_en"]).startswith(q)]
        if len(pref) == 1:
            return pref[0]
        sub = [c for c in champs if q in norm(c["name"]) or q in norm(c["name_en"])]
        if len(sub) == 1:
            return sub[0]
        return None

    def key_from_name(self, text):
        """Champion key (even without a guide) from its display name."""
        c = self.find_champion(text)
        if c:
            return c["key"]
        return self._name_index.get(norm(text))

    def missing_guides(self):
        problems = []
        for key in self.combos:
            g = self.guides.get(key)
            if g is None:
                problems.append("%s: missing guide" % key)
                continue
            role = key.split("|")[1]
            for field in GUIDE_FIELDS:
                name = "jungle_plan" if (field == "lane_plan" and role == "jgl") else field
                if not g.get(name):
                    problems.append("%s: field '%s' empty or missing" % (key, name))
        for key in self.guides:
            if key not in self.combos:
                problems.append("%s: guide without a matching combo" % key)
        return problems


# ----------------------------------------------------------------------------
# Verdicts from the current data
# ----------------------------------------------------------------------------

def matchup_verdict(delta):
    """Win rate gap to the champion's average -> (label, tone)."""
    if delta >= 3:
        return T("Très favorable"), "good2"
    if delta >= 1.5:
        return T("Favorable"), "good"
    if delta > -1.5:
        return T("Équilibré"), "even"
    if delta > -3:
        return T("Difficile"), "bad"
    return T("Très difficile"), "bad2"


def form_verdict(wr, ref):
    d = wr - ref
    if d >= 2:
        return T("Très bons résultats"), "good2"
    if d >= 0.75:
        return T("Bons résultats"), "good"
    if d > -0.75:
        return T("Dans la moyenne"), "even"
    if d > -2:
        return T("Résultats faibles"), "bad"
    return T("Résultats très faibles"), "bad2"


CHECK_LABEL = {"ok": "confirmé par u.gg", "neutral": "neutre sur u.gg", "contradiction": "u.gg dit l'inverse",
               "absent": "u.gg : trop peu de parties"}
_LABELS.append((CHECK_LABEL, dict(CHECK_LABEL)))


REASON_TEXT = {"champion_taken": "champion pris", "champion_banned": "champion banni",
               "rerolled": "relancé avant de jouer", "rerolled_offline": "relancé sans client LoL connecté",
               "not_rift": "partie hors Faille", "group_reroll": "relancé (groupe)"}


def reason_text(r):
    """Reason code stored in the history ("champion_banned", "autofill:top"...) -> UI text."""
    if (r or "").startswith("autofill:"):
        role = r.partition(":")[2]
        return T("autofill (%s)") % ROLE_LABEL.get(role, role)
    return T(REASON_TEXT.get(r, r or ""))


# ----------------------------------------------------------------------------
# History display (texts and tones, shared by the UI and notifications)
# ----------------------------------------------------------------------------

def lp_text(e, with_rank=True):
    lp = e.get("lp")
    if not lp:
        return T("LP en attente…") if e.get("lp_before") and e.get("status") == "played" else ""
    if lp.get("multi"):
        return T("LP non mesurés (plusieurs parties classées entre-temps)")
    if lp.get("placement"):
        left = lp.get("prov_left") or 0
        return T("placement") + ((T(" (%d restantes)") if left > 1 else T(" (%d restante)")) % left if left else "")
    if lp.get("timeout"):
        txt = T("non comptée par le client · 0 LP")
    elif lp.get("delta") is None:
        return ""
    else:
        d = lp["delta"]
        txt = "%s LP" % signed(d)
        if e.get("lp_protected"):
            txt += T(" (perte évitée)")
    if with_rank:
        txt += " → " + lol.rank_label(lp)
    return txt


def division_name(value, with_lp=False):
    value = int(round(value))
    if value >= len(lol.TIERS) * 400:
        return T("Maître+ · %d LP") % (value - len(lol.TIERS) * 400) if with_lp else T("Maître+")
    tier = lol.TIERS[max(0, value) // 400]
    div = lol.DIVISIONS[(max(0, value) % 400) // 100]
    name = "%s %s" % (T(lol.TIER_LABEL[tier]), div)
    return "%s · %d LP" % (name, max(0, value) % 100) if with_lp else name


def lp_points(entries, queue_type):
    pts = []
    for e in entries:
        lp = e.get("lp")
        before = e.get("lp_before")
        if not lp or not before or lp.get("queue") != queue_type or lp.get("multi"):
            continue
        if lol.is_placement(before) or lol.is_placement(lp):
            continue
        if not pts:
            pts.append({"v": lol.abs_lp(before), "kind": "start", "label": division_name(lol.abs_lp(before), True),
                        "date": ""})
        kind = "protected" if e.get("lp_protected") else "win" if lp.get("result") == "win" else \
            "loss" if lp.get("result") == "loss" else "neutral"
        v = lol.abs_lp(lp)
        pts.append({"v": v, "kind": kind, "label": division_name(v, True), "date": e.get("date", ""),
                    "delta": lp.get("delta"), "champ": e.get("played") or e.get("key")})
    return pts


def entry_display(e, data):
    st = e.get("status")
    played = e.get("played")
    other = played and played != e.get("key")
    detail = ""
    if st == "played":
        win = bool(e.get("win"))
        result, tone, glyph = (T("Victoire"), "win", "✔") if win else (T("Défaite"), "loss", "✘")
        parts = []
        if other:
            parts.append(T("joué %s à la place") % data.champ_name(played))
            tone = "other"
        if not win and e.get("lp_protected"):
            result, tone, glyph = T("Défaite sans perte"), "shield", "⊘"
        lp = lp_text(e)
        if lp:
            parts.append(lp)
        detail = " · ".join(parts)
    elif st == "remake":
        result, tone, glyph = T("Remake"), "muted", "≈"
    elif st == "cancelled":
        result, tone, glyph = T("Annulé"), "cancel", "↺"
        detail = reason_text(e.get("reason", ""))
    elif st == "to_check":
        result, tone, glyph = T("À vérifier"), "muted", "?"
        detail = T("vérifié à la prochaine connexion à LoL")
    elif st == "in_game":
        result, tone, glyph = T("En partie"), "live", "▶"
        if other:
            detail = T("joue %s") % data.champ_name(played)
    else:
        result, tone, glyph = T("En attente"), "pending", "…"
    return {"result": result, "tone": tone, "glyph": glyph, "detail": detail}


# ----------------------------------------------------------------------------
# Core
# ----------------------------------------------------------------------------

class NullUI:
    """No UI (tests, dev mode): no window to drive."""

    def show(self):
        pass

    def hide(self):
        pass

    def visible(self):
        return True

    def quit(self):
        pass

    def hide_for_overlay(self):
        pass

    def choose_folder(self, title):
        return None

    frameless = False

    def window_action(self, action, edge=None):
        return {"ok": False}


class Core:
    def __init__(self, use_lol=True):
        seed_data_dir()
        migrate_legacy_paths()
        self.lock = threading.RLock()
        self.profile = Profile(PROFILE_PATH)
        set_lang(self.profile.get("lang") or system_lang())   # before the data: names and guides in that language
        self.data = Data()
        self.history = lol.RollHistory(HISTORY_PATH, self.data.cid_to_key)
        self.events = queue.Queue()      # League client events
        self.actions = queue.Queue()     # tray icon / second launch actions
        self.overlay_cmds = queue.Queue()   # overlay commands (preview, placement)
        self.ui = NullUI()
        self.tray = None
        self.updater = None
        self._clients = []
        self._stop = threading.Event()
        self.watcher = lol.LolWatcher(self.events, BASE, self.profile["lol_dir"]) if use_lol else None
        self.lol_state = {"connected": False}
        self.ranked = {}
        self._lp_check_at = 0.0
        self._game_id = None
        self._cs_champ = 0
        self._cs_role = None
        self._cs_shown = None
        self._requested = set()
        self.rolls = {}
        self.drawn = set()
        self.pending_reason = None
        self.current = None
        self.group = None               # last group roll (to reroll one player)
        self.spinning_until = 0.0
        self.overlay_info = None
        self.live = None              # current game snapshot (live.LivePoller), for the overlay
        self.poller = None
        self.scout = None             # live game: rank and form of the players in the game (scout.py)
        self._live_sig = None
        self._imported = None         # champ select already handled by the import (runes, spells, item set)
        self.import_state = None
        self.status = {"text": "", "tone": "muted"}
        self.update_status = {"state": "idle"}
        try:
            if any(e.get("status") in ("played", "remake") and e.get("queue") and e["queue"] not in lol.SR_QUEUES
                   and not e.get("free") for e in self.history.entries):
                import shutil
                os.makedirs(BACKUP_DIR, exist_ok=True)
                shutil.copy(HISTORY_PATH, os.path.join(BACKUP_DIR, "history_before_rift_fix.json"))
                self.history.fix_off_rift()
        except Exception:
            pass
        # game fonts and gold coin for the overlay, taken from the local LoL install (once, a fraction of a second)
        self.lol_assets = {}
        if not LITE and sys.platform == "win32":
            try:
                self.lol_assets = lolassets.ensure(lol.LolClient(BASE, self.profile["lol_dir"]).candidate_dirs(), DATA)
            except Exception:
                pass

    # --- lifecycle ----------------------------------------------------------------
    def start(self):
        if self.watcher:
            self.watcher.start()
            from scout import Scout
            self.scout = Scout(self.watcher.client, self._live_changed)
            self.scout.start()
        threading.Thread(target=self._loop, name="core", daemon=True).start()

    def stop(self):
        self._stop.set()
        if self.watcher:
            self.watcher.stop()
        if self.poller:
            self.poller.stop()
        if self.scout:
            self.scout.stop()
        if self.updater:
            self.updater.stop()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._process_actions()
                with self.lock:
                    self._process_events()
            except Exception:
                import traceback
                log_error(traceback.format_exc())
            self._stop.wait(0.25)

    # --- UI broadcast (Server-Sent Events) -------------------------------------------
    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self.lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self._clients:
                self._clients.remove(q)

    def emit(self, kind, payload=None):
        msg = {"type": kind, "data": payload}
        for q in list(self._clients):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def set_status(self, text, tone="muted", toast=True):
        self.status = {"text": text, "tone": tone}
        self.emit("status", dict(self.status, toast=toast))

    def notify(self, text):
        """Windows notification, only while the window is hidden in the tray."""
        try:
            if self.tray and self.tray.running and not self.ui.visible():
                self.tray.notify(text)
        except Exception:
            pass

    # --- tray icon / second instance actions ---------------------------------------
    def _process_actions(self):
        while True:
            try:
                action = self.actions.get_nowait()
            except queue.Empty:
                return
            if action == "show":
                self.ui.show()
            elif action == "quit":
                self.ui.quit()
            elif action.startswith("overlay:"):
                self.api_set_pref("overlay_mode", action.split(":", 1)[1])
            elif action == "pause":
                self.api_set_pref("roulette_paused", not self.profile["roulette_paused"])

    # --- views for the UI ------------------------------------------------------------
    def api_boot(self):
        with self.lock:
            d = self.data
            champs = [{"key": c["key"], "cid": c["cid"], "name": c["name"], "name_en": c["name_en"],
                       "roles": [{"role": r, "share": d.combos[d.combo_key(c["key"], r)]["share"]} for r in c["roles"]]}
                      for c in d.sorted_champs]
            favs = [k for k in d.champs if self.profile.is_any_fav(k)]
            gen = d.meta.get("generated")
            if self.profile.get("seen_update") is None:
                self.profile["seen_update"] = gen   # first launch: nothing "new" to announce
            notice = {"patch": d.meta.get("patch"), "generated": gen} \
                if gen and gen != self.profile.get("seen_update") else None
            return {
                "update_notice": notice,
                "lang": lang(),
                "lite": LITE,
                "platform": "mac" if MAC else "windows",
                "download": bool(DOWNLOAD_URL),
                "window": {"frameless": bool(getattr(self.ui, "frameless", False))},
                "app": {"name": APP_NAME, "version": APP_VERSION},
                "meta": {"patch": d.meta.get("patch"), "generated": d.meta.get("generated"),
                         "sources": d.meta.get("sources") or {}, "combos": len(d.combos),
                         "guides": sum(1 for k in d.combos if k in d.guides)},
                "roles": [{"id": r, "label": ROLE_LABEL[r], "long": ROLE_LONG[r], "icon": ROLE_ICON[r]} for r in ROLES],
                "champions": champs,
                "profile": self._profile_view(),
                "hero": random.choice(favs or list(d.champs)),
                "glossary": d.glossary,
                "lol": self._lol_view(),
                "cs": self._cs_view(),
                "recent": self._recent_view(),
                "overlay_modes": [{"id": v, "label": l} for v, l in OVERLAY_MODES],
                "overlay_modules": [dict({k: m[k] for k in ("id", "label", "desc", "key", "mode")}, on=m.get("on", True))
                                    for m in OVERLAY_MODULES],
                "update": self.update_status,
                "autostart": self._autostart_state(),
                "status": self.status,
                "current": self.current or (self._roll_view() or {}).get("combo"),
                "roll": self._roll_view(),
            }

    def _profile_view(self):
        p = self.profile
        keys = ("fav_champs", "fav_combos", "fav_roles", "only_fav_roles", "only_fav_champs", "no_repeat",
                "overlay_mode", "overlay_scale", "overlay_opacity", "auto_update", "glossary_hints", "lol_dir", "ambient",
                "import_runes", "import_spells", "import_items", "import_replace", "roulette_paused")
        out = {k: p[k] for k in keys}
        out["overlay_pos"] = p["overlay_pos"]
        out["overlay_modules"] = {m["id"]: p.module_cfg(m["id"]) for m in OVERLAY_MODULES}
        out["fav_count"] = p.fav_champ_count()
        return out

    def _autostart_state(self):
        try:
            import winreg   # noqa: F401
        except ImportError:
            return {"available": False, "on": False}
        from system import autostart_command, autostart_enabled
        return {"available": bool(autostart_command()), "on": autostart_enabled()}

    def api_combo(self, key):
        if key not in self.data.combos and not self._chaos_combo(key):
            return {"error": "Unknown combo: %s" % key}
        with self.lock:
            self.current = key
            return self._combo_view(key) if key in self.data.combos else self._chaos_view(key)

    def _chaos_combo(self, key, fetch=True):
        """Chaos combo (Swain|jgl...): from the cache, otherwise built (real data downloaded if fetch)."""
        import chaos
        d = self.data
        if key in d.combos:
            return d.combos[key]
        if key in d.chaos_combos and (d.chaos_combos[key]["chaos"]["real"] or not fetch or d.chaos_combos[key].get("tried")):
            return d.chaos_combos[key]
        if not d.is_chaos_key(key):
            return None
        champ, _, role = key.partition("|")
        pc = chaos.cached(d, champ, role)
        if pc is None:
            pc = chaos.fetch(d, champ, role) if fetch else chaos.build(d, champ, role)
            pc["tried"] = fetch
        clean_skills(pc)
        d.chaos_combos[key] = pc
        return pc

    def _matchups_view(self, m, guide=None):
        d = self.data
        base = m["base"]
        by_freq = sorted(m.get("all") or [], key=lambda e: -e["n"])
        freq_rank = {e["cid"]: i + 1 for i, e in enumerate(by_freq)}
        ent = lambda e: self._entry_view(e, base, freq_rank)
        all_entries = {e["key"]: ent(e) for e in m.get("all") or [] if e.get("key")}
        notes = []
        for opp, text in ((guide or {}).get("matchup_notes") or {}).items():
            okey = d.key_from_name(opp)
            notes.append({"name": opp, "key": okey, "text": text, "live": all_entries.get(okey)})
        view = {"base": base, "ugg_base": m.get("ugg_base"), "tier_used": m.get("tier_used"),
                "min_n": m.get("min_n"), "n_opps": m.get("n_opps"),
                "good": [ent(e) for e in m.get("good") or []], "bad": [ent(e) for e in m.get("bad") or []],
                "good_clear": m.get("good_clear", True), "bad_clear": m.get("bad_clear", True),
                "frequent": [ent(e) for e in m.get("frequent") or []],
                "all": [all_entries[e["key"]] for e in by_freq if e.get("key") in all_entries]}
        return view, notes

    def _chaos_view(self, key):
        """Chaos guide: texts and skills of the closest guide, real build and matchups when there are some."""
        d = self.data
        pc = d.chaos_combos[key]
        cx = pc["chaos"]
        view = self._combo_view(cx["from"])
        month = pc.get("month")
        fv, ft = form_verdict(month["wr"], 50.0) if month else ("", "muted")
        mv = self._matchups_view(pc["matchups"])[0] if pc.get("matchups") else None
        view.update({
            "key": key, "role": pc["role"], "role_label": ROLE_LABEL[pc["role"]], "role_long": ROLE_LONG[pc["role"]],
            "share": pc.get("share") or 0, "month": month, "patch": None, "ugg": None,
            "form": {"label": fv, "tone": ft, "ref": 50.0}, "skills": pc.get("skills") or {},
            "builds": self._builds_view(key), "build_pick": (self.profile.get("build_pick") or {}).get(key, "reco"),
            "matchups": mv, "notes": [], "duo": None, "fav": False,
            "chaos": {"from": cx["from"], "real": cx["real"], "games": cx["games"],
                      "from_label": "%s %s" % (d.combos[cx["from"]]["name"], ROLE_LABEL[d.combos[cx["from"]]["role"]])
                      if cx["from"] in d.combos else cx["from_label"],
                      "share": cx["share"], "level": T(cx["level"]), "tone": cx["tone"], "rule": T(cx.get("rule") or "") or None},
        })
        return view

    def _entry_view(self, e, base, freq_rank):
        x = {k: e.get(k) for k in ("cid", "key", "name", "wr", "n", "ugg_wr", "ugg_n", "gd15", "check", "rel")}
        if e.get("key"):
            x["name"] = self.data.champ_name(e["key"])
        x["delta"] = round(e["wr"] - base, 2)
        x["verdict"], x["tone"] = matchup_verdict(x["delta"])
        x["check_label"] = CHECK_LABEL.get(e.get("check"), "")
        x["freq_rank"] = freq_rank.get(e.get("cid"))
        return x

    def _combo_view(self, key):
        d = self.data
        c = d.combos[key]
        g = d.guides.get(key)
        ch = d.champs[c["key"]]
        m = c["matchups"]
        base = m["base"]
        by_freq = sorted(m.get("all") or [], key=lambda e: -e["n"])
        freq_rank = {e["cid"]: i + 1 for i, e in enumerate(by_freq)}
        ent = lambda e: self._entry_view(e, base, freq_rank)
        all_entries = {e["key"]: ent(e) for e in m.get("all") or [] if e.get("key")}
        notes = []
        for opp, text in ((g or {}).get("matchup_notes") or {}).items():
            okey = d.key_from_name(opp)
            notes.append({"name": opp, "key": okey, "text": text, "live": all_entries.get(okey)})
        month = c["month"]
        ref = 50.0
        fv, ft = form_verdict(month["wr"], ref)
        view = {
            "key": key, "champ": {"key": c["key"], "cid": c["cid"], "name": c["name"], "name_en": c.get("name_en")},
            "role": c["role"], "role_label": ROLE_LABEL[c["role"]], "role_long": ROLE_LONG[c["role"]],
            "share": c["share"],
            "roles": [{"role": r, "label": ROLE_LABEL[r], "share": d.combos[d.combo_key(c["key"], r)]["share"]}
                      for r in ch["roles"]],
            "month": month, "patch": c.get("patch"), "ugg": c.get("ugg"),
            "form": {"label": fv, "tone": ft, "ref": ref},
            "skills": c.get("skills") or {},
            "evolve": c.get("evolve"),
            "kit": d.kits.get(c["key"], {}),
            "matchups": {
                "base": base, "ugg_base": m.get("ugg_base"), "tier_used": m.get("tier_used"),
                "min_n": m.get("min_n"), "n_opps": m.get("n_opps"),
                "good": [ent(e) for e in m.get("good") or []], "bad": [ent(e) for e in m.get("bad") or []],
                "good_clear": m.get("good_clear", True), "bad_clear": m.get("bad_clear", True),
                "frequent": [ent(e) for e in m.get("frequent") or []],
                "all": [all_entries[e["key"]] for e in by_freq if e.get("key") in all_entries],
            },
            "guide": g,
            "builds": self._builds_view(key),
            "build_pick": (self.profile.get("build_pick") or {}).get(key, "reco"),
            "notes": notes,
            "fav": self.profile.is_combo_fav(c["key"], c["role"]),
            "fav_global": c["key"] in self.profile["fav_champs"],
            "patch_name": d.meta.get("patch"),
            "duo": self._duo_view(c),
        }
        return view

    def _duo_pair(self, combo, partner_key):
        """Bot lane pair in game: duo win rate (lolalytics) and delta to the champion's average."""
        d = self.data
        du = (d.combos.get(combo) or {}).get("duo")
        if not du or not partner_key:
            return None
        hit = next((x for x in du.get("all") or [] if x[1] == partner_key), None)
        out = {"key": partner_key, "name": d.champ_name(partner_key), "partner_label": ROLE_LABEL[du["partner"]],
               "me_key": d.combos[combo]["key"], "me_name": d.combos[combo]["name"]}
        if not hit:
            out.update({"wr": None, "text": T("Duo %s + %s : trop peu de parties ensemble pour le chiffrer.") % (
                out["me_name"], out["name"]), "tone": "muted"})
            return out
        delta = round(hit[2] - du["base"], 1)
        best = [e.get("key") for e in du.get("good") or []]
        out.update({"wr": hit[2], "n": hit[3], "delta": delta, "best": partner_key in best[:3],
                    "tone": "good" if delta >= 1.5 else "bad" if delta <= -1.5 else "muted"})
        out["text"] = T("Duo %s + %s : %s de victoires sur %s parties (%s%s vs la moyenne de %s)%s") % (
            out["me_name"], out["name"], fmt_pct(hit[2], 1), fmt_int(hit[3]),
            "+" if delta >= 0 else "−", fmt_num(abs(delta), 1), out["me_name"],
            T(" · un des meilleurs duos") if out["best"] else "")
        return out

    def _duo_view(self, c):
        """Bot lane: best partners (supports of an ADC, ADCs of a support), ones to avoid, most frequent."""
        du = c.get("duo")
        if not du:
            return None
        d = self.data
        base = du["base"]

        def ent(e):
            combo = d.combo_key(e.get("key"), du["partner"]) if e.get("key") else None
            x = {k: e.get(k) for k in ("cid", "key", "name", "wr", "n", "pr", "syn", "rel")}
            if e.get("key"):
                x["name"] = d.champ_name(e["key"])
            x["delta"] = round(e["wr"] - base, 2)
            x["combo"] = combo if combo in d.combos else None
            return x
        return {"partner": du["partner"], "partner_label": ROLE_LABEL[du["partner"]], "base": base,
                "n_partners": du.get("n_partners"), "min_n": du.get("min_n"), "total": du.get("total"),
                "good": [ent(e) for e in du.get("good") or []], "bad": [ent(e) for e in du.get("bad") or []],
                "frequent": [ent(e) for e in du.get("frequent") or []]}

    def _builds_view(self, key):
        d = self.data
        rn = d.runes or {}
        trees, names = rn.get("trees") or {}, rn.get("runes") or {}
        shard_names, rows = rn.get("shards") or {}, rn.get("shard_rows") or []
        sums = rn.get("sums") or {}

        def item(i, extra=None):
            out = {"id": i, "name": d.item_names.get(str(i), ""), "gold": d.item_prices.get(str(i))}
            out.update(extra or {})
            return out
        out = []
        for b in d.builds(key):
            r = b["runes"]
            chosen = set(r["perks"])
            tree = lambda t, first: [[{"id": x, "name": names.get(str(x), {}).get("name", ""), "on": x in chosen}
                                      for x in sl] for sl in (trees.get(str(t)) or {}).get("slots", [])[first:]]
            sh = list(r.get("shards") or [])
            v = {"id": b["id"], "label": build_label(b["label"]), "games": b.get("games"), "wr": b.get("wr"), "src": b.get("src"),
                 "patch": b.get("patch"),
                 "runes": {"pri": {"id": r["pri"], "name": (trees.get(str(r["pri"])) or {}).get("name", "")},
                           "sec": {"id": r["sec"], "name": (trees.get(str(r["sec"])) or {}).get("name", "")},
                           "games": r.get("games"), "wr": r.get("wr"),
                           "keystone": r["perks"][0] if r["perks"] else None,
                           "tree_pri": tree(r["pri"], 0), "tree_sec": tree(r["sec"], 1),
                           "shards": [[{"id": x, "name": shard_names.get(str(x), ""), "on": i < len(sh) and sh[i] == x}
                                       for x in row] for i, row in enumerate(rows)]},
                 "sums": dict({k: v2 for k, v2 in (b.get("sums") or {}).items() if k != "ids"},
                              list=[{"id": x, "name": (sums.get(str(x)) or {}).get("name", "")} for x in (b.get("sums") or {}).get("ids", [])]),
                 "start": dict({k: v2 for k, v2 in b["start"].items() if k not in ("ids", "counts")},
                               list=[item(i, {"count": n}) for i, n in zip(b["start"]["ids"], b["start"].get("counts") or [1] * 9)]),
                 "core": dict({k: v2 for k, v2 in b["core"].items() if k != "ids"}, list=[item(i) for i in b["core"]["ids"]]),
                 "opts": [[item(o["id"], {"wr": o.get("wr"), "games": o.get("games")}) for o in col] for col in b.get("opts") or []],
                 "skills": b.get("skills") or {}}
            out.append(v)
        return out

    def api_build_pick(self, key, variant):
        """Build variant picked in the guide: the one imported in champ select."""
        with self.lock:
            picks = dict(self.profile.get("build_pick") or {})
            if variant == "reco":
                picks.pop(key, None)
            else:
                picks[key] = variant
            self.profile["build_pick"] = picks
            # in champ select on the locked champion's guide: re-import the variant right away
            st = self.import_state
            if st and st.get("combo") == key and self.watcher:
                opts = {k: self.profile[k] for k in ("import_runes", "import_spells", "import_items", "import_replace")}
                enemies = [(self.data.cid_to_key[c], None) for c in (st.get("enemies") or []) if c in self.data.cid_to_key]
                threading.Thread(target=self._do_import, args=(key, st["spells"], st["ident"], opts, None, enemies or None),
                                 name="import", daemon=True).start()
                return {"ok": True, "build_pick": variant, "reimport": True}
            return {"ok": True, "build_pick": variant}

    def _roll_view(self):
        """Current roll (pending or in game), for the Guides page and the home screen."""
        e = self.history.last_roll()
        if not e or e.get("status") not in ("pending", "in_game"):
            return None
        combo = self.data.combo_key(e.get("key"), e.get("role"))
        if combo not in self.data.combos and not self.data.is_chaos_key(combo):
            return None
        return {"combo": combo, "key": e.get("key"), "name": self.data.champ_name(e.get("key")),
                "role": e.get("role"), "role_label": ROLE_LABEL.get(e.get("role"), ""), "status": e.get("status"),
                "mode": MODE_LABEL.get(e.get("mode"), "")}

    def api_kits(self):
        """Skills of every champion (guide tooltips): {key: {name, kit}}."""
        with self.lock:
            d = self.data
            return {"kits": {k: {"name": d.champ_name(k), "kit": kit} for k, kit in d.kits.items()}}

    def _recent_view(self, n=30):
        items = []
        for e in list(reversed(self.history.rolls()))[:n]:
            disp = entry_display(e, self.data)
            sub = "%s · %s" % (ROLE_LABEL.get(e.get("role"), ""), disp["result"])
            if e.get("kda") and e.get("status") == "played":
                sub += " · %s" % "/".join(str(x) for x in e["kda"])
            delta = (e.get("lp") or {}).get("delta")
            if isinstance(delta, int) and delta:
                sub += " · %s" % lp_text(e, with_rank=False)
            items.append({"id": e.get("id"), "key": e.get("key"), "name": self.data.champ_name(e.get("key")),
                          "role": e.get("role"), "sub": sub, "tone": disp["tone"], "glyph": disp["glyph"],
                          "combo": self.data.combo_key(e.get("key"), e.get("role")), "date": e.get("date", "")})
        return items

    # --- rolls ------------------------------------------------------------------------
    def _champ_pool(self, role):
        keys = self.data.by_role[role]
        if self.profile["only_fav_champs"]:
            keys = [k for k in keys if self.profile.is_combo_fav(self.data.combos[k]["key"], role)]
        return keys

    def _pool(self, keys, notes):
        if not self.profile["no_repeat"]:
            return list(keys)
        left = [k for k in keys if k not in self.drawn]
        if not left:
            for k in keys:
                self.drawn.discard(k)
            notes.append(T("Tous les champions de ce tirage sont sortis : on remet tout en jeu."))
            left = list(keys)
        return left

    def _role_step(self, roles):
        winner = random.choice(roles)
        seq = [random.choice(roles) for _ in range(34)]
        idx = 28
        seq[idx] = winner
        return winner, {"type": "role", "seq": seq, "index": idx, "pool": len(roles)}

    def _champ_step(self, keys):
        winner = random.choice(keys)
        n = 60 if len(keys) > 1 else 12
        seq = [random.choice(keys) for _ in range(n)]
        idx = n - 7
        seq[idx] = winner
        items = [{"combo": k, "key": self.data.combos[k]["key"], "name": self.data.combos[k]["name"]} for k in seq]
        return winner, {"type": "champ", "seq": items, "index": idx, "pool": len(keys),
                        "role": self.data.combos[winner]["role"]}

    def _chaos_roll(self, reason=None, champ=""):
        """Chaos mode: a random role, then any champion (with or without a guide in that role).
        With a picked champion: that champion in one of the five roles at random."""
        d = self.data
        role, rstep = self._role_step(ROLES)
        ch = d.find_champion(champ) if (champ or "").strip() else None
        keys = [ch["key"]] if ch else list(d.champs)
        winner = random.choice(keys)
        seq = [random.choice(keys) for _ in range(60)]
        seq[53] = winner
        cstep = {"type": "champ", "seq": [{"combo": d.combo_key(k, role), "key": k, "name": d.champ_name(k)} for k in seq],
                 "index": 53, "pool": len(keys), "role": role}
        result = d.combo_key(winner, role)
        rid = "%d%04d" % (time.time() * 1000, random.randint(0, 9999))
        self.rolls = {rid: {"result": result, "mode": "chaos", "favs": [], "reason": reason or self.pending_reason}}
        self.pending_reason = None
        self.spinning_until = time.time() + 12
        notes = [] if result in d.combos else [T("Chaos : %s n'a pas de fiche %s, sa fiche chaos est assemblée.") % (
            d.champ_name(winner), ROLE_LABEL[role])]
        return {"id": rid, "steps": [rstep, cstep], "result": result, "mode": "chaos", "notes": notes, "fav_filter": False}

    def api_roll(self, role="random", champ="", reason=None):
        """Prepares a roll: the UI animates the roulette, then confirms with roll_commit."""
        if role == "chaos":
            with self.lock:
                if (champ or "").strip() and not self.data.find_champion(champ):
                    return {"error": T("Champion introuvable : « %s ». Choisis-le dans la liste.") % champ.strip()}
                return self._chaos_roll(reason, champ)
        with self.lock:
            d = self.data
            text = (champ or "").strip()
            c = d.find_champion(text) if text else None
            if text and c is None:
                return {"error": T("Champion introuvable : « %s ». Choisis-le dans la liste.") % text}
            p = self.profile
            fav_roles = [r for r in ROLES if r in p["fav_roles"]]
            only_fav_roles = p["only_fav_roles"]
            favs = [n for n, on in (("roles", only_fav_roles), ("champions", p["only_fav_champs"])) if on]
            notes, steps = [], []

            if c:
                roles = c["roles"]
                if role in ROLES:
                    if LITE:   # no guide to show: something has to stay random
                        return {"error": T("Choisis un rôle OU un champion : la roulette tire l'autre au hasard.")}
                    if role not in roles:
                        return {"error": T("%s n'est pas assez joué %s pour avoir une fiche. Rôles disponibles : %s.") % (
                            c["name"], ROLE_LABEL[role], ", ".join(ROLE_LABEL[r] for r in roles))}
                    key = d.combo_key(c["key"], role)
                    self.set_status(T("Fiche : %s %s (consultation, pas un tirage)") % (c["name"], ROLE_LABEL[role]),
                                    "teal", toast=False)
                    return {"direct": True, "result": key, "combo": self.api_combo(key)}
                mode = "role"
                cand = roles
                if only_fav_roles:
                    cand = [r for r in roles if r in fav_roles]
                    if not cand:
                        cand = roles
                        notes.append(T("Aucun rôle de %s n'est dans tes favoris : tous ses rôles sont en jeu.") % c["name"])
                if len(cand) == 1:
                    notes.append(T("%s : un seul rôle possible (%s).") % (c["name"], ROLE_LABEL[cand[0]]))
                    result, step = self._champ_step([d.combo_key(c["key"], cand[0])])
                    steps.append(step)
                else:
                    r, step = self._role_step(cand)
                    steps.append(step)
                    result = d.combo_key(c["key"], r)
            elif role in ROLES:
                mode = "champ"
                keys = self._champ_pool(role)
                if not keys:
                    return {"error": T("Aucun champion favori jouable en %s. Ajoute-en dans « Favoris » ou désactive "
                                       "« Champions favoris seulement ».") % ROLE_LABEL[role]}
                result, step = self._champ_step(self._pool(keys, notes))
                steps.append(step)
            else:
                mode = "both"
                roles = ROLES
                if only_fav_roles:
                    if fav_roles:
                        roles = fav_roles
                    else:
                        notes.append(T("Aucun rôle favori coché : tous les rôles sont en jeu."))
                roles = [r for r in roles if self._champ_pool(r)]
                if not roles:
                    return {"error": T("Aucun champion favori dans ces rôles. Ajoute des favoris ou désactive un filtre.")}
                if len(roles) == 1:
                    r = roles[0]
                else:
                    r, step = self._role_step(roles)
                    steps.append(step)
                result, step = self._champ_step(self._pool(self._champ_pool(r), notes))
                steps.append(step)

            rid = "%d%04d" % (time.time() * 1000, random.randint(0, 9999))
            self.rolls = {rid: {"result": result, "mode": mode, "favs": favs, "reason": reason or self.pending_reason}}
            self.pending_reason = None
            self.spinning_until = time.time() + 12
            return {"id": rid, "steps": steps, "result": result, "mode": mode, "notes": notes,
                    "fav_filter": bool(p["only_fav_champs"])}

    # --- group roulette ---------------------------------------------------------------
    def _role_step_to(self, roles, winner):
        seq = [random.choice(roles) for _ in range(30)]
        seq[24] = winner
        return {"type": "role", "seq": seq, "index": 24, "pool": len(roles)}

    def _champ_step_to(self, keys, winner):
        n = 48 if len(keys) > 1 else 10
        seq = [random.choice(keys) for _ in range(n)]
        idx = n - 6
        seq[idx] = winner
        d = self.data
        return {"type": "champ", "seq": [{"combo": k, "key": k.partition("|")[0], "name": d.champ_name(k.partition("|")[0])}
                                         for k in seq], "index": idx, "pool": len(keys)}

    def _group_player(self, i, p, role, combo, steps):
        c = self.data.combo_any(combo) or self._chaos_combo(combo, fetch=False)
        return {"i": i, "name": p["name"], "me": p["me"], "role": role, "role_label": ROLE_LABEL[role],
                "combo": combo, "key": c["key"], "champ": c["name"], "steps": steps,
                "random_role": p["role"] not in ROLES, "random_champ": not p.get("champ")}

    def api_group_roll(self, players, chaos=False):
        """Group roulette (2 to 5 players): each one gets a different role and champion. Everything is decided here
        at once, without duplicates; the UI only reveals the results, one strip at a time.
        players: [{"name", "me", "role": "random" or a role, "champ": "" or a name}]"""
        with self.lock:
            d = self.data
            ps = []
            for i, p in enumerate(players or []):
                name = str(p.get("name") or "").strip()[:32] or (T("Toi") if p.get("me") else T("Joueur %d") % (i + 1))
                ps.append({"name": name, "me": bool(p.get("me")), "role": p.get("role") if p.get("role") in ROLES else "random",
                           "champ": str(p.get("champ") or "").strip()})
            if not 2 <= len(ps) <= 5:
                return {"error": T("La roulette de groupe se joue de 2 à 5 joueurs.")}
            if sum(1 for p in ps if p["me"]) != 1:
                ps[0]["me"] = True
                for p in ps[1:]:
                    p["me"] = False
            fixed = [p["role"] for p in ps if p["role"] in ROLES]
            dup = next((r for r in fixed if fixed.count(r) > 1), None)
            if dup:
                return {"error": T("Deux joueurs ont le même poste (%s) : un seul par poste.") % ROLE_LABEL[dup]}
            chosen = {}
            for i, p in enumerate(ps):
                if p["champ"]:
                    ch = d.find_champion(p["champ"])
                    if not ch:
                        return {"error": T("%s : champion introuvable (« %s »).") % (p["name"], p["champ"])}
                    if p["role"] in ROLES and p["role"] not in ch["roles"] and not chaos:
                        return {"error": T("%s : %s n'a pas de fiche %s.") % (p["name"], ch["name"], ROLE_LABEL[p["role"]])}
                    chosen[i] = ch
            if len({c["key"] for c in chosen.values()}) < len(chosen):
                return {"error": T("Deux joueurs ont choisi le même champion.")}
            taken_roles, taken_champs = set(fixed), {c["key"] for c in chosen.values()}
            out = [None] * len(ps)
            # most constrained first: picked champion, then picked role, then fully random
            order = sorted(range(len(ps)), key=lambda i: (i not in chosen, ps[i]["role"] not in ROLES))
            for i in order:
                p = ps[i]
                steps = []
                if p["role"] in ROLES:
                    role = p["role"]
                else:
                    cand = [r for r in (chosen[i]["roles"] if i in chosen and not chaos else ROLES) if r not in taken_roles]
                    if not cand:
                        return {"error": T("%s : plus de poste libre pour %s.") % (p["name"], chosen[i]["name"] if i in chosen else T("lui"))}
                    role = random.choice(cand)
                    steps.append(self._role_step_to(cand, role))
                    taken_roles.add(role)
                every = [d.combo_key(k, role) for k in d.champs] if chaos else d.by_role[role]
                if i in chosen:   # picked champion: the strip still spins and stops on it
                    combo = d.combo_key(chosen[i]["key"], role)
                    steps.append(self._champ_step_to(every, combo))
                else:
                    pool = [k for k in every if k.partition("|")[0] not in taken_champs]
                    combo = random.choice(pool)
                    steps.append(self._champ_step_to(pool, combo))
                if combo not in d.combos:
                    self._chaos_combo(combo, fetch=False)
                taken_champs.add(combo.partition("|")[0])
                out[i] = self._group_player(i, p, role, combo, steps)
            gid = "g%d%04d" % (time.time() * 1000, random.randint(0, 9999))
            self.group = {"id": gid, "players": out, "inputs": ps, "committed": False, "chaos": bool(chaos)}
            self.spinning_until = time.time() + 20
            return {"id": gid, "players": out}

    def api_group_commit(self, id):
        """Strips stopped: saves the local player's roll with the group list."""
        with self.lock:
            g = self.group
            self.spinning_until = 0.0
            if not g or g["id"] != id:
                return {"error": T("Tirage de groupe expiré.")}
            if not g["committed"]:
                self._group_record(g)
                g["committed"] = True
            return {"ok": True, "players": g["players"]}

    def _group_record(self, g, reason=None):
        me = next((p for p in g["players"] if p["me"]), None)
        if not me:
            return
        members = [{"name": p["name"], "key": p["key"], "role": p["role"], "me": p["me"]} for p in g["players"]]
        self.history.add_roll(me["key"], me["role"], bool(self.lol_state.get("connected")), reason=reason, mode="group",
                              group=members)
        self.drawn.add(me["combo"])
        if self.profile["roulette_paused"]:
            self.profile["roulette_paused"] = False
            self.emit("profile", self._profile_view())
        self._history_changed()

    def api_group_reroll(self, i):
        """Rerolls a single player (banned, champion taken...): new champion in the same role, no duplicates."""
        with self.lock:
            g = self.group
            if not g or not g["committed"]:
                return {"error": T("Aucun tirage de groupe à relancer.")}
            try:
                i = int(i)
                p = g["players"][i]
            except (TypeError, ValueError, IndexError):
                return {"error": T("Joueur inconnu.")}
            d = self.data
            others = {q["key"] for j, q in enumerate(g["players"]) if j != i}
            every = [d.combo_key(k, p["role"]) for k in d.champs] if g.get("chaos") else d.by_role[p["role"]]
            pool = [k for k in every if k.partition("|")[0] not in others and k != p["combo"]]
            if not pool:
                return {"error": T("Plus aucun autre champion disponible pour ce poste.")}
            combo = random.choice(pool)
            if combo not in d.combos:
                self._chaos_combo(combo, fetch=False)
            np_ = self._group_player(i, g["inputs"][i], p["role"], combo, [self._champ_step_to(pool, combo)])
            np_["random_role"] = False
            g["players"][i] = np_
            if np_["me"]:
                self._group_record(g, reason="group_reroll")
            else:   # keep the group list stored with the roll in sync
                e = self.history.last_roll()
                if e and e.get("group"):
                    e["group"][i] = {"name": np_["name"], "key": np_["key"], "role": np_["role"], "me": False}
                    self.history.save()
            return {"player": np_}

    def api_roll_commit(self, id):
        """The roulette stopped: the roll is saved and its guide returned."""
        with self.lock:
            r = self.rolls.pop(str(id), None)
            self.spinning_until = 0.0
            if not r:
                return {"error": T("Tirage expiré.")}
            key, _, role = r["result"].partition("|")
            tracking = bool(self.lol_state.get("connected"))
            self.history.add_roll(key, role, tracking, reason=r["reason"], mode=r["mode"], favs=r["favs"])
            if self.profile["roulette_paused"]:   # rolling means wanting to play it: the pause ends
                self.profile["roulette_paused"] = False
                self.emit("profile", self._profile_view())
            self.drawn.add(r["result"])
            self.set_status(T("Résultat : %s %s%s") % (self.data.champ_name(key), ROLE_LABEL[role],
                                                    " (chaos)" if r["mode"] == "chaos" else ""), "gold", toast=False)
            self._history_changed()
            if LITE:   # no guide in Lite, just the result (and no chaos download)
                return {"combo": {"key": r["result"], "role": role, "role_label": ROLE_LABEL[role],
                                  "champ": {"key": key, "name": self.data.champ_name(key)}}}
        return {"combo": self.api_combo(r["result"])}   # a chaos guide may download: outside the lock

    def api_reroll(self, role, reason=None, **_ignored):
        """Reroll from champ select (autofill, ban, champion taken): the previous roll is cancelled with that reason,
        shown in the history."""
        return self.api_roll(role=role, champ="", reason=reason)

    # --- favorites ----------------------------------------------------------------------
    def _favs_changed(self):
        self.emit("profile", self._profile_view())

    def api_fav_toggle_global(self, key):
        with self.lock:
            on = self.profile.toggle_global(key, self.data.champs[key]["roles"])
            self._favs_changed()
            return {"on": on, "profile": self._profile_view()}

    def api_fav_toggle_combo(self, key, role):
        with self.lock:
            on = self.profile.toggle_combo(key, role, self.data.champs[key]["roles"])
            name = self.data.champ_name(key)
            self.set_status((T("%s %s ajouté à tes favoris.") if on else T("%s %s retiré de tes favoris.")) % (name, ROLE_LABEL[role]), "teal")
            self._favs_changed()
            return {"on": on, "profile": self._profile_view()}

    def api_fav_set_roles(self, key, roles):
        with self.lock:
            self.profile.set_fav_roles(key, self.data.champs[key]["roles"], roles or [])
            self._favs_changed()
            return {"profile": self._profile_view()}

    def api_fav_toggle_role(self, role):
        with self.lock:
            self.profile.toggle_role(role)
            self._favs_changed()
            return {"profile": self._profile_view()}

    def api_fav_clear(self):
        with self.lock:
            p = self.profile
            p.data["fav_champs"], p.data["fav_combos"], p.data["fav_roles"] = [], [], []
            p.save()
            self._favs_changed()
            return {"profile": self._profile_view()}

    # --- settings -------------------------------------------------------------------
    PREFS = {"only_fav_roles": bool, "only_fav_champs": bool, "no_repeat": bool, "auto_update": bool,
             "glossary_hints": bool, "ambient": bool, "overlay_mode": str, "overlay_scale": float,
             "overlay_opacity": float, "import_runes": bool, "import_spells": bool, "import_items": bool,
             "import_replace": bool, "roulette_paused": bool}

    def api_set_pref(self, key, value):
        with self.lock:
            if key not in self.PREFS:
                return {"error": T("Réglage inconnu : %s") % key}
            value = self.PREFS[key](value)
            if key == "overlay_mode" and value not in dict(OVERLAY_MODES):
                return {"error": "Unknown mode"}
            if key == "overlay_scale":
                value = max(0.7, min(1.4, value))
            if key == "overlay_opacity":
                value = max(0.5, min(1.0, value))
            self.profile[key] = value
            self.emit("profile", self._profile_view())
            if key == "roulette_paused":
                e = self.history.pending()
                pending = T(" Ton tirage %s %s reste en attente.") % (self.data.champ_name(e["key"]), ROLE_LABEL.get(e["role"], "")) \
                    if e else ""
                self.set_status((T("Roulette en pause : tes parties ne comptent pas pour la roulette.") + pending) if value
                                else T("Roulette réactivée."), "teal")
                self._history_changed()
            if key.startswith("overlay_"):
                self.overlay_cmds.put(("refresh", None))
            return {"profile": self._profile_view()}

    UGG_ROLE = {"top": "top", "jgl": "jungle", "mid": "mid", "adc": "adc", "sup": "support"}

    def api_open_ugg(self, key, role=None):
        """"See on u.gg" button: the champion's u.gg page for that role, in the browser. u.gg only."""
        k = "".join(ch for ch in str(key or "") if ch.isalnum()).lower()
        if not k:
            return {"error": "?"}
        url = "https://u.gg/lol/champions/%s/build" % k + ("/" + self.UGG_ROLE[role] if role in self.UGG_ROLE else "")
        import webbrowser
        webbrowser.open(url)
        return {"ok": True, "url": url}

    def api_open_download(self):
        """"Download" button of the Lite's full app promo: opens the release page."""
        if not DOWNLOAD_URL:
            return {"error": T("Bientôt disponible.")}
        import webbrowser
        webbrowser.open(DOWNLOAD_URL)
        return {"ok": True}

    def api_set_lang(self, lang):
        """Switches the UI language: data reloaded (names, guides, glossary), then the UI reloads."""
        if lang not in LANGS:
            return {"error": "Unknown language"}
        with self.lock:
            self.profile["lang"] = lang
            set_lang(lang)
        self.reload_data()
        self.overlay_cmds.put(("refresh", None))
        self.emit("lang", {"lang": lang})
        return {"lang": lang}

    def api_window(self, action, edge=None):
        """Title bar: minimize, maximize, close (to the tray), move, resize (edge: n, s, e, w, ne, nw, se, sw)."""
        if action not in ("minimize", "maximize", "close", "move", "resize"):
            return {"error": "Unknown action"}
        if edge is not None and (not isinstance(edge, str) or not set(edge) <= set("nsew")):
            return {"error": "Unknown edge"}
        return self.ui.window_action(action, edge)

    def api_autostart(self, on):
        from system import set_autostart
        set_autostart(bool(on))
        return {"autostart": self._autostart_state()}

    def api_overlay_module(self, module, on=None, mode=None):
        """Shows / hides an overlay module, or changes when it shows (Tab or always)."""
        with self.lock:
            if module not in MODULE_DEFAULT:
                return {"error": "Unknown module"}
            mods = dict(self.profile["overlay_modules"])
            cfg = dict(mods.get(module) or {})
            if on is not None:
                cfg["on"] = bool(on)
            if mode in ("tab", "always"):
                cfg["mode"] = mode
            mods[module] = cfg
            self.profile["overlay_modules"] = mods
            self.emit("profile", self._profile_view())
            return {"profile": self._profile_view()}

    def api_overlay(self, action):
        """Preview, on-screen placement or reset of the overlay positions."""
        with self.lock:
            if action == "reset":
                self.profile["overlay_pos"] = {}
                self.profile["board_geom"] = None   # the scoreboard grid will be measured again
                self.overlay_cmds.put(("refresh", None))
                return {"profile": self._profile_view()}
            if action in ("preview", "place"):
                self.overlay_cmds.put((action, self.current))
                if action == "place":
                    self.ui.hide_for_overlay()
                return {"ok": True}
            return {"error": "Unknown action"}

    def overlay_position_saved(self, module, pos):
        with self.lock:
            allpos = dict(self.profile["overlay_pos"] or {})
            allpos[module] = pos
            self.profile["overlay_pos"] = allpos
            self.emit("profile", self._profile_view())

    def overlay_place_done(self):
        self.ui.show()
        self.emit("overlay_placed", self.profile["overlay_pos"])

    # --- history ----------------------------------------------------------------------
    def _history_changed(self):
        self.emit("history", {"recent": self._recent_view(), "roll": self._roll_view()})
        self.emit("cs", self._cs_view())

    def api_history(self, played_only=False, role="all", champ="all", mode="all", kind="all", queue="all"):
        """kind: all (every game and roll), roulette (rolls), free (games without the roulette)."""
        with self.lock:
            d = self.data
            account = self.profile["account_puuid"]
            mine = [e for e in self.history.entries if not (account and e.get("puuid") and e["puuid"] != account)]
            out = []
            for e in mine:
                if kind == "roulette" and e.get("free") or kind == "free" and not e.get("free"):
                    continue
                if played_only and e.get("status") not in ("played", "in_game"):
                    continue
                if role != "all" and e.get("role") != role:
                    continue
                if champ != "all" and e.get("key") != champ:
                    continue
                if mode != "all" and (e.get("free") or e.get("mode") != mode):
                    continue
                if queue != "all" and str(e.get("queue")) != str(queue):
                    continue
                out.append(e)
            rows = []
            for e in reversed(out):
                disp = entry_display(e, d)
                lp = e.get("lp") or {}
                rows.append({
                    "id": e["id"], "date": e.get("date", ""), "key": e.get("key"), "name": d.champ_name(e.get("key")),
                    "role": e.get("role"), "role_label": ROLE_LABEL.get(e.get("role"), ""),
                    "mode": T("Hors roulette") if e.get("free") else MODE_LABEL.get(e.get("mode"), "—"), "free": bool(e.get("free")),
                    "result": disp["result"], "tone": disp["tone"],
                    "glyph": disp["glyph"], "detail": disp["detail"],
                    "kda": e.get("kda"), "queue": T(lol.queue_name(e.get("queue"))),
                    "lp_delta": lp.get("delta") if isinstance(lp.get("delta"), int) else None,
                    "played": e.get("played"), "played_name": d.champ_name(e.get("played")) if e.get("played") else "",
                    "has_game": bool(e.get("game_id")) and e.get("status") in ("played", "remake", "in_game"),
                    "combo": d.combo_key(e.get("key"), e.get("role")),
                    "has_combo": d.combo_key(e.get("key"), e.get("role")) in d.combos or d.is_chaos_key(d.combo_key(e.get("key"), e.get("role"))),
                })
            s = self.history.summary(out)
            counted = s["respected"] - s["respected_protected"]
            s["rate"] = round(100.0 * s["respected_wins"] / counted) if counted > 0 else None
            champs = sorted({e.get("key") for e in mine if e.get("key")}, key=lambda k: norm(d.champ_name(k)))
            queues = sorted({e["queue"] for e in mine if e.get("queue")}, key=lambda q: lol.queue_name(q))
            return {"rows": rows, "summary": s, "chart": lp_points(out, "RANKED_SOLO_5x5"),
                    "champs": [{"key": k, "name": d.champ_name(k)} for k in champs],
                    "queues": [{"id": q, "name": T(lol.queue_name(q)) if q != 3140 else T("Entraînement")} for q in queues]}

    def api_history_clear(self):
        with self.lock:
            self.history.clear()
            self._history_changed()
            return {"ok": True}

    def api_history_refresh(self):
        with self.lock:
            if self.watcher and self.lol_state.get("connected"):
                self.watcher.request_history()
                self.set_status(T("Historique LoL : actualisation demandée…"), "teal")
                return {"ok": True}
            return {"error": T("Le client LoL n'est pas détecté : impossible d'actualiser.")}

    def _request_game(self, gid):
        if gid and self.watcher and self.lol_state.get("connected"):
            self._requested.add(gid)
            self.watcher.request_game(gid)

    def api_game(self, id):
        """Details of a played game (both teams)."""
        with self.lock:
            e = next((x for x in self.history.entries if str(x.get("id")) == str(id)), None)
            if not e:
                return {"error": T("Tirage introuvable.")}
            gid = e.get("game_id")
            detail = lol.load_detail(GAMES_DIR, gid) if gid else None
            if gid and (not detail or detail.get("source") != "history"):
                self._request_game(gid)
            return self._game_view(e, detail)

    def _group_check(self, e, detail):
        """Group roll: did everyone play the rolled champion? (from the game details)"""
        data = self.data
        players = (detail or {}).get("players") or []
        out = []
        for m in e.get("group") or []:
            nm = (m.get("name") or "").split("#")[0].strip().lower()
            pl = next((p for p in players if p.get("isMe")), None) if m.get("me") else \
                next((p for p in players if (p.get("name") or "").strip().lower() == nm), None)
            played = data.cid_to_key.get(pl["championId"]) if pl else None
            out.append({"name": m.get("name") or (T("Toi") if m.get("me") else "?"), "key": m.get("key"), "champ": data.champ_name(m.get("key")),
                        "role_label": ROLE_LABEL.get(m.get("role"), ""), "played": data.champ_name(played) if played else None,
                        "ok": (played == m.get("key")) if played else None})
        return out

    def _game_view(self, e, d):
        data = self.data
        status = e.get("status")
        win = e.get("win")
        if status == "remake":
            title, tone = T("Remake"), "muted"
        elif status == "in_game":
            title, tone = T("Partie en cours"), "live"
        elif not win and e.get("lp_protected"):
            title, tone = T("Défaite sans perte de LP"), "shield"
        else:
            title, tone = (T("Victoire"), "win") if win else (T("Défaite"), "loss")
        dur = (d or {}).get("duration") or e.get("duration") or 0
        infos = [T(lol.queue_name(e.get("queue"))) or T("Partie"), "%d:%02d" % (dur // 60, dur % 60) if dur else "",
                 e.get("date", ""), lp_text(e)]
        roll_text = T("Tirage : %s %s") % (data.champ_name(e.get("key")), ROLE_LABEL.get(e.get("role"), ""))
        if e.get("free"):
            roll_text = T("Partie hors roulette")
        elif e.get("mode"):
            roll_text += " (%s)" % MODE_LABEL.get(e["mode"], "").lower()
        if e.get("played") and e["played"] != e.get("key"):
            roll_text += T(" — joué %s à la place") % data.champ_name(e["played"])
        if e.get("group"):
            roll_text = T("Tirage de groupe")
        combo = data.combo_key(e.get("key"), e.get("role"))
        played_combo = data.combo_key(e.get("played"), e.get("role")) if e.get("played") else None
        view = {"combo": combo if combo in data.combos or data.is_chaos_key(combo) else None,
                "combo_label": "%s %s" % (data.champ_name(e.get("key")), ROLE_LABEL.get(e.get("role"), "")),
                "played_combo": played_combo if played_combo in data.combos and played_combo != combo else None,
                "played_label": "%s %s" % (data.champ_name(e.get("played")), ROLE_LABEL.get(e.get("role"), ""))
                if e.get("played") else "",
                "id": e.get("id"), "title": title, "tone": tone, "infos": [i for i in infos if i], "roll_text": roll_text,
                "played": e.get("played") or e.get("key"), "state": "ok"}
        if e.get("group"):
            view["group"] = self._group_check(e, d)
        if not d or not d.get("players"):
            view["state"] = "loading" if self.lol_state.get("connected") else "missing"
            return view
        players = d["players"]
        me = next((p for p in players if p.get("isMe")), None)
        if not me:
            ch = data.champs.get(e.get("played") or e.get("key"))
            me = next((p for p in players if ch and p.get("championId") == ch["cid"]), None)
        team_kills, team_dmg = {}, {}
        for p in players:
            team_kills[p["teamId"]] = team_kills.get(p["teamId"], 0) + (p.get("k") or 0)
            team_dmg[p["teamId"]] = team_dmg.get(p["teamId"], 0) + (p.get("dmg") or 0)
        minutes = max(1.0, dur / 60.0)
        if me:
            k, dd, a = me.get("k", 0), me.get("d", 0), me.get("a", 0)
            kp = 100.0 * (k + a) / team_kills[me["teamId"]] if team_kills.get(me["teamId"]) else 0
            share = 100.0 * me.get("dmg", 0) / team_dmg[me["teamId"]] if team_dmg.get(me["teamId"]) else 0
            view["chips"] = [
                {"label": "KDA", "value": "%d / %d / %d" % (k, dd, a),
                 "sub": T("ratio %s") % (T("parfait") if dd == 0 else fmt_num((k + a) / dd, 2))},
                {"label": T("Farm"), "value": str(me.get("cs", 0)), "sub": "%s / min" % fmt_num(me.get("cs", 0) / minutes, 1)},
                {"label": T("Or"), "value": fmt_k(me.get("gold", 0)), "sub": "%s / min" % fmt_int(me.get("gold", 0) / minutes)},
                {"label": T("Dégâts"), "value": fmt_k(me.get("dmg", 0)), "sub": T("%s de l'équipe") % fmt_pct(share, 0)},
                {"label": T("Vision"), "value": str(me.get("vision", 0)), "sub": T("%s wards") % me.get("wards", 0)},
                {"label": T("Participation"), "value": fmt_pct(kp, 0), "sub": T("aux kills")},
            ]
        teams = {t.get("teamId"): t for t in d.get("teams") or []}
        max_dmg = max([p.get("dmg") or 0 for p in players] + [1])
        order = {r: i for i, r in enumerate(ROLES)}
        out_teams = []
        for team_id, side in ((100, "blue"), (200, "red")):
            tp = sorted([p for p in players if p.get("teamId") == team_id], key=lambda p: order.get(p.get("role"), 9))
            if not tp:
                continue
            t = teams.get(team_id, {})
            twin = t.get("win") if "win" in t else tp[0].get("win")
            objs = [T("%d kills") % team_kills.get(team_id, 0)]
            for keyname, one, many in (("towers", "tour", "tours"), ("dragons", "dragon", "dragons"),
                                       ("barons", "baron", "barons"), ("heralds", "héraut", "hérauts"),
                                       ("grubs", "larve", "larves")):
                if t.get(keyname) is not None:
                    objs.append("%s %s" % (t[keyname], T(many) if t[keyname] > 1 else T(one)))
            objs.append(T("%s d'or") % fmt_k(sum(p.get("gold") or 0 for p in tp)))
            rows = []
            for p in tp:
                ck = data.cid_to_key.get(p.get("championId"))
                k, dd, a = p.get("k", 0), p.get("d", 0), p.get("a", 0)
                rows.append({
                    "me": me is not None and p is me, "role": p.get("role"), "key": ck, "champ": data.champ_name(ck),
                    "name": p.get("name") or data.champ_name(ck), "tag": p.get("tag") or "",
                    "level": p.get("level") or "", "kda": "%d/%d/%d" % (k, dd, a),
                    "ratio": "∞" if dd == 0 else fmt_num((k + a) / dd, 1),
                    "cs": "%d (%s)" % (p.get("cs", 0), fmt_num(p.get("cs", 0) / minutes, 1)),
                    "gold": fmt_k(p.get("gold", 0)), "dmg": p.get("dmg") or 0, "dmg_txt": fmt_int(p.get("dmg") or 0),
                    "dmg_frac": (p.get("dmg") or 0) / max_dmg, "taken": fmt_k(p.get("taken", 0)),
                    "vision": "%s (%s/%s)" % (p.get("vision", 0), p.get("wards", 0), p.get("wardsKilled", 0)),
                })
            out_teams.append({"side": side, "win": bool(twin), "objs": objs, "rows": rows,
                              "mine": any(r["me"] for r in rows)})
        view["teams"] = out_teams
        return view

    # --- League client --------------------------------------------------------------------
    def api_lol_dir(self):
        path = self.ui.choose_folder(T("Dossier d'installation de League of Legends"))
        if not path:
            return {"cancelled": True}
        with self.lock:
            self.profile["lol_dir"] = path
            if self.watcher:
                self.watcher.set_custom_dir(path)
            self.set_status(T("Dossier LoL enregistré : %s") % path, "teal")
            return {"profile": self._profile_view()}

    def _lol_view(self):
        st = self.lol_state
        if not st.get("connected"):
            return {"connected": False, "text": T("Client LoL non détecté"), "sub": T("Lance-le pour relier tes parties")}
        phase = st.get("phase") or "None"
        solo = self.ranked.get("RANKED_SOLO_5x5")
        flex = self.ranked.get("RANKED_FLEX_SR")
        return {"connected": True, "phase": phase, "text": PHASE_TEXT.get(phase, phase),
                "summoner": st.get("summoner") or "",
                "rank": lol.rank_label(solo) if solo else "", "rank_tier": (solo or {}).get("tier", ""),
                "flex": lol.rank_label(flex) if flex else "",
                "in_game": phase in ("InProgress", "Reconnect"),
                "lobby": st.get("lobby") or []}

    # --- live game (champ select, loading screen, game) ---------------------------------
    def _live_players(self):
        """(mode, queue, allies, enemies) from the client state."""
        st = self.lol_state
        if not st.get("connected"):
            return None, None, [], []
        phase = st.get("phase")
        if phase == "ChampSelect" and st.get("cs"):
            cs = st["cs"]
            allies = [dict(p) for p in cs.get("team") or []]
            for p in allies:
                if p.get("me") and not p.get("role"):
                    p["role"] = cs.get("assigned")
            enemies = [{"champ": c, "role": None, "puuid": None, "name": None, "me": False, "locked": True}
                       for c in cs.get("enemies") or []]
            return "cs", cs.get("queue"), allies, enemies
        if phase in ("GameStart", "InProgress", "Reconnect") and st.get("teams"):
            teams = st["teams"]
            me = next((p for p in teams if p.get("me")), None)
            side = me["side"] if me else 100
            return ("game", st.get("queue"), [p for p in teams if p["side"] == side],
                    [p for p in teams if p["side"] != side])
        return None, None, [], []

    def _fill_roles(self, team):
        """Missing roles (enemies in champ select, games without roles): guessed, and flagged as such."""
        from analysis import guess_roles
        d = self.data
        keys = [d.cid_to_key.get(p.get("champ")) if p.get("champ") else None for p in team]
        known = {i: p["role"] for i, p in enumerate(team) if p.get("role")}
        if len(known) == len(team):
            return team
        roles = guess_roles(d, keys, known)
        out = []
        for i, p in enumerate(team):
            p = dict(p)
            if not p.get("role") and roles[i]:
                p["role"], p["guessed"] = roles[i], True
            out.append(p)
        return out

    def _live_view(self):
        from analysis import (counter_items, countered_by, matchup_vs, strip_goal, team_profile, third_person,
                             ROLES as R5)
        d = self.data
        mode, queue, allies, enemies = self._live_players()
        if not mode:
            return {"mode": None}
        allies, enemies = self._fill_roles(allies), self._fill_roles(enemies)
        me = next((p for p in allies if p.get("me")), None)
        my_combo = self._combo_for(me["champ"], me.get("role")) if me and me.get("champ") else None
        my_guide = d.guides.get(my_combo) or {} if my_combo else {}

        def player(p, enemy):
            key = d.cid_to_key.get(p["champ"]) if p.get("champ") else None
            out = {"key": key, "champ": d.champ_name(key) if key else None, "role": p.get("role"),
                   "role_label": ROLE_LABEL.get(p.get("role"), "") if p.get("role") else "",
                   "guessed": bool(p.get("guessed")), "has_guide": bool(key and d.combo_key(key, p.get("role")) in d.combos),
                   "player": p.get("name"), "me": bool(p.get("me")), "locked": p.get("locked", True)}
            if p.get("puuid") and self.scout:
                info = self.scout.info(p["puuid"], p.get("champ") or 0)
                out["loading"] = info is None
                if info:
                    q = info.get("rank")
                    if q:
                        tot = q["wins"] + q["losses"]
                        out["rank"] = {"label": lol.rank_label(q), "tier": q["tier"], "games": tot,
                                       "wr": round(100.0 * q["wins"] / tot, 1) if tot else None}
                    out["recent"] = info.get("recent")
            if enemy and my_combo and key:
                mv = matchup_vs(d, my_combo, key, p.get("role"))
                if mv:
                    out["vs"] = {"wr": mv[0], "n": mv[1], "delta": round(mv[2], 1)}
            if enemy and key:
                out["counters"] = countered_by(d, key, p.get("role"))
                eg = d.guides.get(d.combo_key(key, p.get("role"))) or {}
                if eg.get("win_condition"):
                    out["wants"] = third_person(strip_goal(eg["win_condition"]))
                if me and p.get("role") and p.get("role") == me.get("role"):
                    out["lane"] = True   # lane opponent
                    note = (my_guide.get("matchup_notes") or {}).get(d.champ_name(key))
                    if note:
                        out["note"] = note
            return out

        A = [player(p, False) for p in allies]
        E = [player(p, True) for p in enemies]
        # face-to-face rows, in role order (top vs top, jungle vs jungle...)
        rows = []
        for r in R5:
            a = next((x for x in A if x["role"] == r), None)
            e = next((x for x in E if x["role"] == r), None)
            if a or e:
                rows.append({"role": r, "role_label": ROLE_LABEL[r], "ally": a, "enemy": e})
        for x in A:
            if not x["role"]:
                rows.append({"role": None, "role_label": "", "ally": x, "enemy": None})
        for x in E:
            if not x["role"]:
                rows.append({"role": None, "role_label": "", "ally": None, "enemy": x})
        st = self.lol_state
        bans = []
        if mode == "cs":
            bans = [{"key": d.cid_to_key[c], "name": d.champ_name(d.cid_to_key[c])}
                    for c in ((st.get("cs") or {}).get("bans") or []) if c in d.cid_to_key]

        def prof(team):
            pr = team_profile(d, [(x["key"], x["role"]) for x in team if x["key"]])
            return {k: pr[k] for k in ("split", "front", "healers", "divers", "engage", "poke", "control", "n", "tips")}

        duo = None
        if me and my_combo and me.get("role") in ("adc", "sup"):
            mate = next((x for x in A if not x["me"] and x["key"] and x["role"] == ("sup" if me["role"] == "adc" else "adc")),
                        None)
            if mate:
                duo = self._duo_pair(my_combo, mate["key"])
                if duo:
                    duo["guessed"] = mate["guessed"]
        counters = []
        if my_combo and any(x["key"] for x in E):
            for o in counter_items(d, d.combos.get(my_combo), [(x["key"], x["role"]) for x in E if x["key"]]):
                counters.append(dict(o, name=d.item_names.get(str(o["id"]), "")))
        return {"mode": mode, "queue": lol.queue_name(queue), "allies": A, "enemies": E, "rows": rows, "bans": bans,
                "profiles": {"allies": prof(A), "enemies": prof(E)}, "counters": counters, "duo": duo,
                "combo": my_combo, "combo_label": ("%s %s" % (d.combos[my_combo]["name"], ROLE_LABEL[d.combos[my_combo]["role"]]))
                if my_combo else None}

    def _live_changed(self):
        with self.lock:
            self._emit_live(force=True)

    def _emit_live(self, force=False):
        if LITE:
            return   # no Game page in Lite
        mode, queue, allies, enemies = self._live_players()
        if self.scout:
            self.scout.want(allies + enemies)
        sig = repr((mode, queue, allies, enemies))
        if force or sig != self._live_sig:
            self._live_sig = sig
            self.emit("live", self._live_view())

    def api_live(self):
        with self.lock:
            return self._live_view()

    def _cs_view(self):
        """Champ select banner: whether the pending roll is still playable, plus the bot lane duo."""
        view = self._cs_view_inner()
        if view is not None:
            if LITE:
                view["duo"], view["imports"] = None, None
                return view
            try:
                view["duo"] = self._cs_duo()
            except Exception:
                view["duo"] = None
        return view

    def _cs_duo(self):
        cs = (self.lol_state or {}).get("cs") or {}
        role, my = cs.get("assigned"), cs.get("my_champ")
        if role not in ("adc", "sup") or not my:
            return None
        combo = self._combo_for(my, role)
        prole = "sup" if role == "adc" else "adc"
        mate = next((p for p in cs.get("team") or [] if not p.get("me") and p.get("role") == prole and p.get("champ")), None)
        if not combo or not mate:
            return None
        return self._duo_pair(combo, self.data.cid_to_key.get(mate["champ"]))

    def _cs_view_inner(self):
        st = self.lol_state
        if not st.get("connected") or st.get("phase") != "ChampSelect" or not st.get("cs"):
            return None
        d = self.data
        cs = st["cs"]
        assigned = cs.get("assigned")
        pending = self.history.pending()
        imp = self.import_state
        view = {"assigned": assigned, "assigned_label": ROLE_LABEL.get(assigned, "") if assigned else "",
                "lines": [], "buttons": [], "pending": None,
                "imports": {"label": imp["label"], "results": imp["results"]} if imp else None}
        line = lambda text, tone: view["lines"].append({"text": text, "tone": tone})
        button = lambda label, role, reason: view["buttons"].append({"label": label, "role": role, "reason": reason})
        paused = self.profile["roulette_paused"]
        if paused or cs.get("map") not in (None, 11):
            why = T("Roulette en pause") if paused else T("%s : la roulette ne compte pas") % (
                T(lol.queue_name(cs.get("queue"))) or T("Autre mode"))
            if pending:
                line(T("%s. Ton tirage %s %s reste en attente.") % (why, d.champ_name(pending["key"]),
                                                                  ROLE_LABEL.get(pending["role"], "")), "teal")
            else:
                line(why + ".", "muted")
            return view
        if not pending:
            line(T("Aucun tirage en cours."), "muted")
            if assigned:
                button(T("Tirer un champion %s") % ROLE_LABEL[assigned], assigned, None)
            return view
        combo = d.combos.get(d.combo_key(pending["key"], pending["role"])) or {}
        name = combo.get("name") or d.champ_name(pending["key"])
        cid = combo.get("cid") or (d.champs.get(pending["key"]) or {}).get("cid")
        view["pending"] = {"key": pending["key"], "role": pending["role"], "name": name,
                           "combo": d.combo_key(pending["key"], pending["role"])}
        target = assigned or pending["role"]
        problem = False
        if assigned and assigned != pending["role"]:
            line(T("Autofill : tu joues %s, pas %s.") % (ROLE_LABEL[assigned], ROLE_LABEL[pending["role"]]), "warn")
            button(T("Relancer en %s") % ROLE_LABEL[assigned], assigned, "autofill:%s" % assigned)
            problem = True
        if cid in (cs.get("bans") or []):
            line(T("%s a été banni.") % name, "bad")
            if not problem:
                button(T("Relancer (%s)") % ROLE_LABEL[target], target, "champion_banned")
            problem = True
        elif cid in (cs.get("taken") or []):
            line(T("%s a été choisi par un autre joueur.") % name, "bad")
            if not problem:
                button(T("Relancer (%s)") % ROLE_LABEL[target], target, "champion_taken")
            problem = True
        if not problem:
            my = cs.get("my_champ")
            if my == cid and cs.get("locked"):
                line(T("%s verrouillé. Bonne partie !") % name, "good")
            elif my and my != cid and cs.get("locked"):
                line(T("Tu as verrouillé %s au lieu de %s.") % (d.champ_name(d.cid_to_key.get(my)), name), "warn")
            else:
                line(T("Tout est bon : joue %s.") % name, "good")
        return view

    def _process_events(self):
        changed = False
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            t = ev["type"]
            if t == "state":
                self._on_lol_state(ev)
            elif t == "history":
                if ev.get("puuid") and ev["puuid"] != self.profile["account_puuid"]:
                    self.profile["account_puuid"] = ev["puuid"]
                    changed = True
                if self.history.on_history(ev.get("games") or [], ev.get("puuid"), self.profile["roulette_paused"]):
                    changed = True
                if self._fetch_missing_details():
                    changed = True
            elif t == "eog":
                if self.history.on_result(ev["gameId"], ev.get("result") or {}):
                    changed = True
                    self.set_status(T("Partie terminée : résultat enregistré."), "good")
                    e = next((x for x in reversed(self.history.entries) if x.get("game_id") == ev["gameId"]), None)
                    if e and not e.get("lp_before"):   # ranked game: the notification comes with the LP
                        self.notify(T("%s avec %s (%s)") % (entry_display(e, self.data)["result"],
                                                         self.data.champ_name(e.get("played") or e.get("key")),
                                                         "/".join(str(x) for x in e.get("kda") or [])))
                if ev.get("detail") and not lol.load_detail(GAMES_DIR, ev["gameId"]):
                    ev["detail"]["gameId"] = ev["gameId"]
                    lol.save_detail(GAMES_DIR, ev["detail"])
                    self.emit("game", {"game_id": ev["gameId"]})
            elif t == "game":
                if ev.get("detail"):
                    lol.save_detail(GAMES_DIR, ev["detail"])
                    e = next((x for x in reversed(self.history.entries) if x.get("game_id") == ev["gameId"]), None)
                    if e and self._fill_role(e, ev["detail"]):
                        self.history.save()
                        changed = True
                self.emit("game", {"game_id": ev["gameId"]})
            elif t == "roster":
                self._on_roster(ev)
            elif t == "ranked":
                self.ranked = ev.get("queues") or {}
                self.emit("lol", self._lol_view())
                if self.history.on_ranked(self.ranked, ev.get("notif")):
                    changed = True
                    self._announce_lp()
        # ranked game ended without any rank change: it didn't count
        now = time.time()
        if self.ranked and now >= self._lp_check_at:
            self._lp_check_at = now + 10
            if self.history.check_lp_timeout(self.ranked):
                changed = True
                self._announce_lp()
        if changed:
            self._history_changed()
            self.emit("game", {"game_id": None})

    def _announce_lp(self):
        e = next((x for x in reversed(self.history.entries) if x.get("lp")), None)
        if not e:
            return
        txt = lp_text(e)
        if not txt:
            return
        if e.get("lp_protected"):
            self.set_status(T("Défaite sans perte de LP : %s") % txt, "shield")
        else:
            delta = e["lp"].get("delta")
            tone = "good" if isinstance(delta, int) and delta > 0 else "bad" if isinstance(delta, int) and delta < 0 else "teal"
            self.set_status(T("Partie classée : %s") % txt, tone)
        if e.get("lp_announced") != e.get("game_id"):
            e["lp_announced"] = e.get("game_id")
            self.history.save()
            self.notify(T("%s avec %s : %s") % (entry_display(e, self.data)["result"],
                                             self.data.champ_name(e.get("played") or e.get("key")), txt))

    def _fetch_missing_details(self):
        """Keeps the details of recent games (all 10 players); role of the games played without the roulette."""
        filled = False
        for e in self.history.entries[-40:]:
            gid = e.get("game_id")
            if not gid or e.get("status") not in ("played", "remake"):
                continue
            d = lol.load_detail(GAMES_DIR, gid)
            if d is not None and d.get("source") == "history":
                filled = self._fill_role(e, d) or filled
            elif gid not in self._requested:
                self._request_game(gid)
        if filled:
            self.history.save()
        return filled

    @staticmethod
    def _fill_role(e, detail):
        """Game without the roulette: its role, from the game details."""
        if not e.get("free") or e.get("role"):
            return False
        me = next((p for p in (detail or {}).get("players") or [] if p.get("isMe")), None)
        if me and me.get("role"):
            e["role"] = me["role"]
            return True
        return False

    def _combo_for(self, cid, assigned):
        """Combo for a locked champion: assigned role if it has a guide, else its most played role."""
        d = self.data
        key = d.cid_to_key.get(cid)
        if not key or key not in d.champs:
            return None
        roles = d.champs[key]["roles"]
        role = assigned if assigned in roles else max(roles, key=lambda r: d.combos[d.combo_key(key, r)]["share"])
        return d.combo_key(key, role)

    def _show_locked_guide(self, cid, assigned):
        """Opens the guide of the champion locked in champ select."""
        d = self.data
        if LITE:
            return   # no guides in Lite
        combo = self._combo_for(cid, assigned)
        if not combo or time.time() < self.spinning_until:
            return
        key, role = combo.split("|")
        if combo == self.current:
            return
        note = "" if role == assigned or not assigned else T(" (pas de fiche %s : fiche %s)") % (
            ROLE_LABEL.get(assigned, assigned), ROLE_LABEL[role])
        self.current = combo
        self.emit("show_combo", {"key": combo})
        self.set_status(T("Champion verrouillé : fiche de %s %s%s.") % (d.champ_name(key), ROLE_LABEL[role], note), "teal")

    # --- champ select import (runes, summoner spells, item set) ---------------------------
    def _maybe_import(self, cs):
        p = self.profile
        if LITE or not (p["import_runes"] or p["import_spells"] or p["import_items"]) or not self.watcher:
            return
        if not cs.get("locked") or not cs.get("my_champ") or cs.get("map") != 11:   # Summoner's Rift
            return
        ident = (cs.get("session"), cs["my_champ"])
        if self._imported == ident:
            # the whole enemy comp is known: the item set gets the "Against their comp" block
            st = self.import_state
            en = tuple(sorted(cs.get("enemies") or []))
            if st and st.get("ident") == ident and p["import_items"] and len(en) >= 5 and st.get("enemies") != en:
                st["enemies"] = en
                enemies = [(self.data.cid_to_key[c], None) for c in en if c in self.data.cid_to_key]
                opts = {k: p[k] for k in ("import_runes", "import_spells", "import_items", "import_replace")}
                threading.Thread(target=self._do_import, args=(st["combo"], st["spells"], ident, opts, "items", enemies),
                                 name="import", daemon=True).start()
            return
        combo = self._combo_for(cs["my_champ"], cs.get("assigned"))
        pend = self.history.pending()
        ck = self.data.cid_to_key.get(cs["my_champ"])
        if pend and pend.get("key") == ck and pend.get("role") in ROLES and cs.get("assigned") in (None, "", pend["role"]):
            pk = self.data.combo_key(ck, pend["role"])
            if pk not in self.data.combos and self._chaos_combo(pk, fetch=False):
                combo = pk   # chaos roll: its build (real data from the cache, otherwise adapted)
        if not combo:
            return
        self._imported = ident
        opts = {k: p[k] for k in ("import_runes", "import_spells", "import_items", "import_replace")}
        threading.Thread(target=self._do_import, args=(combo, list(cs.get("spells") or []), ident, opts),
                         name="import", daemon=True).start()

    def _do_import(self, combo_key, spells, ident, opts, only=None, enemies=None):
        import imports
        from analysis import counter_items
        d = self.data
        c = d.combo_any(combo_key)
        client = self.watcher.client
        label = "%s %s" % (c["name"], ROLE_LABEL[c["role"]])
        build = d.build_for(combo_key, (self.profile.get("build_pick") or {}).get(combo_key))
        if build and build["id"] != "reco":
            label += " (%s)" % build["label"]
        jobs = [("runes", "Runes", opts["import_runes"],
                 lambda: imports.import_runes(client, build, imports.page_name(c["name"], ROLE_LABEL[c["role"]]),
                                              opts["import_replace"])),
                ("spells", "Sorts d'invocateur", opts["import_spells"], lambda: imports.import_spells(client, build, spells)),
                ("items", "Set d'objets", opts["import_items"],
                 lambda: imports.import_itemset(client, c, build, self.watcher.summoner_id, imports.PREFIX + label,
                                                counter_items(d, c, enemies) if enemies else None))]
        results = []
        for jid, name, on, fn in jobs:
            if not on or (only and jid != only):
                continue
            try:
                state, text = fn()
            except OSError as e:
                state, text = "error", str(e)
            if state == "error":
                log_error("import %s (%s): %s" % (jid, combo_key, text))
            results.append({"id": jid, "label": name, "state": state, "text": text})
        with self.lock:
            if self._imported != ident:
                return
            prev = (self.import_state or {}).get("results") or []
            if only:
                results = [r for r in prev if r["id"] != only] + results
                results.sort(key=lambda r: ["runes", "spells", "items"].index(r["id"]))
            self.import_state = {"combo": combo_key, "label": label, "results": results, "spells": spells,
                                 "ident": ident, "enemies": (self.import_state or {}).get("enemies")}
            ok = [r["label"].lower() for r in results if r["state"] == "ok" and (not only or r["id"] == only)]
            if enemies and ok:
                self.set_status(T("%s : set d'objets complété contre leur compo.") % label, "teal")
            elif ok:
                self.set_status(T("%s : %s importés.") % (label, ", ".join(ok)), "teal")
            self.emit("cs", self._cs_view())

    def api_import_build(self, key, variant=None, replace=False):
        """"Import into LoL" button of the Build tab: the shown variant goes to the client (rune page and item set at any
        time, summoner spells only during champ select). Never picks or bans."""
        import imports
        with self.lock:
            d = self.data
            if key not in d.combos:
                return {"error": T("Fiche inconnue.")}
            if not self.watcher or not self.lol_state.get("connected"):
                return {"error": T("Client LoL non détecté : ouvre-le pour importer.")}
            c = d.combos[key]
            build = d.build_for(key, variant)
            if not build:
                return {"error": T("Pas de build pour cette fiche.")}
            client = self.watcher.client
            cs = self.lol_state.get("cs") if self.lol_state.get("phase") == "ChampSelect" else None
            label = "%s %s" % (c["name"], ROLE_LABEL[c["role"]]) + (" (%s)" % T(build["label"]) if build["id"] != "reco" else "")
            sid = self.watcher.summoner_id
        jobs = [("runes", T("Runes"), lambda: imports.import_runes(client, build, imports.page_name(c["name"], ROLE_LABEL[c["role"]]),
                                                                 replace or self.profile["import_replace"])),
                ("items", T("Set d'objets"), lambda: imports.import_itemset(client, c, build, sid, imports.PREFIX + label))]
        if cs:
            jobs.append(("spells", T("Sorts d'invocateur"), lambda: imports.import_spells(client, build, cs.get("spells"))))
        results = []
        for jid, name, fn in jobs:
            try:
                state, text = fn()
            except OSError as e:
                state, text = "error", str(e)
            if state == "error":
                log_error("manual import %s (%s): %s" % (jid, key, text))
            results.append({"id": jid, "label": name, "state": state, "text": text})
        ok = [r["label"].lower() for r in results if r["state"] == "ok"]
        if ok:
            self.set_status(T("%s : %s importés dans le client.") % (label, ", ".join(ok)), "teal", toast=False)
        return {"label": label, "results": results, "in_cs": bool(cs)}

    def api_import(self, action="retry"):
        """Banner button: replace the selected rune page when there is no free slot."""
        with self.lock:
            st = self.import_state
            if not st:
                return {"error": T("Rien à importer pour l'instant")}
            opts = {k: self.profile[k] for k in ("import_runes", "import_spells", "import_items", "import_replace")}
            if action == "replace":
                opts["import_runes"], opts["import_replace"] = True, True
            threading.Thread(target=self._do_import, args=(st["combo"], st["spells"], st["ident"], opts, "runes"),
                             name="import", daemon=True).start()
            return {"ok": True}

    def _on_lol_state(self, st):
        prev_connected = self.lol_state.get("connected")
        self.lol_state = st
        if not st.get("connected"):
            if prev_connected:
                self.overlay_info = None
            self.emit("lol", self._lol_view())
            self.emit("cs", None)
            self._emit_live()
            return
        phase = st.get("phase") or "None"
        if phase == "ChampSelect":
            cs = st.get("cs") or {}
            if cs.get("my_champ"):
                self._cs_champ = cs["my_champ"]
            if cs.get("assigned"):
                self._cs_role = cs["assigned"]
            if cs.get("locked") and cs.get("my_champ") and cs["my_champ"] != self._cs_shown:
                self._cs_shown = cs["my_champ"]
                self._show_locked_guide(cs["my_champ"], cs.get("assigned"))
            self._maybe_import(cs)
        elif phase not in lol.GAME_PHASES:
            self._cs_shown = None
        if phase != "ChampSelect":
            self._imported = None
            self.import_state = None
        game = st.get("game") or {}
        gid = game.get("gameId")
        if gid and phase in ("InProgress", "Reconnect") and gid != self._game_id:
            self._game_id = gid
            had = self.history.pending()
            kind = self.history.on_game_start(gid, game.get("queueId"), self._cs_champ, ranked=self.ranked,
                                              role=self._cs_role, puuid=getattr(self.watcher, "_puuid", None),
                                              custom=game.get("custom"), mode=game.get("mode"),
                                              paused=self.profile["roulette_paused"])
            if kind == "free" and had and self.history.pending() is had:
                self.set_status(T("Partie hors roulette (%s) : ton tirage %s %s reste en attente.") % (
                    T("pause") if self.profile["roulette_paused"] else T(lol.queue_name(game.get("queueId"))) or T("autre mode"),
                    self.data.champ_name(had["key"]), ROLE_LABEL.get(had["role"], "")), "teal")
            if kind == "roll":
                msg = T("Partie lancée : le tirage est suivi jusqu'au résultat")
                if lol.RANKED_QUEUES.get(game.get("queueId")) in self.ranked:
                    msg += T(" et aux LP")
                self.set_status(msg + ".", "teal")
            if kind:
                self._history_changed()
        if phase not in lol.GAME_PHASES and phase != "ChampSelect":
            self._cs_champ = 0
            self._cs_role = None
        if phase not in ("InProgress", "Reconnect"):
            self.overlay_info = None
        self.emit("lol", self._lol_view())
        self.emit("cs", self._cs_view())
        self._emit_live()

    # --- in-game overlay ----------------------------------------------------------------
    def _champ_key(self, p):
        if p.get("key") in self.data.champs:
            return p["key"]
        return self.data.key_from_name(p.get("name", "")) or p.get("key") or None

    def _on_roster(self, ev):
        """Game roster received: sets the overlay guide and lane opponent."""
        d = self.data
        players = ev.get("players") or []
        if ev.get("me") is None or ev["me"] >= len(players):
            return
        me = players[ev["me"]]
        key = self._champ_key(me)
        if not key or key not in d.champs:
            return
        played_role = me.get("role")
        candidates = [played_role]
        e = next((x for x in reversed(self.history.entries) if x.get("game_id") == ev.get("gameId")), None)
        if e and (e.get("played") or e.get("key")) == key:
            candidates.append(e.get("role"))
        roles = d.champs[key]["roles"]
        candidates += sorted(roles, key=lambda r: -d.combos[d.combo_key(key, r)]["share"])
        role = next((r for r in candidates if r and d.combo_key(key, r) in d.combos), None)
        if not role:
            return
        note = ""
        if played_role and played_role != role:
            note = T("Pas de fiche %s %s : fiche %s affichée.") % (d.champ_name(key), ROLE_LABEL[played_role], ROLE_LABEL[role])
        opp = None
        if played_role:
            p = next((x for x in players if x.get("team") != me.get("team") and x.get("role") == played_role), None)
            opp = self._champ_key(p) if p else None
        enemies = [(self._champ_key(x), x.get("role")) for x in players if x.get("team") != me.get("team")]
        order = {r: i for i, r in enumerate(ROLES)}
        enemies = sorted([x for x in enemies if x[0]], key=lambda x: order.get(x[1], 9))
        self.overlay_info = {"key": key, "role": role, "opp": opp, "note": note, "enemies": enemies,
                             "game": ev.get("gameId")}
        self.profile["overlay_page"] = "early"   # new game: back to the first page

    # --- data update ----------------------------------------------------------------------
    def reload_data(self):
        """New stats installed by the updater: hot reload."""
        new = Data()
        with self.lock:
            self.data = new
            self.history.cid_to_key = new.cid_to_key
            # a current roll stays valid: combo keys don't change with the stats
            self.rolls = {k: r for k, r in self.rolls.items() if r["result"] in new.combos}
        self.emit("data_reloaded", {"patch": new.meta.get("patch"), "generated": new.meta.get("generated")})

    def set_update_status(self, st):
        self.update_status = st
        self.emit("update", st)

    def api_update(self, action="check"):
        if not self.updater:
            return {"error": T("Mise à jour indisponible.")}
        if action == "now":
            self.updater.request(force=True)
        else:
            self.updater.request(force=False)
        return {"update": self.update_status}

    def api_update_seen(self):
        with self.lock:
            self.profile["seen_update"] = self.data.meta.get("generated")
            return {"ok": True}


def check():
    """Command line check: every combo has a complete guide."""
    d = Data()
    problems = d.missing_guides() + d.guide_errors
    print("Combos: %d | guides: %d" % (len(d.combos), len(d.guides)))
    for r in ROLES:
        done = sum(1 for k in d.by_role[r] if k in d.guides)
        print("  %-8s %3d champions, %3d guides" % (r, len(d.by_role[r]), done))
    if problems:
        print("\n%d problem(s):" % len(problems))
        for p in problems:
            print("  - " + p)
        return 1
    print("OK: every champion/role combo has a complete guide.")
    return 0
