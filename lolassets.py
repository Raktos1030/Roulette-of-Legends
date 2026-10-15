"""
League of Legends fonts and icons, read from the local game install (nothing is downloaded or redistributed).

The client and the game store their files in .wad archives (zstd entries, paths replaced by their xxHash64).
They are opened with Windows 11's archive library (archiveint.dll, libarchive), with nothing to install:
  - game fonts (Spiegel for text, Beaufort for LoL for titles and numbers) -> data/fonts/lol;
  - the HUD gold coin (game text icon atlas) -> data/img/ui/gold.png.
If anything is missing (other OS, game not found, atlas changed by a patch), the overlay keeps its own fonts and
drawn coin.
"""

import ctypes
import io
import os
import struct

TYPEKIT = os.path.join("Plugins", "rcp-fe-lol-typekit", "default-assets.wad")
GAME_UI = os.path.join("Game", "DATA", "FINAL", "UI.wad.client")
TEXT_ICONS = "assets/ux/fonts/texticons.tex"
COIN_BOX = (197, 203, 231, 233)         # gold coin in the text icon atlas (256 x 512)
COIN_COLOR = (181, 145, 65)             # its mean color, to detect a patch moving it
HUD_GOLD = (236, 196, 78)               # coin yellow on the HUD
FONTS_NEEDED = ("Spiegel-Regular.otf", "Spiegel-SemiBold.otf", "Spiegel-Bold.otf", "BeaufortforLOL-Bold.otf",
                "BeaufortforLOL-Heavy.otf")


# ----------------------------------------------------------------------------
# xxHash64 (path hashes in .wad files)
# ----------------------------------------------------------------------------

_M = (1 << 64) - 1
_P1, _P2, _P3, _P4, _P5 = (11400714785074694791, 14029467366897019727, 1609587929392839161, 9650029242287828579,
                           2870177450012600261)


def _rotl(x, r):
    return ((x << r) | (x >> (64 - r))) & _M


def _round(acc, v):
    return (_rotl((acc + v * _P2) & _M, 31) * _P1) & _M


def xxh64(data, seed=0):
    n, i = len(data), 0
    if n >= 32:
        v = [(seed + _P1 + _P2) & _M, (seed + _P2) & _M, seed, (seed - _P1) & _M]
        while i + 32 <= n:
            for j, w in enumerate(struct.unpack_from("<QQQQ", data, i)):
                v[j] = _round(v[j], w)
            i += 32
        h = (_rotl(v[0], 1) + _rotl(v[1], 7) + _rotl(v[2], 12) + _rotl(v[3], 18)) & _M
        for w in v:
            h = ((h ^ _round(0, w)) * _P1 + _P4) & _M
    else:
        h = (seed + _P5) & _M
    h = (h + n) & _M
    while i + 8 <= n:
        h = (_rotl(h ^ _round(0, struct.unpack_from("<Q", data, i)[0]), 27) * _P1 + _P4) & _M
        i += 8
    if i + 4 <= n:
        h = (_rotl(h ^ (struct.unpack_from("<I", data, i)[0] * _P1 & _M), 23) * _P2 + _P3) & _M
        i += 4
    while i < n:
        h = (_rotl(h ^ (data[i] * _P5 & _M), 11) * _P1) & _M
        i += 1
    h = ((h ^ (h >> 33)) * _P2) & _M
    h = ((h ^ (h >> 29)) * _P3) & _M
    return h ^ (h >> 32)


# ----------------------------------------------------------------------------
# .wad archives
# ----------------------------------------------------------------------------

class Unzstd:
    """zstd decompression through Windows' archive library (raw format, zstd filter)."""

    _lib = None

    @classmethod
    def lib(cls):
        if cls._lib is None:
            a = ctypes.WinDLL(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "archiveint.dll"))
            vp = ctypes.c_void_p
            a.archive_read_new.restype = vp
            for fn in ("archive_read_support_filter_zstd", "archive_read_support_format_raw", "archive_read_free"):
                getattr(a, fn).argtypes = [vp]
            a.archive_read_open_memory.argtypes = [vp, vp, ctypes.c_size_t]
            a.archive_read_next_header.argtypes = [vp, ctypes.POINTER(vp)]
            a.archive_read_data.argtypes = [vp, vp, ctypes.c_size_t]
            a.archive_read_data.restype = ctypes.c_ssize_t
            cls._lib = a
        return cls._lib

    @classmethod
    def run(cls, data, size):
        a = cls.lib()
        h = a.archive_read_new()
        try:
            a.archive_read_support_filter_zstd(h)
            a.archive_read_support_format_raw(h)
            src = ctypes.create_string_buffer(data, len(data))
            if a.archive_read_open_memory(h, src, len(data)) != 0:
                return None
            entry = ctypes.c_void_p()
            if a.archive_read_next_header(h, ctypes.byref(entry)) != 0:
                return None
            out = ctypes.create_string_buffer(size)
            got = 0
            while got < size:
                n = a.archive_read_data(h, ctypes.addressof(out) + got, size - got)
                if n <= 0:
                    break
                got += n
            return out.raw[:got]
        finally:
            a.archive_read_free(h)


def _unpack(raw, kind, size):
    if kind == 3:
        return Unzstd.run(raw, size)
    return raw if kind == 0 else None   # gzip / link / chunked zstd: not used for what we read


def wad_read(path, wanted=None):
    """Entries of a .wad archive (v3.x), reading only the index and the wanted entries.
    wanted: paths to extract (None = all). Returns {hash or path: content}."""
    want = None if wanted is None else {xxh64(p.lower().encode()): p for p in wanted}
    out = {}
    with open(path, "rb") as f:
        head = f.read(272)
        if head[:2] != b"RW" or head[2] != 3:
            return out
        n = struct.unpack_from("<I", head, 268)[0]
        table = f.read(n * 32)
        for i in range(n):
            h, o, cs, us, t, _dup, _sub, _ck = struct.unpack_from("<QIIIBBHQ", table, i * 32)
            if want is not None and h not in want:
                continue
            f.seek(o)
            raw = _unpack(f.read(cs), t & 0xF, us)
            if raw:
                out[want[h] if want else h] = raw
    return out


def tex_image(raw):
    """Game texture (Riot .tex or .dds) -> RGBA PIL image (largest stored size)."""
    from PIL import Image
    if raw[:4] == b"DDS ":
        return Image.open(io.BytesIO(raw)).convert("RGBA")
    if raw[:4] != b"TEX\x00":
        return None
    w, h = struct.unpack_from("<HH", raw, 4)
    fmt, flags = raw[9], raw[11]
    block = {10: 8, 12: 16}.get(fmt)   # DXT1, DXT5
    size = ((w + 3) // 4) * ((h + 3) // 4) * block if block else w * h * 4
    data = raw[12:]
    top = data[-size:] if flags & 1 else data[:size]   # with mipmaps, the largest image is stored last
    if fmt == 10:
        return Image.frombytes("RGBA", (w, h), top, "bcn", 1)
    if fmt == 12:
        return Image.frombytes("RGBA", (w, h), top, "bcn", 3)
    return Image.frombytes("RGBA", (w, h), top, "raw", "BGRA")


# ----------------------------------------------------------------------------
# What the overlay uses
# ----------------------------------------------------------------------------

def extract_fonts(lol_dir, dest):
    """Copies the client fonts (Spiegel, Beaufort for LoL) to dest. Returns the written file names."""
    wad = os.path.join(lol_dir, TYPEKIT)
    if not os.path.exists(wad):
        return []
    from fontTools.ttLib import TTFont
    os.makedirs(dest, exist_ok=True)
    written = []
    for raw in wad_read(wad).values():
        if raw[:4] not in (b"OTTO", b"\x00\x01\x00\x00"):
            continue
        try:
            name = TTFont(io.BytesIO(raw))["name"].getDebugName(6) or ""   # PostScript name, e.g. Spiegel-SemiBold
        except Exception:
            continue
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_")
        if not safe:
            continue
        fn = safe + (".otf" if raw[:4] == b"OTTO" else ".ttf")
        with open(os.path.join(dest, fn), "wb") as f:
            f.write(raw)
        written.append(fn)
    return sorted(written)


def extract_coin(lol_dir, dest):
    """HUD gold coin cut from the game's text icon atlas, tinted like the HUD. True when written."""
    wad = os.path.join(lol_dir, GAME_UI)
    if not os.path.exists(wad):
        return False
    raw = wad_read(wad, [TEXT_ICONS]).get(TEXT_ICONS)
    atlas = tex_image(raw) if raw else None
    if atlas is None or atlas.size != (256, 512):
        return False
    coin = atlas.crop(COIN_BOX)
    px = [p for p in coin.getdata() if p[3] > 200]
    if len(px) < 300:
        return False
    mean = [sum(p[i] for p in px) / len(px) for i in range(3)]
    if any(abs(m - c) > 30 for m, c in zip(mean, COIN_COLOR)):
        return False   # the atlas changed: don't take another icon by mistake
    from PIL import Image
    k = [h / m for h, m in zip(HUD_GOLD, mean)]
    r, g, b, a = coin.split()
    coin = Image.merge("RGBA", (r.point(lambda v: min(255, int(v * k[0]))), g.point(lambda v: min(255, int(v * k[1]))),
                                b.point(lambda v: min(255, int(v * k[2]))), a))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    coin.save(dest)
    return True


def ensure(lol_dirs, data_dir):
    """Extracts fonts and gold coin when still missing (once). Returns what is available."""
    fonts_dir = os.path.join(data_dir, "fonts", "lol")
    coin = os.path.join(data_dir, "img", "ui", "gold.png")
    have_fonts = all(os.path.exists(os.path.join(fonts_dir, f)) for f in FONTS_NEEDED)
    have_coin = os.path.exists(coin)
    for d in lol_dirs:
        if have_fonts and have_coin:
            break
        if not d or not os.path.isdir(d):
            continue
        try:
            if not have_fonts:
                extract_fonts(d, fonts_dir)
                have_fonts = all(os.path.exists(os.path.join(fonts_dir, f)) for f in FONTS_NEEDED)
            if not have_coin:
                have_coin = extract_coin(d, coin)
        except (OSError, ValueError, struct.error):
            continue
    return {"fonts": have_fonts, "coin": have_coin}


def hud_scale(lol_dirs):
    """HUD scale set in the game (Config/game.cfg, GlobalScale), or None. The scoreboard grid depends on it and is
    measured again when it changes."""
    for d in lol_dirs:
        p = os.path.join(d or "", "Config", "game.cfg")
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.strip().lower().startswith("globalscale="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            continue
    return None
