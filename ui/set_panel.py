import tkinter as tk
from tkinter import ttk, simpledialog
from typing import Optional, Callable

from core.set_manager import SetManager
from core.clip_model import ClipModel
from ui import theme


class SetPanel(ttk.Frame):
    def __init__(self, parent, set_mgr: SetManager, clip_model: ClipModel,
                 on_open_export: Callable, on_play: Callable, on_select: Callable):
        super().__init__(parent, style="Panel.TFrame")
        self._set_mgr = set_mgr
        self._clip_model = clip_model
        self._on_open_export = on_open_export
        self._on_play = on_play
        self._on_select = on_select

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Header
        hdr = ttk.Frame(self, style="Panel.TFrame")
        hdr.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        hdr.columnconfigure(0, weight=1)
        ttk.Label(hdr, text="ACTIVE SET", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(hdr, text="N", command=self._new_set, width=3).grid(row=0, column=1, padx=2)
        ttk.Button(hdr, text="Q", command=self._cycle_set, width=3).grid(row=0, column=2, padx=2)

        # Tabs strip
        self._tabs_frame = tk.Frame(self, bg=theme.PANEL)
        self._tabs_frame.grid(row=1, column=0, sticky="ew", padx=4, pady=2)

        # Listbox
        lb_frame = ttk.Frame(self)
        lb_frame.grid(row=2, column=0, sticky="nsew", padx=4)
        lb_frame.rowconfigure(0, weight=1)
        lb_frame.columnconfigure(0, weight=1)
        self._lb = tk.Listbox(
            lb_frame,
            bg=theme.PANEL,
            fg=theme.FG,
            selectbackground=theme.SEL,
            selectforeground=theme.SEL_FG,
            font=theme.FONT_S,
            relief="flat",
            borderwidth=0,
        )
        self._lb.grid(row=0, column=0, sticky="nsew")
        _vsb = ttk.Scrollbar(lb_frame, orient="vertical", command=self._lb.yview)
        _vsb.grid(row=0, column=1, sticky="ns")
        self._lb.configure(yscrollcommand=_vsb.set)
        self._lb.bind("<<ListboxSelect>>", self._on_lb_select)
        self._lb.bind("<Double-Button-1>", self._on_lb_double)
        self._lb.bind("<Delete>", self._remove_selected)
        self._lb.bind("<BackSpace>", self._remove_selected)

        # History row
        hist_row = ttk.Frame(self, style="Panel.TFrame")
        hist_row.grid(row=3, column=0, sticky="ew", padx=4, pady=2)
        hist_row.columnconfigure(0, weight=1)
        ttk.Label(hist_row, text="removed items", style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(hist_row, text="▾", command=self._show_history, width=3).grid(row=0, column=1)

        # Export button
        self._export_btn = ttk.Button(self, text="Export set [X]", style="Accent.TButton", command=self._on_open_export)
        self._export_btn.grid(row=4, column=0, sticky="ew", padx=4, pady=4)

        self._rebuild_tabs()
        self.refresh()

    # ── Tabs ─────────────────────────────────────────────────────────────────

    def _rebuild_tabs(self):
        for w in self._tabs_frame.winfo_children():
            w.destroy()
        sets = self._set_mgr.sets
        active_id = self._set_mgr.active.id
        for s in sets:
            is_active = s.id == active_id
            btn = tk.Button(
                self._tabs_frame,
                text=s.name,
                bg=theme.SEL if is_active else theme.SURFACE,
                fg=theme.SEL_FG if is_active else theme.FG2,
                font=theme.FONT_XS,
                relief="flat",
                bd=0,
                padx=6,
                pady=2,
                command=lambda sid=s.id: self._switch_set(sid),
            )
            btn.pack(side="left", padx=1)
            btn.bind("<Double-Button-1>", lambda e, sid=s.id: self._rename_set(sid))

    def _switch_set(self, set_id: str):
        self._set_mgr.set_active(set_id)
        self._rebuild_tabs()
        self.refresh()

    def _new_set(self):
        name = simpledialog.askstring("New set", "Set name:", parent=self)
        if name:
            self._set_mgr.new_set(name)
            self._rebuild_tabs()
            self.refresh()

    def _cycle_set(self):
        self._set_mgr.cycle_active()
        self._rebuild_tabs()
        self.refresh()

    def _rename_set(self, set_id: str):
        s = self._set_mgr.get(set_id)
        if not s:
            return
        name = simpledialog.askstring("Rename set", "New name:", initialvalue=s.name, parent=self)
        if name:
            self._set_mgr.rename_set(set_id, name)
            self._rebuild_tabs()

    # ── List ─────────────────────────────────────────────────────────────────

    def refresh(self):
        self._lb.delete(0, tk.END)
        active = self._set_mgr.active
        for item in active.items:
            label = item.name
            if self._clip_model.has_clip(item.path):
                label += " ✂"
            self._lb.insert(tk.END, label)
        self._export_btn.configure(text=f"Export set [{len(active.items)}]")

    def _on_lb_select(self, event=None):
        sel = self._lb.curselection()
        if not sel:
            return
        idx = sel[0]
        items = self._set_mgr.active.items
        if idx < len(items):
            self._on_select(items[idx].path)

    def _on_lb_double(self, event=None):
        sel = self._lb.curselection()
        if not sel:
            return
        idx = sel[0]
        items = self._set_mgr.active.items
        if idx < len(items):
            self._on_play(items[idx].path)

    def _remove_selected(self, event=None):
        sel = self._lb.curselection()
        if not sel:
            return
        idx = sel[0]
        items = self._set_mgr.active.items
        if idx < len(items):
            self._set_mgr.remove_from_active(items[idx].path)
            self.refresh()

    # ── History ───────────────────────────────────────────────────────────────

    def _show_history(self):
        active = self._set_mgr.active
        if not active.history:
            return
        popup = tk.Toplevel(self)
        popup.title("Removed items")
        popup.configure(bg=theme.BG)
        popup.transient(self.winfo_toplevel())
        lb = tk.Listbox(popup, bg=theme.PANEL, fg=theme.FG, font=theme.FONT_S, relief="flat", width=40, height=15)
        lb.pack(fill="both", expand=True, padx=8, pady=8)
        for item in active.history:
            lb.insert(tk.END, item.name)

        def _restore(event=None):
            sel = lb.curselection()
            if sel:
                idx = sel[0]
                if idx < len(active.history):
                    path = active.history[idx].path
                    active.restore(path)
                    self.refresh()
                    popup.destroy()

        lb.bind("<Double-Button-1>", _restore)
        popup.bind("<Escape>", lambda e: popup.destroy())
        lb.focus_set()

    # ── Public ────────────────────────────────────────────────────────────────

    def add_file(self, path: str, name: str) -> bool:
        ok = self._set_mgr.add_to_active(path, name)
        if ok:
            self.refresh()
        return ok

    def add_file_to(self, set_id: str, path: str, name: str) -> bool:
        ok = self._set_mgr.add_to_set(set_id, path, name)
        if ok:
            self.refresh()
        return ok

    def show_quick_add(self, path: str, name: str):
        popup = tk.Toplevel(self)
        popup.title("Add to set")
        popup.configure(bg=theme.BG)
        popup.transient(self.winfo_toplevel())
        ttk.Label(popup, text=f"Add: {name}", style="Accent.TLabel").pack(padx=8, pady=(8, 4))
        lb = tk.Listbox(popup, bg=theme.PANEL, fg=theme.FG, font=theme.FONT_S, relief="flat", width=30, height=8)
        lb.pack(fill="both", expand=True, padx=8, pady=4)
        sets = self._set_mgr.sets
        for s in sets:
            lb.insert(tk.END, s.name)

        def _add(event=None):
            sel = lb.curselection()
            if sel:
                idx = sel[0]
                if idx < len(sets):
                    self._set_mgr.add_to_set(sets[idx].id, path, name)
                    self.refresh()
                    popup.destroy()

        lb.bind("<Double-Button-1>", _add)
        ttk.Button(popup, text="Add", command=_add).pack(pady=(0, 8))
        popup.bind("<Escape>", lambda e: popup.destroy())
        lb.focus_set()

    def apply_theme(self):
        self._tabs_frame.configure(bg=theme.PANEL)
        self._rebuild_tabs()
        self._lb.configure(
            bg=theme.PANEL,
            fg=theme.FG,
            selectbackground=theme.SEL,
            selectforeground=theme.SEL_FG,
        )
