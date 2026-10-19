"""Simule l'Explorateur : une commande lancée par fichier sélectionné, toutes en même temps."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest
from PIL import Image

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="tube nommé Windows")


def test_simultaneous_launches_are_grouped(tmp_path):
    files = []
    for i in range(12):
        path = tmp_path / f"photo{i:02d}.bmp"
        Image.new("RGB", (200, 150), (i * 20, 80, 160)).save(path)
        files.append(path)

    command = [sys.executable, "-I", "-m", "quickconvert", "convert", "--collect", "--to", "png"]
    started = time.monotonic()
    procs = [subprocess.Popen(command + [str(f)], stdout=subprocess.PIPE, text=True,
                              encoding="cp1252", errors="replace") for f in files]
    outputs = [p.communicate(timeout=60)[0] for p in procs]
    elapsed = time.monotonic() - started

    servers = [o for o in outputs if "converti(s)" in o]
    print(f"{len(servers)} serveur(s) pour {len(files)} lancements en {elapsed:.1f}s")
    assert all(p.returncode == 0 for p in procs)
    assert 1 <= len(servers) <= 2  # 1 attendu ; 2 si un retardataire arrive après la fermeture
    produced = sorted(p.name for p in tmp_path.glob("*.png"))
    assert produced == sorted(f.with_suffix(".png").name for f in files)  # ni oubli ni doublon
