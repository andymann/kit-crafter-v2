import threading
from typing import Optional, Callable
import numpy as np

try:
    import pygame
    import pygame.mixer
    _PYGAME = True
except (ImportError, NotImplementedError):
    _PYGAME = False

try:
    import soundfile as sf
    _SF = True
except ImportError:
    _SF = False

AUDIO_EXTS = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".opus"}


class AudioEngine:
    def __init__(self):
        self._current: Optional[str] = None
        self._waveform_cache: dict = {}
        if _PYGAME:
            try:
                pygame.mixer.init(44100, -16, 2, 1024)
            except Exception:
                pass

    def play(self, path: str) -> bool:
        if not _PYGAME:
            return False
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            self._current = path
            return True
        except Exception:
            return False

    def stop(self):
        if _PYGAME:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

    def toggle(self, path: Optional[str] = None):
        if self.is_playing():
            self.stop()
        else:
            target = path or self._current
            if target:
                self.play(target)

    def is_playing(self) -> bool:
        if not _PYGAME:
            return False
        try:
            return bool(pygame.mixer.music.get_busy())
        except Exception:
            return False

    @property
    def current(self) -> Optional[str]:
        return self._current

    def get_position(self) -> Optional[float]:
        if not _PYGAME:
            return None
        try:
            pos = pygame.mixer.music.get_pos()
            return pos / 1000.0 if pos >= 0 else None
        except Exception:
            return None

    def load_waveform(self, path: str, n_points: int = 2000) -> Optional[np.ndarray]:
        if path in self._waveform_cache:
            return self._waveform_cache[path]
        if not _SF:
            return None
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
            # to mono
            mono = data.mean(axis=1)
            # downsample
            total = len(mono)
            if total > n_points:
                indices = np.linspace(0, total - 1, n_points).astype(int)
                result = mono[indices]
            else:
                result = mono
            self._waveform_cache[path] = result
            return result
        except Exception:
            return None

    def load_waveform_async(self, path: str, callback: Callable):
        def _worker():
            result = self.load_waveform(path)
            callback(result)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def file_info(self, path: str) -> dict:
        if not _SF:
            return {}
        try:
            info = sf.info(path)
            return {
                "sr": info.samplerate,
                "channels": info.channels,
                "frames": info.frames,
                "duration": info.frames / info.samplerate,
                "subtype": info.subtype,
            }
        except Exception:
            return {}

    def clear_cache(self):
        self._waveform_cache.clear()

    def cleanup(self):
        if _PYGAME:
            try:
                pygame.mixer.quit()
            except Exception:
                pass
