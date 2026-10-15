"""
End-to-end test of the in-app update (selfupdate.py) with a built app, in a temporary folder:

  1. a corrupted download is refused (checksum);
  2. the archive is downloaded from a local stand-in for the GitHub release, checked and unpacked;
  3. a copy of the app plays the installed old version: it runs its self-test while the new version, started with
     --finish-update, waits for it to exit, replaces its files and starts it again with --updated;
  4. Windows: profile and history kept next to the exe by older versions are moved to the user's folder.

  python packaging/test_update.py full|lite [--dist DIR]

Prints a report and exits with 1 if a check fails. The relaunched app is closed at the end.
"""
import functools
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAC = sys.platform == "darwin"


def main():
    edition = sys.argv[1] if len(sys.argv) > 1 else "full"
    dist = sys.argv[sys.argv.index("--dist") + 1] if "--dist" in sys.argv else os.path.join(ROOT, "_release")
    lite = edition == "lite"
    name = "Roulette of Legends Lite" if lite else "Roulette of Legends"
    archive = ("Roulette-of-Legends-Lite" if lite else "Roulette-of-Legends") + ("-mac.zip" if MAC else "-windows.zip")
    tmp = tempfile.mkdtemp(prefix="rol_update_")
    os.environ["ROL_NO_COUNT"] = "1"   # test launches are not app launches (inherited by the started apps)
    local = os.path.join(tmp, "local")
    if not MAC:
        os.environ["LOCALAPPDATA"] = local   # the app's user folder, for this test only
    sys.path.insert(0, ROOT)
    if lite:
        sys.path.insert(0, os.path.join(ROOT, "lite"))
    import selfupdate as su

    failures = []

    def check(label, ok, detail=""):
        print("%s %s%s" % ("ok  " if ok else "FAIL", label, (": %s" % detail) if detail else ""), flush=True)
        if not ok:
            failures.append(label)

    # installed old version (with a marker the update must remove)
    if MAC:
        install = os.path.join(tmp, "install", name + ".app")
        os.makedirs(os.path.dirname(install))
        subprocess.run(["ditto", os.path.join(dist, name + ".app"), install], check=True)
        exe_old = os.path.join(install, "Contents", "MacOS", name)
        marker = os.path.join(install, "Contents", "OLD_MARKER")
    else:
        install = os.path.join(tmp, "install", name)
        shutil.copytree(os.path.join(dist, name), install)
        exe_old = os.path.join(install, name + ".exe")
        marker = os.path.join(install, "_internal", "OLD_MARKER")
        with open(os.path.join(install, "data", "history.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
        with open(os.path.join(install, "data", "profile.json"), "w", encoding="utf-8") as f:
            json.dump({"lang": "fr"}, f)
    open(marker, "w").close()

    # local stand-in for the release
    folder = os.path.join(tmp, "srv", "download", "v9.9.9")
    os.makedirs(folder)
    shutil.copy(os.path.join(dist, archive), folder)
    with open(os.path.join(folder, archive), "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    sums = os.path.join(folder, "SHA256SUMS.txt")
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    handler = functools.partial(Quiet, directory=os.path.join(tmp, "srv"))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    su.RELEASE_FILE = "http://127.0.0.1:%d/download/v%%s/%%s" % httpd.server_port
    su.STAGING = os.path.join(tmp, "staging")

    class Core:
        states = []

        def set_app_update_state(self, st):
            self.states.append(st)

    with open(sums, "w") as f:
        f.write("%s  %s\n" % ("1" * 64, archive))
    try:
        su.Installer(Core(), "9.9.9")._prepare()
        check("corrupted download refused", False)
    except IOError as e:
        check("corrupted download refused", True, str(e))

    with open(sums, "w") as f:
        f.write("%s  %s\n%s  other.zip\n" % (digest, archive, "0" * 64))
    core = Core()
    started = time.time()
    finisher = su.Installer(core, "9.9.9")._prepare()
    check("download, checksum, unpack", os.path.isfile(finisher), "%.1f s, states %s" % (
        time.time() - started, sorted({s["state"] for s in core.states})))

    # old version running, new one finishing the update
    report = os.path.join(tmp, "autotest.txt")
    old = subprocess.Popen([exe_old, "--autotest", report])
    time.sleep(1)
    args = [finisher, "--finish-update", install, str(old.pid)]
    if MAC:
        fin = subprocess.Popen(args, start_new_session=True)
    else:
        fin = subprocess.Popen(args, creationflags=0x00000008 | 0x00000200)
    old.wait(timeout=240)
    with open(report, encoding="utf-8") as f:
        last = (f.read().strip().splitlines() or ["?"])[-1]
    check("old version self-test", last == "OK", last)
    fin.wait(timeout=240)
    check("finisher exit code", fin.returncode == 0, str(fin.returncode))
    check("files replaced", not os.path.exists(marker))
    parent = os.path.dirname(install) if MAC else install
    check("no leftovers", not [n for n in os.listdir(parent) if n.endswith(".old")], str(os.listdir(parent)))
    if not MAC:
        data = os.path.join(local, name, "data")
        check("history and profile moved to the user folder",
              all(os.path.exists(os.path.join(data, f)) for f in ("history.json", "profile.json", ".bundle")))

    # relaunched app (found by its path in the test folder), then closed
    found = []
    for _ in range(30):
        time.sleep(1)
        if MAC:
            out = subprocess.run(["ps", "-A", "-o", "pid=,args="], capture_output=True, text=True).stdout
            found = [l.strip().split(" ", 1) for l in out.splitlines() if install in l]
        else:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*%s*' } | "
                                  "ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }" % install.replace("'", "''")],
                                 capture_output=True, text=True).stdout
            found = [l.strip().split(" ", 1) for l in out.splitlines() if l.strip() and "powershell" not in l.lower()]
        if found:
            break
    check("app restarted with --updated", any("--updated" in cmd for _pid, cmd in found), str([c[-80:] for _p, c in found]))
    for pid, _cmd in found:
        if MAC:
            subprocess.run(["kill", pid])
        else:
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
    httpd.shutdown()
    time.sleep(2)
    shutil.rmtree(tmp, ignore_errors=True)
    print("OK" if not failures else "%d check(s) failed" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
