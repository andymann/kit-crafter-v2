import tkinter as tk
from typing import Optional, Callable
import numpy as np

CLIP_COLOR = "#5aadff"
CLIP_FILL = "#1e3a5f"
WAVE_COLOR = "#888888"
WAVE_SEL_COLOR = "#aaaaaa"
PLAY_COLOR = "#4aff88"
FADE_COLOR = "#ffaa44"


class WaveformCanvas(tk.Canvas):
    def __init__(self, parent, editor_mode: bool = False, **kwargs):
        kwargs.setdefault("bg", "#1a1a1a")
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(parent, **kwargs)
        self._editor_mode = editor_mode
        self._data: Optional[np.ndarray] = None
        self._sr: int = 44100
        self._duration: float = 0.0
        self._clip_start: float = 0.0  # normalised [0..1]
        self._clip_end: float = 1.0
        self._has_clip: bool = False
        self._fade_in_len: float = 0.0   # seconds
        self._fade_out_len: float = 0.0
        self._view_start: float = 0.0
        self._view_end: float = 1.0
        self._playhead: Optional[float] = None  # normalised

        self.on_clip_change: Optional[Callable] = None

        self._drag_start_x: Optional[int] = None
        self._drag_edge: Optional[str] = None  # "start" or "end" or "body"

        self.bind("<Configure>", lambda e: self._redraw())

        if editor_mode:
            self.bind("<ButtonPress-1>", self._on_press)
            self.bind("<B1-Motion>", self._on_drag)
            self.bind("<ButtonRelease-1>", self._on_release)

    # ── Public API ──────────────────────────────────────────────────────────

    def set_waveform(self, data: Optional[np.ndarray], sr: int = 44100, duration: Optional[float] = None):
        self._data = data
        self._sr = sr
        if duration is not None:
            self._duration = duration
        elif data is not None and len(data) > 0:
            self._duration = len(data) / sr
        else:
            self._duration = 0.0
        self._redraw()

    def set_clip(self, start_s: float, end_s: float, fade_in_s: float = 0.0, fade_out_s: float = 0.0):
        if self._duration > 0:
            self._clip_start = max(0.0, min(1.0, start_s / self._duration))
            self._clip_end = max(0.0, min(1.0, end_s / self._duration))
        self._fade_in_len = fade_in_s
        self._fade_out_len = fade_out_s
        self._has_clip = True
        self._redraw()

    def clear_clip(self):
        self._has_clip = False
        self._redraw()

    def set_playhead(self, pos_s):
        # Guard: None means no playhead; 0.0 is a valid position
        if pos_s is not None:
            self._playhead = pos_s / self._duration if self._duration > 0 else None
        else:
            self._playhead = None
        self._redraw()

    def update_theme(self, bg: str):
        self.configure(bg=bg)
        self._redraw()

    # ── Drawing ─────────────────────────────────────────────────────────────

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return
        if self._editor_mode:
            wave_h = int(h * 0.65)
            over_h = h - wave_h
            self._draw_wave_region(0, 0, w, wave_h)
            self._draw_overview(0, wave_h, w, over_h)
        else:
            self._draw_wave_region(0, 0, w, h)

    def _draw_wave_region(self, x0: int, y0: int, w: int, h: int):
        mid = y0 + h // 2

        # Clip fill
        if self._has_clip:
            cx0 = x0 + int(self._clip_start * w)
            cx1 = x0 + int(self._clip_end * w)
            self.create_rectangle(cx0, y0, cx1, y0 + h, fill=CLIP_FILL, outline="")
            self.create_line(cx0, y0, cx0, y0 + h, fill=CLIP_COLOR, width=1)
            self.create_line(cx1, y0, cx1, y0 + h, fill=CLIP_COLOR, width=1)

            # Fade-in overlay
            if self._fade_in_len > 0 and self._duration > 0:
                fi_norm = self._fade_in_len / self._duration
                fi_x = x0 + int((self._clip_start + fi_norm) * w)
                fi_x = min(fi_x, cx1)
                self.create_rectangle(cx0, y0, fi_x, y0 + h, fill=FADE_COLOR, outline="", stipple="gray25")
                self.create_line(cx0, y0 + h, fi_x, y0, fill=FADE_COLOR, dash=(3, 3))

            # Fade-out overlay
            if self._fade_out_len > 0 and self._duration > 0:
                fo_norm = self._fade_out_len / self._duration
                fo_x = x0 + int((self._clip_end - fo_norm) * w)
                fo_x = max(fo_x, cx0)
                self.create_rectangle(fo_x, y0, cx1, y0 + h, fill=FADE_COLOR, outline="", stipple="gray25")
                self.create_line(fo_x, y0, cx1, y0 + h, fill=FADE_COLOR, dash=(3, 3))

        # Waveform bars
        if self._data is not None and len(self._data) > 0:
            n = len(self._data)
            for px in range(w):
                frac = px / w
                idx = int(frac * n)
                idx = max(0, min(n - 1, idx))
                amp = abs(float(self._data[idx]))
                bar_h = max(1, int(amp * h * 0.5))
                cx = x0 + px
                # colour based on whether inside clip
                if self._has_clip and self._clip_start <= frac <= self._clip_end:
                    col = WAVE_SEL_COLOR
                else:
                    col = WAVE_COLOR
                self.create_line(cx, mid - bar_h, cx, mid + bar_h, fill=col)

        # Playhead
        if self._playhead is not None:
            px = x0 + int(self._playhead * w)
            self.create_line(px, y0, px, y0 + h, fill=PLAY_COLOR, width=2)

    def _draw_overview(self, x0: int, y0: int, w: int, h: int):
        from ui import theme
        mid = y0 + h // 2

        if self._data is not None and len(self._data) > 0:
            n = len(self._data)
            for px in range(w):
                frac = px / w
                idx = int(frac * n)
                idx = max(0, min(n - 1, idx))
                amp = abs(float(self._data[idx]))
                bar_h = max(1, int(amp * h * 0.5))
                self.create_line(x0 + px, mid - bar_h, x0 + px, mid + bar_h, fill=theme.FG3)

        # Viewport highlight
        vx0 = x0 + int(self._view_start * w)
        vx1 = x0 + int(self._view_end * w)
        self.create_rectangle(vx0, y0, vx1, y0 + h, outline=CLIP_COLOR, fill="", width=1)

    # ── Mouse (editor mode only) ─────────────────────────────────────────────

    def _wave_y_limit(self) -> int:
        return int(self.winfo_height() * 0.65)

    def _x_to_frac(self, x: int) -> float:
        w = self.winfo_width()
        return max(0.0, min(1.0, x / w)) if w > 0 else 0.0

    def _on_press(self, event):
        if event.y > self._wave_y_limit():
            return
        frac = self._x_to_frac(event.x)
        self._drag_start_x = event.x
        # Snap to nearest edge if close
        if self._has_clip:
            w = self.winfo_width()
            start_px = int(self._clip_start * w)
            end_px = int(self._clip_end * w)
            if abs(event.x - start_px) < 10:
                self._drag_edge = "start"
            elif abs(event.x - end_px) < 10:
                self._drag_edge = "end"
            else:
                self._drag_edge = "body"
        else:
            self._clip_start = frac
            self._clip_end = frac
            self._has_clip = True
            self._drag_edge = "end"
        self._redraw()

    def _on_drag(self, event):
        if event.y > self._wave_y_limit() or self._drag_edge is None:
            return
        frac = self._x_to_frac(event.x)
        if self._drag_edge == "start":
            self._clip_start = min(frac, self._clip_end - 0.001)
        elif self._drag_edge == "end":
            self._clip_end = max(frac, self._clip_start + 0.001)
        elif self._drag_edge == "body":
            dx = self._x_to_frac(event.x) - self._x_to_frac(self._drag_start_x)
            span = self._clip_end - self._clip_start
            new_start = max(0.0, min(1.0 - span, self._clip_start + dx))
            self._clip_end = new_start + span
            self._clip_start = new_start
            self._drag_start_x = event.x
        self._redraw()

    def _on_release(self, event):
        self._drag_edge = None
        if self._has_clip and self.on_clip_change and self._duration > 0:
            start_s = self._clip_start * self._duration
            end_s = self._clip_end * self._duration
            self.on_clip_change(start_s, end_s, self._fade_in_len, self._fade_out_len)
