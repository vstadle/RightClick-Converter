"""Sous-menu « Convertir en » dans le premier menu du clic droit de Windows 11.

Windows 11 n'y affiche que les commandes IExplorerCommand déclarées par un paquet MSIX
signé. Le paquet est ici « sparse » (avec emplacement externe) : il ne contient que son
manifeste et ses logos, et donne une identité à la DLL de windows11/menu.cpp, copiée avec
menu.txt (la liste des formats) dans windows11\\bin\\external.

`install()` :
    1. compile windows11/*.cpp avec le g++ de MSYS2 si besoin (dans windows11/bin) ;
    2. crée une fois un certificat autosigné dans Cert:\\CurrentUser\\My ;
    3. écrit menu.txt, AppxManifest.xml et les logos ; qcpack.exe empaquette et signe ;
    4. Add-AppxPackage -ExternalLocation (pour l'utilisateur courant).

qcpack.exe remplace MakeAppx et SignTool du Windows SDK, qui n'est donc pas nécessaire.

Windows n'installe le paquet que si l'ordinateur approuve le certificat : c'est l'étape
manuelle windows11\\approuver-certificat.bat (administrateur, une seule fois).
Le menu classique de windows.py reste installé (Windows 10, repli sans ce paquet) ; il est
seulement masqué tant que le paquet est là, sans quoi « Afficher d'autres options »
montrerait deux « Convertir en ».
"""

from __future__ import annotations

import filecmp
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import quoteattr

from .. import __version__
from ..appdata import data_dir
from ..converters import Format
from . import windows
from .windows import MENU_LABEL, menu_targets

PACKAGE_NAME = "QuickConvert.ContextMenu"
PUBLISHER = "CN=QuickConvert"                              # = sujet du certificat
CERT_NAME = "QuickConvert : signature du menu Windows 11"  # nom convivial, pour le retrouver
CLSID = "8d81aa34-5215-40f5-9470-fbe35a5fd602"             # = CLSID_QuickConvertMenu (menu.cpp)
DLL, STUB, PACKER = "QuickConvertMenu.dll", "QuickConvert.exe", "qcpack.exe"
CER, MSIX = "QuickConvert.cer", "QuickConvert.msix"
MIN_BUILD = 22000  # premier Windows 11

# Binaire -> (sources, options, bibliothèques) pour g++.
BUILDS = {
    DLL: (("menu.cpp", "menu.def"), ("-std=c++17", "-shared"),
          ("-lole32", "-lshell32", "-lshlwapi", "-luser32", "-luuid")),
    STUB: (("stub.cpp",), ("-municode", "-mwindows"), ()),
    PACKER: (("qcpack.cpp",), ("-municode",),
             ("-lole32", "-lshlwapi", "-lurlmon", "-lcrypt32", "-luuid")),
}
LOGOS = {"StoreLogo.png": 50, "Square44x44Logo.png": 44, "Square150x150Logo.png": 150}

NO_COMPILER = """\
Compilateur C++ introuvable (g++ 64 bits de MSYS2). Pour l'installer :
    winget install MSYS2.MSYS2
    C:\\msys64\\usr\\bin\\bash.exe -lc "pacman -S --noconfirm mingw-w64-ucrt-x86_64-gcc"
puis relancer installer-win11.bat."""

NEEDS_TRUST = """\
Étape manuelle, une seule fois : Windows n'installe le paquet du menu que si
l'ordinateur approuve son certificat (créé à l'instant, sur ce PC uniquement).
  1. Clic droit sur {script}
     > « Exécuter en tant qu'administrateur »
  2. Relancer installer-win11.bat"""

MANIFEST = """\
<?xml version="1.0" encoding="utf-8"?>
<!-- Écrit par « quickconvert install-win11 » (platforms/windows11.py). -->
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:uap10="http://schemas.microsoft.com/appx/manifest/uap/windows10/10"
         xmlns:desktop4="http://schemas.microsoft.com/appx/manifest/desktop/windows10/4"
         xmlns:desktop5="http://schemas.microsoft.com/appx/manifest/desktop/windows10/5"
         xmlns:com="http://schemas.microsoft.com/appx/manifest/com/windows10"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap uap10 desktop4 desktop5 com rescap">
  <Identity Name="{name}" Publisher="{publisher}" Version="{version}" ProcessorArchitecture="x64"/>
  <Properties>
    <DisplayName>QuickConvert</DisplayName>
    <PublisherDisplayName>QuickConvert</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
    <uap10:AllowExternalContent>true</uap10:AllowExternalContent>
  </Properties>
  <Resources>
    <Resource Language="fr-FR"/>
  </Resources>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.26100.0"/>
  </Dependencies>
  <Capabilities>
    <rescap:Capability Name="runFullTrust"/>
  </Capabilities>
  <Applications>
    <Application Id="QuickConvert" Executable="{stub}" uap10:TrustLevel="mediumIL" uap10:RuntimeBehavior="win32App">
      <uap:VisualElements AppListEntry="none" DisplayName="QuickConvert" BackgroundColor="transparent"
                          Description="Convertir des fichiers depuis le clic droit"
                          Square150x150Logo="Assets\\Square150x150Logo.png" Square44x44Logo="Assets\\Square44x44Logo.png"/>
      <Extensions>
        <desktop4:Extension Category="windows.fileExplorerContextMenus">
          <desktop4:FileExplorerContextMenus>
{item_types}
          </desktop4:FileExplorerContextMenus>
        </desktop4:Extension>
        <com:Extension Category="windows.comServer">
          <com:ComServer>
            <com:SurrogateServer DisplayName="QuickConvert">
              <com:Class Id="{clsid}" Path="{dll}" ThreadingModel="STA"/>
            </com:SurrogateServer>
          </com:ComServer>
        </com:Extension>
      </Extensions>
    </Application>
  </Applications>
</Package>
"""

ITEM_TYPE = """\
            <desktop5:ItemType Type={ext}>
              <desktop5:Verb Id="QuickConvert" Clsid="{clsid}"/>
            </desktop5:ItemType>"""

# Les valeurs arrivent par l'environnement ($env:QC_...) : aucun échappement à gérer.
CERT_SCRIPT = r"""
$cert = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -eq $env:QC_SUBJECT -and $_.FriendlyName -eq $env:QC_NAME -and
                   $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date).AddDays(30) } |
    Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $cert) {
    # Signature de code uniquement (pas une autorité), clé privée non exportable.
    $cert = New-SelfSignedCertificate -Type Custom -Subject $env:QC_SUBJECT -FriendlyName $env:QC_NAME `
        -KeyUsage DigitalSignature -KeyExportPolicy NonExportable -NotAfter (Get-Date).AddYears(10) `
        -CertStoreLocation Cert:\CurrentUser\My `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')
}
Export-Certificate -Cert $cert -FilePath $env:QC_CER | Out-Null
$trusted = @(Get-ChildItem Cert:\LocalMachine\TrustedPeople, Cert:\LocalMachine\Root |
             Where-Object Thumbprint -eq $cert.Thumbprint).Count -gt 0
"$($cert.Thumbprint) $trusted"
"""

INSTALL_SCRIPT = r"""
Get-AppxPackage -Name $env:QC_PACKAGE | Remove-AppxPackage
Add-AppxPackage -Path $env:QC_MSIX -ExternalLocation $env:QC_EXTERNAL
"""

UNINSTALL_SCRIPT = r"""
$packages = @(Get-AppxPackage -Name $env:QC_PACKAGE)
$packages | Remove-AppxPackage
$certs = @(Get-ChildItem Cert:\CurrentUser\My |
           Where-Object { $_.Subject -eq $env:QC_SUBJECT -and $_.FriendlyName -eq $env:QC_NAME })
$trusted = @(Get-ChildItem Cert:\LocalMachine\TrustedPeople |
             Where-Object { $certs.Thumbprint -contains $_.Thumbprint }).Count -gt 0
$certs | Remove-Item -DeleteKey
"$($packages.Count) $trusted"
"""


class InstallError(Exception):
    """Message montré tel quel à l'utilisateur."""


class NeedsTrust(InstallError):
    """Le certificat doit d'abord être approuvé par l'ordinateur (étape administrateur)."""


def source_dir() -> Path:
    # Installé avec « pip install -e . » : src/quickconvert/platforms -> racine du projet.
    return Path(__file__).resolve().parents[3] / "windows11"


def build_dir() -> Path:
    return source_dir() / "bin"


def install_dir() -> Path:
    # L'emplacement externe du paquet. Surtout pas sous %LOCALAPPDATA% : Windows y refuse
    # d'activer la DLL (CoCreateInstance -> 0x80070003, chemin introuvable ; testé).
    return build_dir() / "external"


def is_windows11() -> bool:
    return sys.platform == "win32" and sys.getwindowsversion().build >= MIN_BUILD


def command_for(target_key: str) -> str:
    # Ni --collect ni "%1" : la DLL ajoute elle-même tous les fichiers de la sélection.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" -I -m quickconvert convert --gui --replace --to {target_key}'


def menu_config(icon: Path) -> str:
    """Contenu de menu.txt, relu par la DLL à chaque ouverture du menu (voir menu.cpp)."""
    targets: dict[str, tuple[Format, list[str]]] = {}
    for ext, items in menu_targets().items():
        for name, fmt in items:
            targets.setdefault(name, (fmt, []))[1].append(ext)
    lines = ["# Écrit par « quickconvert install-win11 » : relancer la commande plutôt que modifier ce fichier.",
             f"title\t{MENU_LABEL}",
             f"icon\t{icon}"]
    for name in sorted(targets):  # même ordre que le menu classique
        fmt, exts = targets[name]
        lines.append(f"item\t{fmt.label}\t{command_for(fmt.key)}\t{' '.join(sorted(exts))}")
    return "\n".join(lines) + "\n"


def manifest(extensions: list[str]) -> str:
    numbers = [int(n) for n in re.findall(r"\d+", __version__)][:3]
    version = ".".join(map(str, numbers + [0] * (4 - len(numbers))))
    item_types = "\n".join(ITEM_TYPE.format(ext=quoteattr(ext), clsid=CLSID) for ext in extensions)
    return MANIFEST.format(name=PACKAGE_NAME, publisher=PUBLISHER, version=version, stub=STUB,
                           item_types=item_types, clsid=CLSID, dll=DLL)


def write_logos(folder: Path, icon: Path) -> None:
    from PIL import Image

    with Image.open(icon) as img:  # la plus grande taille de l'icône (256 px)
        img = img.convert("RGBA")
        for name, size in LOGOS.items():
            img.resize((size, size), Image.Resampling.LANCZOS).save(folder / name)


def find_compiler() -> Path | None:
    """g++ 64 bits (MSYS2) : dans le PATH ou à l'emplacement par défaut de MSYS2."""
    candidates = [shutil.which("g++")] + [rf"C:\msys64\{env}\bin\g++.exe" for env in ("ucrt64", "mingw64")]
    for candidate in filter(None, candidates):
        gxx = Path(candidate)
        if not gxx.is_file():
            continue
        try:
            machine = subprocess.run([str(gxx), "-dumpmachine"], capture_output=True, text=True,
                                     timeout=60, env=_compiler_env(gxx)).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        if machine.startswith("x86_64"):  # l'Explorateur 64 bits ne charge pas une DLL 32 bits
            return gxx
    return None


def build(log=print) -> Path:
    """Compile les binaires de windows11/ s'ils manquent ou si leurs sources ont changé."""
    src, out = source_dir(), build_dir()
    if not (src / "menu.cpp").is_file():
        raise InstallError(f"Sources introuvables : {src}\n"
                           "(QuickConvert doit être installé depuis son dossier : pip install -e .)")
    out.mkdir(exist_ok=True)
    compiler = None
    for name, (sources, flags, libs) in BUILDS.items():
        target = out / name
        paths = [src / s for s in sources]
        if target.exists() and target.stat().st_mtime >= max(p.stat().st_mtime for p in paths):
            continue
        compiler = compiler or find_compiler()
        if compiler is None:
            raise InstallError(NO_COMPILER)
        log(f"Compilation de {name}...")
        # -static : la DLL chargée dans l'Explorateur ne dépend d'aucune DLL de MSYS2.
        command = [str(compiler), "-O2", "-Wall", "-static", "-s", *flags, "-o", str(target),
                   *map(str, paths), *libs]
        result = subprocess.run(command, cwd=src, capture_output=True, text=True, errors="replace",
                                env=_compiler_env(compiler))
        if result.returncode != 0:
            target.unlink(missing_ok=True)
            raise InstallError(f"Échec de la compilation de {name} :\n{result.stderr.strip()}")
    return out


def install(log=print) -> None:
    if platform.machine().upper() not in ("AMD64", "X86_64"):
        raise InstallError("Menu Windows 11 : seuls les PC x64 sont gérés pour l'instant.")
    from ..icon import build_icon

    bins = build(log)

    # 1. Certificat, créé une fois (son approbation est vérifiée juste avant l'enregistrement).
    out = _powershell(CERT_SCRIPT, subject=PUBLISHER, name=CERT_NAME, cer=bins / CER)
    thumbprint, trusted = out.split()[-2:]

    # 2. Emplacement externe : la DLL, l'exécutable exigé par le manifeste, la liste des formats.
    target = install_dir()
    target.mkdir(parents=True, exist_ok=True)
    for old in target.glob("*.old"):
        try:
            old.unlink()
        except OSError:
            pass  # encore chargée par l'Explorateur : ce sera pour la prochaine fois
    for name in (DLL, STUB):
        _replace(bins / name, target / name)
    icon = build_icon(data_dir() / "quickconvert.ico")
    (target / "menu.txt").write_text(menu_config(icon), encoding="utf-8")

    # 3. Paquet : manifeste + logos, empaqueté puis signé.
    staging = bins / "package"
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "Assets").mkdir(parents=True)
    (staging / "AppxManifest.xml").write_text(manifest(sorted(menu_targets())), encoding="utf-8")
    write_logos(staging / "Assets", icon)
    msix = bins / MSIX
    _run([bins / PACKER, "pack", staging, msix])
    _run([bins / PACKER, "sign", msix, thumbprint])

    # 4. Enregistrement pour l'utilisateur courant (remplace une version précédente).
    if trusted != "True":
        raise NeedsTrust(NEEDS_TRUST.format(script=source_dir() / "approuver-certificat.bat"))
    log("Enregistrement du paquet...")
    _powershell(INSTALL_SCRIPT, package=PACKAGE_NAME, msix=msix, external=target)
    # Le menu du paquet apparaît aussi dans « Afficher d'autres options » : on y masque
    # le menu classique pour ne pas avoir deux « Convertir en ».
    windows.set_hidden(True)


def uninstall() -> tuple[bool, bool]:
    """Retire le paquet et la clé de signature. Retourne (paquet retiré, certificat encore
    approuvé par l'ordinateur : à retirer avec retirer-certificat.bat)."""
    out = _powershell(UNINSTALL_SCRIPT, package=PACKAGE_NAME, subject=PUBLISHER, name=CERT_NAME)
    count, trusted = out.split()[-2:]
    windows.set_hidden(False)  # le menu classique reprend le relais
    # La DLL peut rester chargée par l'Explorateur : elle partira avec le dossier plus tard.
    shutil.rmtree(install_dir(), ignore_errors=True)
    shutil.rmtree(build_dir() / "package", ignore_errors=True)
    for name in (CER, MSIX):
        (build_dir() / name).unlink(missing_ok=True)
    return int(count) > 0, trusted == "True"


def _replace(src: Path, dst: Path) -> None:
    """Copie src sur dst, même si l'Explorateur a chargé l'ancienne DLL (fichier verrouillé)."""
    if dst.exists() and filecmp.cmp(src, dst, shallow=False):
        return
    try:
        shutil.copy2(src, dst)
    except PermissionError:
        # Un fichier chargé ne peut pas être écrasé, mais il peut être renommé.
        dst.replace(dst.with_name(f"{dst.name}.{time.time_ns()}.old"))
        shutil.copy2(src, dst)


def _compiler_env(gxx: Path) -> dict[str, str]:
    # cc1plus.exe a besoin des DLL de MSYS2 rangées à côté de g++.exe.
    return dict(os.environ, PATH=f"{gxx.parent};{os.environ.get('PATH', '')}")


def _run(command: list) -> None:
    result = subprocess.run([str(c) for c in command], capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        raise InstallError((result.stderr or result.stdout).strip() or f"Échec : {command[0]}")


def _powershell(script: str, **values) -> str:
    env = dict(os.environ, **{f"QC_{k.upper()}": str(v) for k, v in values.items()})
    prelude = ("$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'; "
               "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", prelude + script],
        capture_output=True, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    stdout = result.stdout.decode("utf-8", "replace").strip()
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        raise InstallError(stderr or stdout or f"PowerShell a échoué (code {result.returncode})")
    return stdout
