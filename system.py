"""Windows integration: tray icon, start with Windows, single instance."""

import os
import socket
import sys
import threading

from core import APP_NAME, DATA, INSTANCE_PATH, LITE, OLD_NAMES, OVERLAY_MODES, T

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_command():
    """Startup command line (frozen .exe only)."""
    if getattr(sys, "frozen", False):
        return '"%s" --background' % os.path.abspath(sys.executable)
    return None


def autostart_enabled():
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, APP_NAME)
            return bool(value)
    except OSError:
        return False


def migrate_autostart():
    """Keeps the startup entry current: old app name replaced by the new one, exe path fixed if the folder was moved
    or renamed (same setting; nothing gets enabled without the user)."""
    cmd = autostart_command()
    if sys.platform != "win32" or not cmd:
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
            had = False
            for old in OLD_NAMES:
                try:
                    winreg.QueryValueEx(k, old)
                    winreg.DeleteValue(k, old)
                    had = True
                except OSError:
                    pass
            try:
                current, _ = winreg.QueryValueEx(k, APP_NAME)
                had = had or current != cmd
            except OSError:
                pass
        if had:
            set_autostart(True)
    except OSError:
        pass


def set_autostart(on):
    """Adds or removes the app from Windows startup (current user key, no admin rights)."""
    cmd = autostart_command()
    if sys.platform != "win32" or not cmd:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


# ----------------------------------------------------------------------------
# System memory (never add load when it's nearly full)
# ----------------------------------------------------------------------------

def memory_status():
    """(memory still available to programs, in bytes; RoL private memory, in bytes)."""
    import ctypes
    from ctypes import wintypes

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] + \
                   [(n, ctypes.c_ulonglong) for n in ("tp", "ap", "tpf", "apf", "tv", "av", "aev")]

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("pf", wintypes.DWORD)] + \
                   [(n, ctypes.c_size_t) for n in ("pws", "ws", "qppp", "qpp", "qpnp", "qnp", "pfu", "ppfu", "private")]
    ms = MS()
    ms.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    ctypes.windll.psapi.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return ms.apf, pmc.private


def biggest_process():
    """Process using the most memory (name, bytes), to tell the user. Read-only."""
    import ctypes
    from ctypes import wintypes
    psapi, k = ctypes.windll.psapi, ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("pf", wintypes.DWORD)] + \
                   [(n, ctypes.c_size_t) for n in ("pws", "ws", "qppp", "qpp", "qpnp", "qnp", "pfu", "ppfu", "private")]
    pids = (wintypes.DWORD * 4096)()
    got = wintypes.DWORD()
    if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(got)):
        return None
    totals = {}
    for pid in pids[:got.value // ctypes.sizeof(wintypes.DWORD)]:
        h = k.OpenProcess(0x1000, False, pid)   # limited information: read-only
        if not h:
            continue
        try:
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            buf = ctypes.create_unicode_buffer(520)
            n = wintypes.DWORD(520)
            if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb) and \
                    k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                name = os.path.basename(buf.value)
                totals[name] = totals.get(name, 0) + pmc.private
        finally:
            k.CloseHandle(h)
    return max(totals.items(), key=lambda kv: kv[1]) if totals else None


class Tray:
    """Tray icon (pystray, on its own thread). Clicks go to the core through a queue, never directly."""

    def __init__(self, actions, overlay_mode=None, menu_host=None):
        self.actions = actions
        self.overlay_mode = overlay_mode or (lambda: "tab")
        self.menu_host = menu_host   # menu drawn in the app's style (overlay); Windows menu otherwise
        self.icon = None
        self.running = False

    def start(self):
        try:
            import pystray
            from PIL import Image
        except ImportError:
            return False
        path = os.path.join(DATA, "img", "app.png")
        try:
            image = Image.open(path) if os.path.exists(path) else Image.new("RGB", (64, 64), (200, 170, 110))
        except OSError:
            image = Image.new("RGB", (64, 64), (200, 170, 110))
        items = [pystray.MenuItem(T("Ouvrir la roulette"), lambda icon, item: self.actions.put("show"), default=True)]

        def mode_item(val, lab):
            return pystray.MenuItem(lab, lambda icon, item: self.actions.put("overlay:" + val),
                                    checked=lambda item: self.overlay_mode() == val, radio=True)
        items.append(pystray.MenuItem(T("Overlay en jeu"), pystray.Menu(*[mode_item(v, l) for v, l in OVERLAY_MODES]),
                                      visible=lambda item: not LITE))
        if autostart_command():
            items.append(pystray.MenuItem(T("Lancer au démarrage de Windows"), self._toggle_autostart,
                                          checked=lambda item: autostart_enabled()))
        items += [pystray.Menu.SEPARATOR, pystray.MenuItem(T("Quitter"), lambda icon, item: self.actions.put("quit"))]
        tray = self

        class Icon(pystray.Icon):
            def _on_notify(icon, wparam, lparam):
                if lparam == 0x0205 and tray.menu_host:   # WM_RBUTTONUP: our menu instead of the gray one
                    try:
                        import ctypes
                        from ctypes import wintypes
                        pt = wintypes.POINT()
                        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                        if tray.menu_host(pt.x, pt.y):
                            return
                    except Exception:
                        pass
                super()._on_notify(wparam, lparam)

        self.icon = Icon("roulette_lol", image, APP_NAME, pystray.Menu(*items))
        self.running = True

        def run():
            try:
                self.icon.run()
            except Exception:   # the app stays usable without the tray icon
                self.running = False
        threading.Thread(target=run, name="icone", daemon=True).start()
        return True

    def _toggle_autostart(self, icon, item):
        set_autostart(not autostart_enabled())

    def notify(self, text):
        try:
            if self.icon:
                self.icon.notify(text, APP_NAME)
        except Exception:
            pass

    def stop(self):
        self.running = False
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass


# Single instance: launching the app again shows the window already open.
_instance_server = None


def claim_single_instance(actions):
    """True if this instance is the only one; otherwise asks the other one to show up and returns False."""
    global _instance_server
    try:
        with open(INSTANCE_PATH, encoding="utf-8") as f:
            port = int(f.read().strip())
        with socket.create_connection(("127.0.0.1", port), timeout=1.5) as s:
            s.sendall(b"roulette-lol:show")
            if s.recv(16) == b"ok":
                return False
    except (OSError, ValueError):
        pass
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(2)
        with open(INSTANCE_PATH, "w", encoding="utf-8") as f:
            f.write(str(srv.getsockname()[1]))
    except OSError:
        srv.close()
        return True
    _instance_server = srv

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(2)
                    if conn.recv(64) == b"roulette-lol:show":
                        actions.put("show")
                        conn.sendall(b"ok")
                except OSError:
                    pass
    threading.Thread(target=serve, name="instance", daemon=True).start()
    return True


def release_single_instance():
    global _instance_server
    if _instance_server is not None:
        try:
            _instance_server.close()
        except OSError:
            pass
        _instance_server = None
        try:
            os.remove(INSTANCE_PATH)
        except OSError:
            pass
