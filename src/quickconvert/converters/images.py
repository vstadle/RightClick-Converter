"""Conversion d'images avec Pillow (+ pillow-heif pour le HEIC des iPhone)."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageCms, ImageOps, ImageSequence, UnidentifiedImageError, features

from .base import ConversionError, Converter, Format

try:
    import pillow_heif
except ImportError:  # le HEIC est alors simplement absent du menu
    pillow_heif = None
else:
    pillow_heif.register_heif_opener()

log = logging.getLogger(__name__)

# Les panoramas dépassent la limite « decompression bomb » par défaut de Pillow (~89 Mpx).
Image.MAX_IMAGE_PIXELS = 400_000_000

WHITE = (255, 255, 255)
HIGH_BIT_MODES = {"I", "I;16", "I;16L", "I;16B", "I;16N", "F"}
GRAY_MODES = {"1", "L", "LA", "La"} | HIGH_BIT_MODES
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


@dataclass(frozen=True)
class ImageFormat(Format):
    pil: str = ""                               # nom du format côté Pillow
    modes: frozenset[str] = frozenset({"RGB"})  # modes de couleur acceptés tels quels
    alpha: bool = True                          # gère la transparence ?
    metadata: bool = True                       # peut stocker l'EXIF et le profil ICC ?
    sequence: str = ""                          # "animation", "pages" ou "" (image unique)
    save_options: dict = field(default_factory=dict, compare=False, hash=False)


def _modes(*names: str) -> frozenset[str]:
    return frozenset(names)


JPG = ImageFormat("jpg", "JPG", (".jpg", ".jpeg", ".jfif", ".jpe"), pil="JPEG",
                  modes=_modes("L", "RGB", "CMYK"), alpha=False,
                  save_options={"quality": 92, "optimize": True})
PNG = ImageFormat("png", "PNG", (".png",), pil="PNG",
                  modes=_modes("1", "L", "LA", "P", "RGB", "RGBA", "I;16"), sequence="animation")
WEBP = ImageFormat("webp", "WEBP", (".webp",), pil="WEBP", modes=_modes("RGB", "RGBA"),
                   sequence="animation", save_options={"quality": 90, "method": 4})
AVIF = ImageFormat("avif", "AVIF", (".avif",), pil="AVIF", modes=_modes("RGB", "RGBA"),
                   sequence="animation", save_options={"quality": 80})
HEIC = ImageFormat("heic", "HEIC", (".heic", ".heif"), pil="HEIF", modes=_modes("RGB", "RGBA"),
                   save_options={"quality": 90})
GIF = ImageFormat("gif", "GIF", (".gif",), pil="GIF", modes=_modes("L", "P", "RGB", "RGBA"),
                  metadata=False, sequence="animation")
BMP = ImageFormat("bmp", "BMP", (".bmp", ".dib"), pil="BMP", modes=_modes("1", "L", "P", "RGB"),
                  alpha=False, metadata=False)
TIFF = ImageFormat("tiff", "TIFF", (".tif", ".tiff"), pil="TIFF",
                   modes=_modes("1", "L", "LA", "P", "RGB", "RGBA", "CMYK", "I;16"),
                   sequence="pages", save_options={"compression": "tiff_lzw"})
ICO = ImageFormat("ico", "ICO", (".ico",), pil="ICO", modes=_modes("RGBA"), metadata=False)
PDF = ImageFormat("pdf", "PDF", (".pdf",), pil="PDF", modes=_modes("L", "RGB"),
                  alpha=False, metadata=False, sequence="pages", can_read=False)

# Formats source pouvant contenir plusieurs images, et de quel type.
_SOURCE_SEQUENCE = {"GIF": "animation", "WEBP": "animation", "PNG": "animation",
                    "AVIF": "animation", "TIFF": "pages"}


class ImageConverter(Converter):
    category = "images"

    def __init__(self) -> None:
        formats = [JPG, PNG, WEBP]
        if features.check("avif"):
            formats.append(AVIF)
        if pillow_heif is not None:
            formats.append(HEIC)
        formats += [GIF, BMP, TIFF, ICO, PDF]
        self.formats = tuple(formats)

    def convert(self, src: Path, dst: Path, target: Format) -> None:
        assert isinstance(target, ImageFormat)
        try:
            im = Image.open(src)
        except UnidentifiedImageError:
            raise ConversionError("Image illisible : format non reconnu ou fichier abîmé") from None
        except Image.DecompressionBombError:
            raise ConversionError("Image trop grande (plus de 400 mégapixels)") from None

        with im:
            icc = im.info.get("icc_profile")
            multi = (getattr(im, "n_frames", 1) > 1
                     and _SOURCE_SEQUENCE.get(im.format or "") == target.sequence)
            if multi:
                frames, params = _prepare_sequence(im, target, icc)
            else:
                frames, params = _prepare_single(im, target, icc)

        if target is PDF:
            # Taille de page ≈ A4 quelle que soit la définition de l'image.
            params["resolution"] = max(72.0, max(frames[0].size) / 11.69)
            params["title"] = src.stem
        if len(frames) > 1:
            params.update(save_all=True, append_images=frames[1:])
        _save(frames[0], dst, target, params)


def _prepare_single(im: Image.Image, fmt: ImageFormat, icc: bytes | None):
    img = ImageOps.exif_transpose(im)  # applique la rotation EXIF des photos
    exif = img.info.get("exif")
    dpi = img.info.get("dpi")
    img, icc = _fit(img, fmt, icc)

    params = dict(fmt.save_options)
    if fmt.metadata:
        if icc:
            params["icc_profile"] = icc
        if exif:
            params["exif"] = exif
    if dpi and fmt in (JPG, PNG, TIFF) and min(dpi) > 0:
        params["dpi"] = dpi
    if fmt is ICO:
        img = _square(img)
        params["sizes"] = [(s, s) for s in ICO_SIZES if s <= img.width] or [img.size]
    return [img], params


def _prepare_sequence(im: Image.Image, fmt: ImageFormat, icc: bytes | None):
    frames = [frame.copy() for frame in ImageSequence.Iterator(im)]
    durations = [f.info.get("duration", 100) for f in frames]

    # Toutes les images dans le même mode, sinon certains encodeurs les dégradent.
    if fmt.alpha and any(f.has_transparency_data for f in frames):
        frames = [f.convert("RGBA") for f in frames]
    else:
        frames = [(_flatten(f) if f.has_transparency_data else f).convert("RGB") for f in frames]

    params = dict(fmt.save_options)
    if fmt.metadata and icc and _icc_space(icc) == b"RGB ":
        params["icc_profile"] = icc
    if fmt.sequence == "animation":
        params.update(duration=durations, loop=im.info.get("loop", 0))
        if fmt is GIF:
            params["disposal"] = 2  # chaque image remplace la précédente (pas de traînées)
    return frames, params


def _fit(img: Image.Image, fmt: ImageFormat, icc: bytes | None) -> tuple[Image.Image, bytes | None]:
    """Adapte le mode de couleur de `img` à ce que `fmt` sait enregistrer."""
    if img.mode in HIGH_BIT_MODES and img.mode not in fmt.modes:
        img = _to_8bit(img)

    if img.mode == "CMYK" and "CMYK" not in fmt.modes:
        img, icc = _to_srgb(img, icc), None
    elif icc and not fmt.metadata and img.mode in ("RGB", "RGBA"):
        # Le profil (ex. Display P3 des iPhone) serait perdu : on convertit les couleurs en sRGB.
        img, icc = _to_srgb(img, icc), None

    if not fmt.alpha and img.has_transparency_data:
        img = _flatten(img)
    elif img.mode in ("RGBA", "LA") and img.getchannel("A").getextrema() == (255, 255):
        img = img.convert(img.mode[:-1])  # canal alpha inutile (entièrement opaque)

    if img.mode not in fmt.modes:
        img = img.convert(_closest_mode(img, fmt))

    if icc and _icc_space(icc) != _mode_space(img.mode):
        icc = None  # un profil RGB sur une image en niveaux de gris serait invalide
    return img, icc


def _closest_mode(img: Image.Image, fmt: ImageFormat) -> str:
    alpha = fmt.alpha and img.has_transparency_data
    gray = img.mode in GRAY_MODES
    candidates = [("LA" if alpha else "L") if gray else ("RGBA" if alpha else "RGB"),
                  "RGBA" if alpha else "RGB", "RGB", "RGBA"]
    return next((m for m in candidates if m in fmt.modes), sorted(fmt.modes)[0])


def _flatten(img: Image.Image) -> Image.Image:
    """Pose l'image sur un fond blanc (pour les formats sans transparence)."""
    rgba = img.convert("RGBA")
    out = Image.new("RGB", img.size, WHITE)
    out.paste(rgba, mask=rgba.getchannel("A"))
    return out.convert("L") if img.mode in ("LA", "La") else out


def _to_8bit(img: Image.Image) -> Image.Image:
    if img.mode.startswith("I;16"):
        scale = 1 / 257  # 0..65535 -> 0..255
    else:
        hi = img.getextrema()[1]
        scale = 255 / hi if hi and hi > 255 else 1
    base = img if img.mode == "F" else img.convert("I")
    return base.point(lambda v: v * scale).convert("L")


_srgb_profile = None


def _to_srgb(img: Image.Image, icc: bytes | None) -> Image.Image:
    global _srgb_profile
    mode = "RGBA" if img.mode == "RGBA" else "RGB"
    if icc:
        try:
            if _srgb_profile is None:
                _srgb_profile = ImageCms.createProfile("sRGB")
            src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            out = ImageCms.profileToProfile(img, src_profile, _srgb_profile, outputMode=mode)
            if out is not None:
                return out
        except (ImageCms.PyCMSError, OSError, ValueError) as exc:
            log.warning("Profil ICC ignoré : %s", exc)
    return img.convert(mode)


def _icc_space(icc: bytes) -> bytes:
    return icc[16:20]


def _mode_space(mode: str) -> bytes:
    if mode == "CMYK":
        return b"CMYK"
    return b"GRAY" if mode in GRAY_MODES else b"RGB "


def _square(img: Image.Image) -> Image.Image:
    """Centre l'image sur un carré transparent (une icône doit être carrée)."""
    w, h = img.size
    if w == h:
        return img
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2))
    return canvas


def _save(img: Image.Image, dst: Path, fmt: ImageFormat, params: dict) -> None:
    try:
        img.save(dst, format=fmt.pil, **params)
    except (OSError, ValueError, TypeError, SyntaxError) as exc:
        if not ({"exif", "icc_profile"} & params.keys()):
            raise
        # Métadonnées exotiques refusées par l'encodeur : on réessaie sans elles.
        log.warning("Métadonnées ignorées pour %s : %s", dst.name, exc)
        params = {k: v for k, v in params.items() if k not in ("exif", "icc_profile")}
        img.save(dst, format=fmt.pil, **params)
