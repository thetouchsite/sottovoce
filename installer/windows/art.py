"""The installer's pictures, drawn from Sottovoce's mark (the page's favicon):
three blue bars on the dark ground of the app, the name, and TouchSite
Software. Run by build.ps1 into build/; nothing drawn is committed.

    python installer/windows/art.py <out folder>

    wizard-1x.bmp, wizard-2x.bmp      the tall picture of the first and last page
    small-1x.bmp, small-2x.bmp        the mark at the top right of the other pages
"""
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

GROUND = "#111113"
INK = "#f2f2f3"
MUTED = "#8a8c92"
BLUE = "#4a8ad6"
FONTS = pathlib.Path(r"C:\Windows\Fonts")


def font(name, size):
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default()


def bars(draw, cx, cy, unit):
    """The mark: three bars on a 22-unit grid, centred on (cx, cy)."""
    for x, y, h in [(3, 7, 8), (9.7, 3, 16), (16.4, 9, 4)]:
        x0, y0 = cx + (x - 11) * unit, cy + (y - 11) * unit
        draw.rounded_rectangle([x0, y0, x0 + 2.6 * unit, y0 + h * unit], radius=1.3 * unit, fill=BLUE)


def wizard(scale):
    """164 x 314 at 100%: the mark, the name, who makes it."""
    w, h = 164 * scale, 314 * scale
    img = Image.new("RGB", (w, h), GROUND)
    d = ImageDraw.Draw(img)
    bars(d, w / 2, h * 0.36, 3.4 * scale)
    name = font("segoeuisl.ttf", 25 * scale)
    d.text((w / 2, h * 0.58), "Sottovoce", font=name, fill=INK, anchor="mm")
    line = font("segoeui.ttf", 9 * scale)
    d.text((w / 2, h * 0.65), "Calls, transcribed on this computer", font=line, fill=MUTED, anchor="mm")
    by = font("seguisb.ttf", 9 * scale)
    d.text((w / 2, h - 26 * scale), "TouchSite Software", font=by, fill=MUTED, anchor="mm")
    return img


def small(scale):
    """55 x 55 at 100%: the app's icon, on the white of the page header."""
    s = 55 * scale
    img = Image.new("RGB", (s, s), "white")
    d = ImageDraw.Draw(img)
    pad = 4 * scale
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=10 * scale, fill=GROUND)
    bars(d, s / 2, s / 2, (s - 2 * pad) / 22 * 0.9)
    return img


def main():
    out = pathlib.Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for scale in (1, 2):
        wizard(scale).save(out / f"wizard-{scale}x.bmp")
        small(scale).save(out / f"small-{scale}x.bmp")
    print("pictures in", out)


if __name__ == "__main__":
    main()
