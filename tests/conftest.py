from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from quickconvert.converters import CONVERTERS


def _gradient(size=(120, 80), mode="RGB") -> Image.Image:
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for x in range(size[0]):
        draw.line([(x, 0), (x, size[1])], fill=(x * 2 % 256, 100, 255 - x % 256))
    return img.convert(mode)


@pytest.fixture
def samples(tmp_path: Path) -> dict[str, Path]:
    """Un échantillon de chaque cas délicat, dans tmp_path/src."""
    d = tmp_path / "src"
    d.mkdir()
    out: dict[str, Path] = {}

    # Photo tournée : orientation EXIF 6 = « tourner de 90° dans le sens horaire ».
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "TestCam"
    _gradient().save(out.setdefault("rotated_jpg", d / "rotated.jpg"), exif=exif.tobytes())

    rgba = _gradient(mode="RGBA")
    ImageDraw.Draw(rgba).rectangle([0, 0, 39, 79], fill=(0, 0, 0, 0))  # bande transparente
    rgba.save(out.setdefault("rgba_png", d / "transparent.png"))

    _gradient(mode="L").save(out.setdefault("gray_png", d / "gray.png"))
    _gradient(mode="CMYK").save(out.setdefault("cmyk_jpg", d / "cmyk.jpg"))

    deep = Image.new("I;16", (64, 64))
    deep.putdata([40000] * (64 * 64))  # gris moyen sur 16 bits
    deep.save(out.setdefault("deep_png", d / "deep16.png"))

    pal = _gradient(mode="RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=64)
    pal.info["transparency"] = 0
    pal.save(out.setdefault("pal_gif", d / "palette.gif"), transparency=0)

    frames = [Image.new("RGB", (60, 40), c) for c in ("red", "green", "blue")]
    frames[0].save(out.setdefault("anim_gif", d / "anim.gif"), save_all=True,
                   append_images=frames[1:], duration=[100, 200, 300], loop=0)
    frames_rgba = [Image.new("RGBA", (60, 40), c) for c in ((255, 0, 0, 128), (0, 255, 0, 255))]
    frames_rgba[0].save(out.setdefault("anim_webp", d / "anim.webp"), save_all=True,
                        append_images=frames_rgba[1:], duration=[150, 250], loop=0, lossless=True)

    pages = [_gradient(), _gradient(size=(80, 120))]
    pages[0].save(out.setdefault("pages_tif", d / "pages.tif"), save_all=True, append_images=pages[1:])

    _gradient().save(out.setdefault("plain_bmp", d / "plain.bmp"))
    _gradient().save(out.setdefault("plain_webp", d / "plain.webp"))
    _gradient(size=(64, 64), mode="RGBA").save(out.setdefault("plain_ico", d / "plain.ico"))
    formats = {f.key for f in CONVERTERS[0].formats}
    if "heic" in formats:
        _gradient().save(out.setdefault("plain_heic", d / "plain.heic"))
    if "avif" in formats:
        _gradient().save(out.setdefault("plain_avif", d / "plain.avif"))

    (d / "broken.jpg").write_bytes(b"ceci n'est pas une image")
    out["broken"] = d / "broken.jpg"
    return out
