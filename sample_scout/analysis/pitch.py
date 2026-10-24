"""Tier-1 pitch detection: pYIN.

The original exposes ``pitch::detect_pitch`` calling ``pitch::run_pyin``
— i.e. the probabilistic YIN algorithm (Mauch & Dixon, 2014). We reuse
librosa's implementation of the same algorithm (``librosa.pyin``)
rather than re-deriving its Viterbi/HMM internals from assembly, since
the algorithm is the published reference, not bespoke logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import librosa
import numpy as np

FMIN = librosa.note_to_hz("C2")
FMAX = librosa.note_to_hz("C7")


@dataclass
class PitchResult:
    note: str
    freq: float
    cents: float
    confidence: float


def detect_pitch(y: np.ndarray, sr: int) -> Optional[PitchResult]:
    return run_pyin(y, sr)


def run_pyin(y: np.ndarray, sr: int) -> Optional[PitchResult]:
    if y.size < sr // 10:
        return None
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y, fmin=FMIN, fmax=FMAX, sr=sr
    )
    voiced = f0[voiced_flag]
    probs = voiced_prob[voiced_flag]
    if voiced.size == 0:
        return None
    # Weighted average of voiced frames, matching a single representative
    # pitch for an (often short, single-note) sample.
    freq = float(np.average(voiced, weights=probs))
    confidence = float(np.mean(probs))
    midi = 69 + 12 * np.log2(freq / 440.0)
    nearest_midi = int(round(midi))
    cents = float((midi - nearest_midi) * 100)
    note = librosa.midi_to_note(nearest_midi, unicode=False)
    return PitchResult(note=note, freq=freq, cents=cents, confidence=confidence)
