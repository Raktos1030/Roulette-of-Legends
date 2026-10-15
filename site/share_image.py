"""
Builds the link preview images of the website (Discord, social networks): site/img/share-fr.png and share-en.png,
1200 x 630. Run again after changing the logo or the wording.
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SITE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SITE)
IMG = os.path.join(ROOT, "data", "img")
FONTS = os.path.join(ROOT, "data", "fonts")
W, H = 1200, 630
GOLD, GOLD_PALE, TEAL, MUTED = (200, 170, 110), (240, 230, 210), (25, 211, 196), (160, 155, 140)
CARDS = ["Ahri", "Yasuo", "Jinx", "Thresh", "LeeSin"]   # the middle one is the "winner"
TEXTS = {
    "fr": ("Rôle et champion aléatoire", "League of Legends  ·  Solo  ·  Groupe  ·  Chaos"),
    "en": ("Random role & champion", "League of Legends  ·  Solo  ·  Group  ·  Chaos"),
}


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def logo(size):
    out = Image.new("RGBA", (256, 256))
    for layer in ("logo_base", "logo_wheel", "logo_pointer"):
        out.alpha_composite(Image.open(os.path.join(IMG, layer + ".png")).convert("RGBA"))
    return out.resize((size, size), Image.LANCZOS)


def rounded(im, radius):
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius, fill=255)
    im.putalpha(mask)
    return im


def background():
    bg = Image.new("RGBA", (W, H), (4, 7, 13, 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((560, -120, 1320, 760), fill=(200, 170, 110, 30))
    bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(140)))
    cw, ch, gap = 150, 272, 16
    x0, y0 = 590, (H - ch) // 2
    for i, key in enumerate(CARDS):
        card = Image.open(os.path.join(IMG, "loading", key + ".jpg")).convert("RGBA")
        card = card.resize((cw, int(card.height * cw / card.width)), Image.LANCZOS).crop((0, 0, cw, ch))
        win = i == len(CARDS) // 2
        if win:
            card = card.resize((int(cw * 1.12), int(ch * 1.12)), Image.LANCZOS)
        else:
            card = Image.blend(card, Image.new("RGBA", card.size, (4, 7, 13, 255)), 0.35)
        card = rounded(card, 12)
        x = x0 + i * (cw + gap) - (card.width - cw) // 2
        y = y0 - (card.height - ch) // 2
        if win:
            halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(halo).rounded_rectangle((x - 6, y - 6, x + card.width + 6, y + card.height + 6), 16,
                                                   fill=(232, 208, 154, 150))
            bg.alpha_composite(halo.filter(ImageFilter.GaussianBlur(18)))
        bg.alpha_composite(card, (x, y))
        ImageDraw.Draw(bg).rounded_rectangle((x, y, x + card.width - 1, y + card.height - 1), 12,
                                             outline=(232, 208, 154, 255) if win else (255, 255, 255, 40), width=2 if win else 1)
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(shade)
    for x in range(W):
        a = 255 if x < 470 else max(0, int(255 * (1 - (x - 470) / 330)))
        d.line([(x, 0), (x, H)], fill=(4, 7, 13, a))
    bg.alpha_composite(shade)
    return bg


def build(lang):
    im = background()
    im.alpha_composite(logo(118), (70, 92))
    d = ImageDraw.Draw(im)
    big, small = font("Cinzel-700.ttf", 74), font("Cinzel-700.ttf", 40)
    y = 236
    d.text((68, y), "Roulette", font=big, fill=GOLD_PALE)
    w = d.textlength("Roulette ", font=big)
    d.text((68 + w, y + 24), "of", font=small, fill=GOLD)
    d.text((68, y + 82), "Legends", font=big, fill=GOLD_PALE)
    sub, tag = TEXTS[lang]
    d.text((70, y + 196), sub, font=font("MarcellusSC-Regular.ttf", 34), fill=TEAL)
    d.text((70, y + 248), tag, font=font("MarcellusSC-Regular.ttf", 22), fill=MUTED)
    out = os.path.join(SITE, "img", "share-%s.png" % lang)
    im.convert("RGB").save(out, optimize=True)
    return out


if __name__ == "__main__":
    for lang in TEXTS:
        print(build(lang))
