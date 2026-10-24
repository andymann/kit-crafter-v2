import os
import threading
from dataclasses import dataclass, field
from typing import Optional, Callable, List, Tuple

import numpy as np

try:
    import soundfile as sf
    _SF = True
except ImportError:
    _SF = False

try:
    import librosa
    _LIBROSA = True
except ImportError:
    _LIBROSA = False

from core.clip_model import Clip


@dataclass
class ExportSettings:
    output_dir: str = ""
    fmt: str = "WAV"
    subtype: str = "PCM_16"
    target_sr: int = 44100
    mono: bool = True
    normalize: bool = True
    normalize_db: float = -0.1
    hpf: bool = False
    hpf_freq: float = 40.0
    limiter: bool = False


BUILTIN_PRESETS = {
    "TR-8S": ExportSettings(fmt="WAV", subtype="PCM_16", target_sr=44100, mono=True, normalize=True),
    "Octatrack": ExportSettings(fmt="WAV", subtype="PCM_16", target_sr=44100, mono=False, normalize=True),
    "SP-404 MK2": ExportSettings(fmt="WAV", subtype="PCM_16", target_sr=44100, mono=False, normalize=True),
    "DAW (24-bit)": ExportSettings(fmt="WAV", subtype="PCM_24", target_sr=48000, mono=False, normalize=False),
}

_FMT_MAP = {
    "WAV": "WAV",
    "AIFF": "AIFF",
    "FLAC": "FLAC",
}

_EXT_MAP = {
    "WAV": ".wav",
    "AIFF": ".aif",
    "FLAC": ".flac",
}


def export_file(
    src: str,
    out_dir: str,
    out_name: str,
    settings: ExportSettings,
    clip: Optional[Clip] = None,
) -> Tuple[bool, str]:
    if not _SF:
        return False, "soundfile not available"
    try:
        data, sr = sf.read(src, dtype="float32", always_2d=True)
        total_frames = len(data)

        # Slice clip
        if clip and clip.is_valid():
            s_frame = max(0, int(clip.start * sr))
            e_frame = min(total_frames, int(clip.end * sr))
            data = data[s_frame:e_frame]

            # Apply fades
            n = len(data)
            if clip.fade.fade_in > 0:
                fi_frames = min(int(clip.fade.fade_in * sr), n)
                env = np.linspace(0.0, 1.0, fi_frames) ** clip.fade.in_curve
                data[:fi_frames] *= env[:, np.newaxis]
            if clip.fade.fade_out > 0:
                fo_frames = min(int(clip.fade.fade_out * sr), n)
                env = np.linspace(1.0, 0.0, fo_frames) ** clip.fade.out_curve
                data[n - fo_frames:] *= env[:, np.newaxis]

        # Mono
        if settings.mono and data.shape[1] > 1:
            data = data.mean(axis=1, keepdims=True)
        elif not settings.mono and data.shape[1] == 1:
            data = np.concatenate([data, data], axis=1)

        # Resample
        if sr != settings.target_sr:
            if _LIBROSA:
                mono_in = data[:, 0] if data.shape[1] == 1 else data.T
                if data.shape[1] == 1:
                    resampled = librosa.resample(data[:, 0], orig_sr=sr, target_sr=settings.target_sr)
                    data = resampled[:, np.newaxis]
                else:
                    channels = []
                    for ch in range(data.shape[1]):
                        channels.append(librosa.resample(data[:, ch], orig_sr=sr, target_sr=settings.target_sr))
                    data = np.stack(channels, axis=1)
            else:
                # linear interp fallback
                orig_len = len(data)
                new_len = int(orig_len * settings.target_sr / sr)
                x_old = np.linspace(0, 1, orig_len)
                x_new = np.linspace(0, 1, new_len)
                channels = []
                for ch in range(data.shape[1]):
                    channels.append(np.interp(x_new, x_old, data[:, ch]))
                data = np.stack(channels, axis=1)
            sr = settings.target_sr

        # HPF (first-order IIR)
        if settings.hpf and settings.hpf_freq > 0:
            dt = 1.0 / sr
            rc = 1.0 / (2.0 * np.pi * settings.hpf_freq)
            alpha = rc / (rc + dt)
            filtered = np.zeros_like(data)
            filtered[0] = data[0]
            for i in range(1, len(data)):
                filtered[i] = alpha * (filtered[i - 1] + data[i] - data[i - 1])
            data = filtered

        # Normalize
        if settings.normalize:
            peak = np.abs(data).max()
            if peak > 0:
                target = 10 ** (settings.normalize_db / 20.0)
                data = data * (target / peak)

        # Limiter (simple clip)
        if settings.limiter:
            data = np.clip(data, -1.0, 1.0)

        # Squeeze if mono
        if data.shape[1] == 1:
            data = data[:, 0]

        ext = _EXT_MAP.get(settings.fmt, ".wav")
        base = os.path.splitext(out_name)[0]
        out_path = os.path.join(out_dir, base + ext)
        sf_fmt = _FMT_MAP.get(settings.fmt, "WAV")
        sf.write(out_path, data, sr, subtype=settings.subtype, format=sf_fmt)
        return True, out_path

    except Exception as e:
        return False, str(e)


class BatchExporter:
    def __init__(
        self,
        items: list,
        out_dir: str,
        settings: ExportSettings,
        clip_model,
        on_progress: Callable,
        on_done: Callable,
    ):
        self._items = items
        self._out_dir = out_dir
        self._settings = settings
        self._clip_model = clip_model
        self._on_progress = on_progress
        self._on_done = on_done
        self._cancel_flag = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancel_flag = True

    def _run(self):
        total = len(self._items)
        ok_count = 0
        for i, item in enumerate(self._items):
            if self._cancel_flag:
                break
            clip = self._clip_model.get_clip(item.path) if self._clip_model else None
            ok, msg = export_file(item.path, self._out_dir, item.name, self._settings, clip)
            if ok:
                ok_count += 1
            self._on_progress(i + 1, total, f"{'OK' if ok else 'ERR'}: {item.name}")
        self._on_done(ok_count, total)
