from __future__ import annotations

import re

import pytest
from PIL import Image, ImageSequence

from quickconvert.converters import CONVERTERS, ConversionError, find_target
from quickconvert.runner import convert_file

IMAGES = CONVERTERS[0]
TARGETS = [f.key for f in IMAGES.writable()]


def convert(path, key):
    converter, fmt = find_target(key)
    return convert_file(path, converter, fmt)


@pytest.mark.parametrize("target", TARGETS)
def test_every_sample_to_every_format(samples, target):
    _, fmt = find_target(target)
    for name, src in samples.items():
        if name == "broken" or src.suffix.lower() in fmt.extensions:
            continue
        dst = convert(src, target)
        assert dst.suffix == fmt.ext and dst.stat().st_size > 0, name
        if target == "pdf":
            assert dst.read_bytes().startswith(b"%PDF"), name
            continue
        with Image.open(dst) as out:
            assert out.format == fmt.pil, name
            out.load()


def test_exif_rotation_applied_and_metadata_kept(samples):
    dst = convert(samples["rotated_jpg"], "png")
    with Image.open(dst) as out:
        assert out.size == (80, 120)  # 120x80 tourné de 90°
        exif = out.getexif()
        assert exif.get(0x0112, 1) == 1  # plus d'orientation à appliquer
        assert exif.get(0x010F) == "TestCam"


def test_transparency_becomes_white_in_jpg(samples):
    dst = convert(samples["rgba_png"], "jpg")
    with Image.open(dst) as out:
        r, g, b = out.convert("RGB").getpixel((5, 5))
        assert min(r, g, b) > 245


def test_transparency_kept_in_webp(samples):
    dst = convert(samples["rgba_png"], "webp")
    with Image.open(dst) as out:
        assert out.mode == "RGBA"
        assert out.getpixel((5, 5))[3] == 0


def test_animation_kept(samples):
    dst = convert(samples["anim_gif"], "webp")
    with Image.open(dst) as out:
        assert out.n_frames == 3
        durations = [f.copy().info["duration"] for f in ImageSequence.Iterator(out)]
        assert durations == [100, 200, 300]

    dst = convert(samples["anim_webp"], "gif")
    with Image.open(dst) as out:
        assert out.n_frames == 2


def test_animation_to_still_format_keeps_first_frame(samples):
    dst = convert(samples["anim_gif"], "jpg")
    with Image.open(dst) as out:
        r, g, b = out.getpixel((10, 10))
        assert r > 200 and g < 60 and b < 60  # première image rouge


def test_multipage_tiff_to_pdf(samples):
    dst = convert(samples["pages_tif"], "pdf")
    assert len(re.findall(rb"/Type\s*/Page\b", dst.read_bytes())) == 2


def test_16_bit_is_scaled_not_clipped(samples):
    dst = convert(samples["deep_png"], "jpg")
    with Image.open(dst) as out:
        value = out.getpixel((10, 10))
        value = value[0] if isinstance(value, tuple) else value
        assert 150 < value < 160  # 40000 / 257 ≈ 156, pas 255


def test_cmyk_becomes_rgb(samples):
    dst = convert(samples["cmyk_jpg"], "png")
    with Image.open(dst) as out:
        assert out.mode == "RGB"


def test_ico_is_square_with_several_sizes(samples):
    dst = convert(samples["rotated_jpg"], "ico")
    with Image.open(dst) as out:
        sizes = out.info["sizes"]
        assert all(w == h for w, h in sizes) and (16, 16) in sizes


def test_never_overwrites(samples):
    src = samples["plain_bmp"]
    first = convert(src, "png")
    second = convert(src, "png")
    assert first.name == "plain.png"
    assert second.name == "plain (1).png"
    assert src.exists()


def test_broken_file_leaves_nothing_behind(samples):
    src = samples["broken"]
    before = set(src.parent.iterdir())
    with pytest.raises(ConversionError, match="illisible"):
        convert(src, "png")
    assert set(src.parent.iterdir()) == before


def test_same_format_is_refused(samples):
    with pytest.raises(ConversionError, match="Déjà"):
        convert(samples["rgba_png"], "png")


def test_unknown_target():
    with pytest.raises(ConversionError):
        find_target("xyz")
