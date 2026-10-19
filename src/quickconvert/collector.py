"""Regroupe dans un seul processus les fichiers d'une même sélection.

L'Explorateur Windows lance la commande du menu une fois *par fichier* sélectionné.
Le premier processus crée un tube nommé (named pipe) et devient le « serveur » ; les
suivants lui envoient leur chemin puis se terminent aussitôt. Résultat : une seule
fenêtre de progression et un seul bilan pour toute la sélection, au lieu de 50 Python
lancés en même temps.

Sur macOS (Actions rapides du Finder) tous les fichiers arrivent déjà en une seule
commande : `join()` y renvoie directement un Collector local.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time

log = logging.getLogger(__name__)

IDLE_SECONDS = 1.0    # silence requis avant de fermer le tube (processus encore en démarrage)
JOIN_TIMEOUT = 15.0   # au-delà, on traite le fichier seul plutôt que de le perdre


class Collector:
    def __init__(self, paths: list[str] = (), listener=None, address: str = ""):
        self._lock = threading.Lock()
        self._pending = list(paths)
        self._listener = listener
        self._address = address
        self._closed = listener is None
        self._last = time.monotonic()
        if listener is not None:
            threading.Thread(target=self._serve, name="collector", daemon=True).start()

    @classmethod
    def join(cls, key: str, paths: list[str]) -> Collector | None:
        """Devient le serveur du lot `key` (retourne un Collector) ou confie `paths`
        au serveur déjà lancé (retourne None : ce processus n'a plus rien à faire)."""
        if sys.platform != "win32":
            return cls(paths)
        from multiprocessing.connection import Listener

        address = _pipe_address(key)
        deadline = time.monotonic() + JOIN_TIMEOUT
        delay = 0.01
        while time.monotonic() < deadline:
            try:
                listener = Listener(address, family="AF_PIPE")
            except OSError:  # le tube existe déjà : un serveur tourne
                if _deliver(address, paths):
                    return None
            else:
                return cls(paths, listener, address)
            time.sleep(delay)
            delay = min(delay * 2, 0.25)
        log.warning("Aucun serveur joignable pour %s, traitement isolé", key)
        return cls(paths)

    def drain(self) -> list[str]:
        """Retire et retourne les chemins reçus depuis le dernier appel."""
        with self._lock:
            items, self._pending = self._pending, []
            return items

    def try_close(self, idle: float = IDLE_SECONDS) -> bool:
        """Ferme le lot si plus rien n'est en attente depuis `idle` secondes."""
        with self._lock:
            if self._pending:
                return False
            if not self._closed and time.monotonic() - self._last < idle:
                return False
            already_closed, self._closed = self._closed, True
        if not already_closed:
            self._wake_server()
        return True

    def close(self) -> None:
        with self._lock:
            already_closed, self._closed = self._closed, True
        if not already_closed:
            self._wake_server()

    def _serve(self) -> None:
        try:
            while True:
                try:
                    conn = self._listener.accept()
                except OSError:
                    return
                with conn:
                    try:
                        paths = json.loads(conn.recv_bytes(1 << 20))
                    except (OSError, EOFError, ValueError):
                        continue
                    with self._lock:
                        if self._closed:
                            return  # le client réessaiera et deviendra le prochain serveur
                        self._pending.extend(str(p) for p in paths)
                        self._last = time.monotonic()
                    try:
                        conn.send_bytes(b"ok")
                    except OSError:
                        pass
        finally:
            self._listener.close()

    def _wake_server(self) -> None:
        """Débloque accept() pour que le thread serveur se termine et libère le tube."""
        threading.Thread(target=_deliver, args=(self._address, []), daemon=True).start()


def _deliver(address: str, paths: list[str]) -> bool:
    from multiprocessing.connection import Client

    try:
        with Client(address, family="AF_PIPE") as conn:
            conn.send_bytes(json.dumps(paths).encode())
            return conn.recv_bytes() == b"ok"
    except (OSError, EOFError):
        return False


def _pipe_address(key: str) -> str:
    import getpass

    user = re.sub(r"[^A-Za-z0-9_.-]", "_", getpass.getuser())
    return rf"\\.\pipe\quickconvert-{user}-{re.sub(r'[^a-z0-9]', '', key.lower())}"
