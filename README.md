# RightClick-Converter

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Language-Python-3776AB.svg)](https://www.python.org/)
[![C++](https://img.shields.io/badge/Language-C%2B%2B-00599C.svg)](https://isocpp.org/)
[![Windows](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6.svg)](https://www.microsoft.com/windows)
[![Pillow](https://img.shields.io/badge/Library-Pillow-orange.svg)](https://python-pillow.org/)
[![pytest](https://img.shields.io/badge/Tests-pytest-green.svg)](https://docs.pytest.org/)

Right-click an image → **Convertir en** (*Convert to*) → PNG, JPG, WEBP, AVIF, HEIC, GIF, BMP,
TIFF, ICO or PDF. The converted file replaces the original, which goes to the Recycle Bin.
Built for Windows first, then Linux and macOS, then file types beyond images.

> The menu and messages are in French for now (*Convertir en* = *Convert to*).

## Installation (Windows)

Double-click `installer.bat` (requires Python 3.10+, no administrator rights needed).

Or by hand:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m quickconvert install
```

The menu stores the absolute path of `.venv`: after moving the folder, run `installer.bat`
again. To remove the menu: `desinstaller.bat`.

### Windows 11 main context menu (optional)

On Windows 11, the menu added by `installer.bat` sits under *Show more options*. To get
**Convertir en** right in the first right-click menu, once `installer.bat` has run:

1. Double-click `installer-win11.bat`. The first time, it builds the menu, creates a signing
   certificate specific to this PC, then stops and asks for step 2.
2. Right-click `windows11\approuver-certificat.bat` → *Run as administrator* (only once).
   The script shows the certificate and asks for confirmation before adding it to the
   computer's *Trusted People* store.
3. Run `installer-win11.bat` again: the menu appears. If not, restart File Explorer
   (Task Manager → *Windows Explorer* → *Restart*).

The only prerequisite is MSYS2's 64-bit g++ compiler. No Visual Studio, no Windows SDK.

```bash
winget install MSYS2.MSYS2
```
```bash
C:\msys64\usr\bin\bash.exe -lc "pacman -S --noconfirm mingw-w64-ucrt-x86_64-gcc"
```

After moving the folder or adding a format: run `installer.bat`, then
`installer-win11.bat`. To remove: `desinstaller-win11.bat`, then, as administrator,
`windows11\retirer-certificat.bat`. The classic menu always stays installed (it is the one
Windows 10 uses). Since the Windows 11 menu also shows up under *Show more options*, the
classic entry is only hidden there (`LegacyDisable`) while the package is installed, and
comes back with `desinstaller-win11.bat`.

## Usage

- **Windows 11**: right-click → *Convertir en* with the Windows 11 menu above, otherwise
  *Show more options* (or `Shift+F10`) → *Convertir en*.
  Windows 10: directly in the right-click menu.
- Works with several selected files, even of different types: a single progress window for
  the whole batch (with a cancel button).
- A single quick file: no window at all, the result simply appears.
- The converted file **replaces** the original: once the conversion succeeds, the original
  goes to the **Recycle Bin** (recoverable, never permanently deleted; on a drive without a
  Recycle Bin, Windows asks first). If the conversion fails, the original stays in place.
- Never overwrites: `photo.png` already exists → `photo (1).png`.
- On failure: a message lists the files involved; details in
  `%LOCALAPPDATA%\QuickConvert\quickconvert.log`.

From the command line:

```bash
.venv\Scripts\python -m quickconvert convert --to webp photo1.jpg photo2.png
.venv\Scripts\python -m quickconvert formats
```

From the command line the original is kept; add `--replace` to send it to the Recycle Bin
like the menu does. To make the menu keep originals too: remove `--replace` from
`command_for()` in `platforms/windows.py` and `windows11.py`, then run `installer.bat` and
`installer-win11.bat` again.

## What the conversion handles

| | |
|---|---|
| Reads | JPG, PNG, WEBP, AVIF, HEIC/HEIF (iPhone), GIF, BMP, TIFF, ICO |
| Writes | the same + PDF |
| Rotation | the photo's EXIF orientation is applied (no more sideways images) |
| Metadata | EXIF (camera, date, GPS) and ICC color profile kept when the format allows it; otherwise colors are converted to sRGB |
| Transparency | kept in PNG/WEBP/AVIF/HEIC/GIF/TIFF/ICO; white background in JPG/BMP/PDF |
| Animations | animated GIF/WEBP/APNG/AVIF stay animated between these formats (frame durations kept); first frame otherwise |
| Pages | multi-page TIFF → PDF or multi-page TIFF |
| Misc | CMYK → RGB, 16-bit images brought down to 8-bit without clipping, square multi-size ICO, PDF at ≈ A4 size |

Default quality: JPG 92, WEBP 90, AVIF 80, HEIC 90 (in `converters/images.py`).

## Code layout

```
src/quickconvert/
  converters/base.py     Format + Converter: the interface shared by all file families
  converters/images.py   the "images" family (Pillow + pillow-heif)
  runner.py              converts one file (free name, safe write) and batches in parallel
  collector.py           groups File Explorer's simultaneous launches (named pipe)
  gui.py                 tkinter progress window and error messages
  trash.py               sends originals to the Recycle Bin
  platforms/windows.py   right-click menu (HKCU registry)
  platforms/windows11.py Windows 11 main context menu (MSIX package, see below)
  cli.py                 command line
windows11/               Windows 11 menu in C++: DLL, packaging/signing, certificate scripts
tests/                   pytest: cross conversions, grouping, registry, Windows 11 DLL
```

Why `collector.py`: File Explorer runs the classic menu's command **once per selected
file**. The first process becomes a server and the others hand it their file, hence a
single window and a single report (tested: 60 simultaneous launches → 1 process).

### The Windows 11 menu

Windows 11 only accepts `IExplorerCommand` (COM) commands declared by a **signed MSIX
package** in its main context menu. RightClick-Converter installs a "sparse" package: it
only holds its manifest and logos, and gives an identity to files kept in
`windows11\bin\external` (its "external location"; not under `%LOCALAPPDATA%`, where Windows
refuses to activate the DLL: error 0x80070003):

| File | Role |
|---|---|
| `RightClick-Converter.dll` (`windows11/menu.cpp`) | the submenu. File Explorer hands it the whole selection at once: it starts **a single** `pythonw -m quickconvert convert --gui --to png file1 file2…` (no need for `collector.py`), hides useless formats (no *JPG* for .jpg files) and skips unsupported files. Beyond 30,000 characters, the list goes through a temporary file (`--list-file`) |
| `menu.txt` | labels, commands and extensions, written by `install-win11` from `menu_targets()` (so both menus stay identical) and re-read every time the menu opens |
| `RightClick-Converter.exe` (`windows11/stub.cpp`) | the executable required by the manifest, never launched by the menu |

File Explorer loads the DLL in a `dllhost.exe` process tied to the package; the `pythonw`
it starts does not depend on it (tested: a 10 s conversion keeps running after that process
exits).

`windows11/qcpack.cpp` packs and signs the MSIX by calling the Windows APIs that MakeAppx
and SignTool use, so the Windows SDK is not needed (ClickOnce's older `signtool.exe` fails
on MSIX with 0x80080209).

Why a certificate must be approved: Windows rejects an unsigned package as soon as it
declares an application, which the menu requires (tested: error 0x80073D2B), and only
accepts a self-signed signature if the computer trusts it (otherwise 0x800B0109). The
certificate is created on this PC in `Cert:\CurrentUser\My` ("QuickConvert : signature du
menu Windows 11"), restricted to code signing, with a non-exportable private key, and is
deleted by `desinstaller-win11.bat`. To distribute RightClick-Converter, it would need a real
code-signing certificate and a prebuilt `windows11/bin`.

### Adding other file types

Create a `Converter` subclass (e.g. `converters/audio.py` calling `ffmpeg`), declare its
`formats`, implement `convert(src, dst, target)`, then add it to `CONVERTERS` in
`converters/__init__.py`. The menu (`quickconvert install`) and the command line pick it up
with no other change. Ideas: audio/video via ffmpeg, documents via LibreOffice or pandoc,
SVG via cairosvg.

## Next steps

**Linux (KDE)**: a Dolphin service menu that calls the same engine; Dolphin passes all
selected files at once, so no grouping is needed.

**Windows 11 menu on other PCs**: ship the `windows11/bin` binaries (no more MSYS2), sign
with a real certificate (no more administrator step), and build an ARM64 version of the DLL
for ARM PCs (x64 only today).

**macOS port**: everything except `platforms/windows*.py` is already cross-platform.
- Integration: one *Quick Action* per format (Automator → "Run Shell Script", input "files
  or folders" in Finder, pass input "as arguments"):
  `quickconvert convert --gui --to png "$@"`. Finder hands over all files at once, so no
  grouping is needed (`collector.py` already knows this).
- To write: `platforms/macos.py`, which generates these `.workflow` files in
  `~/Library/Services/`, and hook `install`/`uninstall` to it in `cli.py`.
- For a real distributable app: package with PyInstaller or py2app, or a Finder Sync
  Extension in Swift that calls the engine.

## Tests

```bash
.venv\Scripts\python -m pytest
```

`tests/test_windows11.py` builds the DLL and runs it inside `windows11/test_menu.cpp`, which
plays the part of File Explorer (selection, submenus, click) without installing anything;
these tests are skipped when g++ is missing.

## License

Licensed under the [MIT License](LICENSE).
