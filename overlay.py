"""
In-game overlay: several small transparent modules (tkinter, on their own thread).

  Guide       guide summary; the page follows the game clock (early, laning, mid & late), Tab + click to switch
  Skills      the skill to level lights up in blue right on the game HUD (located on screen, whatever the HUD
              scale); with Tab, a small strip of the next skills
  Stats       CS, gold, kill participation and vision per minute, against the player's average
  Items       most played build: starting items, core trio, options for items 4 to 6
  Gold diff   item value per scoreboard row, placed next to each ally on the scoreboard (Tab), located on
              screen like the HUD icons; separate block when the scoreboard isn't found
  Objectives  next spawns of drakes, Baron, Herald and inhibitors

Each module shows while holding Tab or always (setting), is hidden or pinned with its shortcut (Ctrl + letter)
and moves by dragging its header (Tab held, or "Place on screen" from the settings): corners, edge centers and
its default spot snap it; it never leaves the screen or the game.

Riot rules: only what the game already shows everyone (scoreboard, objective announcements, clock) or data
prepared before the game (guide, skill order, build). No enemy ability tracking, no alerts, no instructions.
Requires LoL in borderless or windowed mode.
"""

import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

import hud
import live
from analysis import counter_items, guess_roles, matchup_vs, strip_goal, team_profile, third_person
from core import (APP_DIR, DATA, GAMES_DIR, LITE, ROLES, ROLE_LABEL, ROLE_LONG, ROLE_ICON, OVERLAY_PAGES, OVERLAY_MODULES,
                  fmt_int, fmt_pct, log_error, T)

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

BG = "#070E1A"
PANEL = "#0A1422"
PANEL2 = "#122238"
LINE = "#1C2B3F"
GOLD_D = "#785A28"
GOLD = "#C8AA6E"
GOLD_L = "#F0E6D2"
TEXT = "#E4DDCF"
MUTED = "#8F8B82"
TEAL = "#0AC8B9"
GREEN = "#3FD18C"
RED = "#F0506E"
BLUE = "#4FB4FF"
BLUE_D = "#1B4F80"
KEY = "#010203"   # color keyed to transparent
ANCHORS = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (0.0, 0.5), (1.0, 0.5), (0.0, 1.0), (0.5, 1.0), (1.0, 1.0)]
MODULES = {m["id"]: m for m in OVERLAY_MODULES}
VK_TAB, VK_RETURN, VK_CONTROL = 0x09, 0x0D, 0x11


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def spaced(text):
    return " ".join(text)


def chamfer(x0, y0, x1, y1, c):
    return [x0 + c, y0, x1 - c, y0, x1, y0 + c, x1, y1 - c, x1 - c, y1, x0 + c, y1, x0, y1 - c, x0, y0 + c]


def signed(v, unit=""):
    v = int(round(v))
    s = fmt_int(abs(v)) + unit
    return ("+" if v > 0 else "−" if v < 0 else "") + s


def fr_dec(v, n=1):
    return ("%.*f" % (n, v)).replace(".", ",")


class Images:
    """PIL images for the overlay: champions, roles, skills, items (original size, scaled at render)."""

    def __init__(self):
        self.cache = {}

    def _load(self, k, path, color=None):
        if k in self.cache:
            return self.cache[k]
        im = None
        if path and os.path.exists(path) and HAS_PIL:
            try:
                im = Image.open(path).convert("RGBA")
                if color:
                    lum = im.convert("L").point(lambda v: min(255, int(v * 255 / 176)))
                    chans = [lum.point(lambda v, c=c: int(v * c / 255)) for c in color]
                    out = Image.merge("RGB", chans)
                    out.putalpha(im.getchannel("A"))
                    im = out
            except OSError:
                im = None
        self.cache[k] = im
        return im

    def icon(self, key):
        return self._load(("icon", key), os.path.join(DATA, "img", "icons", "%s.png" % key) if key else None)

    def spell(self, key, slot):
        return self._load(("spell", key, slot), os.path.join(DATA, "img", "spells", "%s_%s.png" % (key, slot)))

    def item(self, iid):
        return self._load(("item", iid), os.path.join(DATA, "img", "items", "%s.png" % iid))

    def role_icon(self, role, color=None):
        return self._load(("role", role, color), os.path.join(DATA, "img", "roles", "%s.png" % ROLE_ICON.get(role, "fill")),
                          color)


def gold_txt(v):
    """Compact gold diff: +540, −120, +1.2k."""
    v = int(round(v))
    sign = "+" if v > 0 else "−" if v < 0 else ""
    a = abs(v)
    if a >= 1000:
        return "%s%sk" % (sign, ("%.1f" % (a / 1000.0)).replace(".", ",").replace(",0", ""))
    return "%s%d" % (sign, a)


class Win32:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetAncestor.restype = wintypes.HWND
        u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowLongW.restype = ctypes.c_long
        u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.UINT]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.FindWindowW.restype = wintypes.HWND
        self.ctypes, self.wintypes, self.u = ctypes, wintypes, u

    def root_hwnd(self, win):
        return self.u.GetAncestor(win.winfo_id(), 2)

    def set_style(self, win, clickable):
        """Layered, off the taskbar, never activated; clicks pass through unless clickable."""
        hwnd = self.root_hwnd(win)
        ex = self.u.GetWindowLongW(hwnd, -20) | 0x80000 | 0x80 | 0x08000000
        ex = ex & ~0x20 if clickable else ex | 0x20
        self.u.SetWindowLongW(hwnd, -20, ex)

    def topmost(self, win):
        # topmost without activation (SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        self.u.SetWindowPos(self.root_hwnd(win), self.wintypes.HWND(-1), 0, 0, 0, 0, 0x1 | 0x2 | 0x10 | 0x40)

    def rect(self, hwnd):
        r = self.wintypes.RECT()
        if hwnd and self.u.GetWindowRect(hwnd, self.ctypes.byref(r)):
            return r.left, r.top, r.right, r.bottom
        return None

    def lol_window(self):
        return self.u.FindWindowW("RiotWindowClass", None) or None

    def foreground(self):
        return self.u.GetForegroundWindow()

    def cursor(self):
        pt = self.wintypes.POINT()
        self.u.GetCursorPos(self.ctypes.byref(pt))
        return pt.x, pt.y

    def work_area(self, x, y):
        """Work area (without the taskbar) of the monitor containing the point."""
        ct, wt = self.ctypes, self.wintypes

        class MI(ct.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
        self.u.MonitorFromPoint.restype = wt.HANDLE
        self.u.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
        mon = self.u.MonitorFromPoint(wt.POINT(int(x), int(y)), 2)
        mi = MI()
        mi.cbSize = ct.sizeof(MI)
        if mon and self.u.GetMonitorInfoW(mon, ct.byref(mi)):
            r = mi.rcWork
            return r.left, r.top, r.right, r.bottom
        return 0, 0, self.u.GetSystemMetrics(0), self.u.GetSystemMetrics(1)

    def key_down(self, vk):
        return bool(self.u.GetAsyncKeyState(vk) & 0x8000)   # reads the key state, nothing else


# ----------------------------------------------------------------------------
# Rendering: each module is drawn as an image (PIL, at 2x then downscaled for smooth edges) and shown through
# a per-pixel alpha layered window (UpdateLayeredWindow): crisp rounded corners, soft shadow,
# real translucency, text drawn straight over the game without a box.
# ----------------------------------------------------------------------------

SS = 2   # drawing supersampling

# League UI palette (midnight blue, gold, golden gray)
C_PANEL_TOP = (13, 23, 40)
C_PANEL_BOT = (3, 9, 18)
C_GOLD = (200, 170, 110)
C_GOLD_D = (120, 90, 40)
C_GOLD_L = (240, 230, 210)
C_TEXT = (232, 224, 206)
C_MUTED = (160, 155, 140)
C_DIM = (110, 108, 100)
C_GREEN = (72, 214, 146)
C_RED = (238, 78, 98)
C_BLUE = (100, 190, 255)
C_TEAL = (10, 200, 185)
BOARD_TEXT = (220, 214, 196)      # off-white scoreboard digits
BOARD_GREEN = (98, 206, 128)
BOARD_RED = (232, 86, 86)

# game fonts (Spiegel, Beaufort for LoL), extracted from the LoL install by lolassets; Segoe / Cinzel otherwise
_LOL_FONTS = os.path.join(DATA, "fonts", "lol")
_FONT_FILES = {
    "ui": [os.path.join(_LOL_FONTS, "Spiegel-Regular.otf"), r"C:\Windows\Fonts\segoeui.ttf"],
    "ui_b": [os.path.join(_LOL_FONTS, "Spiegel-SemiBold.otf"), r"C:\Windows\Fonts\seguisb.ttf",
             r"C:\Windows\Fonts\segoeuib.ttf"],
    "ui_bb": [os.path.join(_LOL_FONTS, "Spiegel-Bold.otf"), r"C:\Windows\Fonts\segoeuib.ttf",
              r"C:\Windows\Fonts\seguisb.ttf"],
    "disp": [os.path.join(_LOL_FONTS, "BeaufortforLOL-Bold.otf"), os.path.join(DATA, "fonts", "Cinzel-700.ttf"),
             os.path.join(DATA, "fonts", "MarcellusSC-Regular.ttf")],
    "disp_b": [os.path.join(_LOL_FONTS, "BeaufortforLOL-Heavy.otf"), os.path.join(DATA, "fonts", "Cinzel-800.ttf"),
               os.path.join(DATA, "fonts", "Cinzel-700.ttf")],
    # numbers: the game writes CS, KDA and gold in Beaufort for LoL Bold
    "num": [os.path.join(_LOL_FONTS, "BeaufortforLOL-Bold.otf"), r"C:\Windows\Fonts\seguisb.ttf"],
}
_COIN = []


def coin_image():
    """HUD gold coin (extracted by lolassets), or None: a drawn coin is used then."""
    if not _COIN:
        try:
            _COIN.append(Image.open(os.path.join(DATA, "img", "ui", "gold.png")).convert("RGBA"))
        except (OSError, ValueError):
            _COIN.append(None)
    return _COIN[0]
_FONTS = {}


def font(kind, size):
    """Font (size in pixels, already scaled)."""
    k = (kind, int(round(size * SS)))
    if k not in _FONTS:
        f = None
        for path in _FONT_FILES[kind]:
            try:
                f = ImageFont.truetype(path, k[1])
                break
            except OSError:
                continue
        _FONTS[k] = f or ImageFont.load_default()
    return _FONTS[k]


def rgba(c, a=255):
    return (c[0], c[1], c[2], int(a))


class Doc:
    """A module being drawn: top-down layout, then rendered as an RGBA image."""

    def __init__(self, ov, width, pad=12, panel=True, style="panel"):
        self.ov = ov
        self.S = ov.S
        self.style = style        # "panel": game-window-like frame; "bare": sits on the HUD, no frame
        if style == "bare":
            pad = 8
        self.W = int(round(width * self.S))
        self.pad = self.px(pad)
        self.inner = self.W - 2 * self.pad
        self.y = self.px(10)
        self.ops = []           # (draw function, args) in final coordinates
        self.regions = []       # clickable areas: (x0, y0, x1, y1, action)
        self.header_h = 0
        self.panel = panel

    def px(self, v):
        return int(round(v * self.S))

    def f(self, kind, size):
        return font(kind, size * self.S)

    # --- text measurement ---
    def tw(self, s, fnt, track=0):
        return (fnt.getlength(s) + (len(s) - 1) * track * SS) / SS if s else 0

    def lh(self, fnt):
        a, d = fnt.getmetrics()
        return (a + d) / SS

    def wrap(self, s, fnt, maxw):
        out, cur = [], ""
        for word in s.split():
            t = (cur + " " + word) if cur else word
            if self.tw(t, fnt) <= maxw or not cur:
                cur = t
            else:
                out.append(cur)
                cur = word
        if cur:
            out.append(cur)
        return out

    # --- primitives (recorded, drawn at render) ---
    def text(self, x, y, s, fnt, color, anchor="l", track=0, alpha=255):
        """Text; y = top of the line; anchor: l (left), r (right), m (center). Returns the box."""
        w = self.tw(s, fnt, track)
        x0 = x if anchor == "l" else x - w if anchor == "r" else x - w / 2
        self.ops.append(("text", x0, y, s, fnt, rgba(color, alpha), track))
        return (x0, y, x0 + w, y + self.lh(fnt))

    def lines(self, x, y, s, fnt, color, maxw, spacing=1.32, alpha=255):
        """Paragraph; returns the bottom of the text."""
        lh = self.lh(fnt) * spacing
        for i, line in enumerate(self.wrap(s, fnt, maxw)):
            self.ops.append(("text", x, y + i * lh, line, fnt, rgba(color, alpha), 0))
        n = max(1, len(self.wrap(s, fnt, maxw)))
        return y + (n - 1) * lh + self.lh(fnt)

    def rect(self, x0, y0, x1, y1, fill=None, outline=None, width=1, radius=0):
        self.ops.append(("rect", x0, y0, x1, y1, fill, outline, width, radius))

    def line(self, x0, y0, x1, y1, color, width=1):
        self.ops.append(("line", x0, y0, x1, y1, color, width))

    def dot(self, cx, cy, r, color):
        self.ops.append(("dot", cx, cy, r, color))

    def check(self, cx, cy, r, color):
        self.ops.append(("check", cx, cy, r, color))

    def tri(self, cx, cy, r, up, color):
        """Small ▲ / ▼ triangle (the game fonts lack these glyphs)."""
        self.ops.append(("tri", cx, cy, r, up, color))

    def image(self, x, y, im, size, radius=3, gray=False, ring=None, alpha=255):
        if im is None:
            self.rect(x, y, x + size, y + size, fill=rgba(C_PANEL_TOP, alpha), outline=rgba(C_GOLD_D, 160 * alpha // 255),
                      radius=radius)
            return
        self.ops.append(("image", x, y, im, size, radius, gray, ring, alpha))

    def region(self, x0, y0, x1, y1, action):
        self.regions.append((x0, y0, x1, y1, action))

    # --- layout blocks ---
    def grip(self):
        """Small golden grip at the top center (the top of a module drags it)."""
        gx, gy = self.W / 2, self.px(4)
        for i in range(-2, 3):
            self.dot(gx + i * self.px(5), gy, max(1.0, 1.0 * self.S), rgba(C_GOLD_D, 230))

    def header(self, title, right=None, right_color=C_MUTED):
        if self.style == "bare":   # small label, like the widgets built into the HUD
            y = self.px(5)
            self.text(self.pad, y, title.upper(), self.f("disp", 9), C_GOLD, track=1.2)
            if right:
                self.text(self.W - self.pad, y + self.px(0.5), right, self.f("ui", 10), right_color, anchor="r")
            self.y = y + self.px(17)
            self.header_h = self.y
            return self.y
        self.grip()
        y = self.px(9)
        self.text(self.pad, y, title.upper(), self.f("disp", 10), C_GOLD, track=1.3)
        if right:
            self.text(self.W - self.pad, y + self.px(1), right, self.f("ui", 10.5), right_color, anchor="r")
        self.y = y + self.px(18)
        self.line(self.pad, self.y, self.W - self.pad, self.y, rgba(C_GOLD, 40))
        self.y += self.px(7)
        self.header_h = self.y
        return self.y

    def section(self, title):
        self.y += self.px(7)
        self.text(self.pad, self.y, title.upper(), self.f("disp", 9.5), C_GOLD, track=1.2)
        self.y += self.px(15)

    def para(self, s, color=C_TEXT, fnt=None, bullet=False, label=None, size=12):
        if not s:
            return
        fnt = fnt or self.f("ui", size)
        x = self.pad
        if bullet:
            cy = self.y + self.lh(fnt) * 0.55
            r = self.px(2.2)
            self.ops.append(("diamond", x + r, cy, r, rgba(C_GOLD, 220)))
            x += self.px(11)
        if label:
            b = self.text(x, self.y, label, self.f("ui_b", size), C_GOLD_L)
            x = b[2] + self.px(5)
            # text continues after the label, then wraps back to the left
            words = s.split()
            first, rest = "", list(words)
            while rest and self.tw((first + " " + rest[0]).strip(), fnt) <= self.W - self.pad - x:
                first = (first + " " + rest.pop(0)).strip()
            self.text(x, self.y, first, fnt, color)
            if rest:
                self.y += self.lh(fnt) * 1.32
                self.y = self.lines(self.pad, self.y, " ".join(rest), fnt, color, self.inner)
            else:
                self.y += self.lh(fnt)
        else:
            self.y = self.lines(x, self.y, s, fnt, color, self.W - self.pad - x)
        self.y += self.px(4)

    # --- rendering ---
    def render(self, placing=False):
        """Final RGBA image (with the shadow margin around the panel) and the margin used."""
        bare = self.style == "bare"
        H = int(round(self.y + self.px(4 if bare else 9)))
        m = self.px(10 if bare else 8) if self.panel else 0
        W2, H2, M2 = self.W * SS, H * SS, m * SS
        img = Image.new("RGBA", (W2 + 2 * M2, H2 + 2 * M2), (0, 0, 0, 0))
        r = self.px(6) * SS
        if self.panel and bare:
            # very soft dark veil fading at the edges (readable without a frame); golden line while placing
            veil = Image.new("L", img.size, 0)
            ImageDraw.Draw(veil).rounded_rectangle((M2, M2, M2 + W2, M2 + H2), r, fill=150)
            veil = veil.filter(ImageFilter.GaussianBlur(7 * SS))
            img.paste((2, 6, 12, 255), (0, 0), veil)
            img.putalpha(veil)
            if placing:
                ImageDraw.Draw(img).rounded_rectangle((M2, M2, M2 + W2 - 1, M2 + H2 - 1), r, outline=rgba(C_GOLD, 220),
                                                      width=SS)
        elif self.panel:
            # soft shadow
            sh = Image.new("L", img.size, 0)
            ImageDraw.Draw(sh).rounded_rectangle((M2, M2 + 2 * SS, M2 + W2, M2 + H2 + 2 * SS), r, fill=150)
            sh = sh.filter(ImageFilter.GaussianBlur(5 * SS))
            img.paste((0, 0, 0, 255), (0, 0), sh)
            img.putalpha(sh)
            # background: translucent midnight blue vertical gradient
            grad = Image.new("RGBA", (1, 2))
            grad.putpixel((0, 0), rgba(C_PANEL_TOP, 236))
            grad.putpixel((0, 1), rgba(C_PANEL_BOT, 236))
            grad = grad.resize((W2, H2), Image.BILINEAR)
            mask = Image.new("L", (W2, H2), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, W2 - 1, H2 - 1), r, fill=255)
            panel = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
            panel.paste(grad, (0, 0), mask)
            img.alpha_composite(panel, (M2, M2))
            d = ImageDraw.Draw(img)
            # golden border + top highlight (like the game frames)
            d.rounded_rectangle((M2, M2, M2 + W2 - 1, M2 + H2 - 1), r, outline=rgba(C_GOLD if placing else C_GOLD_D,
                                                                                    255 if placing else 210), width=SS)
            d.line((M2 + r, M2 + SS * 1.5, M2 + W2 - r, M2 + SS * 1.5), fill=rgba(C_GOLD, 46), width=SS)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        o = M2

        def P(v):
            return v * SS
        for op in self.ops:
            kind = op[0]
            if kind == "text":
                _, x, y, s, fnt, col, track = op
                if bare:   # one-pixel drop shadow, like the game text
                    sc = (0, 0, 0, min(220, col[3]))
                    if track:
                        cx = o + P(x) + SS
                        for ch in s:
                            d.text((cx, o + P(y) + SS), ch, font=fnt, fill=sc, anchor="la")
                            cx += fnt.getlength(ch) + track * SS
                    else:
                        d.text((o + P(x) + SS, o + P(y) + SS), s, font=fnt, fill=sc, anchor="la")
                if track:
                    cx = o + P(x)
                    for ch in s:
                        d.text((cx, o + P(y)), ch, font=fnt, fill=col, anchor="la")
                        cx += fnt.getlength(ch) + track * SS
                else:
                    d.text((o + P(x), o + P(y)), s, font=fnt, fill=col, anchor="la")
            elif kind == "rect":
                _, x0, y0, x1, y1, fill, outline, width, rad = op
                box = (o + P(x0), o + P(y0), o + P(x1), o + P(y1))
                d.rounded_rectangle(box, P(rad), fill=fill, outline=outline, width=int(P(width)) if outline else 0)
            elif kind == "line":
                _, x0, y0, x1, y1, col, width = op
                d.line((o + P(x0), o + P(y0), o + P(x1), o + P(y1)), fill=col, width=int(max(1, P(width))))
            elif kind == "dot":
                _, cx, cy, rr, col = op
                d.ellipse((o + P(cx - rr), o + P(cy - rr), o + P(cx + rr), o + P(cy + rr)), fill=col)
            elif kind == "diamond":
                _, cx, cy, rr, col = op
                X, Y, R = o + P(cx), o + P(cy), P(rr)
                d.polygon([(X, Y - R), (X + R, Y), (X, Y + R), (X - R, Y)], fill=col)
            elif kind == "tri":
                _, cx, cy, rr, up, col = op
                X, Y, R = o + P(cx), o + P(cy), P(rr)
                h = R * 0.8 * (1 if up else -1)
                d.polygon([(X, Y - h), (X + R, Y + h), (X - R, Y + h)], fill=col)
            elif kind == "check":
                _, cx, cy, rr, col = op
                X, Y, R = o + P(cx), o + P(cy), P(rr)
                d.line([(X - R, Y), (X - R * 0.25, Y + R * 0.7), (X + R, Y - R * 0.65)], fill=col, width=int(max(2, R * 0.45)),
                       joint="curve")
            elif kind == "image":
                _, x, y, im, size, rad, gray, ring, al = op
                s2 = int(round(P(size)))
                pic = im.resize((s2, s2), Image.LANCZOS)
                if gray:
                    a = pic.getchannel("A")
                    pic = Image.merge("RGBA", (*[pic.convert("L").point(lambda v: v * 0.55)] * 3, a))
                mask = Image.new("L", (s2, s2), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, s2 - 1, s2 - 1), int(P(rad)), fill=255)
                a = Image.composite(pic.getchannel("A"), Image.new("L", (s2, s2), 0), mask)
                if al < 255:
                    a = a.point(lambda v: v * al // 255)
                pic.putalpha(a)
                layer.alpha_composite(pic, (int(o + P(x)), int(o + P(y))))
                d.rounded_rectangle((o + P(x), o + P(y), o + P(x) + s2 - 1, o + P(y) + s2 - 1), int(P(rad)),
                                    outline=ring or (0, 0, 0, 150 * al // 255), width=int(P(1.6)) if ring else SS)
        img.alpha_composite(layer)
        out = img.resize((img.width // SS, img.height // SS), Image.LANCZOS)
        return out, m, (self.W, H)


class Layer:
    """Pushes an RGBA image to a layered window (per-pixel alpha)."""

    _api = None

    @classmethod
    def api(cls):
        if cls._api is None:
            import ctypes
            from ctypes import wintypes
            u, g = ctypes.windll.user32, ctypes.windll.gdi32

            class BLEND(ctypes.Structure):
                _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("alpha", ctypes.c_ubyte),
                            ("fmt", ctypes.c_ubyte)]

            class BIH(ctypes.Structure):
                _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                            ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                            ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32), ("a", ctypes.c_int32),
                            ("b", ctypes.c_int32), ("c", ctypes.c_uint32), ("d", ctypes.c_uint32)]
            u.GetDC.restype = wintypes.HDC
            u.GetDC.argtypes = [wintypes.HWND]
            u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            g.CreateCompatibleDC.restype = wintypes.HDC
            g.CreateCompatibleDC.argtypes = [wintypes.HDC]
            g.CreateDIBSection.restype = wintypes.HBITMAP
            g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                           wintypes.HANDLE, wintypes.DWORD]
            g.SelectObject.restype = wintypes.HGDIOBJ
            g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
            g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
            g.DeleteDC.argtypes = [wintypes.HDC]
            u.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                              ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                              wintypes.DWORD, ctypes.POINTER(BLEND), wintypes.DWORD]
            cls._api = (ctypes, wintypes, u, g, BLEND, BIH)
        return cls._api

    @classmethod
    def push(cls, hwnd, im, x, y, alpha):
        ctypes, wintypes, u, g, BLEND, BIH = cls.api()
        w, h = im.size
        data = im.convert("RGBa").tobytes("raw", "BGRa")   # premultiplied colors, as Windows expects
        screen = u.GetDC(None)
        mdc = g.CreateCompatibleDC(screen)
        bi = BIH()
        bi.biSize, bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = ctypes.sizeof(BIH), w, -h, 1, 32
        bits = ctypes.c_void_p()
        bmp = g.CreateDIBSection(mdc, ctypes.byref(bi), 0, ctypes.byref(bits), None, 0)
        ok = False
        if bmp and bits:
            ctypes.memmove(bits, data, len(data))
            old = g.SelectObject(mdc, bmp)
            ok = u.UpdateLayeredWindow(hwnd, screen, ctypes.byref(wintypes.POINT(int(x), int(y))),
                                       ctypes.byref(wintypes.SIZE(w, h)), mdc, ctypes.byref(wintypes.POINT(0, 0)), 0,
                                       ctypes.byref(BLEND(0, 0, max(0, min(255, int(alpha * 255))), 1)), 2)
            g.SelectObject(mdc, old)
            g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(None, screen)
        return bool(ok)

    @classmethod
    def set_alpha(cls, hwnd, alpha):
        ctypes, wintypes, u, g, BLEND, BIH = cls.api()
        return bool(u.UpdateLayeredWindow(hwnd, None, None, None, None, None, 0,
                                          ctypes.byref(BLEND(0, 0, max(0, min(255, int(alpha * 255))), 1)), 2))


# ----------------------------------------------------------------------------
# One module = one layered window (per-pixel alpha image)
# ----------------------------------------------------------------------------

class Panel:
    def __init__(self, ov, mid):
        self.ov, self.id = ov, mid
        w = tk.Toplevel(ov.root)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        tk.Frame(w, bg="#000000", highlightthickness=0, bd=0).pack(fill="both", expand=True)
        w.geometry("1x1+-50+-50")
        w.deiconify()
        w.update_idletasks()
        self.win = w
        self.hwnd = ov.w32.root_hwnd(w)
        ov.w32.set_style(w, clickable=False)   # layered: invisible until an image is set
        self.visible = False
        self.clickable = False
        self.image = None
        self.margin = 0
        self.size = (1, 1)        # panel size (without the shadow margin)
        self.regions = []
        self.header_h = 0
        self.sig = None
        self.pos_px = None        # panel top-left corner on screen
        self.drag = None
        self._alpha = 0.0
        w.bind("<ButtonPress-1>", self._press)
        w.bind("<B1-Motion>", self._motion)
        w.bind("<ButtonRelease-1>", self._release)
        w.bind("<Motion>", self._hover)

    def set_image(self, img, margin, size, regions=(), header_h=0):
        self.image, self.margin, self.size = img, margin, size
        self.regions, self.header_h = list(regions), header_h

    def push(self):
        if self.image is None or self.pos_px is None:
            return
        x, y = self.pos_px[0] - self.margin, self.pos_px[1] - self.margin
        self.win.geometry("%dx%d+%d+%d" % (self.image.width, self.image.height, x, y))
        Layer.push(self.hwnd, self.image, x, y, self._alpha if self.visible else 0.0)

    def set_alpha(self, a):
        self._alpha = a
        if self.image is not None:
            Layer.set_alpha(self.hwnd, a if self.visible else 0.0)

    def set_click(self, click):
        if click != self.clickable:
            self.ov.w32.set_style(self.win, click)
            self.clickable = click

    def show(self, alpha=None):
        a = self.ov.alpha() if alpha is None else alpha
        if not self.visible or abs(a - self._alpha) > 0.004:
            self.visible = True
            self.set_alpha(a)
            self.ov.w32.topmost(self.win)

    def hide(self):
        if self.visible:
            self.visible = False
            self.set_alpha(self._alpha)
        self.drag = None
        self.set_click(False)

    def place(self):
        rect = self.ov.ref_rect()
        pos = self.ov.pos_of(self.id) if self.id in MODULES or self.id == "_controls" else {"fx": 0, "fy": 0}
        self.pos_px = self.ov.px_for(pos["fx"], pos["fy"], rect, self.size)
        self.push()

    # --- clicks and drag (by the top of the module) ---
    def _local(self, e):
        return e.x - self.margin, e.y - self.margin

    def _hit(self, e):
        x, y = self._local(e)
        return next((r[4] for r in self.regions if r[0] <= x <= r[2] and r[1] <= y <= r[3]), None)

    def _hover(self, e):
        if self.clickable and self.id in MODULES:
            x, y = self._local(e)
            self.win.configure(cursor="hand2" if self._hit(e) else "fleur" if 0 <= y < self.header_h else "")

    def _press(self, e):
        if not self.clickable or self.id not in MODULES or self._hit(e):
            return
        if self._local(e)[1] >= self.header_h:
            return
        self.drag = {"dx": e.x_root - self.pos_px[0], "dy": e.y_root - self.pos_px[1], "snap": None}
        self.ov.show_anchors(self)

    def _motion(self, e):
        if not self.drag:
            return
        ov = self.ov
        rect = ov.ref_rect()
        w, h = self.size
        x, y = e.x_root - self.drag["dx"], e.y_root - self.drag["dy"]
        left, top, right, bottom = rect
        m = ov.margin()
        x = min(max(x, left + m), right - m - w)   # never off the screen / game
        y = min(max(y, top + m), max(top + m, bottom - m - h))
        snap = None
        radius = 60 * ov.S0
        for fx, fy in ov.anchors_for(self.id):
            ax, ay = ov.px_for(fx, fy, rect, (w, h))
            if abs(ax - x) < radius and abs(ay - y) < radius:
                snap = (fx, fy)
                x, y = ax, ay
                break
        if not snap:   # edges of the other modules: sit right above, below or beside, aligned
            best = None
            for tx, ty in ov.edge_spots(self):
                d = max(abs(tx - x), abs(ty - y))
                if d < 26 * ov.S0 and (best is None or d < best[0]):
                    best = (d, tx, ty)
            if best and left + m <= best[1] <= right - m - w and top + m <= best[2] <= bottom - m - h:
                x, y = best[1], best[2]
                snap = ("px", x, y)
        self.pos_px = (x, y)
        self.win.geometry("+%d+%d" % (x - self.margin, y - self.margin))
        self.win.update_idletasks()
        if snap != self.drag["snap"]:
            self.drag["snap"] = snap
            ov.show_anchors(self, active=snap)

    def _release(self, e):
        if not self.drag:
            action = self._hit(e) if self.clickable else None
            if action:
                action()
            return
        ov = self.ov
        snap = self.drag["snap"]
        if snap and snap[0] != "px":
            fx, fy = snap
        else:
            fx, fy = ov.fraction_for(self.pos_px[0], self.pos_px[1], ov.ref_rect(), self.size)
        self.drag = None
        ov.hide_anchors()
        ov.core.overlay_position_saved(self.id, {"fx": round(fx, 4), "fy": round(fy, 4)})


class HudWatcher(threading.Thread):
    """Locates the skill icons on the HUD (hud.py), then re-checks their position every 2 seconds.
    Only works during a game with the game in the foreground; sleeps otherwise."""

    def __init__(self):
        super().__init__(name="hud", daemon=True)
        self.loc = hud.HudLocator(DATA)
        self.req = None      # (champion, game window) requested by the overlay
        self.pos = None      # {"Q": (x, y, size), ...} in screen coordinates
        self.board = hud.BoardLocator(DATA)
        self.board_req = None   # (players [(key, side, rank)], game window, known grid, game) while Tab is held
        self.board_pos = None   # {key: (x, y, size)}: scoreboard portraits
        self.board_pitch = None     # row pitch (unit of the scoreboard anchors)
        self.new_geom = None        # freshly measured grid, to store in the profile
        self.board_state = "idle"   # searching (first search running), found, failed
        self.mem_low = False        # system memory nearly full: no more screen captures
        self.mem_info = None        # (biggest process, GB) when that happens
        self._mem_next = 0.0
        self._board_sig = None
        self._board_fails = 0
        self._board_next = 0.0
        self._board_checked = None  # game whose stored grid was already re-measured
        self._rect = None
        self._fails = 0
        self._next_full = 0.0
        self._quality = 0
        self._stop = threading.Event()

    def want(self, key, rect):
        self.req = (key, rect) if key and rect else None

    def stop(self):
        self._stop.set()

    def want_board(self, players, rect, geom, game=None):
        """players: [(key, side 0/1, rank in team)]; geom: stored grid (relative to the window) or None;
        game: game id (the stored grid is re-measured once per game)."""
        self.board_req = (tuple(players), rect, geom, game) if players and rect else None
        if self.board_req and not self.board_pos and self.board_state == "idle":
            self.board_state = "searching"
        elif not self.board_req and self.board_state == "searching":
            self.board_state = "idle"

    MEM_MIN_FREE = 0.5 * 2 ** 30    # below 500 MB of available system memory: pause
    MEM_MAX_OWN = 1.5 * 2 ** 30     # RoL itself must never exceed 1.5 GB

    def _check_memory(self):
        """Every 5 s: when the system is really out of memory (or RoL uses too much), stop screen captures and image
        work until it goes back down, silently (noted in errors.log only). Memory management is Windows' business;
        this only avoids adding load when it is already struggling."""
        now = time.time()
        if now < self._mem_next:
            return
        self._mem_next = now + 5.0
        try:
            from system import memory_status, biggest_process
            free, own = memory_status()
        except Exception:
            return
        low = free < self.MEM_MIN_FREE or own > self.MEM_MAX_OWN
        if low and not self.mem_low:
            try:
                top = biggest_process()
            except Exception:
                top = None
            self.mem_info = (top[0], top[1] / 2 ** 30) if top else None
            log_error("memory: %.1f GB available, RoL %.2f GB, biggest: %s -> captures paused" % (
                free / 2 ** 30, own / 2 ** 30, "%s %.1f GB" % self.mem_info if self.mem_info else "?"))
            self.pos = None
            self.board_pos = None
        self.mem_low = low

    def run(self):
        while not self._stop.is_set():
            wait = 0.5
            try:
                self._check_memory()
                if self.mem_low:
                    # no captures at all; with a stored grid the gold diff is still placed (plain math)
                    if self.board_req and self.board_req[2]:
                        self._board_step()
                    else:
                        self.board_pos = None
                    self._stop.wait(1.0 if self.board_req else 2.0)
                    continue
                wait = self._step()
                if self.board_req:
                    wait = min(wait, self._board_step())
            except Exception:
                import traceback
                log_error("hud : " + traceback.format_exc())
                self.pos = None
                self.board_pos = None
                wait = 5.0
            self._stop.wait(wait)

    @staticmethod
    def _around(spots, margin=8):
        """Small screen area around a few known anchors (x, y, size): the only area captured to check."""
        return (int(min(p[0] for p in spots) - margin), int(min(p[1] for p in spots) - margin),
                int(max(p[0] + p[2] for p in spots) + margin), int(max(p[1] + p[2] for p in spots) + margin))

    def _board_step(self):
        """Scoreboard: with a stored grid, every player is placed without capturing anything. Without one (first time,
        other resolution or HUD scale), a single capture measures it."""
        players, rect, geom, game = self.board_req
        left, top = rect[0], rect[1]
        if geom:
            g = {"S": geom["S"], "x": [left + geom["x"][0], left + geom["x"][1]], "y0": top + geom["y0"],
                 "pitch": geom["pitch"]}
            # once per game (first Tab): the grid is re-measured; if the scoreboard moved, the new measure replaces the
            # old one. If measuring fails (skins, dead players...), the old one is kept.
            if game is not None and self._board_checked != game and not self.mem_low and time.time() >= self._board_next:
                box = self.board.region(rect)
                g2 = self.board.calibrate(hud.grab(box), box[:2], list(players), rect[3] - rect[1]) \
                    if box[2] - box[0] >= 200 else None
                if g2:
                    self._board_checked = game
                    self._board_fails = 0
                    if max(abs(g2["S"] - g["S"]), abs(g2["x"][0] - g["x"][0]), abs(g2["x"][1] - g["x"][1]),
                           abs(g2["y0"] - g["y0"])) > 0.2 * g["S"]:
                        g = g2
                        self.new_geom = {"S": g["S"], "x": [g["x"][0] - left, g["x"][1] - left], "y0": g["y0"] - top,
                                         "pitch": g["pitch"]}
                else:
                    self._board_fails += 1
                    self._board_next = time.time() + 2.0
                    if self._board_fails >= 4:   # not measurable in this game: stick to the stored grid
                        self._board_checked = game
                        self._board_fails = 0
            self.board_pos = self.board.place(g, players)
            self.board_pitch = g["pitch"]
            self.board_state = "found"
            return 1.0
        sig = (frozenset(players), rect)
        if sig != self._board_sig:
            self._board_fails = 0
            self._board_sig = sig
        if time.time() < self._board_next:
            return 0.3
        box = self.board.region(rect)
        if box[2] - box[0] < 200:
            return 1.0
        g = self.board.calibrate(hud.grab(box), box[:2], list(players), rect[3] - rect[1])
        if g:
            self._board_checked = game
            self.new_geom = {"S": g["S"], "x": [g["x"][0] - left, g["x"][1] - left], "y0": g["y0"] - top,
                             "pitch": g["pitch"]}
            self.board_pos = self.board.place(g, players)
            self.board_pitch = g["pitch"]
            self.board_state = "found"
            return 1.0
        self.board_pos = None
        self.board_state = "failed"
        self._board_fails += 1
        # consecutive failures (portraits barely visible): back off (1.5 s, 3 s, 6 s, then 10 s)
        self._board_next = time.time() + min(10.0, 1.5 * 2 ** (self._board_fails - 1))
        return 0.6

    def _step(self):
        req = self.req
        if not req:
            return 0.5
        key, rect = req
        if key != self.loc.key:
            self.pos = None
            if not self.loc.set_champion(key):
                return 3.0
        if len(self.loc.icons) != 4:
            return 3.0
        box = hud.region_of(rect)
        if box[2] - box[0] < 100 or box[3] - box[1] < 40:
            return 2.0
        ok = False
        if self.pos and rect == self._rect:
            sub = self._around(list(self.pos.values()), 6)   # the skill row only, not the whole bottom of the screen
            ok = self.loc.check(hud.grab(sub), sub[:2], self.pos) >= 0.5   # one matching skill is enough
            if ok:
                self._fails = 0
                if self._quality >= 4 or time.time() < self._next_full:
                    return 2.0
                # position partly inferred (skills on cooldown during the search): refine it
            else:
                self._fails += 1
                if self._fails < 2:   # a failed check (animation, shop...): check again soon
                    return 0.4
        if time.time() < self._next_full:
            return 0.5
        found = self.loc.locate(hud.grab(box), box[:2])
        q = self.loc.quality if found else 0
        if found and (not self.pos or rect != self._rect or not ok or q >= self._quality):
            self.pos, self._quality = found, q
        elif not found and (rect != self._rect or not self.pos):
            self.pos, self._quality = None, 0   # search failed mid-fight: keep the known position
        self._rect = rect
        self._fails = 0
        self._next_full = time.time() + (2.0 if found else 4.0)
        return 2.0 if self.pos else 1.0


class TrayMenu:
    """Tray icon menu (right click), drawn in the app's style instead of Windows' gray menu. Closes after a choice,
    on Escape or on a click elsewhere."""

    WIDTH = 252

    def __init__(self, ov):
        self.ov = ov
        self.panel = Panel(ov, "_tray")
        self.panel.win.bind("<Motion>", self._motion, add="+")
        self.panel.win.bind("<Leave>", lambda e: self._set_hover(None), add="+")
        self.rows = []          # (y0, y1, action) in panel coordinates
        self.hover = None
        self.open = False
        self.opened = 0.0
        try:
            self.logo = Image.open(os.path.join(DATA, "img", "app.png")).convert("RGBA")
        except (OSError, ValueError):
            self.logo = None

    # --- content ---
    def _entries(self):
        from system import autostart_command, autostart_enabled, set_autostart
        core = self.ov.core
        out = [("item", T("Ouvrir la roulette"), lambda: core.actions.put("show"), None)]
        out.append(("toggle", T("Tirage en pause"), lambda: core.actions.put("pause"), bool(core.profile["roulette_paused"])))
        if not LITE:
            on = core.profile["overlay_mode"] != "never"
            out.append(("toggle", T("Overlay en jeu"), lambda: core.actions.put("overlay:" + ("never" if on else "tab")), on))
        if autostart_command():
            en = autostart_enabled()
            out.append(("toggle", T("Lancer avec Windows"), lambda: set_autostart(not en), en))
        out.append(("sep",))
        out.append(("quit", T("Quitter"), lambda: core.actions.put("quit"), None))
        return out

    def _status(self):
        core = self.ov.core
        e = core.history.pending()
        if e:
            return T("%s : %s %s") % (T("En pause") if core.profile["roulette_paused"] else T("Tirage en attente"),
                                      core.data.champ_name(e.get("key")), ROLE_LABEL.get(e.get("role"), "")), C_GOLD
        if core.lol_state.get("connected"):
            return T("Relié à League of Legends"), C_GREEN
        return T("League of Legends non détecté"), C_MUTED

    def _render(self):
        from types import SimpleNamespace
        p = Doc(SimpleNamespace(S=self.ov.S0), self.WIDTH, pad=10)
        # header: logo, app name, state
        y = p.px(13)
        x = p.pad + p.px(3)
        if self.logo is not None:
            p.image(x, y, self.logo, p.px(32), radius=p.px(16), ring=rgba(C_GOLD_D, 230))
        tx = x + p.px(42)
        p.text(tx, y + p.px(1), "ROULETTE OF LEGENDS", p.f("disp", 11.5), C_GOLD, track=1.1)
        st, col = self._status()
        fs = p.f("ui", 10.5)
        while p.tw(st, fs) > p.W - p.pad - tx - p.px(10) and len(st) > 8:
            st = st[:-2].rstrip() + "…"
        p.dot(tx + p.px(3), y + p.px(23.8), p.px(2.8), rgba(col))
        p.text(tx + p.px(11), y + p.px(17), st, fs, C_MUTED)
        p.y = y + p.px(44)
        p.line(p.pad, p.y, p.W - p.pad, p.y, rgba(C_GOLD, 48))
        p.y += p.px(6)
        rows, rh = [], p.px(33)
        fnt = p.f("ui_b", 12.5)
        for ent in self._entries():
            if ent[0] == "sep":
                p.y += p.px(4)
                p.line(p.pad, p.y, p.W - p.pad, p.y, rgba(C_GOLD, 48))
                p.y += p.px(5)
                continue
            kind, label, action, state = ent
            y0, y1 = p.y, p.y + rh
            hov = self.hover == len(rows)
            if hov:
                p.rect(p.px(6), y0 + p.px(1), p.W - p.px(6), y1 - p.px(1), fill=rgba(C_RED if kind == "quit" else C_GOLD, 36),
                       radius=p.px(5))
                p.rect(p.px(6), y0 + p.px(8), p.px(8.5), y1 - p.px(8), fill=rgba(C_RED if kind == "quit" else C_GOLD),
                       radius=p.px(1))   # golden mark left of the hovered row
            col = (C_RED if kind == "quit" else C_GOLD_L) if hov else (C_MUTED if kind == "quit" else C_TEXT)
            p.text(p.pad + p.px(8), y0 + (rh - p.lh(fnt)) / 2, label, fnt, col)
            if kind == "toggle":   # switch, like the settings ones
                sw, sh = p.px(32), p.px(17)
                sx, sy = p.W - p.pad - p.px(6) - sw, y0 + (rh - sh) / 2
                p.rect(sx, sy, sx + sw, sy + sh, fill=rgba(C_GOLD if state else (28, 38, 54)),
                       outline=rgba(C_GOLD if state else C_GOLD_D, 230), radius=sh / 2)
                kx = sx + sw - sh / 2 if state else sx + sh / 2
                p.dot(kx, sy + sh / 2, sh / 2 - p.px(3), rgba((12, 18, 28) if state else C_MUTED))
            rows.append((y0, y1, action))
            p.y = y1
        p.y += p.px(2)
        img, m, size = p.render()
        return img, m, size, rows

    def _redraw(self):
        img, m, size, rows = self._render()
        self.rows = rows
        regions = [(0, y0, size[0], y1, self._choose(action)) for y0, y1, action in rows]
        self.panel.set_image(img, m, size, regions)

    def _choose(self, action):
        def run():
            self.close()
            action()
        return run

    # --- display ---
    def show(self, x, y):
        self.hover = None
        self._redraw()
        w, h = self.panel.size
        L, T, R, B = self.ov.w32.work_area(x, y)
        px_ = min(max(L + 6, x - w + 4), R - w - 6)
        py_ = y - h - 8 if y - h - 8 >= T else y + 8   # above the cursor (taskbar at the bottom), below otherwise
        py_ = min(max(T + 6, py_), B - h - 6)
        pan = self.panel
        pan.pos_px = (px_, py_)
        pan.visible = True
        pan._alpha = 0.0
        pan.push()
        pan.set_click(True)
        self.ov.w32.topmost(pan.win)
        self.open = True
        self.opened = time.time()
        self._fade(1)
        self.ov.root.after(60, self._watch)

    def _fade(self, k):
        if not self.open:
            return
        self.panel.set_alpha(min(1.0, k / 4.0))
        if k < 4:
            self.ov.root.after(22, lambda: self._fade(k + 1))

    def close(self):
        if self.open:
            self.open = False
            self.hover = None
            self.panel.hide()
            self.panel.win.configure(cursor="")

    def _watch(self):
        """Click elsewhere or Escape closes the menu (reads the key state, nothing else)."""
        if not self.open:
            return
        w32 = self.ov.w32
        if w32.key_down(0x1B):
            return self.close()
        if time.time() - self.opened > 0.15 and any(w32.key_down(vk) for vk in (0x01, 0x02, 0x04)):
            cx, cy = w32.cursor()
            x0, y0 = self.panel.pos_px
            w, h = self.panel.size
            if not (x0 <= cx < x0 + w and y0 <= cy < y0 + h):
                return self.close()
        self.ov.root.after(40, self._watch)

    def _motion(self, e):
        if not self.open:
            return
        lx, ly = e.x - self.panel.margin, e.y - self.panel.margin
        i = next((k for k, (y0, y1, _a) in enumerate(self.rows) if y0 <= ly < y1 and 0 <= lx <= self.panel.size[0]), None)
        self._set_hover(i)

    def _set_hover(self, i):
        if i == self.hover or not self.open:
            return
        self.hover = i
        self._redraw()
        self.panel.push()
        self.panel.win.configure(cursor="hand2" if i is not None else "")


class Overlay:
    def __init__(self, core, root):
        self.core = core
        self.root = root
        self.images = Images()
        self.S0 = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.preview_until = 0.0
        self.place_until = 0.0
        self.demo = None            # sample (info, snapshot) for preview and placement
        self.toggled = {}           # modules hidden / pinned by their shortcut during the game
        self._keys_prev = set()
        self._toggle_game = None
        self._page = None           # (picked page, automatic phase when it was picked)
        self._avgs = (None, None)
        self._lol_hwnd = None
        self._hwnd_at = 0.0
        self._calc = (None, {}, None, None)
        self._extra = (None, 0)     # skill points on top of the level in this game (Elixir of Skill)
        self._img_cache = {}
        self._tray_menu = None
        self._hud_scale = (0.0, None)
        self._bought, self._bought_game = set(), None   # items that went through the inventory during the game
        self.panels = {}
        self.ctrl = None
        self.anchors_win = None
        self.spell_keys = live.spell_keys()
        try:
            self.w32 = Win32()
        except (AttributeError, OSError):
            self.w32 = None
            return
        self._make_fonts()
        for m in OVERLAY_MODULES:
            self.panels[m["id"]] = Panel(self, m["id"])
        self.ctrl = Panel(self, "_controls")
        self.glow = Panel(self, "_hud")       # blue halo on the icon of the skill to level, on the game HUD
        self.board = Panel(self, "_board")    # gold diff next to the scoreboard portraits
        self.hint = Panel(self, "_hint")      # "hold Tab" reminder, until Tab has been used once
        self._hint_until = None
        self.hudw = HudWatcher()
        self.hudw.start()
        self._make_anchor_window()
        root.after(400, self._tick)

    # --- settings ---
    def _make_fonts(self):
        self.scale = float(self.core.profile.get("overlay_scale", 1.0) or 1.0)
        self.S = self.S0 * self.scale
        fams = set(tkfont.families(self.root))
        disp = "Marcellus SC" if "Marcellus SC" in fams else ("Cinzel" if "Cinzel" in fams else "Segoe UI")
        F = lambda f, s, w="normal": tkfont.Font(root=self.root, family=f, size=max(6, round(s * self.scale)), weight=w)
        self.f_head = F(disp, 12)
        self.f_sec = F(disp, 8)
        self.f_small = F("Segoe UI", 9)
        self.f_small_b = F("Segoe UI Semibold", 9)
        self.f_tiny = F("Segoe UI", 8)
        self.f_num = F("Segoe UI Semibold", 10)
        self.f_key = F("Segoe UI", 7, "bold")

    def alpha(self):
        return float(self.core.profile.get("overlay_opacity", 0.95) or 0.95)

    def _sync_scale(self, rect):
        """The LoL HUD grows with the resolution, so do the modules (1080 px tall base), times the size setting."""
        s_ = round(max(self.S0, (rect[3] - rect[1]) / 1080.0) * self.scale, 3)
        if abs(s_ - self.S) > 0.01:
            self.S = s_
            for p in list(self.panels.values()) + [self.ctrl]:
                p.sig = None

    def cfg(self, mid):
        return self.core.profile.module_cfg(mid)

    def pos_of(self, mid):
        if mid == "_controls":
            return {"fx": 0.5, "fy": 0.42}
        pos = (self.core.profile.get("overlay_pos") or {}).get(mid)
        return pos if isinstance(pos, dict) and "fx" in pos else MODULES[mid]["pos"]

    def anchors_for(self, mid):
        d = MODULES[mid]["pos"]
        return ANCHORS + [(d["fx"], d["fy"])]

    # --- snap points window ---
    def _make_anchor_window(self):
        a = tk.Toplevel(self.root)
        a.withdraw()
        a.overrideredirect(True)
        a.attributes("-topmost", True)
        a.configure(bg=KEY)
        try:
            a.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        self.acv = tk.Canvas(a, bg=KEY, highlightthickness=0, bd=0)
        self.acv.pack(fill="both", expand=True)
        a.geometry("1x1+-50+-50")
        a.deiconify()
        a.update_idletasks()
        self.w32.set_style(a, clickable=False)
        a.withdraw()
        self.anchors_win = a
        self._anchors_shown = False

    def show_anchors(self, panel, active=None):
        if self.hudw.mem_low:
            return   # system memory nearly full: no large anchor window over the game
        left, top, right, bottom = self.ref_rect()
        a, cv = self.anchors_win, self.acv
        cv.delete("all")
        a.geometry("%dx%d+%d+%d" % (right - left, bottom - top, left, top))
        a.update_idletasks()
        w, h = panel.size
        S = self.S0
        home = tuple(MODULES[panel.id]["pos"].values())
        for fx, fy in self.anchors_for(panel.id):
            x, y = self.px_for(fx, fy, (left, top, right, bottom), (w, h))
            cx, cy = x - left + w / 2, y - top + h / 2
            on = active == (fx, fy)
            r = (16 if on else 10) * S
            col = TEAL if (fx, fy) == home else GOLD_D
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=GOLD if on else col, width=max(2, int(2 * S)))
            cv.create_polygon(cx, cy - r * .45, cx + r * .45, cy, cx, cy + r * .45, cx - r * .45, cy,
                              fill=GOLD_L if on else (TEAL if (fx, fy) == home else GOLD), outline="")
            if on:
                cv.create_rectangle(x - left, y - top, x - left + w, y - top + h, outline=GOLD,
                                    width=max(2, int(2 * S)), dash=(6, 4))
        # other modules' edges (magnets) and the target spot when the module sticks to them
        for q in self.panels.values():
            if q is not panel and q.visible and q.pos_px:
                qx, qy = q.pos_px
                cv.create_rectangle(qx - left - 2, qy - top - 2, qx - left + q.size[0] + 2, qy - top + q.size[1] + 2,
                                    outline=GOLD_D, width=1, dash=(3, 5))
        if isinstance(active, tuple) and active and active[0] == "px":
            x, y = active[1], active[2]
            cv.create_rectangle(x - left, y - top, x - left + w, y - top + h, outline=TEAL, width=max(2, int(2 * S)),
                                dash=(6, 4))
        if not self._anchors_shown:
            a.deiconify()
            self.w32.set_style(a, clickable=False)
            self._anchors_shown = True
        self.w32.topmost(a)
        self.w32.topmost(panel.win)

    def edge_spots(self, panel):
        """Positions that stick this module to another visible module (above, below, left, right, aligned edges),
        to stack them neatly."""
        w, h = panel.size
        gap = int(6 * self.S0)
        out = []
        for q in self.panels.values():
            if q is panel or not q.visible or not q.pos_px:
                continue
            qx, qy = q.pos_px
            qw, qh = q.size
            out += [(qx, qy + qh + gap), (qx + qw - w, qy + qh + gap), (qx, qy - h - gap), (qx + qw - w, qy - h - gap),
                    (qx + qw + gap, qy), (qx + qw + gap, qy + qh - h), (qx - w - gap, qy), (qx - w - gap, qy + qh - h)]
        return out

    def hide_anchors(self):
        if self._anchors_shown:
            self.anchors_win.withdraw()
            self._anchors_shown = False

    # --- position ---
    def _lol_window(self, now):
        if now - self._hwnd_at > 2 or not self._lol_hwnd:
            self._lol_hwnd = self.w32.lol_window()
            self._hwnd_at = now
        return self._lol_hwnd

    def ref_rect(self):
        """Reference area: the game window when open, otherwise the primary monitor."""
        r = self.w32.rect(self._lol_window(time.time()))
        if r and r[2] - r[0] > 400 and r[3] - r[1] > 300:
            return r
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def margin(self):
        return int(16 * self.S0)

    def px_for(self, fx, fy, rect, size):
        left, top, right, bottom = rect
        w, h = size
        m = self.margin()
        x = left + m + fx * max(0, (right - left) - 2 * m - w)
        y = top + m + fy * max(0, (bottom - top) - 2 * m - h)
        return int(x), int(y)

    def fraction_for(self, x, y, rect, size):
        left, top, right, bottom = rect
        w, h = size
        m = self.margin()
        spanx = max(1, (right - left) - 2 * m - w)
        spany = max(1, (bottom - top) - 2 * m - h)
        return min(1.0, max(0.0, (x - left - m) / spanx)), min(1.0, max(0.0, (y - top - m) / spany))

    # --- core commands ---
    def _commands(self):
        while True:
            try:
                cmd, arg = self.core.overlay_cmds.get_nowait()
            except queue.Empty:
                return
            if cmd == "preview":
                self.preview(arg, seconds=12)
            elif cmd == "place":
                self.preview(arg, seconds=120)
                self.place_until = time.time() + 120
            elif cmd == "refresh":
                self._make_fonts()
                self._img_cache.clear()
                for p in list(self.panels.values()) + [self.ctrl]:
                    p.sig = None
                    if p.visible:
                        p.show()

    def preview(self, combo_key=None, seconds=12):
        """Preview outside of games: every module with a sample game around the shown guide (or a favorite)."""
        core = self.core
        data = core.data
        if combo_key not in data.combos:
            favs = [k for k in data.combos if core.profile.is_combo_fav(data.combos[k]["key"], data.combos[k]["role"])]
            combo_key = favs[0] if favs else "Ahri|mid" if "Ahri|mid" in data.combos else next(iter(data.combos))
        c = data.combos[combo_key]
        snap = live.demo_snapshot(data, combo_key)
        allies, enemies = live.sides(snap)
        opp = live.lane_opponent(snap)
        info = {"key": c["key"], "role": c["role"], "opp": opp["key"] if opp else None,
                "enemies": [(p["key"], p["role"]) for p in enemies], "note": T("Aperçu : partie d'exemple à 12:34"),
                "game": "demo"}
        self.demo = (info, snap)
        self.preview_until = time.time() + seconds
        for p in self.panels.values():
            p.sig = None

    def finish_place(self):
        self.place_until = 0.0
        self.preview_until = 0.0
        self.hide_anchors()
        self.core.overlay_place_done()

    def show_tray_menu(self, x, y):
        if self._tray_menu is None:
            self._tray_menu = TrayMenu(self)
        self._tray_menu.show(x, y)

    def set_page(self, page):
        snap = self._context()[1]
        auto = live.guide_phase(snap["t"]) if snap else "early"
        self._page = None if page == auto else (page, auto)
        if self.preview_until > time.time():
            self.preview_until = max(self.preview_until, time.time() + 10)
        self.panels["guide"].sig = None

    # --- context: real game, or sample game during preview ---
    def _context(self):
        if time.time() < self.preview_until and self.demo:
            return self.demo[0], self.demo[1], True
        core = self.core
        snap = core.live
        info = core.overlay_info
        if not info and snap:   # roster not received yet (or practice tool): champion from the game data
            me = live.me_of(snap)
            d = core.data
            if me["key"] in d.champs:
                roles = d.champs[me["key"]]["roles"]
                role = me["role"] if me["role"] in roles else max(roles, key=lambda r: d.combos[d.combo_key(me["key"], r)]["share"])
                info = {"key": me["key"], "role": role, "opp": None, "enemies": [], "note": "", "game": None}
        return info, snap, False

    def _calcs(self, info, snap):
        """Current calculations, redone only when the game changed."""
        ident = (id(snap), id(info))
        if self._calc[0] == ident and self._calc[2] is snap and self._calc[3] is info:
            return self._calc[1]
        game = (info or {}).get("game")
        if game != self._bought_game:
            self._bought, self._bought_game = set(), game
        if snap:
            self._bought |= {it[0] for it in live.me_of(snap)["items"]}
        data = self.core.data
        prices = data.item_prices
        out = {}
        if snap:
            self._fill_roles(snap, info)
            role = info["role"] if info else None
            akey = ((info or {}).get("game"), role)
            if self._avgs[0] != akey:
                self._avgs = (akey, live.own_averages(GAMES_DIR, role))
            bench = (data.combo_any(data.combo_key(info["key"], info["role"])) or {}).get("bench") if info else None
            out["stats"] = live.quick_stats(snap, prices, self._avgs[1], bench)
            out["gold"] = live.gold_diff(snap, prices)
            out["obj"] = live.objectives(snap)
            if info:
                c = data.combos.get(data.combo_key(info["key"], info["role"])) or {}
                sk = c.get("skills") or {}
                out["skills"] = live.skill_plan(sk.get("order15"), snap["abilities"], snap["level"], info["key"],
                                                sk.get("prio") or "", self._skill_bonus(info, snap))
        self._calc = (ident, out, snap, info)   # kept: a freed address could be reused by another game
        return out

    def _skill_bonus(self, info, snap):
        """Skill points on top of the level: the Elixir of Skill (Triple Tonic) grants one without a level up.
        Detected when it leaves the inventory, or when there are more ranks than levels (drunk on arrival,
        full inventory)."""
        game = info.get("game")
        if self._extra[0] != game:
            self._extra = (game, 0)
        letters = "QWE" if info["key"] in live.AUTO_R else "QWER"
        over = max(self._extra[1], sum(snap["abilities"].get(c, 0) for c in letters) - snap["level"])
        self._extra = (game, over)
        drunk = live.ELIXIR_SKILL in self._bought and live.ELIXIR_SKILL not in {it[0] for it in live.me_of(snap)["items"]}
        return max(over, 1 if drunk else 0)

    def _board_key(self, rect, mode=""):
        """What the scoreboard grid depends on: game window size, in-game HUD scale and game mode (e.g. the ARAM Mayhem
        scoreboard has a different layout than the Rift one)."""
        now = time.time()
        if now - self._hud_scale[0] > 10:
            try:
                import lolassets
                import lol_client
                dirs = lol_client.LolClient(APP_DIR, self.core.profile["lol_dir"]).candidate_dirs()
                self._hud_scale = (now, lolassets.hud_scale(dirs))
            except Exception:
                self._hud_scale = (now, None)
        return "%dx%d@%s/%s" % (rect[2] - rect[0], rect[3] - rect[1], self._hud_scale[1], mode or "?")

    @staticmethod
    def _board_players(snap):
        """Players in scoreboard order: blue side (ORDER) left, red (CHAOS) right; in each team by role when the game
        gives them all (top, jungle, mid, ADC, support), otherwise in game order."""
        out = []
        for side, team in enumerate(("ORDER", "CHAOS")):
            ps = [p for p in snap["players"] if p.get("team") == team]
            if ps and all(p.get("role") and not p.get("role_guess") for p in ps) and len({p["role"] for p in ps}) == len(ps):
                ps = sorted(ps, key=lambda p: live.ROW_ORDER.get(p["role"], 9))
            out += [(p["key"], side, i) for i, p in enumerate(ps)]
        return out

    def _fill_roles(self, snap, info):
        """The game doesn't always give player positions; without them the gold diff would compare the wrong lane
        opponents. Missing roles are filled with the most likely ones (like u.gg), the local player's role first."""
        players = snap["players"]
        if snap.get("mode") not in ("CLASSIC", "") or all(p["role"] for p in players):
            return
        me = live.me_of(snap)
        for team in {p["team"] for p in players}:
            idx = [i for i, p in enumerate(players) if p["team"] == team]
            if len(idx) != 5:
                continue
            known = {j: players[i]["role"] for j, i in enumerate(idx) if players[i]["role"]}
            if info and info.get("role") and players[idx[0]]["team"] == me["team"] and not me["role"] \
                    and info["role"] not in known.values():
                known[idx.index(snap["me"])] = info["role"]
            roles = guess_roles(self.core.data, [players[i]["key"] for i in idx], known)
            for j, i in enumerate(idx):
                if not players[i]["role"]:
                    players[i]["role"] = roles[j]
                    players[i]["role_guess"] = True   # guessed: not used to order the scoreboard

    # --- loop ---
    def _tick(self):
        if not self.panels or not self.ctrl.win.winfo_exists():
            return
        try:
            self._commands()
            core = self.core
            now = time.time()
            placing = now < self.place_until
            if placing and self.w32.key_down(VK_RETURN) and not any(p.drag for p in self.panels.values()):
                self.finish_place()
                placing = False
            if self.place_until and not placing and now >= self.place_until:
                self.finish_place()
            previewing = now < self.preview_until
            info, snap, demo = self._context()
            self._sync_scale(self.ref_rect())
            st = core.lol_state
            in_game = (bool(st.get("connected")) and st.get("phase") in ("InProgress", "Reconnect")) or snap is not None
            master = core.profile["overlay_mode"] != "never" and not LITE   # Lite: never an overlay
            fg = in_game and self._lol_foreground(now)
            tab = fg and self.w32.key_down(VK_TAB)
            game = (info or {}).get("game")
            if game != self._toggle_game:   # new game: shortcuts and page reset
                self._toggle_game = game
                self.toggled = {}
                self._page = None
            # until the player has held Tab once: a reminder during the first 30 s of each game
            if tab and master and not core.profile.get("overlay_tab_seen"):
                core.profile["overlay_tab_seen"] = True
            if not in_game:
                self._hint_until = None
            elif fg and self._hint_until is None:
                self._hint_until = now + 30
            if (master and fg and not tab and not previewing and not placing and info and self._hint_until
                    and now < self._hint_until and not core.profile.get("overlay_tab_seen")):
                self._show_hint()
            else:
                self.hint.hide()
            if fg and not previewing:
                self._hotkeys()
            calcs = self._calcs(info, snap) if (info or snap) else {}
            # HUD halo: the skill to level, only when a point is available
            plan = calcs.get("skills")
            hud_on = bool(master and fg and not previewing and info and plan and self.cfg("skills")["on"]
                          and not self.hudw.mem_low)
            self.hudw.want(info["key"] if hud_on else None, self.ref_rect() if hud_on else None)
            hud_pos = self.hudw.pos if hud_on else None
            lit = hud_on and plan["avail"] > 0 and plan["next"]
            if lit and hud_pos and plan["next"][0] in hud_pos:
                self._show_glow(hud_pos[plan["next"][0]], now)
            else:
                self.glow.hide()
            # gold diff on the scoreboard (Tab), instead of the block when the portraits are found
            gold = calcs.get("gold")
            board_on = bool(master and fg and tab and not previewing and gold and snap and self.cfg("gold")["on"])
            if board_on:
                rect = self.ref_rect()
                gkey = self._board_key(rect, snap.get("mode"))
                geom = self.core.profile.get("board_geom")
                if isinstance(geom, dict) and not hud.BoardLocator.valid(geom):
                    log_error("scoreboard: stored grid is inconsistent (%s), measuring again" % geom)
                    self.core.profile["board_geom"] = geom = None
                geom = geom if isinstance(geom, dict) and geom.get("key") == gkey else None
                if geom or not self.hudw.mem_low:   # low memory: only with an already known grid
                    self.hudw.want_board(self._board_players(snap), rect, geom, (info or {}).get("game") or snap.get("mode"))
                else:
                    board_on = False
                    self.hudw.want_board(None, None, None)
                if self.hudw.new_geom:   # freshly measured grid: kept for next time
                    g = self.hudw.new_geom
                    log_error("scoreboard: grid measured (%s): portrait %.1f px, rows %.1f px, columns %.0f / %.0f"
                              % (gkey, g["S"], g["pitch"], g["x"][0], g["x"][1]))
                    self.core.profile["board_geom"] = dict(g, key=gkey)
                    self.hudw.new_geom = None
            else:
                self.hudw.want_board(None, None, None)
            on_board = board_on and self._show_board(gold, self.hudw.board_pos, self.ref_rect(), self.hudw.board_pitch)
            if not on_board:
                self.board.hide()
            any_drag = False
            for mid, panel in self.panels.items():
                cfg = self.cfg(mid)
                if previewing:
                    want = cfg["on"]
                elif master and fg and cfg["on"]:
                    want = tab or ((cfg["mode"] == "always") != self.toggled.get(mid, False))
                    if mid == "skills" and lit and not hud_pos:
                        want = True   # HUD not found (exclusive fullscreen...): the strip shows the skill to level
                    if mid == "gold" and (on_board or (board_on and self.hudw.board_state == "searching")):
                        want = False  # already placed on the scoreboard (or searching for it)
                else:
                    want = False
                if want:
                    want = self._render(panel, info, snap, calcs, placing)
                if want:
                    panel.show()
                    panel.set_click(previewing or tab or bool(panel.drag))
                    any_drag = any_drag or bool(panel.drag)
                else:
                    panel.hide()
            if placing:
                self._render_controls()
                self.ctrl.show()
                self.ctrl.set_click(True)
            else:
                self.ctrl.hide()
            if not any_drag:
                self.hide_anchors()
            delay = 35 if (in_game or previewing) else 250
        except Exception:
            import traceback
            log_error("overlay : " + traceback.format_exc())
            delay = 1000
        self.root.after(delay, self._tick)

    def _glow_image(self, size):
        """Level-up halo: crisp blue ring hugging the icon plus a soft glow around it (like the game)."""
        k = ("glow", size)
        if k in self._img_cache:
            return self._img_cache[k]
        pad = max(6, int(round(size * 0.42)))
        W = size + 2 * pad
        S2 = W * SS
        r = max(3, size * 0.12) * SS
        a0 = pad * SS - 2 * SS
        a1 = (pad + size) * SS + 2 * SS
        ring = Image.new("L", (S2, S2), 0)
        ImageDraw.Draw(ring).rounded_rectangle((a0, a0, a1, a1), r, outline=255, width=int(max(3, size * 0.09) * SS))
        glow = ring.filter(ImageFilter.GaussianBlur(size * 0.16 * SS))
        img = Image.new("RGBA", (S2, S2), (60, 160, 255, 0))
        img.putalpha(glow.point(lambda v: min(255, int(v * 1.9))))
        crisp = Image.new("RGBA", (S2, S2), (0, 0, 0, 0))
        dd = ImageDraw.Draw(crisp)
        dd.rounded_rectangle((a0, a0, a1, a1), r, outline=(140, 210, 255, 255), width=int(2 * SS))
        dd.rounded_rectangle((a0 + 2 * SS, a0 + 2 * SS, a1 - 2 * SS, a1 - 2 * SS), max(1, r - 2 * SS),
                             outline=(230, 246, 255, 120), width=SS)
        img.alpha_composite(crisp)
        out = (img.resize((W, W), Image.LANCZOS), pad)
        self._img_cache[k] = out
        return out

    def _show_glow(self, pos, now):
        """Blue halo around the HUD icon (the icon stays visible), gently pulsing."""
        x, y, size = pos
        img, pad = self._glow_image(int(size))
        g = self.glow
        if g.sig != ("glow", int(size)) or g.pos_px != (x, y):
            g.set_image(img, pad, (int(size), int(size)))
            g.sig = ("glow", int(size))
            g.pos_px = (x, y)
            g.push()
        import math
        a = self.alpha() * (0.62 + 0.38 * (0.5 + 0.5 * math.sin(now * 2 * math.pi / 1.3)))
        if not g.visible or abs(a - g._alpha) > 0.035:   # ~10 updates per second are enough for the eye
            g.show(a)
        g.set_click(False)

    # game scoreboard anchors, in row pitches from the portrait's top-left corner
    # (measured on the real scoreboard: they hold whatever the resolution and HUD scale)
    BOARD_KDA_X = 2.24      # middle of the KDA column
    BOARD_SUB_Y = 0.61      # free line under the KDA
    BOARD_HEAD_Y = -0.62    # top banner (team counters), above the first row
    BOARD_HEAD_X = (-0.41, 5.69)   # free space in the banner: left (left team), right (right team)

    def _show_board(self, gold, pos, rect, unit=None):
        """Gold diff on the scoreboard (Tab). The game scoreboard isn't touched: under each player's KDA goes the diff
        with their lane opponent (+X on one side, −X on the other), and each team's diff goes in the free space of
        its banner, next to its counters. Gold coin, font, colors and one-pixel shadow match the game."""
        if not pos:
            return False
        rows = [r for r in gold["rows"] if r["a"] in pos and r["e"]]
        if not rows:
            return False
        size = pos[rows[0]["a"]][2]
        u = unit or size * 1.51      # row pitch
        ally_x = sum(pos[r["a"]][0] for r in rows) / len(rows)
        foes = [pos[r["e"]][0] for r in rows if r["e"] in pos]
        left_side = (ally_x < sum(foes) / len(foes)) if foes else (ally_x + size / 2 < (rect[0] + rect[2]) / 2)
        spots = []      # (x, y, diff) under the KDA of every located player, ally or enemy
        for r in rows:
            y = pos[r["a"]][1] + self.BOARD_SUB_Y * u   # same height on both sides of the row
            for key, v in ((r["a"], r["diff"]), (r["e"], -r["diff"])):
                if key in pos:
                    spots.append((pos[key][0] + self.BOARD_KDA_X * u, y, v))
        tot = gold["total"]
        heads = []      # (x, y, diff) of each team in its banner
        if len(rows) >= 2:
            hy = min(pos[r["a"]][1] for r in rows) + self.BOARD_HEAD_Y * u
            for keys, v, left in (([r["a"] for r in rows], tot, left_side), ([r["e"] for r in rows], -tot, not left_side)):
                found = [pos[k] for k in keys if k in pos]
                if found:
                    x = min(f[0] for f in found) + self.BOARD_HEAD_X[0 if left else 1] * u
                    heads.append((x, hy, v))
        pts = [(x, y) for x, y, _ in spots + heads]
        X0, X1 = int(min(p[0] for p in pts) - 2 * size), int(max(p[0] for p in pts) + 2 * size)
        Y0, Y1 = int(min(p[1] for p in pts) - size), int(max(p[1] for p in pts) + size)
        sig = ("board", tuple((round(x), round(y), int(round(dv / 10))) for x, y, dv in spots + heads))
        g = self.board
        if g.sig != sig:
            canvas = Image.new("RGBA", ((X1 - X0) * SS, (Y1 - Y0) * SS), (0, 0, 0, 0))
            d = ImageDraw.Draw(canvas)

            pic = coin_image()

            def coin(cx, cy, r):
                X, Y, Rr = (cx - X0) * SS, (cy - Y0) * SS, r * SS
                if pic is not None:   # the HUD coin, with a one-pixel shadow
                    h2 = max(2, int(round(2 * Rr)))
                    w2 = max(2, int(round(h2 * pic.width / pic.height)))
                    im = pic.resize((w2, h2), Image.LANCZOS)
                    x0, y0 = int(X - w2 / 2), int(Y - h2 / 2)
                    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
                    sh.putalpha(im.getchannel("A").point(lambda v: v * 170 // 255))
                    canvas.alpha_composite(sh, (x0 + SS, y0 + SS))
                    canvas.alpha_composite(im, (x0, y0))
                    return
                d.ellipse((X - Rr + SS, Y - Rr + SS, X + Rr + SS, Y + Rr + SS), fill=(0, 0, 0, 170))
                d.ellipse((X - Rr, Y - Rr, X + Rr, Y + Rr), fill=(196, 150, 62, 255), outline=(98, 72, 30, 255),
                          width=max(SS, int(Rr * 0.16)))
                r2 = Rr * 0.56
                d.ellipse((X - r2, Y - r2, X + r2, Y + r2), outline=(244, 214, 132, 255), width=max(SS, int(Rr * 0.14)))

            def gold_pair(cx, cy, v, fnt_, r, centered=True):
                txt = gold_txt(v)
                col = BOARD_GREEN if v > 0 else BOARD_RED if v < 0 else BOARD_TEXT
                gap = r * 0.7
                w = 2 * r + gap + fnt_.getlength(txt) / SS
                x = cx - w / 2 if centered else cx
                coin(x + r, cy, r)
                X, Y = (x + 2 * r + gap - X0) * SS, (cy - Y0 + r * 0.06) * SS
                d.text((X + SS, Y + SS), txt, font=fnt_, fill=(0, 0, 0, 215), anchor="lm")   # one-pixel shadow
                d.text((X, Y), txt, font=fnt_, fill=rgba(col), anchor="lm")

            fnt = font("num", max(10.0, size * 0.27))
            for x, y, dv in spots:
                gold_pair(x, y, dv, fnt, max(3.0, size * 0.105))
            fnt_h = font("num", max(11.0, size * 0.36))
            for x, y, dv in heads:
                gold_pair(x, y, dv, fnt_h, max(4.0, size * 0.15))
            img = canvas.resize((X1 - X0, Y1 - Y0), Image.LANCZOS)
            g.set_image(img, 0, img.size)
            g.pos_px = (X0, Y0)
            g.sig = sig
            g.push()
        g.show()
        g.set_click(False)
        return True

    def _hotkeys(self):
        """Ctrl + letter hides or pins a module for the game (reads the key state, nothing else)."""
        if not self.w32.key_down(VK_CONTROL):
            self._keys_prev = set()
            return
        down = {m["id"] for m in OVERLAY_MODULES if self.w32.key_down(ord(m["key"]))}
        for mid in down - self._keys_prev:
            self.toggled[mid] = not self.toggled.get(mid, False)
        self._keys_prev = down

    def _lol_foreground(self, now):
        hwnd = self._lol_window(now)
        fg = self.w32.foreground()
        return bool(hwnd) and fg in [hwnd] + [self.w32.root_hwnd(p.win) for p in self.panels.values()]

    # --- module rendering ---
    def _render(self, panel, info, snap, calcs, placing):
        """Redraws the module when its content changed; False when it has nothing to show."""
        fn = getattr(self, "_draw_" + panel.id)
        sig = fn(None, info, snap, calcs, placing)   # signature only
        if sig is None:
            return False
        sig = (sig, placing, self.S)
        if sig != panel.sig:
            doc = Doc(self, MODULE_WIDTH[panel.id], style=MODULE_STYLE.get(panel.id, "panel"))
            fn(doc, info, snap, calcs, placing)
            img, m, size = doc.render(placing)
            panel.set_image(img, m, size, doc.regions, doc.header_h)
            panel.sig = sig
            if panel.drag:
                panel.push()
            else:
                panel.place()
            if panel.visible:
                self.w32.topmost(panel.win)
        elif not panel.drag and panel.pos_px is None:
            panel.place()
        return True

    def _combo(self, info):
        if not info:
            return None, None
        d = self.core.data
        ck = d.combo_key(info["key"], info["role"])
        return ck, d.combos.get(ck)

    def _draw_guide(self, p, info, snap, calcs, placing):
        if not info:
            return None
        data = self.core.data
        auto = live.guide_phase(snap["t"]) if snap else "early"
        if self._page and self._page[1] != auto:   # the phase changed: follow the clock again
            self._page = None
        page = self._page[0] if self._page else auto
        key, role, opp = info["key"], info["role"], info.get("opp")
        if p is None:
            return (key, role, opp, page, auto, info.get("note"), tuple(info.get("enemies") or ()))
        combo_key, c = self._combo(info)
        g = data.guides.get(combo_key) or {}
        # header: champion, role, lane opponent (also the drag handle)
        p.grip()
        y = p.px(12)
        p.image(p.pad, y, self.images.icon(key), p.px(34), radius=p.px(4), ring=rgba(C_GOLD_D, 255))
        x = p.pad + p.px(43)
        p.text(x, y - p.px(1), data.champ_name(key).upper(), p.f("disp_b", 15), C_GOLD_L, track=0.6)
        p.image(x, y + p.px(21), self.images.role_icon(role, C_GOLD), p.px(12), radius=0, ring=(0, 0, 0, 0))
        p.text(x + p.px(16), y + p.px(21), ROLE_LONG.get(role, ""), p.f("disp", 9), C_GOLD, track=1.4)
        if opp:
            p.image(p.W - p.pad - p.px(30), y + p.px(2), self.images.icon(opp), p.px(30), radius=p.px(4),
                    ring=rgba(C_RED, 200))
            p.text(p.W - p.pad - p.px(38), y + p.px(3), T("CONTRE"), p.f("disp", 8.5), C_MUTED, anchor="r", track=1.2)
            p.text(p.W - p.pad - p.px(38), y + p.px(16), data.champ_name(opp), p.f("ui_b", 12), C_TEXT, anchor="r")
        p.y = y + p.px(42)
        p.header_h = p.y
        # tabs: the page follows the clock (teal dot); Tab held + click to switch
        n = len(OVERLAY_PAGES)
        tw = p.inner / n
        th = p.px(21)
        p.rect(p.pad, p.y, p.W - p.pad, p.y + th, fill=rgba((0, 0, 0), 90), radius=p.px(4))
        for i, (pid, label) in enumerate(OVERLAY_PAGES):
            x0 = p.pad + i * tw
            on = pid == page
            if on:
                p.rect(x0 + p.px(2), p.y + p.px(2), x0 + tw - p.px(2), p.y + th - p.px(2), fill=rgba(C_GOLD, 46),
                       outline=rgba(C_GOLD, 170), radius=p.px(3))
            p.text(x0 + tw / 2, p.y + p.px(5), label.upper(), p.f("disp", 8.5), C_GOLD_L if on else C_MUTED, anchor="m",
                   track=0.8)
            if pid == auto and snap:
                p.dot(x0 + tw - p.px(7), p.y + p.px(6), p.px(2.2), rgba(C_TEAL))
            p.region(x0, p.y, x0 + tw, p.y + th, lambda pg=pid: self.set_page(pg))
        p.y += th + p.px(4)
        if info.get("note"):
            p.para(info["note"], C_TEAL, size=10.5)

        def wr_color(delta):
            return C_GREEN if delta >= 1.5 else C_RED if delta <= -1.5 else C_GOLD_L

        if not c:
            p.section(T("Fiche"))
            p.para(T("Pas de fiche pour %s %s.") % (data.champ_name(key), ROLE_LABEL.get(role, "")), C_MUTED)
        elif page == "early":
            p.section(T("Début de partie"))
            p.para(g.get("early_game"))
            p.section(T("Plan de jungle") if role == "jgl" else T("Plan de lane"))
            p.para(g.get("jungle_plan") if role == "jgl" else g.get("lane_plan"))
        elif page == "matchup":
            if opp:
                m = next((e for e in c["matchups"].get("all") or [] if e.get("key") == opp), None)
                p.section(T("Contre %s") % data.champ_name(opp))
                if m:
                    p.para(T("%s de victoires") % fmt_pct(m["wr"]), wr_color(m["wr"] - c["matchups"]["base"]),
                           p.f("ui_b", 12.5))
                p.para((g.get("matchup_notes") or {}).get(data.champ_name(opp)))
            else:
                p.section(T("Phase de lane"))
                p.para(g.get("trading"))
            p.section(T("À surveiller"))
            for s in (g.get("threats") or [])[:3]:
                p.para(s, bullet=True)
        elif page == "late":
            p.section(T("Mid game"))
            p.para(g.get("mid_game"))
            p.section(T("Late game"))
            p.para(g.get("late_game"))
            p.para(g.get("ahead"), label=T("Devant"))
            p.para(g.get("behind"), label=T("Derrière"))
            p.section(T("Condition de victoire"))
            p.para(strip_goal(g.get("win_condition", "")), C_GOLD_L, p.f("ui_b", 12))
        elif page == "team":
            enemies = [(k, r) for k, r in info.get("enemies") or [] if k]
            if not enemies:
                p.section(T("Équipe adverse"))
                p.para(T("Composition adverse pas encore connue."), C_MUTED)
            else:
                prof = team_profile(data, enemies)
                p.section(T("Leur équipe"))
                if prof["split"]:
                    sp = prof["split"]
                    p.para(T("%d %% AD · %d %% AP · %d %% brut") % (sp["physical"], sp["magic"], sp["true"]), label=T("Dégâts"))
                p.para(", ".join(prof["front"]) if prof["front"] else T("aucun vrai tank"), label=T("Frontline"))
                for t in prof["tips"][:3]:
                    p.para(t, bullet=True)
                p.section(T("Toi contre eux"))
                for ek, er in enemies:
                    p.image(p.pad, p.y, self.images.icon(ek), p.px(22), radius=p.px(3))
                    p.text(p.pad + p.px(30), p.y + p.px(3), data.champ_name(ek), p.f("ui_b", 12), C_TEXT)
                    mv = matchup_vs(data, combo_key, ek, er)
                    if mv:
                        wr, n_, delta = mv
                        p.text(p.W - p.pad, p.y + p.px(3), fmt_pct(wr), p.f("ui_b", 12),
                               wr_color(delta) if n_ >= 1000 else C_MUTED, anchor="r")
                    p.y += p.px(27)
        p.y += p.px(2)

    # Aphelios: each point picks a stat from his HUD menu (Q, W, E keys); the ultimate comes on its own
    APH_SHORT = {"Q": "AD", "W": "VA", "E": "Léta", "R": "Ult."}   # translated at display

    def _draw_aphelios(self, p, info, snap, c):
        order = ((c.get("skills") or {}).get("order15") or "")
        level = int((snap or {}).get("level") or 1)
        pts = [(lv, order[lv - 1]) for lv in range(level, min(len(order), level + 3) + 1)]
        if not pts:
            return None
        if p is None:
            return ("aph", tuple(pts))
        p.header(T("Points d'Aphelios"))
        w, h, gap = p.px(30), p.px(24), p.px(5)
        x = p.pad
        for i, (lv, k) in enumerate(pts):
            on = i == 0
            p.rect(x, p.y, x + w, p.y + h, fill=rgba((4, 8, 14), 200), outline=rgba(C_GOLD if on else C_MUTED, 230 if on else 90),
                   width=max(1, p.px(1)), radius=p.px(4))
            p.text(x + w / 2, p.y + h / 2 - p.px(6.5), T(self.APH_SHORT.get(k, k)), p.f("ui_bb", 10.5),
                   C_GOLD_L if on else C_MUTED if k == "R" else C_TEXT, anchor="m")
            p.text(x + w / 2, p.y + h + p.px(3), str(lv), p.f("num", 11), C_GOLD_L if on else C_MUTED, anchor="m")
            x += w + gap
        p.y += h + p.px(17)

    def _evolve_line(self, info, snap, c):
        """Kha'Zix and Viktor: evolution order (u.gg). Kha'Zix gets one per ultimate rank: the current one is
        highlighted. (Kai'Sa's evolutions come from items, nothing to pick.)"""
        ev = (c or {}).get("evolve") or {}
        key = (info or {}).get("key")
        if key not in ("Khazix", "Viktor") or not ev.get("order"):
            return None
        order = ev["order"][:3] if key == "Khazix" else ev["order"]
        cur = None
        if key == "Khazix":
            r = int(((snap or {}).get("abilities") or {}).get("R") or 0)
            cur = min(r, 3) - 1 if r else None
        return order, cur

    def _draw_skills(self, p, info, snap, calcs, placing):
        plan = calcs.get("skills")
        c = (self._combo(info)[1] or {}) if info else {}
        if info and info["key"] == "Aphelios":
            return self._draw_aphelios(p, info, snap, c)
        evo = self._evolve_line(info, snap, c)
        if not info or not plan or not plan["next"]:
            return None   # every skill maxed: nothing to show
        nxt = plan["next"][:4]
        lit = plan["avail"] > 0 and not self.hudw.pos   # the halo is on the HUD when it is found
        if p is None:
            return (info["key"], tuple(nxt), plan["first_level"], lit, tuple(sorted(self.spell_keys.items())), evo)
        keys = self.spell_keys
        prio = (c.get("skills") or {}).get("prio") or ""
        p.header(T("Sorts"), " › ".join(keys.get(x, x) for x in prio) if prio else None)
        size, gap = p.px(28), p.px(9)
        x = p.pad
        for i, s in enumerate(nxt):
            on = i == 0
            ring = rgba(C_BLUE) if (on and lit) else rgba(C_GOLD) if on else None
            p.image(x, p.y, self.images.spell(info["key"], s), size, radius=p.px(4), ring=ring)
            # keyboard key, like on the HUD
            kw = p.px(11)
            p.rect(x + size - kw, p.y + size - kw, x + size + p.px(1), p.y + size + p.px(1), fill=rgba((4, 8, 14), 235),
                   radius=p.px(2))
            p.text(x + size - kw / 2 + p.px(0.5), p.y + size - kw + p.px(0.5), keys.get(s, s), p.f("ui_bb", 8),
                   C_BLUE if (on and lit) else C_GOLD_L, anchor="m")
            p.text(x + size / 2, p.y + size + p.px(3), str(plan["first_level"] + i), p.f("num", 11),
                   C_BLUE if (on and lit) else C_GOLD_L if on else C_MUTED, anchor="m")
            x += size + gap
        p.y += size + p.px(17)
        if evo:
            order, cur = evo
            p.y += p.px(2)
            p.text(p.pad, p.y, T("Évolutions") if info["key"] == "Khazix" else T("Améliorations"), p.f("ui", 10), C_MUTED)
            p.y += p.px(15)
            small, x = p.px(20), p.pad
            for i, s in enumerate(order):
                on = cur is not None and i == cur
                p.image(x, p.y, self.images.spell(info["key"], s), small, radius=p.px(3), gray=cur is not None and i < cur,
                        ring=rgba(C_GOLD) if on else None)
                if info["key"] == "Khazix":
                    p.text(x + small / 2, p.y + small + p.px(2), ("6", "11", "16")[i], p.f("num", 9.5),
                           C_GOLD_L if on else C_MUTED, anchor="m")
                x += small
                if i < len(order) - 1:
                    p.text(x + p.px(5), p.y + small / 2 - p.px(7), "›", p.f("ui", 12), C_MUTED, anchor="m")
                    x += p.px(10)
            p.y += small + (p.px(15) if info["key"] == "Khazix" else p.px(6))

    def _draw_stats(self, p, info, snap, calcs, placing):
        qs = calcs.get("stats")
        if not qs:
            return None
        rows = qs["rows"]
        if p is None:
            return (int(snap["t"]) // 60, tuple((r["id"], round(r["value"] or 0, 2), r["cmp"], r["src"]) for r in rows),
                    qs["level"], qs["opp_level"], qs["cs"], qs["opp_cs"])
        # benchmarks: Emerald+ players on the same champion and role (CS, KDA); the player's average in that role (the
        # rest, or everything without a benchmark), across all roles with fewer than 3 games in that role
        role = (info or {}).get("role")
        mine = (T("ta moy. %s") % ROLE_LABEL[role]) if qs["avg_scope"] == "role" and role in ROLE_LABEL else T("ta moy. tous postes")
        p.header(T("Tes stats · %d min") % (snap["t"] // 60), T("vs Émeraude+") if qs["elo"] else
                 ("vs " + mine) if qs["avg_n"] else None)
        labels = {"cs": "CS / min", "kda": "KDA", "kp": T("Part. kills"), "vision": "Vision / min"}

        def fmt(k, v):
            if v is None:
                return "—"
            return fr_dec(v, 1) if k in ("cs", "kda") else "%d %%" % round(100 * v) if k == "kp" else fr_dec(v, 2)
        fl, fv, fr = p.f("ui", 11.5), p.f("num", 14), p.f("ui", 11)
        cx1, cx2 = p.pad + p.px(100), p.W - p.pad
        for r in rows:
            col = C_GREEN if r["cmp"] == 1 else C_RED if r["cmp"] == -1 else C_GOLD_L
            p.text(p.pad, p.y + p.px(1), labels[r["id"]], fl, C_MUTED)
            p.text(cx1, p.y - p.px(3.5), fmt(r["id"], r["value"]), fv, col)
            # "toi" marks the rows compared with the player's average when the title announces Emerald+ players
            who = T("toi ") if qs["elo"] and r["src"] == "toi" else ""
            if r["ref"] is not None and r["cmp"] is None:
                p.text(cx2, p.y + p.px(1.5), "%s%s" % (who or (T("réf. ") if r["src"] == "elo" else T("moy. ")),
                                                        fmt(r["id"], r["ref"])), fr, C_MUTED, anchor="r")
            elif r["ref"] is not None:
                txt = "%s%s" % (who, fmt(r["id"], r["ref"]))
                p.text(cx2, p.y + p.px(1.5), txt if r["cmp"] else "= " + txt, fr, col if r["cmp"] else C_MUTED, anchor="r")
                if r["cmp"]:
                    p.tri(cx2 - p.tw(txt, fr) - p.px(7), p.y + p.px(8.5), p.px(3.6), r["cmp"] == 1, rgba(col))
            p.y += p.px(19)
        if qs["opp"]:
            d = self.core.data
            p.y += p.px(2)
            p.line(p.pad, p.y, p.W - p.pad, p.y, rgba(C_GOLD, 40))
            p.y += p.px(6)
            for lab, mine, theirs in ((T("Niveau"), qs["level"], qs["opp_level"]), ("CS", qs["cs"], qs["opp_cs"])):
                col = C_GREEN if mine > theirs else C_RED if mine < theirs else C_GOLD_L
                p.text(p.pad, p.y + p.px(1), lab, fl, C_MUTED)
                p.text(cx1, p.y - p.px(3.5), str(mine), fv, col)
                p.text(cx2, p.y + p.px(1.5), "%s %s" % (d.champ_name(qs["opp"]), theirs), fr, C_MUTED, anchor="r")
                p.y += p.px(19)

    def _draw_items(self, p, info, snap, calcs, placing):
        ck, c = self._combo(info)
        data = self.core.data
        b = data.build_for(ck, (self.core.profile.get("build_pick") or {}).get(ck)) if c else None
        if not b or not b.get("core"):
            return None
        owned = {it[0] for it in (live.me_of(snap)["items"] if snap else [])}
        bought = self._bought - owned   # bought during the game but no longer in the inventory (drunk potions, sold...)
        if p is None:
            return (ck, b["id"], tuple(sorted(owned)), tuple(sorted(bought)), tuple(info.get("enemies") or ()),
                    (snap or {}).get("t", 0) > 90)
        p.header(T("Objets") if b["id"] == "reco" else T("Objets · %s") % T(b["label"]))
        size, gap = p.px(22), p.px(4)

        have = owned | bought
        st = b.get("start") or {}
        rows = [(T("Départ"), list(zip(st.get("ids") or [], st.get("counts") or [1] * 9)),
                 (snap or {}).get("t", 0) > 90 or any(i in have for i in st.get("ids") or [])),
                (T("Build"), b["core"].get("ids") or [], all(i in have for i in b["core"].get("ids") or []))]
        for label, opts in zip((T("4e objet"), T("5e objet"), T("6e objet")), b.get("opts") or []):
            if opts:
                ids = [o["id"] for o in opts]
                rows.append((label, ids, any(i in have for i in ids)))
        counters = [o for o in counter_items(data, c, info.get("enemies") or []) if not o["in_core"]]
        if counters:
            rows.append((T("Contre leur compo"), [o["id"] for o in counters[:4]], False))
        cur = next((i for i, r in enumerate(rows) if not r[2]), len(rows))
        for i, (label, ids, done) in enumerate(rows):
            al = 255 if i == cur or label == T("Contre leur compo") else 120 if done else 165
            p.text(p.pad, p.y, label, p.f("ui_b", 9.5), C_GOLD_L if i == cur else C_MUTED, alpha=al)
            p.y += p.px(14)
            x = p.pad
            for it in ids:
                iid, cnt = (it if isinstance(it, (list, tuple)) else (it, 1))
                if x + size > p.W - p.pad + p.px(1):   # line break
                    x = p.pad
                    p.y += size + gap
                self._item(p, iid, x, p.y, size, owned, bought, cnt, alpha=al)
                x += size + gap
            p.y += size + p.px(7)

    def _item(self, p, iid, x, y, size, owned, bought, count=1, alpha=255):
        """Item icon; already bought: green check (in the inventory) or gold (drunk, sold, merged)."""
        col = C_GREEN if iid in owned else C_GOLD if iid in bought else None
        p.image(x, y, self.images.item(iid), size, radius=p.px(4), ring=rgba(col) if col else None, alpha=alpha)
        if count and count > 1:
            p.rect(x + size - p.px(14), y + size - p.px(11), x + size + p.px(1), y + size + p.px(1),
                   fill=rgba((4, 8, 14), 235), radius=p.px(2))
            p.text(x + size - p.px(6.5), y + size - p.px(11), "×%d" % count, p.f("ui_bb", 8.5), C_GOLD_L, anchor="m")
        if col:
            r = p.px(5.5)
            p.dot(x + size - p.px(2), y + p.px(2), r, rgba(col))
            p.check(x + size - p.px(2), y + p.px(2), r * 0.62, (4, 8, 14, 255))

    def _draw_gold(self, p, info, snap, calcs, placing):
        gd = calcs.get("gold")
        rows = [r for r in (gd or {}).get("rows") or [] if r["a"] and r["e"]]
        if not rows:
            return None
        if p is None:
            return (tuple((r["a"], r["e"], int(round(r["diff"] / 10))) for r in rows), int(round(gd["total"] / 10)))
        tot = gd["total"]
        p.header(T("Écart d'or"), T("équipe %s") % gold_txt(tot), C_GREEN if tot > 0 else C_RED if tot < 0 else C_MUTED)
        size = p.px(22)
        for r in rows:
            if r["mine"]:
                p.rect(p.pad - p.px(5), p.y - p.px(3), p.W - p.pad + p.px(5), p.y + size + p.px(3),
                       fill=rgba(C_GOLD, 26), radius=p.px(4))
            p.image(p.pad, p.y, self.images.icon(r["a"]), size, radius=p.px(3), ring=rgba(C_TEAL, 150))
            p.image(p.W - p.pad - size, p.y, self.images.icon(r["e"]), size, radius=p.px(3), ring=rgba(C_RED, 150))
            d = r["diff"]
            p.text(p.W / 2, p.y + p.px(2), gold_txt(d), p.f("num", 14), C_GREEN if d > 0 else C_RED if d < 0 else C_GOLD_L,
                   anchor="m")
            p.y += size + p.px(6)

    def _draw_objectives(self, p, info, snap, calcs, placing):
        ob = calcs.get("obj")
        if not ob:
            return None
        if p is None:
            return (int(snap["t"]), tuple(sorted(ob["drakes"].items())),
                    tuple((r["id"], r.get("label"), r.get("taken"), r.get("own")) for r in ob["rows"]))
        dk = ob["drakes"]
        p.header(T("Objectifs · %s") % live.mmss(ob["t"]), T("drakes %d – %d") % (dk["ally"], dk["enemy"]))
        t = ob["t"]
        for r in ob["rows"]:
            label = T(r["label"])
            if r["id"] == "inhib":
                label += T(" (le tien)") if r["own"] == "ally" else T(" (le leur)")
            if r.get("taken"):
                txt, col = (T("pris par ton équipe") if r["taken"] == "ally" else T("pris par eux") if r["taken"] == "enemy"
                            else T("pris")), C_MUTED
            elif r["in"] > 0:
                txt, col = T("dans %s") % live.mmss(r["in"]), C_GOLD_L
            elif r.get("until") and t >= r["until"]:
                continue
            else:
                txt, col = T("apparu") + (T(" · part à %s") % live.mmss(r["until"]) if r.get("until") else ""), C_GREEN
            p.text(p.pad, p.y, label, p.f("ui_b", 12), C_TEXT)
            p.text(p.W - p.pad, p.y + p.px(0.5), txt, p.f("ui", 11.5), col, anchor="r")
            p.y += p.px(19)

    def _show_hint(self):
        panel = self.hint
        sig = ("hint", self.S)
        if panel.sig != sig:
            p = Doc(self, 300)
            p.y = p.px(12)
            p.text(p.W / 2, p.y, "ROULETTE OF LEGENDS", p.f("disp", 9.5), C_GOLD, anchor="m", track=1.5)
            p.y += p.px(19)
            for line in p.wrap(T("Maintiens Tab pour afficher l'overlay."), p.f("ui", 12.5), p.inner):
                p.text(p.W / 2, p.y, line, p.f("ui", 12.5), C_TEXT, anchor="m")
                p.y += p.px(17)
            img, m, size = p.render()
            panel.set_image(img, m, size)
            panel.sig = sig
            panel.pos_px = None
        pos = self.px_for(0.5, 0.14, self.ref_rect(), panel.size)
        if panel.pos_px != pos:
            panel.pos_px = pos
            panel.push()
        panel.show()

    def _render_controls(self):
        panel = self.ctrl
        sig = ("controls", self.S)
        if panel.sig == sig:
            if panel.pos_px is None:
                panel.place()
            return
        p = Doc(self, 400)
        p.y = p.px(14)
        p.text(p.W / 2, p.y, T("PLACEMENT DE L'OVERLAY"), p.f("disp", 10.5), C_GOLD, anchor="m", track=1.5)
        p.y += p.px(22)
        for line in p.wrap(T("Glisse chaque module par le haut. Il s'aimante aux coins, aux bords, aux autres modules et "
                             "à sa place par défaut (repère turquoise)."), p.f("ui", 12), p.inner):
            p.text(p.W / 2, p.y, line, p.f("ui", 12), C_TEXT, anchor="m")
            p.y += p.px(16)
        p.y += p.px(8)
        bw, bh = p.px(132), p.px(28)
        bx = (p.W - bw) / 2
        p.rect(bx, p.y, bx + bw, p.y + bh, fill=rgba(C_GOLD, 235), outline=rgba(C_GOLD_L, 200), radius=p.px(4))
        p.text(p.W / 2, p.y + p.px(6), T("TERMINÉ"), p.f("disp_b", 10.5), (20, 14, 6), anchor="m", track=1.5)
        p.region(bx, p.y, bx + bw, p.y + bh, self.finish_place)
        p.y += bh + p.px(2)
        p.text(p.W / 2, p.y + p.px(6), T("ou Entrée"), p.f("ui", 10.5), C_MUTED, anchor="m")
        p.y += p.px(20)
        img, m, size = p.render(True)
        panel.set_image(img, m, size, p.regions, 0)
        panel.sig = sig
        panel.place()


MODULE_WIDTH = {"guide": 340, "skills": 156, "stats": 224, "items": 118, "gold": 210, "objectives": 236}
# skills, items and stats sit on the HUD without a frame, where the u.gg widgets they replace would be
MODULE_STYLE = {"skills": "bare", "items": "bare", "stats": "bare"}


class OverlayHost:
    """Overlay thread: its own (invisible) tkinter root and loop."""

    def __init__(self, core):
        self.core = core
        self.overlay = None
        self._stop = threading.Event()
        self.ready = threading.Event()
        self.thread = None

    def start(self):
        if sys.platform != "win32":
            return False
        self.thread = threading.Thread(target=self._run, name="overlay", daemon=True)
        self.thread.start()
        return True

    def tray_menu(self, x, y):
        """Opens the tray icon menu (called from the tray thread). False when impossible."""
        ov = self.overlay
        if ov is None or not self.ready.is_set():
            return False
        try:
            ov.root.after(0, lambda: ov.show_tray_menu(x, y))
            return True
        except Exception:
            return False

    def _run(self):
        try:
            root = tk.Tk()
            root.withdraw()
            root.report_callback_exception = lambda t, v, tb: log_error(
                "overlay : " + "".join(__import__("traceback").format_exception(t, v, tb)))
            self.overlay = Overlay(self.core, root)

            def watch():
                if self._stop.is_set():
                    root.quit()
                    return
                root.after(200, watch)
            root.after(200, watch)
            self.ready.set()
            root.mainloop()
            root.destroy()
            # release tkinter on its own thread (Tcl warning at exit otherwise)
            self.overlay = None
            del root
            import gc
            gc.collect()
        except Exception:
            import traceback
            log_error("overlay : " + traceback.format_exc())
            self.ready.set()

    def stop(self):
        self._stop.set()
        if self.overlay and getattr(self.overlay, "hudw", None):
            self.overlay.hudw.stop()
