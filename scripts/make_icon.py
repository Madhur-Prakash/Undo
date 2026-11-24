"""Draw Undo's icon: a counter-clockwise arrow around clock hands ("go back in time").

Writes
  gui/assets/undo.png                                   1024 px master (Linux .desktop icon)
  gui/assets/undo.ico                                   16-256 px, for Windows
  gui/undo_desktop/windows/runner/resources/app_icon.ico  the same .ico, used by the Flutter
                                                        runner when it builds Undo.exe
  gui/undo_desktop/assets/undo.png                      256 px logo shown in the app's sidebar

Run from anywhere:  uv run --with pillow python scripts/make_icon.py
Small sizes (<= 32 px) leave out the clock hands, which would only blur there.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "gui" / "assets"
APP_LOGO = ROOT / "gui" / "undo_desktop" / "assets" / "undo.png"
RUNNER_ICO = ROOT / "gui" / "undo_desktop" / "windows" / "runner" / "resources" / "app_icon.ico"

SIZE = 1024
TOP = (0x4A, 0x6F, 0x9C)  # lighter slate
BOTTOM = (0x2B, 0x40, 0x5E)  # the app's seed colour (#3D5A80), darkened
WHITE = (255, 255, 255, 255)
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def _background() -> Image.Image:
    gradient = Image.new("RGBA", (SIZE, SIZE))
    px = gradient.load()
    for y in range(SIZE):
        t = y / (SIZE - 1)
        row = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM, strict=True))
        for x in range(SIZE):
            px[x, y] = (*row, 255)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, SIZE - 40, SIZE - 40), radius=210, fill=255)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(gradient, (0, 0), mask)
    return out


def _point(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def draw(*, hands: bool, stroke: int) -> Image.Image:
    img = _background()
    d = ImageDraw.Draw(img)
    cx, cy, r = SIZE / 2, SIZE / 2 + 20, 285
    # Pillow angles grow clockwise from 3 o'clock (y points down). The ring runs clockwise
    # from the arrowhead at the left (188 deg) over the top and round to its tail at the
    # lower left (122 deg). The head points counter-clockwise, down into the gap: "back".
    head_at, tail_at = 188.0, 122.0
    mid = r - stroke / 2  # the stroke's centre line (Pillow draws the width inwards)
    box = (cx - r, cy - r, cx + r, cy + r)
    d.arc(box, start=head_at - 2, end=tail_at + 360, fill=WHITE, width=stroke)
    tx_, ty_ = _point(cx, cy, mid, tail_at)  # round tail
    d.ellipse((tx_ - stroke / 2, ty_ - stroke / 2, tx_ + stroke / 2, ty_ + stroke / 2), fill=WHITE)

    # Arrowhead: moving counter-clockwise (decreasing angle) heads along (sin a, -cos a).
    a = math.radians(head_at)
    bx, by = _point(cx, cy, mid, head_at)
    tx, ty = math.sin(a), -math.cos(a)
    nx, ny = math.cos(a), math.sin(a)  # outward normal
    length, half = stroke * 1.9, stroke * 1.35
    tip = (bx + tx * length, by + ty * length)
    d.polygon(
        [tip, (bx + nx * half, by + ny * half), (bx - nx * half, by - ny * half)],
        fill=WHITE,
    )

    if hands:
        hw = stroke * 0.62
        hcx, hcy = cx, cy
        for ex, ey in ((hcx, hcy - 150), (hcx + 115, hcy + 70)):
            d.line((hcx, hcy, ex, ey), fill=WHITE, width=round(hw))
            d.ellipse((ex - hw / 2, ey - hw / 2, ex + hw / 2, ey + hw / 2), fill=WHITE)
        d.ellipse((hcx - hw * 0.8, hcy - hw * 0.8, hcx + hw * 0.8, hcy + hw * 0.8), fill=WHITE)
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    full = draw(hands=True, stroke=92)
    small = draw(hands=False, stroke=130)  # bolder ring, no hands: readable at 16-32 px
    full.save(ASSETS / "undo.png")
    frames = [
        (small if s <= 32 else full).resize((s, s), Image.Resampling.LANCZOS) for s in ICO_SIZES
    ]
    big = frames[-1]
    big.save(
        ASSETS / "undo.ico",
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[:-1],
    )
    shutil.copy2(ASSETS / "undo.ico", RUNNER_ICO)
    APP_LOGO.parent.mkdir(parents=True, exist_ok=True)
    full.resize((256, 256), Image.Resampling.LANCZOS).save(APP_LOGO)
    print(f"wrote {ASSETS}, {RUNNER_ICO} and {APP_LOGO}")


if __name__ == "__main__":
    main()
