import atexit
import json
import os
import tkinter as tk
from tkinter import ttk
from typing import Optional

from constants import APPNAME, VERSION
from core.audio_engine import AudioEngine
from core.analysis import Analyzer
from core.file_scanner import FileScanner
from core.set_manager import SetManager
from core.clip_model import ClipModel, FadeSpec
from ui import theme
from ui.browser_panel import BrowserPanel
from ui.editor_view import EditorView
from ui.set_panel import SetPanel
from ui.detail_pane import DetailPane
from ui.export_panel import ExportPanel
from ui.shortcuts_overlay import ShortcutsOverlay

_CONFIG_PATH = os.path.expanduser("~/.kit_crafter_config.json")


class AppWindow:
    def __init__(self, root: tk.Tk):
        self._root = root
        root.title(f"{APPNAME} {VERSION}")
        root.geometry("1100x700")
        root.minsize(700, 480)

        # Core
        self._engine = AudioEngine()
        self._analyzer = Analyzer()
        self._scanner = FileScanner()
        self._set_mgr = SetManager()
        self._clip_model = ClipModel()
        self._current_path: Optional[str] = None
        self._in_editor: bool = False

        theme.apply(root)

        self._build_ui()
        self._bind_keys()
        self._restore_state()
        atexit.register(self._save_state)
        root.protocol("WM_DELETE_WINDOW", self._on_quit)
        try:
            root.createcommand("tk::mac::Quit", self._on_quit)
        except Exception:
            pass
        root.after_idle(self._browser.focus_tree)
        self._poll_playing()

    # ── UI build ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = self._root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # Toolbar
        toolbar = tk.Frame(root, bg=theme.PANEL, height=32)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        self._toolbar = toolbar

        tk.Label(toolbar, text=f"{APPNAME} {VERSION}", bg=theme.PANEL, fg=theme.FG2,
                 font=theme.FONT_XS, padx=10).grid(row=0, column=0, sticky="w")
        self._path_lbl = tk.Label(toolbar, text="No folder", bg=theme.PANEL, fg=theme.FG3,
                                  font=theme.FONT_XS)
        self._path_lbl.grid(row=0, column=1, sticky="w", padx=4)
        self._playing_lbl = tk.Label(toolbar, text="", bg=theme.PANEL, fg=theme.GREEN,
                                     font=theme.FONT_XS, padx=10)
        self._playing_lbl.grid(row=0, column=2, sticky="e")

        # Main pane
        paned = ttk.PanedWindow(root, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew")

        # Left: main_slot holds browser + editor stacked
        self._main_slot = ttk.Frame(paned)
        self._main_slot.columnconfigure(0, weight=1)
        self._main_slot.rowconfigure(0, weight=1)
        paned.add(self._main_slot, weight=3)

        def _on_select(node):
            self._current_path = node.path
            self._detail.set_file(node.path)
            self._analyze_for_detail(node.path)

        def _on_add_to_set(node):
            self._set_panel.add_file(node.path, node.name)

        def _on_quick_add(node):
            self._set_panel.show_quick_add(node.path, node.name)

        self._browser = BrowserPanel(
            self._main_slot,
            scanner=self._scanner,
            engine=self._engine,
            on_select=_on_select,
            on_add_to_set=_on_add_to_set,
            on_quick_add=_on_quick_add,
        )
        self._browser.grid(row=0, column=0, sticky="nsew")

        self._editor = EditorView(
            self._main_slot,
            engine=self._engine,
            clip_model=self._clip_model,
            on_close=self._show_browser,
        )
        # editor starts hidden
        self._editor.grid(row=0, column=0, sticky="nsew")
        self._editor.grid_remove()

        # Right: set panel
        self._set_panel = SetPanel(
            paned,
            set_mgr=self._set_mgr,
            clip_model=self._clip_model,
            on_open_export=self._open_export,
            on_play=lambda p: self._engine.play(p),
            on_select=lambda p: self._on_set_select(p),
        )
        paned.add(self._set_panel, weight=0)

        # Separator + detail pane
        ttk.Separator(root, orient="horizontal").grid(row=2, column=0, sticky="ew")
        self._detail = DetailPane(root, engine=self._engine)
        self._detail.grid(row=3, column=0, sticky="ew")

    # ── View switching ───────────────────────────────────────────────────────

    def _show_browser(self):
        self._editor.grid_remove()
        self._browser.grid()
        self._in_editor = False
        self._root.unbind("<Escape>")
        self._browser.focus_list()

    def _show_editor(self):
        if not self._current_path:
            return
        self._browser.grid_remove()
        self._editor.grid()
        self._editor.load(self._current_path)
        self._in_editor = True
        self._root.bind("<Escape>", lambda e: self._show_browser())

    def _toggle_editor(self):
        if self._in_editor:
            self._show_browser()
        else:
            self._show_editor()

    # ── Key bindings ──────────────────────────────────────────────────────────

    def _bind_keys(self):
        self._root.bind_all("<KeyPress>", self._on_global_key)
        self._root.bind_all("<Tab>", self._on_tab)

    def _is_entry_focused(self) -> bool:
        focused = self._root.focus_get()
        return isinstance(focused, (tk.Entry, ttk.Entry))

    def _on_global_key(self, event):
        if self._is_entry_focused():
            return
        key = event.keysym
        char = event.char.lower() if event.char else ""
        state = event.state

        # Ctrl+T
        if key == "t" and (state & 0x4):
            theme.cycle(self._root)
            self._apply_theme()
            return "break"

        if key == "question":
            ShortcutsOverlay(self._root)
            return "break"

        if char == "c":
            self._toggle_editor()
            return "break"

        if char == "e":
            if self._current_path:
                if state & 0x1:  # Shift
                    node = self._scanner.get_node(self._current_path)
                    name = os.path.basename(self._current_path) if self._current_path else ""
                    self._set_panel.show_quick_add(self._current_path, name)
                else:
                    name = os.path.basename(self._current_path) if self._current_path else ""
                    self._set_panel.add_file(self._current_path, name)
            return "break"

        if char == "q":
            self._set_mgr.cycle_active()
            self._set_panel.apply_theme()
            self._set_panel.refresh()
            return "break"

        if char == "f":
            self._browser.focus_search()
            return "break"

        if char == "x" and not self._in_editor:
            self._open_export()
            return "break"

        if key == "space":
            self._engine.toggle(self._current_path)
            return "break"

    def _on_tab(self, event):
        if self._is_entry_focused():
            return
        self._browser.set_autoplay(not self._browser.autoplay)
        return "break"

    # ── Playing label poll ───────────────────────────────────────────────────

    def _poll_playing(self):
        if self._engine.is_playing():
            cur = self._engine.current or ""
            self._playing_lbl.configure(text=f"▶ {os.path.basename(cur)}")
        else:
            self._playing_lbl.configure(text="")
        self._root.after(500, self._poll_playing)

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self):
        self._toolbar.configure(bg=theme.PANEL)
        for w in self._toolbar.winfo_children():
            if isinstance(w, tk.Label):
                w.configure(bg=theme.PANEL)
        self._playing_lbl.configure(fg=theme.GREEN)
        self._browser.apply_theme()
        self._set_panel.apply_theme()
        self._detail.apply_theme()

    # ── Export ────────────────────────────────────────────────────────────────

    def _open_export(self):
        ExportPanel(self._root, self._set_mgr, self._clip_model)

    # ── Set select ────────────────────────────────────────────────────────────

    def _on_set_select(self, path: str):
        self._current_path = path
        self._detail.set_file(path)
        self._analyze_for_detail(path)

    def _analyze_for_detail(self, path: str):
        def _on_result(result):
            def _apply():
                if self._current_path == path:
                    self._detail.set_bpm_key(result.bpm, result.key_display)
            self._detail.after(0, _apply)

        self._analyzer.analyze_async(path, _on_result)

    # ── State persistence ─────────────────────────────────────────────────────

    def _save_state(self):
        try:
            sets_data = []
            for s in self._set_mgr.sets:
                sets_data.append({
                    "id": s.id,
                    "name": s.name,
                    "items": [{"path": i.path, "name": i.name, "clip_id": i.clip_id} for i in s.items],
                    "history": [{"path": i.path, "name": i.name} for i in s.history],
                })

            clips_data = {}
            for path in self._clip_model.all_paths_with_clips():
                clip = self._clip_model.get_clip(path)
                history = self._clip_model.get_history(path)
                if clip:
                    clips_data[path] = {
                        "active": {
                            "start": clip.start,
                            "end": clip.end,
                            "label": clip.label,
                            "fade_in": clip.fade.fade_in,
                            "fade_out": clip.fade.fade_out,
                            "in_curve": clip.fade.in_curve,
                            "out_curve": clip.fade.out_curve,
                        },
                        "history": [
                            {
                                "start": h.start, "end": h.end, "label": h.label,
                                "fade_in": h.fade.fade_in, "fade_out": h.fade.fade_out,
                                "in_curve": h.fade.in_curve, "out_curve": h.fade.out_curve,
                            }
                            for h in history
                        ],
                    }

            active_idx = 0
            active_id = self._set_mgr.active.id
            for i, s in enumerate(self._set_mgr.sets):
                if s.id == active_id:
                    active_idx = i
                    break

            data = {
                "last_folder": self._path_lbl.cget("text") if self._path_lbl.cget("text") != "No folder" else "",
                "active_set_index": active_idx,
                "sets": sets_data,
                "clips": clips_data,
                "theme": theme.current_name(),
                "autoplay": self._browser.autoplay,
            }
            with open(_CONFIG_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _restore_state(self):
        if not os.path.exists(_CONFIG_PATH):
            return
        try:
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
        except Exception:
            return

        # Theme first
        t = data.get("theme", "Classic")
        theme.set_theme(t, self._root)
        self._apply_theme()

        # Autoplay
        self._browser.set_autoplay(data.get("autoplay", False))

        # Restore clips before sets so badges render correctly
        for path, cdata in data.get("clips", {}).items():
            active = cdata.get("active")
            if active:
                fade = FadeSpec(
                    fade_in=active.get("fade_in", 0.0),
                    fade_out=active.get("fade_out", 0.0),
                    in_curve=active.get("in_curve", 1.0),
                    out_curve=active.get("out_curve", 1.0),
                )
                self._clip_model.set_clip(path, active["start"], active["end"], fade)

        # Restore sets
        saved_sets = data.get("sets", [])
        if saved_sets:
            # Clear default set, build from saved
            self._set_mgr._sets.clear()
            for sd in saved_sets:
                from core.set_manager import SampleSet, SetItem
                s = SampleSet(id=sd["id"], name=sd["name"])
                for item in sd.get("items", []):
                    s.items.append(SetItem(path=item["path"], name=item["name"], clip_id=item.get("clip_id")))
                for item in sd.get("history", []):
                    s.history.append(SetItem(path=item["path"], name=item["name"]))
                self._set_mgr._sets.append(s)
            active_idx = min(data.get("active_set_index", 0), len(self._set_mgr._sets) - 1)
            self._set_mgr._active_index = active_idx
        self._set_panel.apply_theme()
        self._set_panel.refresh()

        # Folder
        folder = data.get("last_folder", "")
        if folder and os.path.isdir(folder):
            self._browser.set_library_root(folder)
            self._path_lbl.configure(text=folder)

    def _on_quit(self):
        self._save_state()
        self._engine.cleanup()
        self._root.destroy()


