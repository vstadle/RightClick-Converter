"""--replace : les originaux bien convertis, et eux seuls, partent à la Corbeille.

La vraie Corbeille est remplacée par un faux pour ne pas la remplir à chaque test.
"""

from __future__ import annotations

import pytest

from quickconvert import trash
from quickconvert.cli import main


@pytest.fixture
def fake_trash(monkeypatch):
    sent: list[list[str]] = []
    refused: set[str] = set()

    def move_to_trash(paths):
        sent.append(list(paths))
        return [p for p in paths if p in refused]

    monkeypatch.setattr(trash, "move_to_trash", move_to_trash)
    return sent, refused


def test_replace_trashes_only_converted_originals(samples, fake_trash):
    sent, _ = fake_trash
    ok, broken = samples["plain_bmp"], samples["broken"]
    assert main(["convert", "--to", "png", "--replace", str(ok), str(broken)]) == 1  # broken.jpg échoue
    assert ok.with_suffix(".png").exists()
    assert sent == [[str(ok)]]  # pas l'image illisible


def test_without_replace_nothing_is_trashed(samples, fake_trash):
    sent, _ = fake_trash
    assert main(["convert", "--to", "png", str(samples["plain_bmp"])]) == 0
    assert sent == []


def test_refused_original_is_reported(samples, fake_trash, capsys):
    sent, refused = fake_trash
    refused.add(str(samples["plain_webp"]))
    assert main(["convert", "--to", "png", "--replace", str(samples["plain_webp"])]) == 0
    out = capsys.readouterr().out
    assert "0 original(aux) à la Corbeille" in out
    assert "[conservé] plain.webp" in out
