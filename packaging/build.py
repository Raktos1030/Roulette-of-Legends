"""
Builds one edition of the app with PyInstaller and packs it for a release. Used by build_release.bat and
build_exe.bat on Windows, and by the release workflow (.github/workflows/release.yml) on Windows and macOS.

Usage: python packaging/build.py full|lite [--dist DIR] [--dev]
  Windows  DIST/<name>/ (exe + data/ + ui/) and DIST/<archive>-windows.zip (in-app updates); the installer is made
           from that folder by installer.py
  macOS    DIST/<name>.app (data/ and ui/ bundled, copied to the user's Library on first launch),
           DIST/<archive>-mac.dmg (first install: the app next to a link to Applications) and
           DIST/<archive>-mac.zip (in-app updates); Lite only for now (the overlay is Windows-only)
  --dev    Windows: exe only, no data copy or zip (the exe reads data/ and ui/ of the project, two levels up)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from package import EDITIONS, stage  # noqa: E402

ARCHIVES = {"full": "Roulette-of-Legends", "lite": "Roulette-of-Legends-Lite"}
BUNDLE_IDS = {"full": "com.raktos.rouletteoflegends", "lite": "com.raktos.rouletteoflegends.lite"}


def main():
    args = sys.argv[1:]
    if not args or args[0] not in EDITIONS:
        sys.exit(__doc__)
    edition = args[0]
    dist = os.path.abspath(args[args.index("--dist") + 1]) if "--dist" in args else os.path.join(ROOT, "_release")
    dev = "--dev" in args
    mac = sys.platform == "darwin"
    if mac and edition != "lite":
        sys.exit("The full app is Windows-only for now.")
    name = EDITIONS[edition]
    work = os.path.join(tempfile.gettempdir(), "rol_build_" + edition)
    opts = ["--noconfirm", "--clean", "--windowed", "--name", name, "--distpath", dist, "--workpath", work,
            "--specpath", work, "--paths", ROOT, "--hidden-import", "chaos", "--collect-all", "webview"]
    if edition == "lite":
        opts += ["--paths", os.path.join(ROOT, "lite"), "--hidden-import", "rol_lite"]
    if mac:
        staging = os.path.join(work, "stage")
        stage(edition, staging)
        opts += ["--icon", os.path.join(ROOT, "data", "img", "app.icns"), "--osx-bundle-identifier", BUNDLE_IDS[edition],
                 "--add-data", os.path.join(staging, "data") + os.pathsep + "data",
                 "--add-data", os.path.join(staging, "ui") + os.pathsep + "ui"]
        for module in ("overlay", "hud", "numpy", "tkinter"):   # Windows-only overlay
            opts += ["--exclude-module", module]
    else:
        opts += ["--icon", os.path.join(ROOT, "data", "img", "app.ico"), "--hidden-import", "pystray._win32",
                 "--collect-all", "clr_loader", "--hidden-import", "clr"]
    import PyInstaller.__main__
    PyInstaller.__main__.run(opts + [os.path.join(ROOT, "roulette_lol.py")])
    if dev:
        return
    if mac:
        app = os.path.join(dist, name + ".app")
        archive = os.path.join(dist, ARCHIVES[edition] + "-mac.zip")
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, archive], check=True)
        folder = os.path.join(work, "dmg")
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
        subprocess.run(["ditto", app, os.path.join(folder, name + ".app")], check=True)
        os.symlink("/Applications", os.path.join(folder, "Applications"))
        dmg = os.path.join(dist, ARCHIVES[edition] + "-mac.dmg")
        subprocess.run(["hdiutil", "create", "-volname", name, "-srcfolder", folder, "-ov", "-format", "UDZO", dmg],
                       check=True)
        print("Disk image: %s (%.0f MB)" % (dmg, os.path.getsize(dmg) / 1e6))
    else:
        stage(edition, os.path.join(dist, name))
        archive = shutil.make_archive(os.path.join(dist, ARCHIVES[edition] + "-windows"), "zip", dist, name)
    print("Archive: %s (%.0f MB)" % (archive, os.path.getsize(archive) / 1e6))


if __name__ == "__main__":
    main()
