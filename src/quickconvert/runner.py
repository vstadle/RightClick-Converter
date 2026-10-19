"""Conversion d'un fichier (nommage, écriture sûre) et d'un lot de fichiers en parallèle."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from .collector import Collector
from .converters import ConversionError, Converter, Format, find_target

log = logging.getLogger(__name__)


def convert_file(src: Path, converter: Converter, target: Format) -> Path:
    """Convertit `src` à côté de l'original, sans jamais écraser un fichier existant."""
    src = Path(src)
    if not src.is_file():
        raise ConversionError("Fichier introuvable")
    if src.suffix.lower() in target.extensions:
        raise ConversionError(f"Déjà au format {target.label}")

    dst = reserve_path(src.with_suffix(target.ext))
    tmp = dst.with_name(f"~{dst.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        converter.convert(src, tmp, target)
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        dst.unlink(missing_ok=True)
        raise
    return dst


def reserve_path(path: Path) -> Path:
    """Crée un fichier vide au premier nom libre : photo.png, photo (1).png, photo (2).png...

    La création exclusive évite que deux conversions simultanées choisissent le même nom.
    """
    for n in range(10_000):
        candidate = path if n == 0 else path.with_name(f"{path.stem} ({n}){path.suffix}")
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.close(fd)
        return candidate
    raise ConversionError("Aucun nom de fichier libre pour le résultat")


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, ConversionError):
        return str(exc)
    if isinstance(exc, PermissionError):
        return "Accès refusé (fichier ouvert ailleurs ou dossier protégé)"
    if isinstance(exc, FileNotFoundError):
        return "Fichier introuvable"
    if isinstance(exc, MemoryError):
        return "Pas assez de mémoire pour cette image"
    return f"{type(exc).__name__} : {exc}"


class Batch:
    """Un lot de conversions vers un même format, alimenté par un Collector.

    `run()` tourne dans un thread ; l'interface lit simplement les compteurs.
    """

    def __init__(self, target_key: str, source: Collector, workers: int | None = None,
                 replace: bool = False):
        self.converter, self.target = find_target(target_key)
        self.source = source
        self.workers = workers or min(4, os.cpu_count() or 2)
        self.replace = replace  # originaux convertis envoyés à la Corbeille à la fin du lot
        self.on_result: Callable[[str, Path | None, str | None], None] | None = None

        self.total = 0
        self.done = 0
        self.converted: list[Path] = []
        self.originals: list[str] = []   # sources des fichiers de `converted`
        self.kept: list[str] = []        # originaux que la Corbeille a refusés
        self.failures: list[tuple[str, str]] = []
        self.cancelled = 0
        self.current = ""
        self.finished = False
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:
        seen: set[str] = set()
        running: dict[Future, str] = {}
        try:
            with ThreadPoolExecutor(self.workers, thread_name_prefix="convert") as pool:
                while True:
                    if not self.is_cancelled:
                        for path in self.source.drain():
                            key = os.path.normcase(os.path.abspath(path))
                            if key not in seen:
                                seen.add(key)
                                self.total += 1
                                running[pool.submit(self._convert_one, path)] = path

                    if running:
                        if self.is_cancelled:
                            for fut in running:
                                fut.cancel()
                        finished, _ = wait(running, timeout=0.1, return_when=FIRST_COMPLETED)
                        for fut in finished:
                            self._record(running.pop(fut), fut)
                    elif self.is_cancelled:
                        self.source.close()
                        break
                    elif self.source.try_close():
                        break
                    else:
                        time.sleep(0.05)
            if self.replace:
                self._trash_originals()
        finally:
            self.finished = True

    def _trash_originals(self) -> None:
        # Seulement les fichiers bien convertis, et à la Corbeille (récupérables) : un
        # original n'est jamais perdu sur une erreur ou un arrêt brutal en cours de lot.
        from .trash import move_to_trash

        self.current = "Corbeille…"
        self.kept = move_to_trash([os.path.abspath(p) for p in self.originals])
        for path in self.kept:
            log.warning("Original conservé (Corbeille impossible) : %s", path)

    def _convert_one(self, path: str) -> Path:
        self.current = os.path.basename(path)
        return convert_file(Path(path), self.converter, self.target)

    def _record(self, path: str, fut: Future) -> None:
        self.done += 1
        if fut.cancelled():
            self.cancelled += 1
            return
        exc = fut.exception()
        if exc is None:
            dst = fut.result()
            self.converted.append(dst)
            self.originals.append(path)
            log.info("%s -> %s", path, dst.name)
            if self.on_result:
                self.on_result(path, dst, None)
        else:
            message = describe_error(exc)
            self.failures.append((path, message))
            log.error("%s : %s", path, message, exc_info=not isinstance(exc, ConversionError))
            if self.on_result:
                self.on_result(path, None, message)
