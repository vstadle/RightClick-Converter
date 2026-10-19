"""Dessine l'icône du menu (deux flèches opposées sur un carré arrondi)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256


def build_icon(path: Path) -> Path:
    scale = 4  # dessin en grand puis réduction = bords lisses
    s = SIZE * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fond : dégradé vertical bleu -> violet, découpé en carré arrondi.
    gradient = Image.new("RGBA", (s, s))
    top, bottom = (59, 130, 246), (139, 92, 246)
    gdraw = ImageDraw.Draw(gradient)
    for y in range(s):
        t = y / (s - 1)
        gdraw.line([(0, y), (s, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=s // 5, fill=255)
    img.paste(gradient, mask=mask)

    # Flèche du haut vers la droite, flèche du bas vers la gauche.
    white = (255, 255, 255, 255)
    width, head = s // 13, s // 7
    left, right = s * 0.24, s * 0.76
    y1, y2 = s * 0.37, s * 0.63
    draw.line([(left, y1), (right - head * 0.6, y1)], fill=white, width=width)
    draw.polygon([(right, y1), (right - head, y1 - head * 0.75), (right - head, y1 + head * 0.75)],
                 fill=white)
    draw.line([(left + head * 0.6, y2), (right, y2)], fill=white, width=width)
    draw.polygon([(left, y2), (left + head, y2 - head * 0.75), (left + head, y2 + head * 0.75)],
                 fill=white)

    icon = img.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    icon.save(path, format="ICO", sizes=[(n, n) for n in (16, 20, 24, 32, 48, 64, 256)])
    return path
