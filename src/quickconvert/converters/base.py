from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ConversionError(Exception):
    """Erreur dont le message peut être montré tel quel à l'utilisateur."""


@dataclass(frozen=True)
class Format:
    """Un format de fichier géré par un convertisseur."""

    key: str                     # identifiant court utilisé en ligne de commande : "png"
    label: str                   # texte affiché dans le menu : "PNG"
    extensions: tuple[str, ...]  # la première sert à nommer les fichiers produits
    can_read: bool = True
    can_write: bool = True

    @property
    def ext(self) -> str:
        return self.extensions[0]


class Converter:
    """Une famille de conversions (images aujourd'hui ; audio, vidéo, documents plus tard).

    Pour ajouter une famille : sous-classer, remplir `formats`, implémenter `convert`,
    puis l'ajouter à CONVERTERS dans converters/__init__.py. Le menu clic droit et la
    ligne de commande la prennent en compte automatiquement.
    """

    category: str = ""
    formats: tuple[Format, ...] = ()

    def readable(self) -> list[Format]:
        return [f for f in self.formats if f.can_read]

    def writable(self) -> list[Format]:
        return [f for f in self.formats if f.can_write]

    def convert(self, src: Path, dst: Path, target: Format) -> None:
        """Lit `src` et écrit le résultat dans `dst` (chemin déjà réservé, à écraser)."""
        raise NotImplementedError
