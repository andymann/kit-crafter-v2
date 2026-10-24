import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable

from ui.waveform_view import WaveformCanvas
from ui import theme
from core.clip_model import ClipModel, FadeSpec


class EditorView(ttk.Frame):
    def __init__(self, parent, engine, clip_model: ClipModel, on_close: Callable):
        super().__init__(parent)
        self._engine = engine
        self._clip_model = clip_model
        self._on_close = on_close
        self._path: Optional[str] = None
        self._start_s: float = 0.0
        self._end_s: float = 0.0
        self._tracking: bool = False

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Row 0: header
        hdr = ttk.Frame(self, style="Panel.TFrame")
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(0, weight=1)
        self._title_lbl = ttk.Label(hdr, text="—", style="Accent.TLabel")
        self._title_lbl.grid(row=0, column=0, padx=8, pady=4, sticky="w")
        ttk.Button(hdr, text="Esc / close", command=self._close).grid(row=0, column=1, padx=4, pady=2)

        # Row 1: waveform
        self._wave = WaveformCanvas(self, editor_mode=True, height=280)
        self._wave.grid(row=1, column=0, sticky="nsew")
        self._wave.on_clip_change = self._on_clip_drag

        # Row 2: fade controls
        fade_frame = ttk.Frame(self)
        fade_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        ttk.Label(fade_frame, text="Fade in:", style="Muted.TLabel").grid(row=0, column=0, padx=(0, 4))
        self._fi_var = tk.DoubleVar(value=0.0)
        self._fi_scale = ttk.Scale(fade_frame, from_=0.0, to=2.0, variable=self._fi_var, orient="horizontal", length=120, command=self._on_fade_change)
        self._fi_scale.grid(row=0, column=1)
        self._fi_lbl = ttk.Label(fade_frame, text="0.00s", style="Muted.TLabel", width=6)
        self._fi_lbl.grid(row=0, column=2, padx=(4, 16))

        ttk.Label(fade_frame, text="Fade out:", style="Muted.TLabel").grid(row=0, column=3, padx=(0, 4))
        self._fo_var = tk.DoubleVar(value=0.0)
        self._fo_scale = ttk.Scale(fade_frame, from_=0.0, to=2.0, variable=self._fo_var, orient="horizontal", length=120, command=self._on_fade_change)
        self._fo_scale.grid(row=0, column=4)
        self._fo_lbl = ttk.Label(fade_frame, text="0.00s", style="Muted.TLabel", width=6)
        self._fo_lbl.grid(row=0, column=5, padx=(4, 0))

        # Row 3: clip info + buttons
        ctrl = ttk.Frame(self)
        ctrl.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 6))
        ctrl.columnconfigure(0, weight=1)
        self._info_var = tk.StringVar(value="No clip")
        ttk.Label(ctrl, textvariable=self._info_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self._hist_lbl = ttk.Label(ctrl, text="", style="Hint.TLabel")
        self._hist_lbl.grid(row=0, column=1, padx=8)
        ttk.Button(ctrl, text="▶ Preview", command=self._preview).grid(row=0, column=2, padx=2)
        ttk.Button(ctrl, text="Clear clip", command=self._clear_clip).grid(row=0, column=3, padx=2)
        ttk.Button(ctrl, text="Save clip", command=self._save_clip).grid(row=0, column=4, padx=2)

    def load(self, path: str):
        self._path = path
        self._title_lbl.configure(text=path.split("/")[-1])
        self._tracking = False

        def _got_waveform(data):
            def _apply():
                info = self._engine.file_info(path)
                duration = info.get("duration", 0.0)
                sr = info.get("sr", 44100)
                self._wave.set_waveform(data, sr, duration)
                # Restore clip
                clip = self._clip_model.get_clip(path)
                if clip and clip.is_valid():
                    self._start_s = clip.start
                    self._end_s = clip.end
                    self._fi_var.set(clip.fade.fade_in)
                    self._fo_var.set(clip.fade.fade_out)
                    self._fi_lbl.configure(text=f"{clip.fade.fade_in:.2f}s")
                    self._fo_lbl.configure(text=f"{clip.fade.fade_out:.2f}s")
                    self._wave.set_clip(clip.start, clip.end, clip.fade.fade_in, clip.fade.fade_out)
                    self._update_info()
                else:
                    self._wave.clear_clip()
                    self._info_var.set("No clip")
                hist = self._clip_model.get_history(path)
                self._hist_lbl.configure(text=f"history: {len(hist)}" if hist else "")
                self._start_tick()
            self.after(0, _apply)

        self._engine.load_waveform_async(path, _got_waveform)

    def _start_tick(self):
        if not self._tracking:
            self._tracking = True
            self._tick_playhead()

    def _tick_playhead(self):
        if not self._tracking:
            return
        if self._engine.is_playing() and self._engine.current == self._path:
            pos = self._engine.get_position()
            self._wave.set_playhead(pos)
        else:
            self._wave.set_playhead(None)
        self.after(40, self._tick_playhead)

    def _on_clip_drag(self, start_s: float, end_s: float, fi: float, fo: float):
        self._start_s = start_s
        self._end_s = end_s
        # Update wave with current fade slider values (don't override sliders)
        self._wave.set_clip(start_s, end_s, self._fi_var.get(), self._fo_var.get())
        self._update_info()

    def _on_fade_change(self, _=None):
        fi = self._fi_var.get()
        fo = self._fo_var.get()
        self._fi_lbl.configure(text=f"{fi:.2f}s")
        self._fo_lbl.configure(text=f"{fo:.2f}s")
        if self._wave._has_clip:
            self._wave.set_clip(self._start_s, self._end_s, fi, fo)

    def _update_info(self):
        dur = self._end_s - self._start_s
        self._info_var.set(f"Clip: {self._start_s:.3f}s – {self._end_s:.3f}s  ({dur:.3f}s)")

    def _preview(self):
        if self._path:
            self._engine.play(self._path)

    def _clear_clip(self):
        if self._path:
            self._clip_model.clear_clip(self._path)
            self._wave.clear_clip()
            self._info_var.set("No clip")
            hist = self._clip_model.get_history(self._path)
            self._hist_lbl.configure(text=f"history: {len(hist)}" if hist else "")

    def _save_clip(self):
        if not self._path:
            return
        fi = self._fi_var.get()
        fo = self._fo_var.get()
        self._clip_model.set_clip(
            self._path,
            self._start_s,
            self._end_s,
            FadeSpec(fade_in=fi, fade_out=fo),
        )
        hist = self._clip_model.get_history(self._path)
        self._hist_lbl.configure(text=f"history: {len(hist)}" if hist else "")

    def _close(self):
        self._tracking = False
        self._wave.set_playhead(None)
        self._on_close()
