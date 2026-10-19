"""Menu Windows 11 : manifeste, menu.txt, et la DLL chargée par un banc d'essai (test_menu.cpp).

Rien n'est installé : la DLL est copiée dans un dossier temporaire avec son menu.txt, et
test_menu.exe joue le rôle de l'Explorateur (sélection, sous-menus, clic).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows uniquement")

if sys.platform == "win32":
    from quickconvert.cli import main
    from quickconvert.platforms import windows, windows11

HIDDEN, VISIBLE = 2, 0  # EXPCMDSTATE

RECORD = """\
import json, os, sys
out, args = sys.argv[1], sys.argv[2:]
data = {"args": args}
if args[:1] == ["--list-file"]:
    with open(args[1], encoding="utf-8") as f:
        data["list"] = f.read().splitlines()
with open(out + ".tmp", "w", encoding="utf-8") as f:
    json.dump(data, f)
os.replace(out + ".tmp", out)
"""


def test_manifest():
    xml = windows11.manifest(sorted(windows.menu_targets()))
    root = ET.fromstring(xml.encode("utf-8"))
    ns = {"m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
          "d5": "http://schemas.microsoft.com/appx/manifest/desktop/windows10/5",
          "com": "http://schemas.microsoft.com/appx/manifest/com/windows10"}
    identity = root.find("m:Identity", ns)
    assert identity.get("Publisher") == windows11.PUBLISHER
    assert len(identity.get("Version").split(".")) == 4
    types = {t.get("Type") for t in root.iter(f"{{{ns['d5']}}}ItemType")}
    assert types == set(windows.menu_targets())
    assert {".jpg", ".png", ".webp"} <= types
    assert root.find(".//com:Class", ns).get("Id") == windows11.CLSID
    # Le même CLSID doit être compilé dans la DLL.
    source = (windows11.source_dir() / "menu.cpp").read_text(encoding="utf-8")
    assert "0x" + windows11.CLSID.split("-")[0] in source


def test_menu_config_matches_classic_menu(tmp_path):
    config = windows11.menu_config(tmp_path / "icon.ico")
    items = [line.split("\t") for line in config.splitlines() if line.startswith("item\t")]
    for ext, entries in windows.menu_entries().items():
        labels = [label for _, label, _ in entries]
        assert [i[1] for i in items if ext in i[3].split()] == labels
    jpg = next(i for i in items if i[1] == "JPG")
    assert jpg[2].endswith("-I -m quickconvert convert --gui --replace --to jpg")
    assert "--collect" not in config and "%1" not in config


def test_cli_list_file(samples, tmp_path):
    listing = tmp_path / "selection.txt"
    listing.write_text(f"{samples['plain_bmp']}\n{samples['rgba_png']}\n", encoding="utf-8")
    assert main(["convert", "--to", "webp", "--list-file", str(listing)]) == 0
    assert samples["plain_bmp"].with_suffix(".webp").exists()
    assert samples["rgba_png"].with_suffix(".webp").exists()
    assert not listing.exists()  # fichier temporaire consommé


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    compiler = windows11.find_compiler()
    if compiler is None:
        pytest.skip("g++ (MSYS2) introuvable")
    bins = windows11.build(log=lambda msg: None)
    exe = tmp_path_factory.mktemp("harness") / "test_menu.exe"
    subprocess.run([str(compiler), "-std=c++17", "-O2", "-municode", "-static", "-o", str(exe),
                    str(windows11.source_dir() / "test_menu.cpp"), "-lole32", "-lshell32", "-luuid"],
                   check=True, capture_output=True, env=windows11._compiler_env(compiler))
    return exe, bins / windows11.DLL


def _install_dll(folder: Path, dll: Path, items: list[tuple[str, str, str]]) -> Path:
    folder.mkdir()
    shutil.copy2(dll, folder / dll.name)
    lines = ["# test", "title\tConvertir en", "icon\tC:\\test\\icon.ico"]
    lines += [f"item\t{label}\t{command}\t{exts}" for label, command, exts in items]
    (folder / "menu.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder / dll.name


def _run(harness, dll: Path, click: str, files: list[Path], env=None) -> tuple[tuple, dict[str, int], list[str]]:
    exe, _ = harness
    listing = dll.parent.parent / "selection.txt"  # trop de fichiers pour la ligne de commande
    listing.write_text("\n".join(map(str, files)), encoding="utf-8")
    result = subprocess.run([str(exe), str(dll), click, f"@{listing}"],
                            capture_output=True, check=True, timeout=60, env=env)
    lines = [line.split("|") for line in result.stdout.decode("utf-8", "replace").splitlines()]
    root = next(tuple(l[1:]) for l in lines if l[0] == "root")
    subs = {l[1]: int(l[2]) for l in lines if l[0] == "sub"}
    other = [f"{l[0]}|{l[1]}" for l in lines if l[0] in ("invoke", "unload")]
    return root, subs, other


def _wait_json(path: Path, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, "la DLL n'a pas lancé la commande"
        time.sleep(0.05)
    return json.loads(path.read_text(encoding="utf-8"))


def _touch(folder: Path, *names: str) -> list[Path]:
    folder.mkdir(exist_ok=True)
    paths = [folder / n for n in names]
    for p in paths:
        p.write_bytes(b"")
    return paths


def test_dll_menu_and_single_launch(harness, tmp_path):
    record = tmp_path / "record.py"
    record.write_text(RECORD, encoding="utf-8")
    out = tmp_path / "args.json"
    command = f'"{sys.executable}" -I "{record}" "{out}"'
    dll = _install_dll(tmp_path / "ext", harness[1], [
        ("JPG", command + " --to jpg", ".png .webp"),
        ("PNG", command + " --to png", ".jpg .jpeg .webp"),
    ])
    jpg, jpg_upper, png, txt = _touch(tmp_path / "images é", "a.jpg", "B.JPG", "c.png", "d.txt")

    # Sélection mixte : tout est proposé ; le clic sur PNG ne passe que les fichiers .jpg,
    # tous dans UN seul processus.
    root, subs, other = _run(harness, dll, "PNG", [jpg, jpg_upper, png, txt])
    assert root == ("Convertir en", str(VISIBLE), "1", "C:\\test\\icon.ico")
    assert subs == {"JPG": VISIBLE, "PNG": VISIBLE}
    assert other == ["invoke|0", "unload|0"]
    assert _wait_json(out) == {"args": ["--to", "png", str(jpg), str(jpg_upper)]}

    # Que des .png : pas de « PNG » dans le sous-menu.
    _, subs, _ = _run(harness, dll, "-", [png])
    assert subs == {"JPG": VISIBLE, "PNG": HIDDEN}

    # Rien de convertible : menu caché.
    root, _, _ = _run(harness, dll, "-", [txt])
    assert root[1] == str(HIDDEN)


def test_dll_without_menu_txt_hides_menu(harness, tmp_path):
    folder = tmp_path / "ext"
    folder.mkdir()
    dll = folder / harness[1].name
    shutil.copy2(harness[1], dll)
    root, subs, _ = _run(harness, dll, "-", _touch(tmp_path, "a.jpg"))
    assert root[1] == str(HIDDEN) and subs == {}


def test_dll_end_to_end_with_list_file(harness, tmp_path):
    """Très grande sélection : la liste passe par --list-file, et la vraie commande convertit tout."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")  # comme le vrai menu
    command = f'"{pythonw}" -I -m quickconvert convert --to png'
    dll = _install_dll(tmp_path / "ext", harness[1], [("PNG", command, ".jpg .bmp")])
    folder = tmp_path / "photos"
    folder.mkdir()
    files = []
    for i in range(160):  # 160 chemins d'environ 200 caractères > limite de la ligne de commande
        path = folder / f"{i:03d}-{'vacances-ete-' * 9}{'é' if i % 2 else ''}.jpg"
        Image.new("RGB", (8, 8), (i, 100, 200)).save(path)
        files.append(path)
    assert sum(len(str(p)) + 3 for p in files) > 30000

    temp = tmp_path / "temp"  # dossier temporaire de la DLL (GetTempPath lit TMP)
    temp.mkdir()
    env = dict(os.environ, TMP=str(temp), TEMP=str(temp))
    _, _, other = _run(harness, dll, "PNG", files, env=env)
    assert other == ["invoke|0", "unload|0"]
    deadline = time.monotonic() + 120
    while not all(p.with_suffix(".png").exists() for p in files) or any(temp.iterdir()):
        assert time.monotonic() < deadline, "conversion incomplète ou liste temporaire non supprimée"
        time.sleep(0.2)
