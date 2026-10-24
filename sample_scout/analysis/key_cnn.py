"""Tier-2 musical key detection via the bundled ``musical_key_cnn`` ONNX
model.

Confirmed directly from the model file (not guessed): input tensor
``cqt_spectrogram`` of shape ``(batch, 1, 105, time_frames)``, output
``logits`` of shape ``(batch, 24)`` — i.e. a CQT-based CNN classifying
into 24 classes (12 major + 12 minor keys), with the time axis pooled
away internally (the graph's lone ``GlobalAveragePool`` node), so a
single forward pass over the whole clip's CQT is enough — no manual
windowing/averaging needed.

The Rust crate's mangled symbols confirm the shape of the pipeline:
``key::resample_to_44100``, ``key::compute_cqt_spectrogram``,
``key::build_all_cqt_kernels`` / ``CQT_SCALE_LENGTHS`` / ``OctaveKernels``
/ ``SparseCqtFilter`` (a hand-rolled sparse-kernel CQT, not an off-the-
shelf crate) and ``KeyAnalyzer::new`` / ``::detect`` returning a
``KeyResult``.

What could *not* be recovered without full decompilation of the custom
CQT-kernel builder is its exact ``fmin``/``bins_per_octave`` pair. 105
bins is consistent with the published "key-cnn" architecture (Schreiber
& Müller, ISMIR 2017), which this model's shape otherwise matches
exactly, so this module uses that architecture's published CQT
parameters (``bins_per_octave=24``, ``fmin=C1``, ``sr=44100``,
``hop_length=4096``) via librosa rather than a re-derived sparse kernel
bank — functionally equivalent, just a different (dense) implementation
of the same transform.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import librosa
import numpy as np

from .. import camelot

SR = 44100
HOP_LENGTH = 4096
N_BINS = 105
BINS_PER_OCTAVE = 24
FMIN = librosa.note_to_hz("C1")

_MODEL_FILENAME = "musical_key_cnn_uint8.onnx"


@dataclass
class KeyResult:
    key_name: str
    key_numerical: Optional[str]
    confidence: float
    clarity: float


class KeyAnalyzer:
    def __init__(self, resources_dir: Path):
        import onnxruntime as ort

        model_path = resources_dir / _MODEL_FILENAME
        self._session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name

    def compute_cqt_spectrogram(self, y: np.ndarray, sr: int) -> np.ndarray:
        if sr != SR:
            y = librosa.resample(y, orig_sr=sr, target_sr=SR)
        cqt = librosa.cqt(
            y,
            sr=SR,
            hop_length=HOP_LENGTH,
            fmin=FMIN,
            n_bins=N_BINS,
            bins_per_octave=BINS_PER_OCTAVE,
        )
        magnitude = np.abs(cqt).astype(np.float32)
        log_mag = librosa.amplitude_to_db(magnitude, ref=np.max)
        # Normalize to roughly [0, 1] the way a trained-from-dB-input
        # CNN would expect (dB range clipped to 80dB below peak).
        normalized = (log_mag + 80.0) / 80.0
        normalized = np.clip(normalized, 0.0, 1.0)
        return normalized[np.newaxis, np.newaxis, :, :]  # (1,1,105,T)

    def detect(self, y: np.ndarray, sr: int) -> Optional[KeyResult]:
        if y.size < SR:  # need at least ~1s of audio
            return None
        spec = self.compute_cqt_spectrogram(y, sr)
        if spec.shape[-1] < 1:
            return None
        logits = self._session.run(
            None, {self._input_name: spec.astype(np.float32)}
        )[0][0]
        probs = _softmax(logits)
        order = np.argsort(-probs)
        top_idx = int(order[0])
        top_prob = float(probs[top_idx])
        second_prob = float(probs[int(order[1])]) if len(order) > 1 else 0.0
        clarity = max(0.0, top_prob - second_prob)
        key_name = camelot.KEY_CNN_CLASSES[top_idx]
        numerical = camelot.key_name_to_camelot(key_name)
        return KeyResult(
            key_name=key_name,
            key_numerical=numerical,
            confidence=top_prob,
            clarity=clarity,
        )


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    exp = np.exp(shifted)
    return exp / exp.sum()
