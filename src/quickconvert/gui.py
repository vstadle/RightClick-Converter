"""Petite fenêtre de progression (tkinter, fourni avec Python) et boîtes de message.

Une conversion rapide d'un seul fichier n'affiche rien : le fichier apparaît, c'est tout.
La fenêtre ne s'ouvre que pour un lot ou une conversion qui dure.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from . import APP_NAME
from .appdata import data_dir, log_path
from .runner import Batch

SHOW_AFTER = 0.8      # secondes avant d'afficher la fenêtre pour un fichier seul
CLOSE_AFTER_MS = 1500  # durée d'affichage du message « Terminé »
MAX_LISTED_ERRORS = 12


def run_with_progress(batch: Batch) -> None:
    import tkinter as tk
    from tkinter import ttk

    _enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    root.title(APP_NAME)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    icon = data_dir() / "quickconvert.ico"
    if icon.exists():
        try:
            root.iconbitmap(default=str(icon))
        except tk.TclError:
            pass

    frame = ttk.Frame(root, padding=(18, 14))
    frame.pack(fill="both", expand=True)
    title = ttk.Label(frame, text=f"Conversion en {batch.target.label}…",
                      font=("Segoe UI", 11, "bold"))
    title.grid(row=0, column=0, columnspan=2, sticky="w")
    bar = ttk.Progressbar(frame, length=340, mode="determinate")
    bar.grid(row=1, column=0, columnspan=2, pady=(10, 6), sticky="ew")
    status = ttk.Label(frame, text="", width=46)
    status.grid(row=2, column=0, sticky="w")
    button = ttk.Button(frame, text="Annuler", command=batch.cancel)
    button.grid(row=2, column=1, sticky="e", padx=(12, 0))
    root.protocol("WM_DELETE_WINDOW", batch.cancel)

    threading.Thread(target=batch.run, name="batch", daemon=True).start()
    started = time.monotonic()
    visible = False

    def show() -> None:
        nonlocal visible
        visible = True
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        # En bas à droite, au-dessus de la barre des tâches, comme une notification.
        x = root.winfo_screenwidth() - w - 24
        y = root.winfo_screenheight() - h - 80
        root.geometry(f"+{x}+{y}")
        root.deiconify()
        root.lift()

    def tick() -> None:
        if not batch.finished:
            if not visible and (batch.total > 1 or time.monotonic() - started > SHOW_AFTER):
                show()
            bar.configure(maximum=max(batch.total, 1), value=batch.done)
            name = batch.current if len(batch.current) <= 32 else batch.current[:31] + "…"
            status.configure(text=f"{batch.done} / {batch.total}   {name}")
            root.after(100, tick)
            return

        if batch.failures or batch.kept:
            root.withdraw()
            show_message(failure_report(batch), warning=True)
            root.destroy()
        elif visible:
            bar.configure(maximum=max(batch.total, 1), value=batch.done)
            title.configure(text="Conversion annulée" if batch.is_cancelled else "Terminé")
            status.configure(text=summary(batch))
            button.configure(text="Fermer", command=root.destroy)
            root.protocol("WM_DELETE_WINDOW", root.destroy)
            root.after(CLOSE_AFTER_MS, root.destroy)
        else:
            root.destroy()

    root.after(50, tick)
    root.mainloop()


def summary(batch: Batch) -> str:
    n = len(batch.converted)
    text = f"{n} fichier{'s' if n > 1 else ''} converti{'s' if n > 1 else ''}"
    if batch.cancelled:
        text += f", {batch.cancelled} annulé{'s' if batch.cancelled > 1 else ''}"
    return text


def failure_report(batch: Batch) -> str:
    lines = []
    n = len(batch.failures)
    if n:
        lines += [f"{n} fichier{'s' if n > 1 else ''} n'{'ont' if n > 1 else 'a'} pas pu être "
                  f"converti{'s' if n > 1 else ''} en {batch.target.label} :", ""]
        lines += _listed(f"{Path(path).name} — {message}" for path, message in batch.failures)
    k = len(batch.kept)
    if k:
        if lines:
            lines.append("")
        lines += [f"Converti{'s' if k > 1 else ''}, mais original{'s' if k > 1 else ''} "
                  f"conservé{'s' if k > 1 else ''} (Corbeille impossible : fichier ouvert ailleurs ?) :", ""]
        lines += _listed(Path(path).name for path in batch.kept)
    if batch.converted:
        lines += ["", summary(batch) + "."]
    lines += ["", f"Détails : {log_path()}"]
    return "\n".join(lines)


def _listed(items) -> list[str]:
    items = list(items)
    lines = [f"•  {item}" for item in items[:MAX_LISTED_ERRORS]]
    if len(items) > MAX_LISTED_ERRORS:
        lines.append(f"…et {len(items) - MAX_LISTED_ERRORS} autre(s)")
    return lines


def show_message(text: str, warning: bool = False) -> None:
    if sys.platform == "win32":
        import ctypes

        MB_ICONWARNING, MB_ICONINFORMATION = 0x30, 0x40
        MB_SETFOREGROUND, MB_TOPMOST = 0x10000, 0x40000
        icon = MB_ICONWARNING if warning else MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, icon | MB_SETFOREGROUND | MB_TOPMOST)
        return
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    (messagebox.showwarning if warning else messagebox.showinfo)(APP_NAME, text, parent=root)
    root.destroy()


def _enable_dpi_awareness() -> None:
    """Sans ça, tkinter est flou sur les écrans avec mise à l'échelle (125 %, 150 %...)."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
