"""Envoi de fichiers à la Corbeille : jamais de suppression définitive sans confirmation."""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)


def move_to_trash(paths: list[str]) -> list[str]:
    """Envoie `paths` (chemins absolus) à la Corbeille. Retourne ceux restés en place."""
    if not paths:
        return []
    if sys.platform != "win32":
        log.warning("Corbeille pas encore gérée sur ce système : originaux conservés")
        return list(paths)  # macOS : NSFileManager.trashItem, à faire avec le portage
    _recycle(paths)  # un seul appel pour tout le lot (rapide)...
    left = [p for p in paths if os.path.lexists(p)]
    for path in left:  # ...puis un par un, si un fichier verrouillé a interrompu le lot
        _recycle([path])
    return [p for p in left if os.path.lexists(p)]


def _recycle(paths: list[str]) -> None:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE = 3
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO = 0x4, 0x10, 0x40
    FOF_NOERRORUI = 0x400
    FOF_WANTNUKEWARNING = 0x4000  # pas de Corbeille (clé USB, réseau) : Windows demande d'abord
    # Liste terminée par deux caractères nuls : le tampon ajoute le second.
    buffer = ctypes.create_unicode_buffer("\0".join(paths) + "\0")
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=ctypes.cast(buffer, wintypes.LPCWSTR),
                         fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
                         | FOF_NOERRORUI | FOF_WANTNUKEWARNING)
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result:
        log.warning("Corbeille : code %#x pour %d fichier(s)", result, len(paths))
