"""
Locates the skill icons of the League HUD, so the skill to level up can be highlighted right on the HUD.

Looks at the bottom of the game window (in memory only, nothing is saved or sent) for the champion's official
skill icons (Data Dragon) at every possible size, so it works with any resolution and HUD scale. The position is
re-checked every two seconds; a HUD scale change mid-game is picked up right away.

Zero-normalized cross-correlation, insensitive to brightness: unlearned or on-cooldown skills (darker) match too.
"""

import os

import numpy as np
from PIL import Image

SLOTS = "QWER"
REGION = (0.22, 0.70, 0.78, 1.0)   # area of the game window holding the skill bar (x0, y0, x1, y1)
WORK_H = 640                       # working height of the window (icons are about 15 to 50 px there)
INNER = 0.72                       # only the icon center is compared (the HUD frame differs from the icons)


def _gray(im):
    return np.asarray(im.convert("L"), dtype=np.float32)


def _ncc(img, tpl):
    """Normalized correlation map of tpl in img (valid positions, top-left corner)."""
    H, W = img.shape
    h, w = tpl.shape
    if h > H or w > W:
        return None
    t = tpl - tpl.mean()
    tn = np.sqrt((t * t).sum())
    if tn < 1e-3:
        return None
    fh, fw = H + h - 1, W + w - 1
    sh, sw = 1 << (fh - 1).bit_length(), 1 << (fw - 1).bit_length()
    corr = np.fft.irfft2(np.fft.rfft2(img, (sh, sw)) * np.fft.rfft2(t[::-1, ::-1], (sh, sw)), (sh, sw))
    corr = corr[h - 1:H, w - 1:W]
    ii = np.pad(img, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    ii2 = np.pad(img * img, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    s = ii[h:, w:] - ii[:-h, w:] - ii[h:, :-w] + ii[:-h, :-w]
    s2 = ii2[h:, w:] - ii2[:-h, w:] - ii2[h:, :-w] + ii2[:-h, :-w]
    n = h * w
    var = s2 - s * s / n
    out = corr / (np.sqrt(np.maximum(var, 1e-3)) * tn)
    out[var < n * 9.0] = 0.0   # nearly flat area (std dev < 3 gray levels): not an icon
    return np.clip(out, -1.0, 1.0)


class _Prepared:
    """Image prepared for several correlations (keeps its FFT and integral images)."""

    def __init__(self, img):
        self.img = img
        self.ii = np.pad(img, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        self.ii2 = np.pad(img * img, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        self.ffts = {}

    def ncc(self, tpl):
        img = self.img
        H, W = img.shape
        h, w = tpl.shape
        if h > H or w > W:
            return None
        t = tpl - tpl.mean()
        tn = np.sqrt((t * t).sum())
        if tn < 1e-3:
            return None
        sh, sw = 1 << (H + h - 2).bit_length(), 1 << (W + w - 2).bit_length()
        if (sh, sw) not in self.ffts:
            self.ffts[(sh, sw)] = np.fft.rfft2(img, (sh, sw))
        corr = np.fft.irfft2(self.ffts[(sh, sw)] * np.fft.rfft2(t[::-1, ::-1], (sh, sw)), (sh, sw))[h - 1:H, w - 1:W]
        ii, ii2 = self.ii, self.ii2
        s = ii[h:, w:] - ii[:-h, w:] - ii[h:, :-w] + ii[:-h, :-w]
        s2 = ii2[h:, w:] - ii2[:-h, w:] - ii2[h:, :-w] + ii2[:-h, :-w]
        n = h * w
        var = s2 - s * s / n
        out = corr / (np.sqrt(np.maximum(var, 1e-3)) * tn)
        out[var < n * 9.0] = 0.0
        return np.clip(out, -1.0, 1.0)


def _template(icon, size):
    """Icon center at the given size (the full icon would be size x size)."""
    im = icon.resize((size, size), Image.LANCZOS)
    m = int(round(size * (1 - INNER) / 2))
    return _gray(im.crop((m, m, size - m, size - m))), m


class HudLocator:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.icons = {}
        self.key = None
        self.quality = 0

    def set_champion(self, key):
        if key == self.key:
            return bool(self.icons)
        self.key = key
        self.icons = {}
        for s in SLOTS:
            p = os.path.join(self.data_dir, "img", "spells", "%s_%s.png" % (key, s))
            if os.path.exists(p):
                self.icons[s] = Image.open(p).convert("RGB")
        return len(self.icons) == 4

    # --- full search ---
    def locate(self, shot, origin=(0, 0)):
        """shot: REGION of the game window (PIL), origin: its screen position.
        Returns {"Q": (x, y, size), ...} in screen coordinates, or None. Two visible skills are enough (others may
        be on cooldown, darkened and covered by their countdown)."""
        if len(self.icons) != 4:
            return None
        k = WORK_H / float(shot.height / (REGION[3] - REGION[1]))   # working scale
        small = shot.resize((max(1, int(shot.width * k)), max(1, int(shot.height * k))), Image.BILINEAR)
        prep = _Prepared(_gray(small))
        cache = {}

        def at(size):
            if size not in cache:
                scores = {}
                for s in SLOTS:
                    tpl, m = _template(self.icons[s], size)
                    cm = prep.ncc(tpl)
                    if cm is None:
                        scores = None
                        break
                    i = int(np.argmax(cm))
                    y, x = divmod(i, cm.shape[1])
                    scores[s] = (float(cm[y, x]), x - m, y - m)
                cache[size] = scores
            return cache[size]

        def value(size):
            sc = at(size)
            return sum(sorted(v[0] for v in sc.values())[-2:]) if sc else -1.0

        # icon size: coarse search (step 3), then fine around the best
        coarse = max(range(14, 52, 3), key=value)
        size = max(range(max(14, coarse - 2), min(52, coarse + 3)), key=value)
        scores = at(size)
        if not scores:
            return None
        found = self._row(scores, size)
        if not found:
            return None
        # pixel-accurate refinement on the full-resolution image
        full = _gray(shot)
        out = {}
        for s, (x, y) in found.items():
            rx, ry, rs, sc = self._refine(full, s, x / k, y / k, size / k)
            # covered icon (cooldown): refinement would drift, keep the position inferred from the row
            out[s] = (rx, ry, rs) if sc >= 0.6 else (x / k, y / k, None)
        sizes = sorted(v[2] for v in out.values() if v[2])
        if not sizes:
            return None
        size_full = sizes[len(sizes) // 2]
        good = [(SLOTS.index(s), v) for s, v in out.items() if v[2]]
        self.quality = len(good)   # well-matched icons (4 = reliable position; fewer = partly inferred)
        if len(good) >= 2:   # row fitted on the well-matched icons (regular step between them)
            (i0, a), (i1, b) = good[0], good[-1]
            step = (b[0] - a[0]) / (i1 - i0) if i1 != i0 else 0
            yy = sum(v[1] for _i, v in good) / len(good)
            for s, v in out.items():
                if not v[2]:
                    out[s] = (a[0] + (SLOTS.index(s) - i0) * step, yy, None)
        return {s: (origin[0] + x, origin[1] + y, size_full) for s, (x, y, _) in out.items()}

    @staticmethod
    def _row(scores, size):
        """The 4 icons sit on one line, in Q W E R order, evenly spaced."""
        good = {s: (x, y) for s, (sc, x, y) in scores.items() if sc >= 0.55}
        if len(good) < 2:
            return None
        ys = [p[1] for p in good.values()]
        if max(ys) - min(ys) > max(3, size * 0.12):
            return None
        idx = {s: SLOTS.index(s) for s in good}
        order = sorted(good, key=lambda s: idx[s])
        steps = []
        for a, b in zip(order, order[1:]):
            n = idx[b] - idx[a]
            steps.append((good[b][0] - good[a][0]) / n)
        step = sorted(steps)[len(steps) // 2]
        if not (size * 0.95 <= step <= size * 1.8):
            return None
        if any(abs(st - step) > max(2.5, size * 0.12) for st in steps):
            return None
        a = order[0]
        x0 = good[a][0] - idx[a] * step
        y0 = sum(ys) / len(ys)
        return {s: (x0 + i * step, y0) for i, s in enumerate(SLOTS)}

    def _refine(self, full, slot, x, y, size):
        best = None
        for sz in range(max(8, int(size) - 3), int(size) + 4):
            tpl, m = _template(self.icons[slot], sz)
            x0, y0 = int(x) - 6, int(y) - 6
            x1, y1 = int(x) + sz + 6, int(y) + sz + 6
            if x0 < 0 or y0 < 0 or x1 > full.shape[1] or y1 > full.shape[0]:
                continue
            cm = _ncc(full[y0 + m:y1 - m, x0 + m:x1 - m], tpl)
            if cm is None:
                continue
            i = int(np.argmax(cm))
            yy, xx = divmod(i, cm.shape[1])
            sc = float(cm[yy, xx])
            if not best or sc > best[0]:
                best = (sc, x0 + xx, y0 + yy, sz)
        if not best:
            return x, y, size, 0.0
        return best[1], best[2], best[3], best[0]

    # --- quick check (is the position still right?) ---
    def check(self, shot, origin, pos):
        """Best icon score at the known position (± 2 px). One matching skill is enough to tell the HUD is still there
        (others may be on cooldown)."""
        full = _gray(shot)
        scores = []
        for s, (X, Y, size) in pos.items():
            x, y = X - origin[0], Y - origin[1]
            tpl, m = _template(self.icons[s], size)
            x0, y0 = int(x) - 2 + m, int(y) - 2 + m
            x1, y1 = x0 + tpl.shape[1] + 4, y0 + tpl.shape[0] + 4
            if x0 < 0 or y0 < 0 or x1 > full.shape[1] or y1 > full.shape[0]:
                scores.append(0.0)
                continue
            cm = _ncc(full[y0:y1, x0:x1], tpl)
            scores.append(float(cm.max()) if cm is not None else 0.0)
        return max(scores) if scores else 0.0


class BoardLocator:
    """Scoreboard (Tab) portraits, used to place the gold difference next to each champion (any player count:
    5v5, 1v1, practice tool...). The local player's portrait may be grayed out (dead, countdown on it): the others
    are used as anchors then."""

    REGION = (0.08, 0.04, 0.92, 0.90)
    WORK_W = 900

    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.icons = {}

    def _icon(self, key):
        if key not in self.icons:
            p = os.path.join(self.data_dir, "img", "icons", "%s.png" % key)
            self.icons[key] = Image.open(p).convert("RGB") if os.path.exists(p) else None
        return self.icons[key]

    def region(self, rect):
        left, top, right, bottom = rect
        W, H = right - left, bottom - top
        R = self.REGION
        return (int(left + R[0] * W), int(top + R[1] * H), int(left + R[2] * W), int(top + R[3] * H))

    def locate(self, shot, origin, keys, win_h):
        """keys: champion keys of the game (local player first). {key: (x, y, size)} on screen, or None."""
        icons = [(k, self._icon(k)) for k in keys if k and self._icon(k) is not None]
        if not icons:
            return None
        k = self.WORK_W / float(shot.width)
        small = shot.resize((self.WORK_W, max(1, int(shot.height * k))), Image.BILINEAR)
        prep = _Prepared(_gray(small))
        lo, hi = max(10, int(win_h * 0.022 * k)), max(11, int(win_h * 0.07 * k) + 1)

        def best_size(icon):
            """Portrait size: coarse search (step 3), then fine around the best."""
            def score(size):
                tpl, _m = _template(icon, size)
                cm = prep.ncc(tpl)
                return float(cm.max()) if cm is not None else -1.0
            coarse = max(range(lo, hi, 3), key=score)
            fine = max(range(max(lo, coarse - 2), min(hi, coarse + 3)), key=score)
            return score(fine), fine

        best = None
        for _key, icon in icons[:3]:   # local player's portrait first; another one if it's grayed out (dead)
            sc, size = best_size(icon)
            if not best or sc > best[0]:
                best = (sc, size)
            if sc >= 0.75:
                break
        if best[0] < 0.6:
            return None
        size = best[1]
        found = {}
        for key, icon in icons:
            tpl, m = _template(icon, size)
            cm = prep.ncc(tpl)
            if cm is None:
                continue
            i = int(np.argmax(cm))
            y, x = divmod(i, cm.shape[1])
            if cm[y, x] >= 0.55:
                found[key] = (origin[0] + (x - m) / k, origin[1] + (y - m) / k, size / k)
        if len(found) < max(1, len(icons) - 3):
            return None
        return found

    # --- scoreboard grid: measured once, then each player is placed without searching again ---
    # measured on the real scoreboard; the row pitch is the most reliable measure and everything is relative to it
    COL_GAP = 7.07      # gap between the left and right columns, in row pitches
    ROW_PITCH = 1.51    # row pitch in portrait sizes (only when it can't be measured)
    PITCH_RANGE = (1.45, 1.72)   # accepted row pitch / portrait size ratio (1.57 measured on the real scoreboard)

    @classmethod
    def valid(cls, geom):
        """Does the grid match the Summoner's Rift scoreboard proportions? A grid measured elsewhere (another scoreboard
        such as ARAM Mayhem's, or portraits seen outside the scoreboard) is rejected rather than reused."""
        try:
            S, pitch, x = float(geom["S"]), float(geom["pitch"]), geom["x"]
            ratio = pitch / S
            gap = (float(x[1]) - float(x[0])) / pitch
        except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
            return False
        return cls.PITCH_RANGE[0] <= ratio <= cls.PITCH_RANGE[1] and abs(gap - cls.COL_GAP) <= 0.3

    def calibrate(self, shot, origin, players, win_h):
        """Measures the scoreboard grid from well-matched portraits (skins, "?" and grayed portraits are ignored).
        players: [(key, side 0 = left / 1 = right, rank in team)].
        Returns {"S", "x": [left column, right column], "y0", "pitch"} in screen coordinates, or None."""
        icons = [(key, side, row, self._icon(key)) for key, side, row in players if key and self._icon(key) is not None]
        if not icons:
            return None
        k = self.WORK_W / float(shot.width)
        small = shot.resize((self.WORK_W, max(1, int(shot.height * k))), Image.BILINEAR)
        prep = _Prepared(_gray(small))
        lo, hi = max(10, int(win_h * 0.022 * k)), max(11, int(win_h * 0.07 * k) + 1)

        def best_size(icon):
            def score(size):
                tpl, _m = _template(icon, size)
                cm = prep.ncc(tpl)
                return float(cm.max()) if cm is not None else -1.0
            coarse = max(range(lo, hi, 3), key=score)
            fine = max(range(max(lo, coarse - 2), min(hi, coarse + 3)), key=score)
            return score(fine), fine
        sizes = sorted((best_size(ic) for _k, _s, _r, ic in icons[:4]), reverse=True)
        if not sizes or sizes[0][0] < 0.75:
            return None
        size = sizes[0][1]
        S = size / k
        # reliable portraits: well matched (no skin, no "?", not grayed)
        pts = []
        for key, side, row, icon in icons:
            tpl, m = _template(icon, size)
            cm = prep.ncc(tpl)
            if cm is None:
                continue
            i = int(np.argmax(cm))
            y, x = divmod(i, cm.shape[1])
            if cm[y, x] >= 0.8:
                pts.append((side, row, origin[0] + (x - m) / k, origin[1] + (y - m) / k))
        if len(pts) < 2:
            return None
        # rows: the (pitch, top) model explaining the most reliable portraits
        best = None
        for a in pts:
            for b in pts:
                if b[1] <= a[1]:
                    continue
                pitch = (b[3] - a[3]) / (b[1] - a[1])
                if not (self.PITCH_RANGE[0] * S <= pitch <= self.PITCH_RANGE[1] * S):
                    continue
                y0 = a[3] - a[1] * pitch
                n = sum(1 for p in pts if abs(p[3] - (y0 + p[1] * pitch)) < 0.3 * S)
                if not best or n > best[0]:
                    best = (n, pitch, y0)
        if not best:   # reliable portraits all on one row: use the usual scoreboard pitch
            pitch = self.ROW_PITCH * S
            ys = [p[3] - p[1] * pitch for p in pts]
            best = (sum(1 for y in ys if abs(y - sorted(ys)[len(ys) // 2]) < 0.3 * S), pitch, sorted(ys)[len(ys) // 2])
        n, pitch, y0 = best
        rows_ok = [p for p in pts if abs(p[3] - (y0 + p[1] * pitch)) < 0.3 * S]
        if n < 2 and len(pts) > 1:
            return None
        # columns: one per side; a side without a reliable portrait is inferred from the other
        cols = [None, None]
        for side in (0, 1):
            xs = sorted(p[2] for p in rows_ok if p[0] == side)
            if xs:
                cols[side] = xs[len(xs) // 2]
        if cols[0] is None and cols[1] is None:
            return None
        if cols[0] is None:
            cols[0] = cols[1] - self.COL_GAP * pitch
        if cols[1] is None:
            cols[1] = cols[0] + self.COL_GAP * pitch
        if any(abs(p[2] - cols[p[0]]) > 0.3 * S for p in rows_ok):
            return None
        g = {"S": S, "x": cols, "y0": y0, "pitch": pitch}
        return g if self.valid(g) else None

    @staticmethod
    def place(geom, players):
        """Portrait positions from the measured grid: {key: (x, y, size)}."""
        S = geom["S"]
        return {key: (geom["x"][side], geom["y0"] + row * geom["pitch"], S) for key, side, row in players if key}

    def check(self, shot, origin, known):
        """Is the scoreboard still there, at the same place? known: [(key, (x, y, size))] for a few portraits.
        Best score among them (one grayed or covered portrait isn't enough to restart the search)."""
        full = _gray(shot)
        best = 0.0
        for key, (X, Y, size) in known:
            icon = self._icon(key)
            if icon is None:
                continue
            tpl, m = _template(icon, int(round(size)))
            x0, y0 = int(X - origin[0]) + m - 3, int(Y - origin[1]) + m - 3
            x1, y1 = x0 + tpl.shape[1] + 6, y0 + tpl.shape[0] + 6
            if x0 < 0 or y0 < 0 or x1 > full.shape[1] or y1 > full.shape[0]:
                continue
            cm = _ncc(full[y0:y1, x0:x1], tpl)
            if cm is not None:
                best = max(best, float(cm.max()))
        return best


def region_of(rect):
    """Area to capture (screen coordinates) in the game window."""
    left, top, right, bottom = rect
    W, H = right - left, bottom - top
    return (int(left + REGION[0] * W), int(top + REGION[1] * H), int(left + REGION[2] * W), int(bottom))


_GDI = None


def _gdi():
    global _GDI
    if _GDI is None:
        import ctypes
        from ctypes import wintypes
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        u.GetDC.restype = wintypes.HDC
        u.GetDC.argtypes = [wintypes.HWND]
        u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        g.CreateCompatibleDC.restype = wintypes.HDC
        g.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        g.SelectObject.restype = wintypes.HGDIOBJ
        g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC,
                             ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                ctypes.c_void_p, wintypes.UINT]
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g.DeleteDC.argtypes = [wintypes.HDC]

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                        ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                        ("biSizeImage", ctypes.c_uint32), ("a", ctypes.c_int32), ("b", ctypes.c_int32),
                        ("c", ctypes.c_uint32), ("d", ctypes.c_uint32)]
        _GDI = (ctypes, u, g, BIH)
    return _GDI


def grab(box):
    """Captures the HUD area only (screen copy, without the overlay's layered windows)."""
    ctypes, u, g, BIH = _gdi()
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    hdc = u.GetDC(None)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    old = g.SelectObject(mdc, bmp)
    try:
        g.BitBlt(mdc, 0, 0, w, h, hdc, x0, y0, 0x00CC0020)   # SRCCOPY
        bi = BIH()
        bi.biSize, bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = ctypes.sizeof(BIH), w, -h, 1, 32
        buf = ctypes.create_string_buffer(w * h * 4)
        g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    finally:
        g.SelectObject(mdc, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(None, hdc)
