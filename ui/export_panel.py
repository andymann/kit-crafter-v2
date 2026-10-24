import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional

from core.exporter import ExportSettings, BatchExporter, BUILTIN_PRESETS
from core.set_manager import SetManager
from core.clip_model import ClipModel
from ui import theme


class ExportPanel(tk.Toplevel):
    def __init__(self, parent, set_mgr: SetManager, clip_model: ClipModel):
        super().__init__(parent)
        self._set_mgr = set_mgr
        self._clip_model = clip_model
        self._exporter: Optional[BatchExporter] = None

        self.title("Export Set")
        self.resizable(False, False)
        self.configure(bg=theme.BG)
        self.geometry("460x440")
        self.transient(parent)
        self.grab_set()

        # Header
        ttk.Label(self, text="Export Set", style="Accent.TLabel", font=theme.FONT).pack(padx=12, pady=(10, 6), anchor="w")

        # Preset strip
        preset_frame = ttk.Frame(self)
        preset_frame.pack(fill="x", padx=12, pady=(0, 6))
        for name in BUILTIN_PRESETS:
            btn = tk.Button(
                preset_frame, text=name,
                bg=theme.SURFACE, fg=theme.FG2, font=theme.FONT_XS,
                relief="flat", padx=6, pady=2,
                command=lambda n=name: self._apply_preset(n),
            )
            btn.pack(side="left", padx=2)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=12, pady=4)

        # Settings
        grid_frame = ttk.Frame(self)
        grid_frame.pack(fill="x", padx=12)

        self._mono_var = tk.BooleanVar(value=True)
        self._norm_var = tk.BooleanVar(value=True)
        self._peak_var = tk.StringVar(value="-0.1")
        self._hpf_var = tk.BooleanVar(value=False)
        self._hpf_freq_var = tk.StringVar(value="40.0")
        self._lim_var = tk.BooleanVar(value=False)
        self._fmt_var = tk.StringVar(value="WAV")
        self._depth_var = tk.StringVar(value="PCM_16")
        self._sr_var = tk.StringVar(value="44100")

        rows = [
            ("Mono", "check", self._mono_var),
            ("Normalize", "check", self._norm_var),
            ("Peak dBFS", "entry", self._peak_var),
            ("High-pass", "check", self._hpf_var),
            ("HPF freq (Hz)", "entry", self._hpf_freq_var),
            ("Limiter", "check", self._lim_var),
            ("Format", "combo", (self._fmt_var, ["WAV", "AIFF", "FLAC"])),
            ("Bit depth", "combo", (self._depth_var, ["PCM_16", "PCM_24", "PCM_32"])),
            ("Sample rate", "combo", (self._sr_var, ["22050", "44100", "48000", "96000"])),
        ]

        for i, (label, typ, var) in enumerate(rows):
            ttk.Label(grid_frame, text=label, style="Muted.TLabel").grid(row=i, column=0, sticky="w", pady=2)
            if typ == "check":
                ttk.Checkbutton(grid_frame, variable=var).grid(row=i, column=1, sticky="w", padx=8)
            elif typ == "entry":
                ttk.Entry(grid_frame, textvariable=var, width=10, font=theme.FONT_S).grid(row=i, column=1, sticky="w", padx=8)
            elif typ == "combo":
                cvar, values = var
                ttk.Combobox(grid_frame, textvariable=cvar, values=values, state="readonly", width=12).grid(row=i, column=1, sticky="w", padx=8)

        # Output folder
        folder_frame = ttk.Frame(self)
        folder_frame.pack(fill="x", padx=12, pady=8)
        ttk.Label(folder_frame, text="Output folder:", style="Muted.TLabel").grid(row=0, column=0, padx=(0, 6))
        self._dir_var = tk.StringVar()
        ttk.Entry(folder_frame, textvariable=self._dir_var, width=28, font=theme.FONT_S).grid(row=0, column=1, sticky="ew")
        folder_frame.columnconfigure(1, weight=1)
        ttk.Button(folder_frame, text="…", command=self._browse, width=3).grid(row=0, column=2, padx=(4, 0))

        # Progress
        self._progress = ttk.Progressbar(self, mode="determinate")
        self._progress.pack(fill="x", padx=12, pady=(4, 0))
        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self._status_var, style="Hint.TLabel").pack(anchor="w", padx=12)

        # Export button
        ttk.Button(self, text="Export set", style="Accent.TButton", command=self._start_export).pack(pady=10)

        self.bind("<Escape>", lambda e: self.destroy())

    def _apply_preset(self, name: str):
        p = BUILTIN_PRESETS[name]
        self._mono_var.set(p.mono)
        self._norm_var.set(p.normalize)
        self._peak_var.set(str(p.normalize_db))
        self._fmt_var.set(p.fmt)
        self._depth_var.set(p.subtype)
        self._sr_var.set(str(p.target_sr))

    def _browse(self):
        d = filedialog.askdirectory(parent=self)
        if d:
            self._dir_var.set(d)

    def _build_settings(self) -> ExportSettings:
        try:
            peak = float(self._peak_var.get())
        except ValueError:
            peak = -0.1
        try:
            hpf_freq = float(self._hpf_freq_var.get())
        except ValueError:
            hpf_freq = 40.0
        try:
            sr = int(self._sr_var.get())
        except ValueError:
            sr = 44100
        return ExportSettings(
            output_dir=self._dir_var.get(),
            fmt=self._fmt_var.get(),
            subtype=self._depth_var.get(),
            target_sr=sr,
            mono=self._mono_var.get(),
            normalize=self._norm_var.get(),
            normalize_db=peak,
            hpf=self._hpf_var.get(),
            hpf_freq=hpf_freq,
            limiter=self._lim_var.get(),
        )

    def _start_export(self):
        settings = self._build_settings()
        out_dir = settings.output_dir
        if not out_dir or not os.path.isdir(out_dir):
            messagebox.showerror("Export", "Please select a valid output folder.", parent=self)
            return

        items = list(self._set_mgr.active.items)
        if not items:
            messagebox.showinfo("Export", "Active set is empty.", parent=self)
            return

        total = len(items)
        self._progress.configure(maximum=total, value=0)
        self._status_var.set("Exporting…")

        def _progress_cb(done, tot, msg):
            self.after(0, lambda: self._on_progress(done, tot, msg))

        def _done_cb(ok, tot):
            self.after(0, lambda: self._on_done(ok, tot))

        self._exporter = BatchExporter(
            items=items,
            out_dir=out_dir,
            settings=settings,
            clip_model=self._clip_model,
            on_progress=_progress_cb,
            on_done=_done_cb,
        )

    def _on_progress(self, done: int, total: int, msg: str):
        self._progress.configure(value=done)
        self._status_var.set(msg)

    def _on_done(self, ok: int, total: int):
        self._progress.configure(value=total)
        self._status_var.set(f"Done: {ok}/{total} exported")
        messagebox.showinfo("Export complete", f"{ok} of {total} files exported.", parent=self)
