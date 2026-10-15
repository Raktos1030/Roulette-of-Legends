"""
Roulette of Legends
===================

Rolls a random role and/or champion, then shows a guide specific to that champion + role pair.

Run:    python roulette_lol.py            (or "Roulette of Legends\\Roulette of Legends.exe")
Check:  python roulette_lol.py --check    (every combo has its guide)
Flags:  --no-lol (no client link), --no-tray (no tray icon), --background (start hidden in the tray),
        --dev (server only, for a browser)

Layout:
  core.py        data, profile, rolls, history, client link (no UI)
  webserver.py   local server for the UI (ui/ folder) and the core API
  ui/            UI (HTML, CSS, JavaScript) shown in a WebView2 window (pywebview)
  overlay.py     in-game overlay (tkinter, transparent window)
  updater.py     automatic stats update
  system.py      tray icon, start with Windows, single instance
  lol_client.py  League client link
  live.py        current game data (overlay)
  imports.py     rune, summoner spell and item set import in champ select (optional)

Guides deliberately contain no runes or items: the overlay Items module and the champ select import handle those.
"""

import ctypes
import os
import queue
import sys
import threading
import time
import traceback

import core
from core import APP_NAME, DATA, MAC, log_error

if sys.platform == "win32":
    import ctypes.wintypes   # frameless window helpers

GUI = "edgechromium" if sys.platform == "win32" else None   # WebView2 on Windows, WKWebView on macOS


def load_fonts():
    """App fonts (Marcellus SC...) loaded for this process only (tkinter overlay)."""
    if sys.platform != "win32":
        return
    import glob
    try:
        for path in glob.glob(os.path.join(DATA, "fonts", "*.ttf")):
            ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0)
    except (AttributeError, OSError):
        pass


def _rgb(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return r | (g << 8) | (b << 16)


class WindowUI:
    """Main window (pywebview / WebView2), driven by the core and the tray icon.

    To stay light in the background, the WebView2 engine only exists while the window is used: hidden for
    RELEASE_AFTER seconds, it is destroyed, then recreated (with the last guide) when reopened.
    All windows are created on the main thread (run loop)."""

    RELEASE_AFTER = 60
    MIN_W, MIN_H = 1180, 760
    frameless = not MAC   # Windows: title bar drawn by the UI (ui/js/app.js); macOS: native window

    def __init__(self, core_, tray, url):
        self.core = core_
        self.tray = tray
        self.url = url
        self.window = None
        self._visible = False
        self.quitting = False
        self._open_req = threading.Event()
        self._release_timer = None
        self._lock = threading.Lock()
        self._restore_rect = None   # rect before maximize (frameless window, maximized by hand)
        self._track = None          # move / resize in progress (thread following the mouse)

    # --- main thread loop ---
    def run(self, start_hidden=False):
        import webview
        icon = os.path.join(DATA, "img", "app.ico")
        if not start_hidden:
            self._open_req.set()
        while not self.quitting:
            self._open_req.wait()
            if self.quitting:
                break
            self._open_req.clear()
            w = webview.create_window(
                APP_NAME, self.url, width=1440, height=920, min_size=(self.MIN_W, self.MIN_H),
                background_color="#04070d", text_select=False, zoomable=False, frameless=self.frameless,
                easy_drag=False, shadow=True)
            w.events.closing += self.on_closing
            w.events.shown += self._on_shown
            w.events.loaded += self._style
            with self._lock:
                self.window = w
            webview.start(gui=GUI, icon=icon if os.path.exists(icon) else None)
            with self._lock:
                self.window = None
                self._visible = False
            if not (self.tray and self.tray.running):
                break   # without a tray icon, closing the window quits the app

    def hwnd(self):
        w = self.window
        if not w:
            return None
        try:
            return w.native.Handle.ToInt32()
        except Exception:
            return None

    def _style(self):
        """Frameless window: rounded corners, thin dark border (Windows 11), drop shadow."""
        hwnd = self.hwnd()
        if not hwnd:
            return
        try:
            dwm = ctypes.windll.dwmapi

            def put(attr, value):
                v = ctypes.c_int(value)
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
            put(20, 1)                 # dark mode
            put(33, 2)                 # rounded corners
            put(34, _rgb("#1a1a1f"))   # nearly invisible border
        except (AttributeError, OSError):
            pass

    # --- UI title bar: minimize, maximize, close, move, resize ---
    def _rect(self, hwnd):
        r = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom

    def _work_area(self, hwnd):
        """Work area of the window's monitor (without the taskbar)."""
        class MI(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint32), ("rcMonitor", ctypes.wintypes.RECT),
                        ("rcWork", ctypes.wintypes.RECT), ("dwFlags", ctypes.c_uint32)]
        u = ctypes.windll.user32
        u.MonitorFromWindow.restype = ctypes.c_void_p
        mon = u.MonitorFromWindow(ctypes.wintypes.HWND(hwnd), 2)
        mi = MI()
        mi.cbSize = ctypes.sizeof(MI)
        u.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi))
        w = mi.rcWork
        return w.left, w.top, w.right, w.bottom

    def _set_rect(self, hwnd, l, t, r, b):
        ctypes.windll.user32.SetWindowPos(hwnd, None, int(l), int(t), int(r - l), int(b - t), 0x0004 | 0x0010)

    def window_action(self, action, edge=None):
        hwnd = self.hwnd()
        if not hwnd:
            return {"ok": False}
        u = ctypes.windll.user32
        if action == "minimize":
            u.ShowWindow(hwnd, 6)   # SW_MINIMIZE
        elif action == "maximize":
            self.toggle_maximize(hwnd)
        elif action == "close":
            if self.on_closing():
                self.quit()
        elif action in ("move", "resize"):
            self._start_track(hwnd, action, edge)
        return {"ok": True, "maximized": self._restore_rect is not None}

    def toggle_maximize(self, hwnd):
        if self._restore_rect:
            self._set_rect(hwnd, *self._restore_rect)
            self._restore_rect = None
        else:
            self._restore_rect = self._rect(hwnd)
            self._set_rect(hwnd, *self._work_area(hwnd))

    def _start_track(self, hwnd, action, edge):
        """Follows the mouse while the left button is down (real Windows positions, whatever the display scaling):
        moves the window, or resizes it by the grabbed edge or corner."""
        if self._track and self._track.is_alive():
            return
        u = ctypes.windll.user32
        pt = ctypes.wintypes.POINT()
        u.GetCursorPos(ctypes.byref(pt))
        start = (pt.x, pt.y)
        rect = self._rect(hwnd)
        scale = u.GetDpiForWindow(hwnd) / 96.0 if hasattr(u, "GetDpiForWindow") else 1.0
        minw, minh = self.MIN_W * scale, self.MIN_H * scale

        def loop():
            l, t, r, b = rect
            if action == "move" and self._restore_rect:
                # grabbing a maximized window: it restores its size under the mouse
                rl, rt, rr, rb = self._restore_rect
                w, h = rr - rl, rb - rt
                fx = (start[0] - l) / max(1, r - l)
                l, t = start[0] - fx * w, rect[1]
                r, b = l + w, t + h
                self._restore_rect = None
            base = (l, t, r, b)
            while u.GetAsyncKeyState(0x01) & 0x8000:
                p2 = ctypes.wintypes.POINT()
                u.GetCursorPos(ctypes.byref(p2))
                dx, dy = p2.x - start[0], p2.y - start[1]
                l, t, r, b = base
                if action == "move":
                    l, t, r, b = l + dx, t + dy, r + dx, b + dy
                else:
                    if "w" in edge:
                        l = min(l + dx, r - minw)
                    if "e" in edge:
                        r = max(r + dx, l + minw)
                    if "n" in edge:
                        t = min(t + dy, b - minh)
                    if "s" in edge:
                        b = max(b + dy, t + minh)
                self._set_rect(hwnd, l, t, r, b)
                time.sleep(0.008)
            if action == "move":   # dropped at the top of the screen: maximized, like a regular window
                p2 = ctypes.wintypes.POINT()
                u.GetCursorPos(ctypes.byref(p2))
                wl, wt, wr, wb = self._work_area(hwnd)
                if p2.y <= wt + 1:
                    self._restore_rect = base
                    self._set_rect(hwnd, wl, wt, wr, wb)
        self._track = threading.Thread(target=loop, name="fenetre", daemon=True)
        self._track.start()

    def _on_shown(self):
        self._visible = True
        self._style()

    def visible(self):
        return bool(self.window) and self._visible

    # --- commands (from any thread) ---
    def show(self):
        self._cancel_release()
        w = self.window
        if w is None:
            self._open_req.set()   # the main loop recreates the window
            return
        try:
            w.show()
            w.restore()
            self._visible = True
            hwnd = self.hwnd()
            if hwnd:
                u = ctypes.windll.user32
                u.ShowWindow(hwnd, 9)          # SW_RESTORE
                u.SetForegroundWindow(hwnd)
        except Exception:
            log_error("window show: " + traceback.format_exc())

    def hide(self, release=True):
        w = self.window
        if w is not None:
            try:
                w.hide()
            except Exception:
                pass
        self._visible = False
        if release:
            self._cancel_release()
            self._release_timer = threading.Timer(self.RELEASE_AFTER, self._release)
            self._release_timer.daemon = True
            self._release_timer.start()

    def hide_for_overlay(self):
        self._cancel_release()
        self.hide(release=False)

    def _cancel_release(self):
        if self._release_timer:
            self._release_timer.cancel()
            self._release_timer = None

    def _release(self):
        """Window hidden for a while: release WebView2 (the window is recreated when opened)."""
        w = self.window
        if w is not None and not self._visible:
            self._destroying = True
            try:
                w.destroy()
            except Exception:
                pass

    def on_closing(self):
        """Window close button: the app keeps running in the tray (when available)."""
        if self.quitting or not (self.tray and self.tray.running) or getattr(self, "_destroying", False):
            self._destroying = False
            return True
        threading.Thread(target=self.hide, daemon=True).start()
        if not self.core.profile.get("tray_hint_shown"):
            self.core.profile["tray_hint_shown"] = True
            self.tray.notify(core.T("La roulette continue de suivre tes parties ici. "
                                    "Clic droit sur l'icône → Quitter pour la fermer complètement."))
        return False

    def quit(self):
        self.quitting = True
        self._cancel_release()
        self._open_req.set()
        w = self.window
        if w is not None:
            try:
                w.destroy()
            except Exception:
                os._exit(0)

    def choose_folder(self, title):
        import webview
        w = self.window
        if w is None:
            return None
        try:
            res = w.create_file_dialog(webview.FileDialog.FOLDER)
        except Exception:
            return None
        if not res:
            return None
        return res[0] if isinstance(res, (list, tuple)) else res


def start_services(c, with_tray=True, with_overlay=True, with_updater=True):
    """Starts the core, local server, overlay, tray icon and updater. macOS: no tray icon or overlay (Lite only)."""
    import webserver
    if MAC:
        with_tray = with_overlay = False
    c.start()
    server = webserver.Server(c)
    server.start()
    overlay = None
    if with_overlay:
        from overlay import OverlayHost
        from live import LivePoller
        overlay = OverlayHost(c)   # also draws the tray menu, so the Lite starts it too
        overlay.start()
        if not core.LITE:
            c.poller = LivePoller(c)   # current game (Live Client Data), read for the overlay only
            c.poller.start()
    tray = None
    if with_tray:
        from system import Tray
        tray = Tray(c.actions, lambda: c.profile["overlay_mode"], menu_host=overlay.tray_menu if overlay else None)
        if not tray.start():
            tray = None
    c.tray = tray
    if with_updater:
        from updater import Updater
        c.updater = Updater(c)
        c.updater.start()
    return server, overlay, tray


def stop_services(c, server, overlay, tray):
    from system import release_single_instance
    c.stop()
    if overlay:
        overlay.stop()
    if tray:
        tray.stop()
    server.stop()
    release_single_instance()


# flags of older versions (French), still accepted: Windows startup entries may hold them
LEGACY_FLAGS = {"--sans-lol": "--no-lol", "--sans-icone": "--no-tray", "--arriere-plan": "--background"}


def run_app(args):
    from system import claim_single_instance, migrate_autostart
    actions = queue.Queue()
    if not claim_single_instance(actions):
        return   # already running: its window was just shown again
    migrate_autostart()
    c = core.Core(use_lol="--no-lol" not in args)
    c.actions = actions
    server, overlay, tray = start_services(c, with_tray="--no-tray" not in args)
    ui = WindowUI(c, tray, server.url)
    c.ui = ui
    try:
        ui.run(start_hidden="--background" in args and tray is not None)
    finally:
        stop_services(c, server, overlay, tray)


def run_dev(args):
    """Server only (development): open the printed address in a browser."""
    c = core.Core(use_lol="--no-lol" not in args)
    server, overlay, tray = start_services(c, with_tray=False, with_overlay="--overlay" in args, with_updater=False)
    print(server.url, flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_services(c, server, overlay, tray)


def autotest(path):
    """Self-test of the .exe: starts everything off-screen, checks the UI, then exits."""
    import webview
    lines = []

    def report():
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    try:
        c = core.Core(use_lol=False)
        server, overlay, tray = start_services(c, with_tray=True, with_overlay=True, with_updater=False)
        lines.append("BASE=%s" % core.BASE)
        lines.append("guides=%d combos=%d" % (len(c.data.guides), len(c.data.combos)))
        lines.append("glossary=%d" % len((c.data.glossary or {}).get("terms") or []))
        window = webview.create_window("Autotest", server.url, width=1300, height=860, x=-4000, y=60,
                                       background_color="#04070d")

        def drive():
            try:
                for _ in range(60):
                    time.sleep(0.5)
                    n = window.evaluate_js("document.querySelectorAll('.nav-item').length")
                    if n:
                        break
                lines.append("ui=%s tabs" % n)
                time.sleep(1.5)
                lines.append("font=%s" % window.evaluate_js("document.fonts.check('20px \"Marcellus SC\"')"))
                window.evaluate_js("location.hash='#/glossary'")
                time.sleep(0.8)
                lines.append("glossary_cards=%s" % window.evaluate_js("document.querySelectorAll('.lex-card').length"))
                window.evaluate_js("location.hash='#/guides'")
                time.sleep(1.0)
                lines.append("guide_list=%s portraits" % window.evaluate_js("document.querySelectorAll('.ltile').length"))
                window.evaluate_js("location.hash='#/roulette'")
                v = c.api_combo("Ahri|mid")
                lines.append("guide=%s" % (v.get("champ", {}).get("name")))
                d = c.data
                lines.append("imports=%d runes, %d builds, %d item prices" % (
                    sum(1 for x in d.combos.values() if x.get("runes")), sum(1 for x in d.combos.values() if x.get("items")),
                    len(d.item_prices)))
                ov = overlay.overlay if overlay and overlay.ready.wait(5) else None
                lines.append("overlay=%s modules" % (len(ov.panels) if ov else 0))
                if ov:   # render a module (fonts, transparency) without showing it
                    from overlay import Doc
                    doc = Doc(ov, 240)
                    doc.header("Stats", "vs average")
                    doc.para("Overlay test text.")
                    img = doc.render()[0]
                    lines.append("overlay_render=%dx%d %s" % (img.width, img.height, img.mode))
                    from overlay import font, coin_image
                    lines.append("lol_fonts=%s gold_coin=%s" % (font("num", 12).getname()[0], coin_image() is not None))
                cv = c.api_combo("Yuumi|jgl")
                lines.append("chaos=%s" % ("ok (closest guide %s)" % cv["chaos"]["from_label"] if cv.get("chaos") else cv))
                gr = c.api_group_roll([{"name": "Me", "me": True}, {"name": "Test"}])
                lines.append("group=%s" % ("ok" if gr.get("players") else gr))
                c.group = None
                lines.append("tray_icon=%s" % bool(tray and tray.running))
                lines.append("OK")
            except Exception:
                lines.append(traceback.format_exc())
            report()
            window.destroy()

        webview.start(drive, gui=GUI)
        stop_services(c, server, overlay, tray)
    except Exception:
        lines.append(traceback.format_exc())
    report()


def main():
    args = [LEGACY_FLAGS.get(a, a) for a in sys.argv[1:]]
    if "--check" in args:
        sys.exit(core.check())
    sys.excepthook = lambda t, v, tb: log_error("".join(traceback.format_exception(t, v, tb)))
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            # app-specific taskbar icon and grouping
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(core.APP_ID)
        except (AttributeError, OSError):
            pass
    load_fonts()
    if "--autotest" in args:
        autotest(args[args.index("--autotest") + 1])
        return
    if "--dev" in args:
        run_dev(args)
        return
    try:
        run_app(args)
    except Exception:
        log_error(traceback.format_exc())
        try:
            ctypes.windll.user32.MessageBoxW(0, core.T("L'application n'a pas pu démarrer. Détail dans data\\errors.log."),
                                             APP_NAME, 0x10)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
