from __future__ import annotations

from .base import ConversionError, Converter, Format
from .images import ImageConverter

# Ajouter ici les futures familles (audio, vidéo, documents...).
CONVERTERS: tuple[Converter, ...] = (ImageConverter(),)


def find_target(key: str) -> tuple[Converter, Format]:
    """Retourne le convertisseur et le format de sortie correspondant à `key` ("png"...)."""
    key = key.lower().lstrip(".")
    for converter in CONVERTERS:
        for fmt in converter.writable():
            if fmt.key == key or ("." + key) in fmt.extensions:
                return converter, fmt
    raise ConversionError(f"Format de sortie inconnu : {key}")


__all__ = ["CONVERTERS", "ConversionError", "Converter", "Format", "find_target"]
