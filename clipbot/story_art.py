"""Original layered shadow-theatre artwork, rather than stock footage or copied images.

Coordinates, pigments and drawing proportions are artwork (like icon.py). Production
dimensions, motion, timing and quality come from Settings in story_render.py.
"""
from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def scene_layers(scene: dict, folder: Path, width: int, height: int) -> dict[str, Path]:
    """Draw a narrative setting plus independent character and atmosphere layers."""
    folder.mkdir(parents=True, exist_ok=True)
    seed = int.from_bytes(hashlib.sha256(scene["visual_prompt"].encode()).digest()[:8])
    rng = random.Random(seed)
    visual = scene.get("visual") or {}
    prompt = scene["visual_prompt"].casefold()
    setting = visual.get("setting") or next((key for key, words in {
        "forest": ("forest", "woods", "tree"), "street": ("street", "road", "town"),
        "station": ("station", "space", "ship"), "room": ("bedroom", "room", "house"),
    }.items() if any(word in prompt for word in words)), "corridor")
    subject = visual.get("subject", "figure")
    # Work at a common illustration scale, then resize once for the chosen orientation.
    w, h = 720, round(720 * height / width)
    bg = Image.new("RGB", (w, h))
    pixels = bg.load()
    cold = setting in ("station", "forest", "street")
    for y in range(h):
        for x in range(w):
            r = math.sqrt(((x - w * .51) / w) ** 2 + ((y - h * .39) / h) ** 2)
            light = max(0, 1 - r * 1.6)
            grain = rng.randrange(4)
            pixels[x, y] = (int(5 + 14 * light) + grain,
                            int(8 + (21 if cold else 16) * light) + grain,
                            int(13 + (28 if cold else 17) * light) + grain)
    d = ImageDraw.Draw(bg)
    horizon = h * .58
    amber, steel = (178, 131, 76), (68, 91, 103)
    if setting in ("corridor", "station"):
        # Receding ribs converge on the door; the void is the visual reveal point.
        d.polygon([(0, h), (w * .4, horizon), (w * .6, horizon), (w, h)], fill=(11, 14, 17))
        for n in range(8):
            depth = (n + 1) / 9
            a = .5 - .5 * depth
            left, right = w * a, w * (1 - a)
            top, bottom = h * (.42 - .4 * depth), h * (.58 + .42 * depth)
            d.line([(left, bottom), (left, top), (right, top), (right, bottom)], fill=tuple(int(c * depth) for c in steel), width=3)
            d.line([(left + 8, top + 8), (right - 8, top + 8)], fill=(56, 48, 35), width=2)
        door = [w * .415, h * .34, w * .585, h * .6]
        d.rectangle(door, fill=(2, 4, 7), outline=(79, 74, 60), width=4)
        d.line([(door[2], door[1]), (door[2], door[3])], fill=amber, width=3)
        for side in (0.12, .88):
            d.line([(w * side, 0), (w * .5, horizon)], fill=(33, 39, 44), width=5)
        if setting == "station":
            d.ellipse((w * .65, h * .19, w * .83, h * .19 + w * .18), fill=(4, 8, 17), outline=steel, width=6)
            for _ in range(22):
                x, y = rng.uniform(.68, .8) * w, rng.uniform(.22, .29) * h
                d.point((x, y), fill=(135, 152, 160))
    elif setting == "forest":
        d.ellipse((w * .57, h * .13, w * .72, h * .13 + w * .15), fill=(125, 143, 150))
        d.polygon([(0, h), (w * .48, horizon), (w * .57, horizon), (w, h)], fill=(29, 34, 34))
        for _ in range(30):
            x = rng.uniform(-.1, 1.1) * w
            if w * .4 < x < w * .62:
                continue
            thick = rng.uniform(5, 34)
            base = rng.uniform(.64, 1.15) * h
            top = rng.uniform(-.1, .25) * h
            d.polygon([(x - thick, base), (x + thick, base), (x + thick * .2, top), (x - thick * .2, top)], fill=(3, 8, 11))
            for _ in range(4):
                by = rng.uniform(top, base * .6)
                direction = rng.choice((-1, 1))
                d.line([(x, by + 30), (x + direction * rng.uniform(30, 100), by - 25)], fill=(4, 9, 12), width=5)
    elif setting == "street":
        d.polygon([(w * .2, h), (w * .48, horizon), (w * .55, horizon), (w * .9, h)], fill=(23, 28, 32))
        for side in (0, 1):
            for n in range(5):
                bw = 110 - n * 15
                x = side * w + (1 if side == 0 else -1) * n * 36
                y = horizon - 200 + n * 28
                d.rectangle((x - bw, y, x + bw, h * .7 - n * 16), fill=(8 + n, 13 + n, 18 + n), outline=(30, 40, 48))
                for row in range(3):
                    d.rectangle((x - 30, y + 20 + row * 39, x - 8, y + 44 + row * 39), fill=(61, 52, 35) if rng.random() > .55 else (3, 6, 10))
        d.line([(w * .73, h * .77), (w * .73, h * .28), (w * .6, h * .28)], fill=(65, 72, 72), width=5)
        d.ellipse((w * .58, h * .275, w * .63, h * .29), fill=amber)
    else:
        d.polygon([(0, 0), (w * .18, h * .18), (w * .18, h * .73), (0, h)], fill=(17, 21, 27))
        d.polygon([(w, 0), (w * .81, h * .18), (w * .81, h * .73), (w, h)], fill=(10, 15, 21))
        d.rectangle((w * .18, h * .18, w * .81, h * .73), fill=(20, 25, 31), outline=(44, 51, 54))
        d.rectangle((w * .51, h * .28, w * .71, h * .55), fill=(9, 18, 28), outline=steel, width=5)
        d.line([(w * .61, h * .28), (w * .61, h * .55)], fill=steel, width=3)
        d.line([(w * .51, h * .41), (w * .71, h * .41)], fill=steel, width=3)
        d.polygon([(w * .08, h * .79), (w * .34, h * .64), (w * .64, h * .66), (w * .78, h * .9)], fill=(35, 37, 39), outline=(57, 58, 53))
        d.rectangle((w * .13, h * .81, w * .69, h * .97), fill=(17, 20, 24))
    # A light cone and vignette are painted into the environment, not camera movement.
    glow = Image.new("RGBA", (w, h))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((w * .3, h * .15, w * .8, h * .67), fill=(100, 124, 134, 18))
    bg = Image.alpha_composite(bg.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(65))).convert("RGB")
    # Cut-paper character: independent limbs/head/coat silhouette with rim light.
    figure = Image.new("RGBA", (round(w * .3), round(h * .43)))
    fd = ImageDraw.Draw(figure)
    fw, fh = figure.size
    if subject != "none":
        ink = (2, 4, 7, 255)
        rim = (43, 54, 59, 255)
        fd.ellipse((fw * .34, fh * .02, fw * .65, fh * .22), fill=ink, outline=rim, width=2)
        fd.polygon([(fw * .3, fh * .2), (fw * .7, fh * .2), (fw * .82, fh * .73), (fw * .18, fh * .73)], fill=ink)
        fd.line([(fw * .3, fh * .22), (fw * .2, fh * .69)], fill=rim, width=2)
        for side in (.34, .61):
            fd.polygon([(fw * side, fh * .65), (fw * (side + .11), fh * .65), (fw * (side + .06), fh * .98), (fw * (side - .03), fh * .98)], fill=ink)
        if subject == "creature":
            for side in (.2, .8):
                fd.line([(fw * .5, fh * .12), (fw * side, 0)], fill=ink, width=8)
            fd.ellipse((fw * .42, fh * .11, fw * .46, fh * .12), fill=(180, 162, 101, 255))
            fd.ellipse((fw * .55, fh * .11, fw * .59, fh * .12), fill=(180, 162, 101, 255))
    fog = Image.new("RGBA", (w, h))
    fogd = ImageDraw.Draw(fog)
    for _ in range(13):
        x, y = rng.uniform(-.4, 1.2) * w, rng.uniform(.55, 1.05) * h
        fogd.ellipse((x, y, x + rng.uniform(200, 600), y + 65), fill=(114, 136, 141, rng.randrange(8, 25)))
    fog = fog.filter(ImageFilter.GaussianBlur(24))
    paths = {}
    for name, img in (("background", bg), ("figure", figure), ("fog", fog)):
        if name == "figure":
            target = (round(width * .3), round(height * .43))
        else:
            target = (width, height)
        path = folder / f"{name}.png"
        img.resize(target, Image.Resampling.LANCZOS).save(path)
        paths[name] = path
    return paths
