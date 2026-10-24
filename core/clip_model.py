from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class FadeSpec:
    fade_in: float = 0.0
    fade_out: float = 0.0
    in_curve: float = 1.0
    out_curve: float = 1.0


@dataclass
class Clip:
    start: float
    end: float
    fade: FadeSpec = field(default_factory=FadeSpec)
    label: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def is_valid(self) -> bool:
        return self.end > self.start and self.start >= 0


class ClipModel:
    def __init__(self):
        # path -> (active_clip_or_None, history_list)
        self._data: Dict[str, Tuple[Optional[Clip], List[Clip]]] = {}

    def _ensure(self, path: str):
        if path not in self._data:
            self._data[path] = (None, [])

    def get_clip(self, path: str) -> Optional[Clip]:
        self._ensure(path)
        return self._data[path][0]

    def get_history(self, path: str) -> List[Clip]:
        self._ensure(path)
        return list(self._data[path][1])

    def has_clip(self, path: str) -> bool:
        clip = self.get_clip(path)
        return clip is not None and clip.is_valid()

    def set_clip(self, path: str, start: float, end: float, fade: Optional[FadeSpec] = None):
        self._ensure(path)
        active, history = self._data[path]
        if active is not None:
            history = [active] + history
        new_clip = Clip(start=start, end=end, fade=fade or FadeSpec())
        self._data[path] = (new_clip, history)

    def clear_clip(self, path: str):
        self._ensure(path)
        active, history = self._data[path]
        if active is not None:
            history = [active] + history
        self._data[path] = (None, history)

    def restore_from_history(self, path: str, index: int):
        self._ensure(path)
        active, history = self._data[path]
        if index < 0 or index >= len(history):
            return
        restored = history[index]
        new_history = history[:index] + history[index + 1:]
        if active is not None:
            new_history = [active] + new_history
        self._data[path] = (restored, new_history)

    def all_paths_with_clips(self) -> List[str]:
        result = []
        for path, (active, _) in self._data.items():
            if active is not None and active.is_valid():
                result.append(path)
        return result
