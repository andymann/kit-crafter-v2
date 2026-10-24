"""Tier-1 fast tempo detection: onset-envelope autocorrelation.

Matches the shape of the original's ``autocorrelation`` module, whose
mangled Rust symbols are ``detect_acf_tempo``, ``score_candidates``
(operating on a ``Scored`` struct) and ``onset_phase_check`` (operating
on a ``PhasedOnset`` struct) — i.e.: build an onset envelope, find
candidate periods via autocorrelation, score each candidate, then use
the actual onset times ("phase") to disambiguate harmonically-related
candidates (half/double-tempo confusion) and reward tempos whose grid
the onsets actually line up with.

No ONNX model is involved here; this is the always-available fallback
used when Tier 2 hasn't run yet (or for files too short/quiet for it),
hence it sits last in the ``bpm`` COALESCE chain.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import librosa

MIN_BPM = 60.0
MAX_BPM = 200.0
SR = 22050
HOP_LENGTH = 512


@dataclass
class BpmCandidate:
    bpm: float
    score: float


def _onset_envelope(y: np.ndarray, sr: int) -> np.ndarray:
    return librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP_LENGTH)


def _autocorrelate(envelope: np.ndarray) -> np.ndarray:
    envelope = envelope - envelope.mean()
    n = len(envelope)
    if n < 2:
        return np.zeros(1)
    fft_size = int(2 ** np.ceil(np.log2(2 * n)))
    spec = np.fft.rfft(envelope, n=fft_size)
    acf = np.fft.irfft(spec * np.conj(spec))[:n]
    return acf


def score_candidates(acf: np.ndarray, sr: int, hop_length: int) -> List[BpmCandidate]:
    fps = sr / hop_length
    min_lag = int(round(fps * 60.0 / MAX_BPM))
    max_lag = int(round(fps * 60.0 / MIN_BPM))
    max_lag = min(max_lag, len(acf) - 1)
    if max_lag <= min_lag:
        return []
    candidates: List[BpmCandidate] = []
    window = acf[min_lag:max_lag + 1]
    if window.max(initial=0) <= 0:
        return []
    peak_idx = np.argpartition(-window, min(10, len(window) - 1))[:10]
    for idx in peak_idx:
        lag = min_lag + idx
        if lag <= 0:
            continue
        bpm = 60.0 * fps / lag
        score = float(window[idx])
        candidates.append(BpmCandidate(bpm=bpm, score=score))
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def onset_phase_check(
    onset_times: np.ndarray, candidate: BpmCandidate
) -> float:
    """Reward a candidate BPM whose implied beat grid the actual onsets
    line up with (checked at several phase offsets), and lightly
    penalize candidates whose half/double-tempo sibling fits better —
    a standard octave-error correction for onset-autocorrelation tempo
    estimators.
    """
    if len(onset_times) == 0 or candidate.bpm <= 0:
        return candidate.score
    period = 60.0 / candidate.bpm
    best_alignment = 0.0
    for phase_frac in np.linspace(0, 1, 8, endpoint=False):
        phase = phase_frac * period
        residual = np.abs(((onset_times - phase) % period) - period / 2) - period / 2
        alignment = float(np.mean(np.exp(-(residual ** 2) / (2 * (0.04 ** 2)))))
        best_alignment = max(best_alignment, alignment)
    return candidate.score * (0.5 + best_alignment)


def detect_acf_tempo(y: np.ndarray, sr: int) -> Optional[BpmCandidate]:
    if y.size == 0:
        return None
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
        sr = SR
    envelope = _onset_envelope(y, sr)
    if envelope.size < 4:
        return None
    acf = _autocorrelate(envelope)
    candidates = score_candidates(acf, sr, HOP_LENGTH)
    if not candidates:
        return None

    onset_frames = librosa.onset.onset_detect(
        onset_envelope=envelope, sr=sr, hop_length=HOP_LENGTH
    )
    onset_times = librosa.frames_to_time(
        onset_frames, sr=sr, hop_length=HOP_LENGTH
    )

    rescored = [
        BpmCandidate(bpm=c.bpm, score=onset_phase_check(onset_times, c))
        for c in candidates
    ]
    rescored.sort(key=lambda c: c.score, reverse=True)
    best = rescored[0]
    total = sum(c.score for c in rescored) or 1.0
    confidence = best.score / total
    return BpmCandidate(bpm=round(best.bpm, 2), score=confidence)
