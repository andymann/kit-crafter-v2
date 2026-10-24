import os
import tkinter as tk
from tkinter import ttk
from typing import Optional

from ui import theme


class DetailPane(ttk.Frame):
    def __init__(self, parent, engine):
        super().__init__(parent)
        self._engine = engine
        self._path: Optional[str] = None
        self._tag_labels: list = []

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)

        # Col 0: file info
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="ew", padx=8, pady=4)
        left.columnconfigure(1, weight=1)

        self._name_lbl = ttk.Label(left, text="—", style="Accent.TLabel")
        self._name_lbl.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 4))

        fields = [("sr", "SR:"), ("ch", "Ch:"), ("dur", "Dur:"), ("bpm", "BPM:"), ("key", "Key:")]
        self._field_vars: dict = {}
        for col, (key, label) in enumerate(fields):
            ttk.Label(left, text=label, style="Hint.TLabel").grid(row=1, column=col * 2, padx=(0 if col == 0 else 6, 2))
            var = tk.StringVar(value="—")
            self._field_vars[key] = var
            ttk.Label(left, textvariable=var, style="Muted.TLabel").grid(row=1, column=col * 2 + 1, padx=(0, 2))

        # Tags row
        ttk.Label(left, text="tags:", style="Hint.TLabel").grid(row=2, column=0, padx=(0, 2), pady=(4, 0))
        self._tag_var = tk.StringVar()
        self._tag_entry = ttk.Entry(left, textvariable=self._tag_var, width=20, font=theme.FONT_S)
        self._tag_entry.grid(row=2, column=1, columnspan=5, sticky="ew", padx=(0, 4), pady=(4, 0))
        ttk.Button(left, text="save", command=self._save_tags, width=5).grid(row=2, column=6, pady=(4, 0))

        # Col 1: shortcut hints
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="e", padx=8, pady=4)
        shortcuts = [
            ("F", "search"),
            ("Space", "play/stop"),
            ("E", "add to set"),
            ("C", "editor"),
            ("X", "export"),
            ("Ctrl+T", "theme"),
        ]
        self._kbd_labels: list = []
        for row_i, (key, desc) in enumerate(shortcuts):
            kl = theme.kbd_label(right, key)
            kl.grid(row=row_i, column=0, padx=(0, 4), pady=1, sticky="e")
            self._kbd_labels.append(kl)
            ttk.Label(right, text=desc, style="Hint.TLabel").grid(row=row_i, column=1, sticky="w", pady=1)

    def set_file(self, path: str):
        self._path = path
        name = os.path.basename(path)
        self._name_lbl.configure(text=name)
        info = self._engine.file_info(path)
        if info:
            self._field_vars["sr"].set(f"{info.get('sr', '—')}")
            self._field_vars["ch"].set(str(info.get("channels", "—")))
            dur = info.get("duration", 0.0)
            self._field_vars["dur"].set(f"{dur:.2f}s")
        else:
            for k in ("sr", "ch", "dur"):
                self._field_vars[k].set("—")
        self._field_vars["bpm"].set("—")
        self._field_vars["key"].set("—")

    def set_bpm_key(self, bpm, key):
        self._field_vars["bpm"].set(str(bpm) if bpm else "—")
        self._field_vars["key"].set(str(key) if key else "—")

    def _save_tags(self):
        pass  # placeholder for tag persistence

    def apply_theme(self):
        for kl in self._kbd_labels:
            kl.configure(bg=theme.SURFACE, fg=theme.FG2)
