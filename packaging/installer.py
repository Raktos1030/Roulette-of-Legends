"""
Windows installer of one edition (Setup.exe), from the folder made by build.py, with Inno Setup 6 (installer.iss).

Usage: python packaging/installer.py full|lite [--dist DIR]
  reads   DIST/<name>/ (exe + data/ + ui/)
  writes  DIST/<archive>-Setup.exe
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from package import EDITIONS  # noqa: E402
from build import ARCHIVES  # noqa: E402

ISCC_PATHS = [os.path.join(os.environ.get(v, ""), "Inno Setup 6", "ISCC.exe")
              for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]


def core_value(pattern):
    with open(os.path.join(ROOT, "core.py"), encoding="utf-8") as f:
        m = re.search(pattern, f.read(), re.M)
    if not m:
        sys.exit("core.py: %s not found" % pattern)
    return m.groups()


def small_images(work):
    """Logo at the top right of the wizard, one size per display scale (100 to 250 %)."""
    from PIL import Image
    ico = Image.open(os.path.join(ROOT, "data", "img", "app.ico"))
    ico.size = (256, 256)
    logo = ico.convert("RGBA")
    paths = []
    for size in (55, 69, 83, 110, 138):
        img = Image.new("RGBA", (size, size), (255, 255, 255, 255))
        img.alpha_composite(logo.resize((size, size), Image.LANCZOS))
        path = os.path.join(work, "small_%d.bmp" % size)
        img.convert("RGB").save(path)
        paths.append(path)
    return ",".join(paths)


def main():
    args = sys.argv[1:]
    if not args or args[0] not in EDITIONS:
        sys.exit(__doc__)
    edition = args[0]
    dist = os.path.abspath(args[args.index("--dist") + 1]) if "--dist" in args else os.path.join(ROOT, "_release")
    name = EDITIONS[edition]
    source = os.path.join(dist, name)
    if not os.path.isfile(os.path.join(source, name + ".exe")):
        sys.exit("Build the app first: python packaging/build.py %s --dist %s" % (edition, dist))
    iscc = shutil.which("iscc") or next((p for p in ISCC_PATHS if os.path.isfile(p)), None)
    if not iscc:
        sys.exit("Inno Setup 6 not found (https://jrsoftware.org/isdl.php)")
    version, = core_value(r'^APP_VERSION = "([0-9.]+)"')
    lite_id, full_id = core_value(r'^INSTALLER_ID = "\{([0-9A-F-]+)\}" if LITE else "\{([0-9A-F-]+)\}"')
    numeric = ".".join((version.split(".") + ["0"] * 4)[:4])
    work = tempfile.mkdtemp(prefix="rol_setup_")
    defines = {"AppName": name, "AppExe": name + ".exe", "AppVersion": version, "AppNumVersion": numeric,
               "AppGuid": lite_id if edition == "lite" else full_id, "SourceDir": source, "OutputDir": dist,
               "OutputBase": ARCHIVES[edition] + "-Setup", "SmallImages": small_images(work)}
    subprocess.run([iscc, "/Q"] + ["/D%s=%s" % kv for kv in defines.items()] + [os.path.join(HERE, "installer.iss")],
                   check=True)
    shutil.rmtree(work, ignore_errors=True)
    setup = os.path.join(dist, ARCHIVES[edition] + "-Setup.exe")
    print("Installer: %s (%.0f MB)" % (setup, os.path.getsize(setup) / 1e6))


if __name__ == "__main__":
    main()
