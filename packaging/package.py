"""
What ships with each edition: a copy of ui/ and of data/, without anything personal or not meant for distribution
(user files, cache, League fonts and gold coin extracted from the local install). Used by build.py.

  full  Roulette of Legends: everything else, guides included
  lite  Roulette of Legends Lite: roulette data only (no guides, glossary or team comp data)
"""
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITIONS = {"full": "Roulette of Legends", "lite": "Roulette of Legends Lite"}

# paths relative to data/ never shipped (current and legacy names)
SKIP_ALWAYS = {
    "profile.json", "history.json", "errors.log", "update.json", ".instance", "games", "cache",
    "profil.json", "historique.json", "erreurs.log", "maj.json", "parties",
    os.path.join("fonts", "lol"), os.path.join("img", "ui"),
}
SKIP_LITE = {"guides", "guides_en", "glossary.json", "glossary_en.json", "compo.json"}


def copy_data(src, dst, skip):
    for base, dirs, files in os.walk(src):
        rel = os.path.relpath(base, src)
        rel = "" if rel == "." else rel
        dirs[:] = [d for d in dirs if os.path.join(rel, d) not in skip]
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            if os.path.join(rel, f) in skip or f.endswith(".tmp"):
                continue
            shutil.copy2(os.path.join(base, f), os.path.join(dst, rel, f))


def stage(edition, dest):
    """Writes dest/data and dest/ui for that edition (replacing any previous copy)."""
    for sub in ("data", "ui"):
        shutil.rmtree(os.path.join(dest, sub), ignore_errors=True)
    skip = SKIP_ALWAYS | (SKIP_LITE if edition == "lite" else set())
    copy_data(os.path.join(ROOT, "data"), os.path.join(dest, "data"), skip)
    shutil.copytree(os.path.join(ROOT, "ui"), os.path.join(dest, "ui"))
