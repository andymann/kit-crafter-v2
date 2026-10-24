"""Tier-2 BPM detection via the bundled ``beat_this_small0`` ONNX model.

Confirmed directly from the model file: input tensor ``mel_spectrogram``
of shape ``(batch, time_frames, 128)``, output ``logits`` of shape
``(batch, time_frames, 2)`` — i.e. a per-frame beat/downbeat activation
transformer, matching the public "Beat This!" architecture (Foscarin,
Schlüter & Widmer, ISMIR 2024, CPJKU) which this model is named after
(``beat_this_small0``) and whose headline feature is *not* needing a
DBN/HMM postprocessor — frame activations are turned into beat times by
simple peak-picking.

The crate's mangled symbols (``tempo::MEL_FILTERBANK`` /
``build_mel_filterbank``, ``tempo::HANN_WINDOW`` / ``build_hann_window``,
``tempo::run_inference``, ``tempo::beats_to_bpm``) confirm this exact
shape: a hand-rolled STFT + mel filterbank feeding the ONNX model,
followed by a beat-times -> BPM conversion. The mel-filterbank's exact
``fmin``/``fmax`` could not be recovered without decompiling
``build_mel_filterbank``; the values below are the published Beat This!
preprocessing (22050 Hz, 1024-sample FFT, 441-sample hop -> 50 fps, 128
mel bands, 30-11000 Hz), which this model's shape otherwise matches
exactly.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import librosa
import numpy as np

SR = 22050
N_FFT = 1024
HOP_LENGTH = 441  # 50 fps at 22050 Hz
N_MELS = 128
FMIN = 30.0
FMAX = 11000.0
FPS = SR / HOP_LENGTH

MIN_BPM = 55.0
MAX_BPM = 215.0

_MODEL_FILENAME = "beat_this_small0_uint8.onnx"


@dataclass
class TempoResult:
    bpm: float
    grid_stability: float
    beat_times: np.ndarray


class TempoAnalyzer:
    def __init__(self, resources_dir: Path):
        import onnxruntime as ort

        model_path = resources_dir / _MODEL_FILENAME
        self._session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name
        self._mel_filterbank = _build_mel_filterbank()
        self._hann_window = _build_hann_window()

    def _mel_spectrogram(self, y: np.ndarray, sr: int) -> np.ndarray:
        if sr != SR:
            y = librosa.resample(y, orig_sr=sr, target_sr=SR)
        stft = librosa.stft(
            y, n_fft=N_FFT, hop_length=HOP_LENGTH, window=self._hann_window,
            center=True,
        )
        power = np.abs(stft) ** 2
        mel = self._mel_filterbank @ power
        log_mel = np.log1p(mel * 1000.0)
        return log_mel.T.astype(np.float32)  # (time_frames, 128)

    def run_inference(self, y: np.ndarray, sr: int) -> Optional[np.ndarray]:
        mel = self._mel_spectrogram(y, sr)
        if mel.shape[0] < 2:
            return None
        batch = mel[np.newaxis, :, :]
        logits = self._session.run(
            None, {self._input_name: batch.astype(np.float32)}
        )[0][0]
        return logits  # (time_frames, 2) -> [beat, downbeat]

    def detect(self, y: np.ndarray, sr: int) -> Optional[TempoResult]:
        if y.size < sr:
            return None
        logits = self.run_inference(y, sr)
        if logits is None:
            return None
        beat_activation = _sigmoid(logits[:, 0])
        beat_frames = _pick_peaks(beat_activation, min_distance_frames=int(FPS * 60 / MAX_BPM))
        if beat_frames.size < 2:
            return None
        beat_times = beat_frames / FPS
        return beats_to_bpm(beat_times)


def beats_to_bpm(beat_times: np.ndarray) -> Optional[TempoResult]:
    if beat_times.size < 2:
        return None
    iois = np.diff(beat_times)
    iois = iois[(iois > 60.0 / MAX_BPM) & (iois < 60.0 / MIN_BPM)]
    if iois.size == 0:
        return None
    median_ioi = float(np.median(iois))
    bpm = 60.0 / median_ioi
    # grid_stability: how tightly the inter-beat-intervals cluster
    # around the median, normalized to roughly [0, 1].
    relative_dev = np.abs(iois - median_ioi) / median_ioi
    grid_stability = float(np.clip(1.0 - np.mean(relative_dev) * 4.0, 0.0, 1.0))
    return TempoResult(bpm=round(bpm, 2), grid_stability=grid_stability, beat_times=beat_times)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _pick_peaks(activation: np.ndarray, min_distance_frames: int, threshold: float = 0.3) -> np.ndarray:
    peaks = []
    last_peak = -min_distance_frames
    for i in range(1, len(activation) - 1):
        if activation[i] < threshold:
            continue
        if activation[i] >= activation[i - 1] and activation[i] >= activation[i + 1]:
            if i - last_peak >= min_distance_frames:
                peaks.append(i)
                last_peak = i
    return np.array(peaks, dtype=np.int64)


def _build_hann_window() -> np.ndarray:
    return np.hanning(N_FFT).astype(np.float32)


def _build_mel_filterbank() -> np.ndarray:
    return librosa.filters.mel(
        sr=SR, n_fft=N_FFT, n_mels=N_MELS, fmin=FMIN, fmax=FMAX
    ).astype(np.float32)
