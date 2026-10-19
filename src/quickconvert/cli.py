"""Ligne de commande : `python -m quickconvert {convert,formats,install,uninstall,...-win11}`."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import APP_NAME, __version__
from .appdata import setup_logging

log = logging.getLogger("quickconvert")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quickconvert", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    convert = commands.add_parser("convert", help="convertir des fichiers")
    convert.add_argument("--to", required=True, metavar="FORMAT", help="png, jpg, webp...")
    convert.add_argument("--gui", action="store_true", help="fenêtre de progression (menu clic droit)")
    convert.add_argument("--collect", action="store_true",
                         help="regrouper les lancements simultanés en un seul lot")
    convert.add_argument("--replace", action="store_true",
                         help="envoyer l'original à la Corbeille une fois converti")
    convert.add_argument("--list-file", metavar="FICHIER",
                         help="fichier temporaire de chemins (UTF-8, un par ligne), supprimé après "
                              "lecture : utilisé par le menu Windows 11 pour les très grandes sélections")
    convert.add_argument("files", nargs="*")

    commands.add_parser("formats", help="lister les formats disponibles")
    commands.add_parser("install", help="ajouter « Convertir en » au clic droit")
    commands.add_parser("uninstall", help="retirer « Convertir en » du clic droit")
    commands.add_parser("install-win11", help="ajouter « Convertir en » au premier menu de Windows 11")
    commands.add_parser("uninstall-win11", help="retirer le menu Windows 11")

    args = parser.parse_args(argv)
    if args.command == "convert" and not (args.files or args.list_file):
        convert.error("aucun fichier à convertir")
    setup_logging()
    if sys.stdout:
        sys.stdout.reconfigure(errors="replace")  # console Windows en cp1252
    handlers = {"convert": _convert, "formats": _formats,
                "install": _install, "uninstall": _uninstall,
                "install-win11": _install_win11, "uninstall-win11": _uninstall_win11}
    try:
        return handlers[args.command](args)
    except Exception as exc:
        log.exception("Erreur inattendue")
        if getattr(args, "gui", False):
            from .gui import show_message
            show_message(f"Erreur inattendue : {exc}", warning=True)
            return 1
        raise


def _convert(args) -> int:
    from .collector import Collector

    files = list(args.files)
    if args.list_file:
        files += _read_list_file(args.list_file)
    paths = [os.path.abspath(p) for p in files]
    if args.collect:
        source = Collector.join(args.to, paths)
        if source is None:
            return 0  # un autre processus s'occupe de ces fichiers
    else:
        source = Collector(paths)

    # Imports lourds (Pillow...) seulement pour le processus qui convertit vraiment.
    from .converters import ConversionError
    from .runner import Batch

    try:
        batch = Batch(args.to, source, replace=args.replace)
    except ConversionError as exc:
        source.close()
        if args.gui:
            from .gui import show_message
            show_message(str(exc), warning=True)
        else:
            print(exc, file=sys.stderr)
        return 2

    if args.gui:
        from .gui import run_with_progress
        run_with_progress(batch)
    else:
        def report(path, dst, error):
            name = os.path.basename(path)
            print(f"[ok]     {name} -> {dst.name}" if dst else f"[erreur] {name} : {error}", flush=True)

        batch.on_result = report
        batch.run()
        print(f"{len(batch.converted)} converti(s), {len(batch.failures)} erreur(s)")
        if args.replace:
            print(f"{len(batch.originals) - len(batch.kept)} original(aux) à la Corbeille")
            for path in batch.kept:
                print(f"[conservé] {os.path.basename(path)} : Corbeille impossible")
    return 1 if batch.failures else 0


def _read_list_file(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8-sig") as f:
            return [line for line in f.read().splitlines() if line.strip()]
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _formats(args) -> int:
    from .converters import CONVERTERS

    for converter in CONVERTERS:
        print(f"[{converter.category}]")
        for fmt in converter.formats:
            rights = ("lecture " if fmt.can_read else "") + ("écriture" if fmt.can_write else "")
            print(f"  {fmt.key:<6} {' '.join(fmt.extensions):<28} {rights}")
    return 0


def _install(args) -> int:
    if sys.platform != "win32":
        print("Installation du menu pas encore disponible sur ce système.", file=sys.stderr)
        return 2
    from .platforms import windows

    extensions = windows.install()
    print(f"Menu « {windows.MENU_LABEL} » installé pour {len(extensions)} extensions :")
    print("  " + " ".join(extensions))
    print("Windows 11 : clic droit > « Afficher d'autres options » (ou Maj+F10) ;")
    print("installer-win11.bat l'ajoute aussi au premier menu.")
    return 0


def _uninstall(args) -> int:
    if sys.platform != "win32":
        return 0
    from .platforms import windows

    removed = windows.uninstall()
    print(f"Menu retiré pour {len(removed)} extensions.")
    return 0


def _install_win11(args) -> int:
    if sys.platform != "win32":
        print("Commande réservée à Windows 11.", file=sys.stderr)
        return 2
    from .platforms import windows11

    if not windows11.is_windows11():
        print("Windows 10 : le menu classique (installer.bat) apparaît déjà directement dans le clic droit.")
        return 0
    try:
        windows11.install()
    except windows11.NeedsTrust as exc:
        print(exc)
        return 3
    except windows11.InstallError as exc:
        print(f"Menu Windows 11 non installé :\n{exc}", file=sys.stderr)
        return 1
    print("Menu « Convertir en » ajouté au premier menu du clic droit de Windows 11.")
    print("S'il n'apparaît pas tout de suite : Gestionnaire des tâches > Explorateur Windows > Redémarrer.")
    return 0


def _uninstall_win11(args) -> int:
    if sys.platform != "win32":
        return 0
    from .platforms import windows11

    try:
        removed, still_trusted = windows11.uninstall()
    except windows11.InstallError as exc:
        print(f"Échec du retrait du menu Windows 11 :\n{exc}", file=sys.stderr)
        return 1
    print("Menu Windows 11 retiré." if removed else "Menu Windows 11 : rien à retirer.")
    if still_trusted:
        print("Pour retirer aussi l'approbation du certificat : clic droit sur")
        print(f"{windows11.source_dir() / 'retirer-certificat.bat'} > « Exécuter en tant qu'administrateur ».")
    return 0
