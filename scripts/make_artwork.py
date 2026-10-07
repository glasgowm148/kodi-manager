"""Draw the Kodi add-on icon (256x256 PNG) and fanart (1920x1080 JPEG) from scratch.

Original abstract artwork based on docs/images/logo.svg: a screen outline with a code-style
chevron pair. Needs Pillow (not a runtime dependency). Output is committed, so the add-on
build itself does not need Pillow:

    python scripts/make_artwork.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "addon" / "service.kodi.addonadmin" / "resources"
BG = (17, 24, 39)
ACCENT = (125, 211, 252)
TEXT = (238, 242, 247)
MUTED = (154, 165, 180)


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def mark(draw, x, y, scale):
    """The logo: screen, stand, chevrons and dot. Unit grid is the 96px SVG."""
    s = scale
    w = max(2, round(4 * s))
    draw.rounded_rectangle((x + 12 * s, y + 16 * s, x + 84 * s, y + 66 * s), radius=10 * s, outline=ACCENT, width=w)
    draw.line((x + 36 * s, y + 79 * s, x + 60 * s, y + 79 * s), fill=ACCENT, width=w)
    draw.line((x + 48 * s, y + 66 * s, x + 48 * s, y + 79 * s), fill=ACCENT, width=w)
    draw.line([(x + 35 * s, y + 32 * s), (x + 26 * s, y + 41 * s), (x + 35 * s, y + 50 * s)], fill=ACCENT, width=w, joint="curve")
    draw.line([(x + 61 * s, y + 32 * s), (x + 70 * s, y + 41 * s), (x + 61 * s, y + 50 * s)], fill=ACCENT, width=w, joint="curve")
    r = 4 * s
    draw.ellipse((x + 48 * s - r, y + 41 * s - r, x + 48 * s + r, y + 41 * s + r), fill=ACCENT)


def centered(draw, text, y, size, fill, width):
    f = font(size)
    left, _, right, _ = draw.textbbox((0, 0), text, font=f)
    draw.text(((width - (right - left)) / 2, y), text, font=f, fill=fill)


def icon():
    image = Image.new("RGB", (256, 256), BG)
    draw = ImageDraw.Draw(image)
    mark(draw, 48, 6, 1.667)
    centered(draw, "Kodi Manager", 196, 30, TEXT, 256)
    return image


def fanart():
    width, height = 1920, 1080
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    for i in range(0, width + height, 48):  # faint diagonal grid
        draw.line((i, 0, i - height, height), fill=(24, 33, 51), width=2)
    mark(draw, (width - 96 * 4) / 2, 180, 4)
    centered(draw, "Kodi Manager", 600, 120, TEXT, width)
    centered(draw, "Your Kodi setup at a glance", 760, 48, MUTED, width)
    return image


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    icon().save(OUT / "icon.png", optimize=True)
    fanart().save(OUT / "fanart.jpg", quality=85, optimize=True)
    print(OUT / "icon.png", OUT / "fanart.jpg")


if __name__ == "__main__":
    main()
