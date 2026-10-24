import os
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Callable

from core.audio_engine import AUDIO_EXTS


@dataclass
class DirNode:
    path: str
    name: str
    is_dir: bool
    children: List["DirNode"] = field(default_factory=list)
    parent: Optional["DirNode"] = field(default=None, repr=False)


class FileScanner:
    def __init__(self):
        self._root: Optional[DirNode] = None
        self._current_dir: Optional[DirNode] = None
        self._flat_view: bool = False
        self._scan_id: int = 0
        self._node_by_path: dict = {}
        self._lock = threading.Lock()

    def set_root(self, path: str, on_done: Optional[Callable] = None):
        self._scan_id += 1
        scan_id = self._scan_id

        def _worker():
            node_map = {}
            root_node = self._build_tree(path, None, node_map)
            with self._lock:
                if scan_id != self._scan_id:
                    return
                self._root = root_node
                self._current_dir = root_node
                self._node_by_path = node_map
            if on_done:
                on_done()

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _build_tree(self, path: str, parent: Optional[DirNode], node_map: dict) -> DirNode:
        name = os.path.basename(path) or path
        node = DirNode(path=path, name=name, is_dir=True, parent=parent)
        node_map[path] = node

        try:
            entries = os.listdir(path)
        except PermissionError:
            return node

        entries = [e for e in entries if not e.startswith(".")]
        dirs = sorted([e for e in entries if os.path.isdir(os.path.join(path, e))], key=str.lower)
        files = sorted([e for e in entries if not os.path.isdir(os.path.join(path, e))], key=str.lower)

        for d in dirs:
            child_path = os.path.join(path, d)
            child = self._build_tree(child_path, node, node_map)
            node.children.append(child)

        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in AUDIO_EXTS:
                child_path = os.path.join(path, f)
                child = DirNode(path=child_path, name=f, is_dir=False, parent=node)
                node_map[child_path] = child
                node.children.append(child)

        return node

    def get_node(self, path: str) -> Optional[DirNode]:
        return self._node_by_path.get(path)

    def toggle_flat_view(self):
        self._flat_view = not self._flat_view

    def set_current_dir(self, node: DirNode):
        if node.is_dir:
            self._current_dir = node

    def navigate_up(self):
        if self._current_dir and self._current_dir.parent:
            self._current_dir = self._current_dir.parent

    @property
    def file_list(self) -> List[DirNode]:
        if self._flat_view:
            return self._collect_audio(self._root)
        if self._current_dir is None:
            return []
        return [c for c in self._current_dir.children if not c.is_dir]

    def _collect_audio(self, node: Optional[DirNode]) -> List[DirNode]:
        if node is None:
            return []
        result = []
        for child in node.children:
            if child.is_dir:
                result.extend(self._collect_audio(child))
            else:
                result.append(child)
        return result

    @property
    def dir_children(self) -> List[DirNode]:
        if self._current_dir is None:
            return []
        return [c for c in self._current_dir.children if c.is_dir]

    def search(self, query: str) -> List[DirNode]:
        q = query.lower()
        return self._search_node(self._root, q)

    def _search_node(self, node: Optional[DirNode], q: str) -> List[DirNode]:
        if node is None:
            return []
        result = []
        for child in node.children:
            if child.is_dir:
                result.extend(self._search_node(child, q))
            elif q in child.name.lower():
                result.append(child)
        return result

    @property
    def root(self) -> Optional[DirNode]:
        return self._root

    @property
    def current_dir(self) -> Optional[DirNode]:
        return self._current_dir

    @property
    def flat_view(self) -> bool:
        return self._flat_view
