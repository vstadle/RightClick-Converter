# RightClick-Converter

Clic droit sur une image → **Convertir en** → PNG, JPG, WEBP, AVIF, HEIC, GIF, BMP, TIFF, ICO ou PDF.
Le fichier converti apparaît à côté de l'original. Pensé pour Windows d'abord, puis macOS,
puis d'autres types de fichiers que les images.

## Installation (Windows)

Double-cliquer sur `installer.bat` (Python 3.10+ requis, pas besoin des droits administrateur).

Ou à la main :

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m quickconvert install
```

Le menu enregistre le chemin absolu de `.venv` : après avoir déplacé le dossier, relancer
`installer.bat`. Pour retirer le menu : `desinstaller.bat`.

### Premier menu de Windows 11 (optionnel)

Sous Windows 11, le menu de `installer.bat` est rangé dans *Afficher d'autres options*.
Pour avoir **Convertir en** dès le premier clic droit, une fois `installer.bat` fait :

1. Double-cliquer sur `installer-win11.bat`. La première fois, il compile le menu, crée un
   certificat de signature propre à ce PC, puis s'arrête en demandant l'étape 2.
2. Clic droit sur `windows11\approuver-certificat.bat` → *Exécuter en tant
   qu'administrateur* (une seule fois). Le script affiche le certificat et demande
   confirmation avant de l'ajouter aux « Personnes autorisées » de l'ordinateur.
3. Relancer `installer-win11.bat` : le menu apparaît. Sinon, redémarrer l'Explorateur
   (Gestionnaire des tâches → *Explorateur Windows* → *Redémarrer*).

Seul prérequis : le compilateur g++ 64 bits de MSYS2. Ni Visual Studio ni le Windows SDK.

```bash
winget install MSYS2.MSYS2
```
```bash
C:\msys64\usr\bin\bash.exe -lc "pacman -S --noconfirm mingw-w64-ucrt-x86_64-gcc"
```

Après un déplacement du dossier ou un ajout de format : relancer `installer.bat` puis
`installer-win11.bat`. Pour retirer : `desinstaller-win11.bat`, puis, en administrateur,
`windows11\retirer-certificat.bat`. Le menu classique reste installé dans tous les cas
(c'est celui de Windows 10) : comme le menu Windows 11 apparaît aussi dans *Afficher
d'autres options*, il y est seulement masqué (`LegacyDisable`) tant que le paquet est là,
et revient avec `desinstaller-win11.bat`.

## Utilisation

- **Windows 11** : clic droit → *Convertir en* avec le menu Windows 11 ci-dessus, sinon
  *Afficher d'autres options* (ou `Maj+F10`) → *Convertir en*.
  Windows 10 : directement dans le clic droit.
- Fonctionne avec plusieurs fichiers sélectionnés, même de types différents : une seule
  fenêtre de progression pour tout le lot (bouton *Annuler*).
- Un seul fichier rapide : aucune fenêtre, le résultat apparaît simplement.
- Le fichier converti **remplace** l'original : une fois la conversion réussie, l'original
  part à la **Corbeille** (récupérable, jamais supprimé définitivement ; sur un disque sans
  Corbeille, Windows demande avant). En cas d'erreur, l'original reste en place.
- Jamais d'écrasement : `photo.png` existe déjà → `photo (1).png`.
- En cas d'échec : un message liste les fichiers en cause ; détails dans
  `%LOCALAPPDATA%\QuickConvert\quickconvert.log`.

En ligne de commande :

```bash
.venv\Scripts\python -m quickconvert convert --to webp photo1.jpg photo2.png
.venv\Scripts\python -m quickconvert formats
```

En ligne de commande, l'original est gardé ; ajouter `--replace` pour l'envoyer à la
Corbeille comme le fait le menu. Pour que le menu garde aussi les originaux : retirer
`--replace` de `command_for()` dans `platforms/windows.py` et `windows11.py`, puis relancer
`installer.bat` et `installer-win11.bat`.

## Ce que fait la conversion

| | |
|---|---|
| Lecture | JPG, PNG, WEBP, AVIF, HEIC/HEIF (iPhone), GIF, BMP, TIFF, ICO |
| Écriture | les mêmes + PDF |
| Rotation | l'orientation EXIF des photos est appliquée (plus d'images couchées) |
| Métadonnées | EXIF (appareil, date, GPS) et profil couleur ICC conservés quand le format le permet ; sinon les couleurs sont converties en sRGB |
| Transparence | gardée en PNG/WEBP/AVIF/HEIC/GIF/TIFF/ICO ; fond blanc en JPG/BMP/PDF |
| Animations | GIF/WEBP/APNG/AVIF animés restent animés entre ces formats (durées conservées) ; première image sinon |
| Pages | TIFF multipage → PDF ou TIFF multipage |
| Divers | CMYK → RGB, images 16 bits ramenées en 8 bits sans écrêtage, ICO carré multi-tailles, PDF au format ≈ A4 |

Qualités par défaut : JPG 92, WEBP 90, AVIF 80, HEIC 90 (dans `converters/images.py`).

## Organisation du code

```
src/quickconvert/
  converters/base.py     Format + Converter : l'interface commune à toutes les familles
  converters/images.py   la famille « images » (Pillow + pillow-heif)
  runner.py              conversion d'un fichier (nom libre, écriture sûre) et lots en parallèle
  collector.py           regroupe les lancements simultanés de l'Explorateur (tube nommé)
  gui.py                 fenêtre de progression tkinter et messages d'erreur
  platforms/windows.py   menu clic droit (registre HKCU)
  platforms/windows11.py premier menu de Windows 11 (paquet MSIX, voir ci-dessous)
  cli.py                 ligne de commande
windows11/               menu Windows 11 en C++ : DLL, empaquetage/signature, scripts du certificat
tests/                   pytest : conversions croisées, regroupement, registre, DLL Windows 11
```

Pourquoi `collector.py` : l'Explorateur lance la commande **une fois par fichier**
sélectionné. Le premier processus devient serveur et les autres lui passent leur fichier,
d'où une seule fenêtre et un seul bilan (testé : 60 lancements simultanés → 1 processus).

### Le menu Windows 11

Windows 11 n'accepte dans son premier menu que des commandes `IExplorerCommand` (COM)
déclarées par un **paquet MSIX signé**. RightClick-Converter installe un paquet « sparse » : il ne
contient que son manifeste et des logos, et donne une identité à des fichiers restés dans
`windows11\bin\external` (son « emplacement externe » ; pas sous `%LOCALAPPDATA%`, où
Windows refuse d'activer la DLL : erreur 0x80070003) :

| Fichier | Rôle |
|---|---|
| `RightClick-Converter.dll` (`windows11/menu.cpp`) | le sous-menu. L'Explorateur lui passe toute la sélection d'un coup : elle lance **un seul** `pythonw -m quickconvert convert --gui --to png fichier1 fichier2…` (pas besoin de `collector.py`), cache les formats inutiles (pas de *JPG* pour des .jpg) et ignore les fichiers non gérés. Au-delà de 30 000 caractères, la liste passe par un fichier temporaire (`--list-file`) |
| `menu.txt` | libellés, commandes et extensions, écrits par `install-win11` à partir de `menu_targets()` (les deux menus restent identiques) et relus à chaque ouverture du menu |
| `RightClick-Converter.exe` (`windows11/stub.cpp`) | l'exécutable qu'exige le manifeste, jamais lancé par le menu |

L'Explorateur charge la DLL dans un processus `dllhost.exe` lié au paquet ; le
`pythonw` qu'elle lance n'en dépend pas (testé : une conversion de 10 s continue après la
fermeture de ce processus).

`windows11/qcpack.cpp` empaquette et signe le MSIX en appelant directement les API de
Windows qu'utilisent MakeAppx et SignTool : le Windows SDK n'est pas nécessaire (le
`signtool.exe` de ClickOnce, trop ancien, échoue sur les MSIX avec 0x80080209).

Pourquoi un certificat à approuver : Windows refuse un paquet non signé dès qu'il déclare
une application, ce qu'exige le menu (testé : erreur 0x80073D2B), et n'accepte une
signature autosignée que si l'ordinateur l'approuve (sinon 0x800B0109). Le certificat est
créé sur ce PC dans `Cert:\CurrentUser\My` (« QuickConvert : signature du menu Windows
11 »), limité à la signature de code, clé privée non exportable, et supprimé par
`desinstaller-win11.bat`. Pour distribuer RightClick-Converter, il faudrait un vrai certificat de
signature de code et livrer `windows11/bin` déjà compilé.

### Ajouter d'autres types de fichiers

Créer une sous-classe de `Converter` (ex. `converters/audio.py` qui appelle `ffmpeg`),
déclarer ses `formats`, implémenter `convert(src, dst, target)`, puis l'ajouter à
`CONVERTERS` dans `converters/__init__.py`. Le menu (`quickconvert install`) et la ligne de
commande la prennent en compte sans autre modification. Pistes : audio/vidéo via ffmpeg,
documents via LibreOffice ou pandoc, SVG via cairosvg.

## Prochaines étapes

**Menu Windows 11 sur d'autres PC** : livrer les binaires de `windows11/bin` (plus besoin
de MSYS2), signer avec un vrai certificat (plus d'étape administrateur), et compiler une
version ARM64 de la DLL pour les PC ARM (aujourd'hui x64 uniquement).

**Portage macOS** : tout sauf `platforms/windows.py` est déjà multiplateforme.
- Intégration : une *Action rapide* par format (Automator → « Exécuter un script shell »,
  entrée « fichiers ou dossiers » dans Finder, passage des entrées « comme arguments ») :
  `quickconvert convert --gui --to png "$@"`. Finder donne tous les fichiers d'un coup, le
  regroupement n'est donc pas nécessaire (`collector.py` le sait déjà).
- À écrire : `platforms/macos.py` qui génère ces fichiers `.workflow` dans
  `~/Library/Services/`, et brancher `install`/`uninstall` dessus dans `cli.py`.
- Pour une vraie app distribuable : empaqueter avec PyInstaller ou py2app, ou une Finder
  Sync Extension en Swift qui appelle le moteur.

## Tests

```bash
.venv\Scripts\python -m pytest
```

`tests/test_windows11.py` compile la DLL et la fait tourner dans `windows11/test_menu.cpp`,
qui joue le rôle de l'Explorateur (sélection, sous-menus, clic) sans rien installer ;
ces tests sont ignorés si g++ est absent.
