#!/usr/bin/env python3
"""M3+M4 — GUI (tkinter) : éditeur Markdown + panneau voix + génération + UX.

Backend : ``engine``. La génération tourne dans un fil (UI non bloquée) et les
résultats remontent via une file d'attente. La logique pure (autocomplétion,
insertion de bloc, gras) est isolée dans ``EditorLogic``.
"""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import config, multi
from engine.voix import load_voix


class EditorLogic:
    """Autocomplétion et insertion de bloc (`[Nom]:`), indépendante des widgets."""

    def __init__(self, voix_names=()):
        self.names = list(voix_names)

    def completion(self, word: str):
        """Première voix dont le nom commence par ``word`` (insensible à la casse)."""
        if not word:
            return None
        low = word.lower()
        for n in self.names:
            if n.lower().startswith(low):
                return n
        return None

    def block_text(self, name: str) -> str:
        return f"[{name}]: "


class App(ttk.Frame):
    def __init__(self, master, chargeur_voix=None):
        super().__init__(master, padding=8)
        self.chargeur_voix = chargeur_voix or (lambda: load_voix())
        self.queue = queue.Queue()
        self.cfg = {
            "pause": config.DEFAULT_PAUSE,
            "speed": config.DEFAULT_SPEED,
            "max_chars": config.DEFAULT_MAX_BLOCK_CHARS,
            "verify": config.VERIFY_ENABLED,
            "device": config.DEFAULT_DEVICE,
        }
        self.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_toolbar()
        self._build_main()
        self._load_voix()
        self._renumber()

    # --------------------------------------------------------------- layout
    def _build_toolbar(self):
        bar = ttk.Frame(self)
        ttk.Button(bar, text="Insérer [Nom]:", command=self._insert_block).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Réglages…", command=self._settings).pack(
            side=tk.LEFT, padx=2)
        self.gen_button = ttk.Button(bar, text="Générer", command=self._on_generate)
        self.gen_button.pack(side=tk.LEFT, padx=8)
        self.status_var = tk.StringVar()
        self.status = ttk.Label(bar, textvariable=self.status_var)
        self.status.pack(side=tk.LEFT, padx=12)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

    def _build_main(self):
        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.grid(row=1, column=0, sticky="nsew")
        self.rowconfigure(1, weight=1)

        left = ttk.Frame(paned)
        self._build_editor(left)

        right = ttk.Frame(paned)
        self.voix_list = tk.Listbox(right, width=28, exportselection=False)
        self.voix_list.pack(fill=tk.BOTH, expand=True)
        ttk.Label(right, text="voix.txt").pack()

        paned.add(left, weight=3)
        paned.add(right, weight=1)

    def _build_editor(self, parent):
        frame = ttk.Frame(parent)
        scroll = ttk.Scrollbar(frame)
        self.lines = tk.Text(frame, width=4, wrap="none", takefocus=0,
                             state="disabled", font=("monospace", 11))
        self.editor = tk.Text(frame, wrap="word", yscrollcommand=scroll.set,
                              font=("monospace", 11))
        scroll.config(command=self._scroll_sync)
        self.lines.pack(side=tk.LEFT, fill=tk.Y)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        frame.pack(fill=tk.BOTH, expand=True)
        self.editor.bind("<KeyRelease>", lambda e: self._highlight())
        self.editor.bind("<Tab>", self._on_complete)
        self.editor.bind("<Button-1>", lambda e: self._renumber(), add="+")

    def _scroll_sync(self, *args):
        self.editor.yview_moveto(args[0])
        self.lines.yview_moveto(args[0])

    # --------------------------------------------------------------- édition
    def _renumber(self, _event=None):
        self.lines.config(state="normal")
        self.lines.delete("1.0", tk.END)
        n = int(self.editor.index("end-1c").split(".")[0])
        self.lines.insert("1.0", "\n".join(str(i) for i in range(1, n + 1)))
        self.lines.config(state="disabled")

    def _highlight(self):
        self._renumber()
        for tag in ("lead", "colon"):
            self.editor.tag_remove(tag, "1.0", tk.END)
        for lineno, line in enumerate(self.editor.get("1.0", "end-1c").splitlines(), 1):
            if line.startswith("[") and "]" in line:
                end = line.index("]")
                self.editor.tag_add("lead", f"{lineno}.0", f"{lineno}.{end + 1}")
                self.editor.tag_add("colon", f"{lineno}.{end + 1}", f"{lineno}.{end + 2}")
        self.editor.tag_config("lead", foreground="#cc5500",
                               font=("monospace", 11, "bold"))
        self.editor.tag_config("colon", foreground="#888")

    # --------------------------------------------------------- autocomplétion
    def _on_complete(self, _event=None):
        """Tab : complète ``[Pré`` -> ``[Narrateur]`` si unique."""
        c = self.editor.get("insert linestart", "insert")
        m = c.rfind("[")
        if m < 0:
            return "break"
        prefix = c[m + 1:]
        name = self.sugg.completion(prefix)
        if name:
            self.editor.insert("insert", name[len(prefix):])
        return "break"

    # --------------------------------------------------------------- actions
    def _insert_block(self):
        sel = self.voix_list.curselection()
        if not sel:
            messagebox.showinfo("VoiceBuilder", "Sélectionnez une voix dans le panneau.")
            return
        name = self.voix.names()[sel[0]]
        self.editor.insert("end", "\n" + self.sugg.block_text(name))
        self.editor.focus_set()

    def _settings(self):
        dlg = tk.Toplevel(self)
        dlg.title("Réglages")
        rows = [("Pause (s)", "pause", float), ("Vitesse", "speed", float),
                ("Max chars/bloc", "max_chars", int)]
        entries = {}
        for r, (label, key, _typ) in enumerate(rows):
            ttk.Label(dlg, text=label).grid(row=r, column=0, sticky="e")
            e = ttk.Entry(dlg, width=8)
            e.insert(0, str(self.cfg[key]).replace(".", ",") if key == "pause"
                     else str(self.cfg[key]))
            e.grid(row=r, column=1, padx=4, pady=2)
            entries[key] = e
        self.verify_var = tk.BooleanVar(value=self.cfg["verify"])
        ttk.Checkbutton(dlg, text="Vérification Whisper",
                        variable=self.verify_var).grid(row=r + 1, column=0,
                                                       columnspan=2, sticky="w")
        self.device_var = tk.StringVar(value=self.cfg["device"])
        ttk.Label(dlg, text="device").grid(row=r + 2, column=0, sticky="e")
        ttk.Combobox(dlg, textvariable=self.device_var, width=6,
                     values=["cuda:0", "cpu"], state="readonly").grid(
            row=r + 2, column=1, padx=4, pady=2)

        def ok():
            try:
                self.cfg["pause"] = float(entries["pause"].get().replace(",", "."))
                self.cfg["speed"] = float(entries["speed"].get().replace(",", "."))
                self.cfg["max_chars"] = int(entries["max_chars"].get())
            except ValueError:
                messagebox.showerror("Réglages", "Valeur invalide.")
                return
            self.cfg["verify"] = self.verify_var.get()
            self.cfg["device"] = self.device_var.get()
            dlg.destroy()

        ttk.Button(dlg, text="OK", command=ok).grid(row=r + 3, column=0, columnspan=2)

    # ------------------------------------------------------------- génération
    def _on_generate(self):
        if self.voix is None:
            messagebox.showwarning("VoiceBuilder", "Aucune voix chargée.")
            return
        text = self.editor.get("1.0", "end-1c").strip()
        if not text:
            messagebox.showinfo("VoiceBuilder", "Éditeur vide.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".wav",
                                            filetypes=[("Wave", "*.wav")])
        if not out:
            return
        self.status_var.set("Génération…")
        self.gen_button.config(state="disabled")
        t = threading.Thread(target=self._run,
                             args=(text, self.voix, out, dict(self.cfg)), daemon=True)
        t.start()
        self.after(120, self._drain)

    def _run(self, text, voix, out, cfg):
        import tempfile
        tmp = Path(tempfile.mkstemp(suffix=".md")[1])
        tmp.write_text(text, encoding="utf-8")
        try:
            res = multi.generate(str(tmp), voix, out=out,
                                 pause=cfg["pause"], speed=cfg["speed"],
                                 max_block_chars=cfg["max_chars"],
                                 verify=cfg["verify"], device=cfg["device"],
                                 fp16=False)
            self.queue.put(("ok", res))
        except Exception as exc:
            self.queue.put(("err", str(exc)))
        finally:
            tmp.unlink(missing_ok=True)

    def _drain(self):
        try:
            kind, payload = self.queue.get_nowait()
        except queue.Empty:
            self.after(120, self._drain)
            return
        self.gen_button.config(state="normal")
        if kind == "ok":
            self.status_var.set(f"OK → {payload['out']} ({payload['duration']} s)")
            messagebox.showinfo("VoiceBuilder",
                                f"Montage terminé :\n{payload['out']}\n"
                                f"{payload['duration']} s")
        else:
            self.status_var.set("Erreur")
            messagebox.showerror("VoiceBuilder", payload)

    # ------------------------------------------------------------ data / voix
    def _load_voix(self):
        try:
            self.voix = self.chargeur_voix()
        except Exception as exc:
            self.voix = None
            self.status_var.set(f"Erreur voix : {exc}")
            self.voix_list.delete(0, tk.END)
            return
        self.voix_list.delete(0, tk.END)
        for n in self.voix.names():
            self.voix_list.insert(tk.END, n)
        self.sugg = EditorLogic(self.voix.names())
        self.status_var.set(f"{len(self.voix.names())} voix chargées")


def main():
    root = tk.Tk()
    root.title("VoiceBuilder — éditeur multi-voix (CosyVoice3)")
    root.geometry("1020x660")
    App(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()