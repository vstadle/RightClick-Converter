"""Installation du sous-menu « Convertir en » dans le clic droit de l'Explorateur Windows.

Tout est écrit dans HKEY_CURRENT_USER : pas besoin des droits administrateur, et
`uninstall()` retire proprement les clés. Pour chaque extension lisible (.jpg, .png...) :

    HKCU\\Software\\Classes\\SystemFileAssociations\\.jpg\\shell\\QuickConvert
        MUIVerb = "Convertir en"      SubCommands = ""      Icon = ...\\quickconvert.ico
        shell\\01png\\command  = "pythonw.exe" -I -m quickconvert convert --gui --collect --replace --to png "%1"
        shell\\02webp\\command = ...

SystemFileAssociations s'applique quel que soit le programme par défaut de l'extension.
Sous Windows 11, ces entrées apparaissent dans « Afficher d'autres options » (Maj+F10) ;
le premier menu demande un paquet MSIX, voir windows11.py.
"""

from __future__ import annotations

import ctypes
import sys
import winreg
from pathlib import Path

from ..appdata import data_dir
from ..converters import CONVERTERS, Format

VERB = "QuickConvert"
MENU_LABEL = "Convertir en"
CLASSES = r"Software\Classes\SystemFileAssociations"
LEGACY_DISABLE = "LegacyDisable"  # valeur de l'Explorateur : verbe masqué, mais pas supprimé


def command_for(target_key: str) -> str:
    # pythonw = pas de fenêtre console ; -I = n'importe aucun module du dossier de l'image.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" -I -m quickconvert convert --gui --collect --replace --to {target_key} "%1"'


def menu_targets() -> dict[str, list[tuple[str, Format]]]:
    """{extension: [(nom de clé, format cible), ...]} pour chaque extension gérée.

    Sert aussi au menu Windows 11 (windows11.py), pour que les deux menus restent identiques.
    """
    targets: dict[str, list[tuple[str, Format]]] = {}
    for converter in CONVERTERS:
        # Même nom de clé pour un format donné dans tous les sous-menus : nécessaire
        # pour qu'une sélection mélangeant .jpg et .png lance la bonne commande partout.
        order = {fmt.key: i for i, fmt in enumerate(converter.formats, start=1)}
        for src in converter.readable():
            items = [(f"{order[t.key]:02d}{t.key}", t)
                     for t in converter.writable() if t.key != src.key]
            for ext in src.extensions:
                targets[ext] = items
    return targets


def menu_entries() -> dict[str, list[tuple[str, str, str]]]:
    """{extension: [(nom de clé, libellé, commande), ...]} pour chaque extension gérée."""
    return {ext: [(name, fmt.label, command_for(fmt.key)) for name, fmt in items]
            for ext, items in menu_targets().items()}


def install(classes: str = CLASSES) -> list[str]:
    from ..icon import build_icon

    icon = build_icon(data_dir() / "quickconvert.ico")
    entries = menu_entries()
    for ext, items in entries.items():
        root = rf"{classes}\{ext}\shell\{VERB}"
        hidden = _has_value(root, LEGACY_DISABLE)
        _delete_tree(root)  # repart de zéro si une ancienne version était installée
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root) as key:
            _set(key, "MUIVerb", MENU_LABEL)
            _set(key, "SubCommands", "")
            _set(key, "Icon", str(icon))
            _set(key, "MultiSelectModel", "Player")  # visible même au-delà de 15 fichiers
            if hidden:
                _set(key, LEGACY_DISABLE, "")
        for name, label, command in items:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{root}\shell\{name}") as key:
                _set(key, "MUIVerb", label)
                _set(key, "MultiSelectModel", "Player")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{root}\shell\{name}\command") as key:
                _set(key, "", command)
    _notify_shell()
    return sorted(entries)


def uninstall(classes: str = CLASSES) -> list[str]:
    removed = []
    try:
        parent = winreg.OpenKey(winreg.HKEY_CURRENT_USER, classes)
    except FileNotFoundError:
        return removed
    with parent:
        extensions = list(_subkeys(parent))
    for ext in extensions:
        root = rf"{classes}\{ext}\shell\{VERB}"
        if _delete_tree(root):
            removed.append(ext)
            # Nettoie les clés parentes si elles ne servaient qu'à nous.
            _delete_if_empty(rf"{classes}\{ext}\shell")
            _delete_if_empty(rf"{classes}\{ext}")
    _notify_shell()
    return removed


def set_hidden(hidden: bool, classes: str = CLASSES) -> None:
    """Masque (ou réaffiche) ce menu, sans le désinstaller.

    Le menu du paquet Windows 11 apparaît aussi dans « Afficher d'autres options » :
    windows11.py masque donc celui-ci tant que le paquet est installé, pour éviter deux
    « Convertir en » à la suite. `install()` conserve cet état.
    """
    for ext in menu_entries():
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{ext}\shell\{VERB}", 0,
                                 winreg.KEY_SET_VALUE)
        except FileNotFoundError:
            continue  # menu classique non installé pour cette extension
        with key:
            if hidden:
                _set(key, LEGACY_DISABLE, "")
            else:
                try:
                    winreg.DeleteValue(key, LEGACY_DISABLE)
                except FileNotFoundError:
                    pass
    _notify_shell()


def _has_value(path: str, name: str) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            winreg.QueryValueEx(key, name)
        return True
    except FileNotFoundError:
        return False


def _set(key, name: str, value: str) -> None:
    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _subkeys(key):
    i = 0
    while True:
        try:
            yield winreg.EnumKey(key, i)
        except OSError:
            return
        i += 1


def _delete_tree(path: str) -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        return False
    with key:
        children = list(_subkeys(key))
    for child in children:
        _delete_tree(rf"{path}\{child}")
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    return True


def _delete_if_empty(path: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            subkeys, values, _ = winreg.QueryInfoKey(key)
        if subkeys == 0 and values == 0:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass


def _notify_shell() -> None:
    """Prévient l'Explorateur que les associations ont changé (pas besoin de le redémarrer)."""
    SHCNE_ASSOCCHANGED, SHCNF_IDLIST = 0x08000000, 0
    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
