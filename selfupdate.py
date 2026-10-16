"""
In-app update of a release build.

The new version is downloaded from the GitHub release, checked against the release's SHA256SUMS.txt and unpacked in
the user's folder. That copy is then started with --finish-update: once the running app has exited, it replaces the
installed files with its own and starts the app again. Profile, history and stats live in the user's data folder
(core.DATA), which an update never touches.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

from core import APP_DIR, APP_NAME, APP_VERSION, BASE, BUNDLED_DATA, INSTALLER_ID, LITE, MAC, T, log_error

RELEASE_FILE = "https://github.com/Raktos1030/Roulette-of-Legends/releases/download/v%s/%s"
ARCHIVE = ("Roulette-of-Legends-Lite" if LITE else "Roulette-of-Legends") + ("-mac.zip" if MAC else "-windows.zip")
CHECKSUMS = "SHA256SUMS.txt"
STAGING = os.path.join(BASE, "update")
UA = "RouletteOfLegends/%s" % APP_VERSION


def installed_target():
    """What an update replaces: the exe's folder (Windows) or the .app bundle (macOS). None when this build can't
    update itself: source run, development build, or a location it can't write to."""
    if not getattr(sys, "frozen", False) or not BUNDLED_DATA:
        return None
    if MAC:
        app = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))
        # an app opened from a quarantined download runs from a read-only random path (App Translocation)
        if not app.endswith(".app") or "/AppTranslocation/" in app:
            return None
        return app if os.access(os.path.dirname(app), os.W_OK) and os.access(app, os.W_OK) else None
    probe = os.path.join(APP_DIR, ".write_test")
    try:
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
    except OSError:
        return None
    return APP_DIR


def _retry(fn, tries=15, delay=1.0):
    """For files still held for a moment by the closing app or an antivirus scan."""
    for i in range(tries):
        try:
            return fn()
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(delay)


def _remove(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)


def _copy(src, dst):
    if os.path.lexists(dst):   # left by a failed attempt
        _remove(dst)
    if MAC:
        subprocess.run(["ditto", src, dst], check=True)
    elif os.path.isdir(src):
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def cleanup():
    """Leftovers of a finished update (unpacked copy, previous files), removed at the next launch."""
    shutil.rmtree(STAGING, ignore_errors=True)
    target = installed_target()
    if not target:
        return
    folder = os.path.dirname(target) if MAC else target
    for name in os.listdir(folder):
        if name.endswith(".old") and (not MAC or name == os.path.basename(target) + ".old"):
            try:
                _remove(os.path.join(folder, name))
            except OSError:
                pass


class Installer(threading.Thread):
    """Downloads and unpacks a version, starts its finishing step, then closes the app."""

    def __init__(self, core, version):
        super().__init__(name="selfupdate", daemon=True)
        self.core = core
        self.version = version

    def run(self):
        try:
            finisher = self._prepare()
        except Exception as e:
            import traceback
            log_error("app update: " + traceback.format_exc())
            self.core.set_app_update_state({"state": "error", "text": T("La mise à jour n'a pas pu se faire (%s).") % e})
            return
        self.core.set_app_update_state({"state": "restart"})
        args = [finisher, "--finish-update", installed_target(), str(os.getpid())]
        if MAC:
            subprocess.Popen(args, start_new_session=True, close_fds=True)
        else:
            subprocess.Popen(args, creationflags=0x00000008 | 0x00000200, close_fds=True)   # detached, own group
        time.sleep(0.8)
        self.core.actions.put("quit")

    def _get(self, url, path=None, progress=None):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            if path is None:
                return r.read()
            total = int(r.headers.get("Content-Length") or 0)
            done, last = 0, 0.0
            with open(path, "wb") as f:
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress and total and time.time() - last > 0.25:
                        last = time.time()
                        progress(done / total)

    def _prepare(self):
        """Path of the new version's executable, ready to finish the update."""
        shutil.rmtree(STAGING, ignore_errors=True)
        os.makedirs(STAGING)
        sums = self._get(RELEASE_FILE % (self.version, CHECKSUMS)).decode("utf-8", "replace")
        expected = next((line.split()[0].lower() for line in sums.splitlines()
                         if len(line.split()) == 2 and line.split()[1].lstrip("*") == ARCHIVE), None)
        if not expected:
            raise IOError(T("fichier introuvable dans la version publiée"))
        archive = os.path.join(STAGING, ARCHIVE)
        self.core.set_app_update_state({"state": "download", "progress": 0})
        self._get(RELEASE_FILE % (self.version, ARCHIVE), archive,
                  lambda p: self.core.set_app_update_state({"state": "download", "progress": round(p, 3)}))
        h = hashlib.sha256()
        with open(archive, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != expected:
            raise IOError(T("téléchargement corrompu"))
        self.core.set_app_update_state({"state": "install"})
        out = os.path.join(STAGING, "new")
        if MAC:
            subprocess.run(["ditto", "-x", "-k", archive, out], check=True)
            exe = os.path.join(out, APP_NAME + ".app", "Contents", "MacOS", APP_NAME)
        else:
            with zipfile.ZipFile(archive) as z:
                z.extractall(out)
            exe = os.path.join(out, APP_NAME, APP_NAME + ".exe")
        os.remove(archive)
        if not os.path.isfile(exe):
            raise IOError(T("version téléchargée incomplète"))
        return exe


def _wait_exit(pid, timeout=60):
    end = time.time() + timeout
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
        if h:
            k32.WaitForSingleObject(h, int(timeout * 1000))
            k32.CloseHandle(h)
        return
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.3)


def finish(target, pid):
    """Run by the new version (from the unpacked copy): waits for the old app to exit, replaces its files, starts it.
    Each replaced entry is first renamed to <name>.old, and put back if anything fails."""
    _wait_exit(pid)
    if MAC:
        source = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))
        pairs = [(source, target)]
    else:
        source = os.path.dirname(os.path.abspath(sys.executable))
        pairs = [(os.path.join(source, n), os.path.join(target, n)) for n in os.listdir(source)]
    moved = []
    try:
        for src, dst in pairs:
            backup = dst + ".old"
            if os.path.lexists(backup):
                _retry(lambda: _remove(backup))
            if os.path.lexists(dst):
                _retry(lambda: os.rename(dst, backup))
            moved.append(dst)
            _retry(lambda: _copy(src, dst))
    except Exception:
        import traceback
        log_error("app update (install): " + traceback.format_exc())
        for dst in reversed(moved):
            try:
                if os.path.lexists(dst):
                    _remove(dst)
                if os.path.lexists(dst + ".old"):
                    os.rename(dst + ".old", dst)
            except OSError:
                log_error("app update (restore %s): failed" % dst)
        start(target, updated=False)
        return
    for dst in moved:
        try:
            _remove(dst + ".old")
        except OSError:
            pass   # removed at the next launch
    record_version(target)
    start(target, updated=True)


def record_version(target, version=APP_VERSION):
    """App installed with the setup: the version shown in Windows' installed apps follows the update."""
    if sys.platform != "win32":
        return
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\%s_is1" % INSTALLER_ID
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
            location = winreg.QueryValueEx(k, "InstallLocation")[0]
            if os.path.normcase(os.path.abspath(location)) == os.path.normcase(os.path.abspath(target)):
                winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, version)
    except OSError:
        pass


def start(target, updated):
    flag = ["--updated"] if updated else []
    if MAC:
        subprocess.Popen(["open", "-n", target, "--args"] + flag, close_fds=True)
    else:
        exe = os.path.join(target, os.path.basename(sys.executable))
        subprocess.Popen([exe] + flag, cwd=target, creationflags=0x00000008 | 0x00000200, close_fds=True)
