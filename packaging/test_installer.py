"""
Test of the first-install packages made for a release, on the system they target.

  Windows  <archive>-Setup.exe: silent per-user install in a temporary folder, files, Start menu shortcut and
           installed apps entry, self-test of the installed app, version record after an in-app update, then
           silent uninstall (files, shortcut and entry gone)
  macOS    <archive>-mac.dmg: attached read-only, holds the app and a link to Applications

  python packaging/test_installer.py full|lite [--dist DIR]

Prints a report and exits with 1 if a check fails.
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from build import ARCHIVES  # noqa: E402
from package import EDITIONS  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print("%s %s%s" % ("ok  " if ok else "FAIL", label, (": %s" % detail) if detail else ""), flush=True)
    if not ok:
        failures.append(label)


def wait(cond, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(1)
    return cond()


def test_windows(edition, dist, name):
    import winreg
    sys.path.insert(0, ROOT)
    if edition == "lite":
        sys.path.insert(0, os.path.join(ROOT, "lite"))
    import core
    import selfupdate
    setup = os.path.join(dist, ARCHIVES[edition] + "-Setup.exe")
    check("installer built", os.path.isfile(setup), setup)
    tmp = tempfile.mkdtemp(prefix="rol_setup_test_")
    target = os.path.join(tmp, name)
    env = dict(os.environ, LOCALAPPDATA=os.path.join(tmp, "local"), ROL_NO_COUNT="1")
    r = subprocess.run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=" + target], timeout=300)
    check("silent install", r.returncode == 0, "exit code %d" % r.returncode)
    exe = os.path.join(target, name + ".exe")
    check("files", all(os.path.isfile(p) for p in (exe, os.path.join(target, "data", "stats.json"),
                                                   os.path.join(target, "ui", "index.html"),
                                                   os.path.join(target, "unins000.exe"))))
    shortcut = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", name + ".lnk")
    check("Start menu shortcut", os.path.isfile(shortcut))
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\%s_is1" % core.INSTALLER_ID

    def entry():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                return {v: winreg.QueryValueEx(k, v)[0] for v in ("DisplayName", "DisplayVersion", "InstallLocation")}
        except OSError:
            return None
    e = entry()
    check("installed apps entry", bool(e) and e["DisplayName"] == name and e["DisplayVersion"] == core.APP_VERSION, str(e))

    report = os.path.join(tmp, "autotest.txt")
    subprocess.run([exe, "--autotest", report], env=env, timeout=300)
    last = open(report, encoding="utf-8").read().strip().splitlines()[-1] if os.path.exists(report) else "no report"
    check("installed app self-test", last == "OK", last)
    data = os.path.join(tmp, "local", name, "data")
    check("user data outside the install folder", os.path.isfile(os.path.join(data, ".bundle")))

    selfupdate.record_version(target, "9.9.9")
    check("version recorded after an in-app update", (entry() or {}).get("DisplayVersion") == "9.9.9")

    subprocess.run([os.path.join(target, "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=120)
    gone = wait(lambda: not os.path.exists(exe) and entry() is None, 90)   # the uninstaller runs from a temporary copy
    check("silent uninstall", gone, str(os.listdir(target)) if os.path.isdir(target) else "folder removed")
    check("shortcut removed", not os.path.exists(shortcut))
    check("user data kept", os.path.isfile(os.path.join(data, ".bundle")))


def test_mac(edition, dist, name):
    dmg = os.path.join(dist, ARCHIVES[edition] + "-mac.dmg")
    check("disk image built", os.path.isfile(dmg), dmg)
    mount = tempfile.mkdtemp(prefix="rol_dmg_")
    r = subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", mount, dmg],
                       capture_output=True, text=True)
    check("attached", r.returncode == 0, r.stderr.strip())
    try:
        app = os.path.join(mount, name + ".app", "Contents", "MacOS", name)
        check("app inside", os.access(app, os.X_OK))
        link = os.path.join(mount, "Applications")
        check("link to Applications", os.path.islink(link) and os.readlink(link) == "/Applications")
    finally:
        subprocess.run(["hdiutil", "detach", mount], capture_output=True)


def main():
    edition = sys.argv[1] if len(sys.argv) > 1 else "full"
    dist = os.path.abspath(sys.argv[sys.argv.index("--dist") + 1]) if "--dist" in sys.argv else os.path.join(ROOT, "_release")
    name = EDITIONS[edition]
    (test_mac if sys.platform == "darwin" else test_windows)(edition, dist, name)
    print("OK" if not failures else "%d check(s) failed" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
