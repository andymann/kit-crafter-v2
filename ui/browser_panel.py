import os
import threading
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable, List

from core.file_scanner import FileScanner, DirNode
from core.audio_engine import AudioEngine, AUDIO_EXTS
from ui import theme

try:
    import soundfile as sf
    _SF = True
except ImportError:
    _SF = False

_CHUNK = 200
_META_BATCH = 100
_PLACEHOLDER = "search…"


class BrowserPanel(ttk.Frame):
    def __init__(self, parent, scanner: FileScanner, engine: AudioEngine,
                 on_select: Callable, on_add_to_set: Callable, on_quick_add: Callable):
        super().__init__(parent)
        self._scanner = scanner
        self._engine = engine
        self._on_select = on_select
        self._on_add_to_set = on_add_to_set
        self._on_quick_add = on_quick_add
        self._autoplay = tk.BooleanVar(value=False)
        self._current_node: Optional[DirNode] = None
        self._in_search = False

        # IID maps
        self._tree_iid_to_path: dict = {}
        self._path_to_tree_iid: dict = {}
        self._list_iid_to_node: dict = {}
        self._list_iid_counter = 0
        self._tree_iid_counter = 0

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Top bar
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        bar.columnconfigure(1, weight=1)

        self._search_var = tk.StringVar()
        self._search_entry = ttk.Entry(bar, textvariable=self._search_var, style="Placeholder.TEntry")
        self._search_entry.insert(0, _PLACEHOLDER)
        self._search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        self._search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self._search_entry.bind("<FocusOut>", self._on_search_focus_out)
        self._search_entry.bind("<Return>", self._do_search)
        self._search_entry.bind("<Escape>", self._clear_search)

        self._flat_btn = ttk.Button(bar, text="Flat [V]", command=self._toggle_flat, width=8)
        self._flat_btn.grid(row=0, column=2, padx=(0, 4))
        ttk.Checkbutton(bar, text="Auto", variable=self._autoplay).grid(row=0, column=3)

        # Paned window
        self._paned = ttk.PanedWindow(self, orient="horizontal")
        self._paned.grid(row=1, column=0, sticky="nsew")

        # Left: folder tree
        self._tree_frame = tk.Frame(self._paned, highlightthickness=2, highlightbackground=theme.BORDER)
        self._tree_frame.rowconfigure(0, weight=1)
        self._tree_frame.columnconfigure(0, weight=1)
        self._tree = ttk.Treeview(self._tree_frame, show="tree", selectmode="browse")
        self._tree.grid(row=0, column=0, sticky="nsew")
        _vsb = ttk.Scrollbar(self._tree_frame, orient="vertical", command=self._tree.yview)
        _vsb.grid(row=0, column=1, sticky="ns")
        self._tree.configure(yscrollcommand=_vsb.set)
        self._paned.add(self._tree_frame, weight=1)

        # Right: file list
        self._list_frame = tk.Frame(self._paned, highlightthickness=2, highlightbackground=theme.BORDER)
        self._list_frame.rowconfigure(0, weight=1)
        self._list_frame.columnconfigure(0, weight=1)
        self._list = ttk.Treeview(self._list_frame, show="headings", columns=("name", "dur", "sr"), selectmode="browse")
        self._list.heading("name", text="Name")
        self._list.heading("dur", text="Dur")
        self._list.heading("sr", text="SR")
        self._list.column("name", width=220, minwidth=100)
        self._list.column("dur", width=60, minwidth=40)
        self._list.column("sr", width=60, minwidth=40)
        self._list.grid(row=0, column=0, sticky="nsew")
        _lvsb = ttk.Scrollbar(self._list_frame, orient="vertical", command=self._list.yview)
        _lvsb.grid(row=0, column=1, sticky="ns")
        self._list.configure(yscrollcommand=_lvsb.set)
        self._paned.add(self._list_frame, weight=2)

        # Bindings
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<KeyPress>", self._on_tree_key)
        self._tree.bind("<FocusIn>", lambda e: self._set_tree_border(True))
        self._tree.bind("<FocusOut>", lambda e: self._set_tree_border(False))

        self._list.bind("<<TreeviewSelect>>", self._on_list_select)
        self._list.bind("<KeyPress>", self._on_list_key)
        self._list.bind("<Double-Button-1>", self._on_list_double)
        self._list.bind("<FocusIn>", lambda e: self._set_list_border(True))
        self._list.bind("<FocusOut>", lambda e: self._set_list_border(False))

    # ── Borders ─────────────────────────────────────────────────────────────

    def _set_tree_border(self, focused: bool):
        self._tree_frame.configure(highlightbackground=theme.SEL_FG if focused else theme.BORDER)

    def _set_list_border(self, focused: bool):
        self._list_frame.configure(highlightbackground=theme.SEL_FG if focused else theme.BORDER)

    # ── Search ───────────────────────────────────────────────────────────────

    def _on_search_focus_in(self, event):
        if self._search_entry.get() == _PLACEHOLDER:
            self._search_entry.configure(style="TEntry")
            self._search_entry.delete(0, tk.END)

    def _on_search_focus_out(self, event):
        if not self._search_entry.get():
            self._search_entry.configure(style="Placeholder.TEntry")
            self._search_entry.insert(0, _PLACEHOLDER)
            if self._in_search:
                self._clear_search()

    def _do_search(self, event=None):
        q = self._search_entry.get().strip()
        if not q or q == _PLACEHOLDER:
            return
        results = self._scanner.search(q)
        self._in_search = True
        self._populate_list(results)

    def _clear_search(self, event=None):
        self._in_search = False
        self._search_entry.delete(0, tk.END)
        self._search_entry.configure(style="Placeholder.TEntry")
        self._search_entry.insert(0, _PLACEHOLDER)
        self._refresh_list()

    # ── Library root ─────────────────────────────────────────────────────────

    def set_library_root(self, path: str):
        self._tree.delete(*self._tree.get_children())
        self._tree.insert("", "end", text="Scanning…")

        def _done():
            self.after(0, self._rebuild_tree)

        self._scanner.set_root(path, on_done=_done)

    def _rebuild_tree(self):
        self._tree.delete(*self._tree.get_children())
        self._tree_iid_to_path.clear()
        self._path_to_tree_iid.clear()
        self._tree_iid_counter = 0

        root = self._scanner.root
        if root:
            self._insert_tree_node("", root)
            # Expand root
            children = self._tree.get_children("")
            if children:
                self._tree.item(children[0], open=True)
                self._tree.selection_set(children[0])
        self._refresh_list()

    def _insert_tree_node(self, parent_iid: str, node: DirNode) -> str:
        iid = str(self._tree_iid_counter)
        self._tree_iid_counter += 1
        self._tree.insert(parent_iid, "end", iid=iid, text=node.name)
        self._tree_iid_to_path[iid] = node.path
        self._path_to_tree_iid[node.path] = iid
        for child in node.children:
            if child.is_dir:
                self._insert_tree_node(iid, child)
        return iid

    # ── Tree navigation ──────────────────────────────────────────────────────

    def _on_tree_select(self, event=None):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        path = self._tree_iid_to_path.get(iid)
        if path:
            node = self._scanner.get_node(path)
            if node and node.is_dir:
                self._scanner.set_current_dir(node)
                self._refresh_list()

    def _on_tree_key(self, event):
        key = event.keysym
        sel = self._tree.selection()
        iid = sel[0] if sel else None

        if key in ("Up", "Down"):
            # Let treeview handle movement natively
            return
        elif key == "Right":
            if iid:
                if self._tree.item(iid, "open"):
                    children = self._tree.get_children(iid)
                    if children:
                        self._tree.selection_set(children[0])
                        self._tree.focus(children[0])
                        self._on_tree_select()
                else:
                    self._tree.item(iid, open=True)
            return "break"
        elif key == "Left":
            if iid:
                if self._tree.item(iid, "open"):
                    self._tree.item(iid, open=False)
                else:
                    parent = self._tree.parent(iid)
                    if parent:
                        self._tree.selection_set(parent)
                        self._tree.focus(parent)
                        self._on_tree_select()
            return "break"
        elif key == "Return":
            self.focus_list()
            return "break"

    # ── List population ───────────────────────────────────────────────────────

    def _refresh_list(self):
        if self._in_search:
            return
        nodes = self._scanner.file_list
        self._populate_list(nodes)

    def _populate_list(self, nodes: List[DirNode]):
        self._list.delete(*self._list.get_children())
        self._list_iid_to_node.clear()
        self._list_iid_counter = 0
        self._fill_chunk(nodes, 0)
        # Schedule metadata loading
        self.after(10, lambda: self._load_meta_batch(nodes, 0))

    def _fill_chunk(self, nodes: List[DirNode], offset: int):
        chunk = nodes[offset: offset + _CHUNK]
        for node in chunk:
            iid = str(self._list_iid_counter)
            self._list_iid_counter += 1
            self._list.insert("", "end", iid=iid, values=(node.name, "", ""))
            self._list_iid_to_node[iid] = node
        if offset + _CHUNK < len(nodes):
            self.after(0, lambda: self._fill_chunk(nodes, offset + _CHUNK))

    def _load_meta_batch(self, nodes: List[DirNode], offset: int):
        if not _SF:
            return
        batch = nodes[offset: offset + _META_BATCH]
        if not batch:
            return

        def _worker():
            results = []
            for node in batch:
                try:
                    info = sf.info(node.path)
                    dur = f"{info.frames / info.samplerate:.1f}s"
                    sr = f"{info.samplerate // 1000}k"
                    results.append((node.path, dur, sr))
                except Exception:
                    results.append((node.path, "", ""))
            self.after(0, lambda: self._apply_meta(results, nodes, offset))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_meta(self, results: list, nodes: List[DirNode], offset: int):
        # Build reverse map: path -> iid
        path_to_iid = {n.path: iid for iid, n in self._list_iid_to_node.items()}
        for path, dur, sr in results:
            iid = path_to_iid.get(path)
            if iid and self._list.exists(iid):
                name = self._list.set(iid, "name")
                self._list.item(iid, values=(name, dur, sr))
        next_offset = offset + _META_BATCH
        if next_offset < len(nodes):
            self.after(0, lambda: self._load_meta_batch(nodes, next_offset))

    # ── List events ──────────────────────────────────────────────────────────

    def _on_list_select(self, event=None):
        sel = self._list.selection()
        if not sel:
            return
        node = self._list_iid_to_node.get(sel[0])
        if node:
            self._current_node = node
            self._on_select(node)
            if self._autoplay.get():
                self._engine.play(node.path)

    def _on_list_double(self, event=None):
        sel = self._list.selection()
        if not sel:
            return
        node = self._list_iid_to_node.get(sel[0])
        if node:
            self._engine.play(node.path)

    def _on_list_key(self, event):
        key = event.keysym
        if key == "space" or key == "Space":
            sel = self._list.selection()
            if sel:
                node = self._list_iid_to_node.get(sel[0])
                if node:
                    self._engine.toggle(node.path)
            return "break"
        elif key == "Left":
            self.focus_tree()
            return "break"
        elif key == "v" or key == "V":
            self._toggle_flat()
            return "break"

    # ── Controls ─────────────────────────────────────────────────────────────

    def _toggle_flat(self):
        self._scanner.toggle_flat_view()
        self._refresh_list()

    # ── Public ───────────────────────────────────────────────────────────────

    @property
    def current_node(self) -> Optional[DirNode]:
        return self._current_node

    def focus_tree(self):
        self._tree.focus_set()

    def focus_search(self):
        self._search_entry.focus_set()
        if self._search_entry.get() == _PLACEHOLDER:
            self._search_entry.configure(style="TEntry")
            self._search_entry.delete(0, tk.END)

    def focus_list(self):
        self._list.focus_set()
        items = self._list.get_children()
        if items and not self._list.selection():
            self._list.selection_set(items[0])
            self._list.focus(items[0])

    @property
    def autoplay(self) -> bool:
        return self._autoplay.get()

    def set_autoplay(self, val: bool):
        self._autoplay.set(val)

    def apply_theme(self):
        self._tree_frame.configure(highlightbackground=theme.BORDER)
        self._list_frame.configure(highlightbackground=theme.BORDER)
