import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class SetItem:
    path: str
    name: str
    clip_id: Optional[str] = None


@dataclass
class SampleSet:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "New set"
    items: List[SetItem] = field(default_factory=list)
    history: List[SetItem] = field(default_factory=list)

    def add(self, path: str, name: str) -> bool:
        if self.contains(path):
            return False
        self.items.append(SetItem(path=path, name=name))
        return True

    def remove(self, path: str):
        for i, item in enumerate(self.items):
            if item.path == path:
                self.history.insert(0, item)
                self.items.pop(i)
                return

    def restore(self, path: str):
        for i, item in enumerate(self.history):
            if item.path == path:
                self.items.append(item)
                self.history.pop(i)
                return

    def contains(self, path: str) -> bool:
        return any(item.path == path for item in self.items)

    def rename_item(self, path: str, new_name: str):
        for item in self.items:
            if item.path == path:
                item.name = new_name
                return


class SetManager:
    def __init__(self):
        self._sets: List[SampleSet] = [SampleSet(name="Set 1")]
        self._active_index: int = 0

    @property
    def active(self) -> SampleSet:
        return self._sets[self._active_index]

    def cycle_active(self):
        if len(self._sets) > 1:
            self._active_index = (self._active_index + 1) % len(self._sets)

    def set_active(self, set_id: str):
        for i, s in enumerate(self._sets):
            if s.id == set_id:
                self._active_index = i
                return

    def new_set(self, name: str = "New set") -> SampleSet:
        s = SampleSet(name=name)
        self._sets.append(s)
        self._active_index = len(self._sets) - 1
        return s

    def remove_set(self, set_id: str) -> bool:
        if len(self._sets) <= 1:
            return False
        for i, s in enumerate(self._sets):
            if s.id == set_id:
                self._sets.pop(i)
                self._active_index = min(self._active_index, len(self._sets) - 1)
                return True
        return False

    def rename_set(self, set_id: str, name: str):
        s = self.get(set_id)
        if s:
            s.name = name

    def add_to_active(self, path: str, name: str) -> bool:
        return self.active.add(path, name)

    def add_to_set(self, set_id: str, path: str, name: str) -> bool:
        s = self.get(set_id)
        if s:
            return s.add(path, name)
        return False

    def remove_from_active(self, path: str):
        self.active.remove(path)

    @property
    def sets(self) -> List[SampleSet]:
        return list(self._sets)

    def get(self, set_id: str) -> Optional[SampleSet]:
        for s in self._sets:
            if s.id == set_id:
                return s
        return None
