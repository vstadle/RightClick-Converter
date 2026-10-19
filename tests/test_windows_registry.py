"""Installe le menu dans une branche de test du registre (HKCU), vérifie, puis désinstalle."""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="registre Windows")

if sys.platform == "win32":
    import winreg

    from quickconvert.platforms import windows

TEST_ROOT = r"Software\QuickConvertTest"
TEST_CLASSES = TEST_ROOT + r"\SystemFileAssociations"


def _read(path, name=""):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
        return winreg.QueryValueEx(key, name)[0]


def test_install_and_uninstall():
    try:
        installed = windows.install(TEST_CLASSES)
        assert {".jpg", ".png", ".webp", ".gif"} <= set(installed)

        root = TEST_CLASSES + r"\.jpg\shell\QuickConvert"
        assert _read(root, "MUIVerb") == "Convertir en"
        assert _read(root, "SubCommands") == ""
        command = _read(root + r"\shell\02png\command")
        assert command.endswith('convert --gui --collect --replace --to png "%1"')
        assert "pythonw.exe" in command
        # Pas d'entrée « JPG » dans le sous-menu d'un .jpg, mais bien dans celui d'un .png.
        with pytest.raises(FileNotFoundError):
            _read(root + r"\shell\01jpg\command")
        assert _read(TEST_CLASSES + r"\.png\shell\QuickConvert\shell\01jpg", "MUIVerb") == "JPG"

        # Masqué pendant que le menu Windows 11 est installé, et le reste après un install().
        windows.set_hidden(True, TEST_CLASSES)
        assert _read(root, "LegacyDisable") == ""
        windows.install(TEST_CLASSES)
        assert _read(root, "LegacyDisable") == ""
        windows.set_hidden(False, TEST_CLASSES)
        with pytest.raises(FileNotFoundError):
            _read(root, "LegacyDisable")

        removed = windows.uninstall(TEST_CLASSES)
        assert set(removed) == set(installed)
        with pytest.raises(FileNotFoundError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, root)
    finally:
        windows._delete_tree(TEST_ROOT)
