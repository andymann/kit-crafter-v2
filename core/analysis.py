"""BPM / musical key / pitch analysis for samples.

This mirrors the feature set of commercial sample browsers (filename tag
parsing + analyzed fallback for BPM and key, plus single-note pitch
detection) using only classic, public-domain DSP and music-theory
techniques -- no bundled ML models or third-party trained weights.

Priority order for each field (same idea used by every sample browser
that supports filename tags):
    bpm: explicit filename tag  >  analyzed (onset autocorrelation)
    key: explicit filename tag  >  analyzed (chroma / key-profile correlation)
    pitch: always analyzed (autocorrelation pitch tracking)
"""
import os
import re
import threading
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import numpy as np

try:
    import soundfile as sf
    _SF = True
except ImportError:
    _SF = False

# ── Filename tag parsing ────────────────────────────────────────────────────

_TOKEN_SPLIT_RE = re.compile(r"[_\s\-.]+")
_KEY_TAG_RE = re.compile(r"^([A-G])([#b])?\s*(m(?:in(?:or)?)?|maj(?:or)?)?$", re.IGNORECASE)

_BPM_LABELED_RE = re.compile(r"bpm\s*[_\-]?\s*(\d{2,3})", re.IGNORECASE)
_RBPM_LABELED_RE = re.compile(r"(\d{2,3})\s*[_\-]?\s*bpm", re.IGNORECASE)
_TEMPO_LABELED_RE = re.compile(r"tempo\s*[_\-]?\s*(\d{2,3})", re.IGNORECASE)
_BARE_NUM_RE = re.compile(r"(?:^|[_\s\-.])(\d{2,3})(?:[_\s\-.]|$)")

_BPM_MIN, _BPM_MAX = 40, 220

_FLAT_TO_SHARP = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E"}


def parse_bpm_from_filename(name: str) -> Optional[float]:
    stem = os.path.splitext(name)[0]
    for pattern in (_BPM_LABELED_RE, _RBPM_LABELED_RE, _TEMPO_LABELED_RE):
        m = pattern.search(stem)
        if m:
            val = int(m.group(1))
            if _BPM_MIN <= val <= _BPM_MAX:
                return float(val)
    for m in _BARE_NUM_RE.finditer(stem):
        val = int(m.group(1))
        if _BPM_MIN <= val <= _BPM_MAX:
            return float(val)
    return None


def parse_key_from_filename(name: str) -> Optional[Tuple[str, str]]:
    """Returns (root_note, mode) e.g. ('C#', 'minor'), or None.

    The key regex allows internal whitespace between the note and the mode
    word (`\\s*`), so a tag split across two filename tokens -- "A_min",
    "F#_minor" -- is tried as a two-word phrase ("A min") before falling
    back to a single token, so the mode word isn't missed.
    """
    stem = os.path.splitext(name)[0]
    words = [w for w in _TOKEN_SPLIT_RE.split(stem) if w]
    for i in range(len(words)):
        for span in (2, 1):
            if i + span > len(words):
                continue
            candidate = " ".join(words[i:i + span])
            m = _KEY_TAG_RE.match(candidate)
            if not m:
                continue
            root = m.group(1).upper()
            accidental = m.group(2)
            mode_raw = (m.group(3) or "").lower()
            if accidental:
                root = root + ("#" if accidental == "#" else "b")
            root = _FLAT_TO_SHARP.get(root, root)
            mode = "major" if mode_raw.startswith("maj") else ("minor" if mode_raw else "major")
            return root, mode
    return None


# ── Camelot wheel (standard DJ-convention mapping, public domain) ──────────

CAMELOT_MAJOR = {
    "C": "8B", "G": "9B", "D": "10B", "A": "11B", "E": "12B", "B": "1B",
    "F#": "2B", "C#": "3B", "G#": "4B", "D#": "5B", "A#": "6B", "F": "7B",
}
CAMELOT_MINOR = {
    "A": "8A", "E": "9A", "B": "10A", "F#": "11A", "C#": "12A", "G#": "1A",
    "D#": "2A", "A#": "3A", "F": "4A", "C": "5A", "G": "6A", "D": "7A",
}

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Kessler key profiles (classic, widely-published tonal-hierarchy
# weights per semitone above the tonic; public domain).
_KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def freq_to_note(freq: Optional[float]) -> Tuple[Optional[str], Optional[float]]:
    if not freq or freq <= 0:
        return None, None
    midi = 69.0 + 12.0 * np.log2(freq / 440.0)
    midi_round = int(round(midi))
    cents = (midi - midi_round) * 100.0
    name = _NOTE_NAMES[midi_round % 12]
    octave = midi_round // 12 - 1
    return f"{name}{octave}", float(cents)


# ── DSP building blocks (pure numpy, no extra dependencies) ────────────────

def _autocorr_pitch_frame(frame: np.ndarray, sr: int, fmin: float, fmax: float):
    frame = frame.astype(np.float64) - frame.mean()
    n = len(frame)
    if n < 8:
        return None, 0.0
    spec = np.fft.rfft(frame, n=2 * n)
    acf = np.fft.irfft(spec * np.conj(spec))[:n]
    if acf[0] <= 0:
        return None, 0.0
    acf = acf / acf[0]
    min_lag = max(1, int(sr / fmax))
    max_lag = min(n - 1, int(sr / fmin))
    if max_lag <= min_lag:
        return None, 0.0
    seg = acf[min_lag:max_lag]
    peak_idx = int(np.argmax(seg))
    lag = min_lag + peak_idx
    conf = float(seg[peak_idx])
    return sr / lag, conf


def estimate_pitch_track(mono: np.ndarray, sr: int, frame_size: int = 2048, hop: int = 512,
                          fmin: float = 50.0, fmax: float = 1200.0, conf_thresh: float = 0.5):
    n = len(mono)
    if n < frame_size:
        if n < 8:
            return None, 0.0
        f, c = _autocorr_pitch_frame(mono, sr, fmin, fmax)
        return (f, c) if f and c >= conf_thresh else (None, c)

    freqs, confs = [], []
    for start in range(0, n - frame_size, hop):
        f, c = _autocorr_pitch_frame(mono[start:start + frame_size], sr, fmin, fmax)
        if f is not None and c >= conf_thresh:
            freqs.append(f)
            confs.append(c)
    if not freqs:
        return None, 0.0
    return float(np.median(freqs)), float(np.median(confs))


def _onset_envelope(mono: np.ndarray, sr: int, n_fft: int = 2048, hop: int = 512):
    n = len(mono)
    if n < n_fft + hop:
        return np.zeros(0), sr / hop
    window = np.hanning(n_fft)
    starts = range(0, n - n_fft, hop)
    frames = np.stack([mono[s:s + n_fft] * window for s in starts])
    spec = np.abs(np.fft.rfft(frames, axis=1))
    flux = np.diff(spec, axis=0)
    flux[flux < 0] = 0
    env = flux.sum(axis=1)
    env = env - env.min()
    return env, sr / hop


def _acf_tempo(env: np.ndarray, frame_rate: float, bpm_min: int = _BPM_MIN, bpm_max: int = _BPM_MAX,
               min_prominence: float = 6.0):
    """Autocorrelation-based tempo from an onset-flux envelope.

    `min_prominence` gates out sustained tones/chords/noise: a real rhythmic
    signal produces a sharp autocorrelation peak far above its surrounding
    lags, while non-percussive audio only produces a shallow, noisy bump.
    Empirically a genuine beat grid separates by >10x; sustained/non-rhythmic
    audio tops out around 3x, so 6x is a safe cutoff.
    """
    if len(env) < 4 or frame_rate <= 0:
        return None, 0.0
    env = env.astype(np.float64) - env.mean()
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    ac0 = ac[0] if ac[0] > 0 else 1.0
    min_lag = max(1, int(frame_rate * 60.0 / bpm_max))
    max_lag = min(len(ac) - 1, int(frame_rate * 60.0 / bpm_min))
    if max_lag <= min_lag:
        return None, 0.0
    seg = ac[min_lag:max_lag]
    if seg.max() <= 0:
        return None, 0.0
    peak_idx = int(np.argmax(seg))
    median = float(np.median(np.abs(seg))) + 1e-12
    prominence = float(seg[peak_idx]) / median
    if prominence < min_prominence:
        return None, 0.0
    lag = min_lag + peak_idx
    bpm = 60.0 * frame_rate / lag
    conf = float(seg[peak_idx] / ac0)
    return bpm, max(0.0, min(1.0, conf))


def _chroma(mono: np.ndarray, sr: int, n_fft: int = 4096, hop: int = 2048,
            fmin: float = 55.0, fmax: float = 5000.0):
    n = len(mono)
    if n < n_fft:
        padded = np.zeros(n_fft)
        padded[:n] = mono
        mono = padded
        n = n_fft

    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    valid = (freqs >= fmin) & (freqs <= fmax)
    pitch_class = np.full(len(freqs), -1, dtype=int)
    midi = 69.0 + 12.0 * np.log2(freqs[valid] / 440.0)
    pitch_class[valid] = np.mod(np.round(midi), 12).astype(int)

    mask = np.zeros((len(freqs), 12), dtype=np.float64)
    rows = np.where(pitch_class >= 0)[0]
    mask[rows, pitch_class[rows]] = 1.0

    window = np.hanning(n_fft)
    chroma = np.zeros(12)
    frame_count = 0
    for start in range(0, n - n_fft, hop):
        mag = np.abs(np.fft.rfft(mono[start:start + n_fft] * window))
        chroma += mag @ mask
        frame_count += 1
    if frame_count == 0:
        return None
    total = chroma.sum()
    return chroma / total if total > 0 else None


def detect_key_from_chroma(chroma: Optional[np.ndarray]) -> Tuple[Optional[str], Optional[str], float]:
    if chroma is None:
        return None, None, 0.0
    maj = _KK_MAJOR - _KK_MAJOR.mean()
    minr = _KK_MINOR - _KK_MINOR.mean()
    c = chroma - chroma.mean()
    c_norm = np.linalg.norm(c)
    if c_norm <= 0:
        return None, None, 0.0

    best_corr, best_root, best_mode = -2.0, 0, "major"
    for root in range(12):
        rotated = np.roll(c, -root)
        for mode, profile in (("major", maj), ("minor", minr)):
            denom = np.linalg.norm(profile) * c_norm
            corr = float(np.dot(rotated, profile) / denom) if denom > 0 else 0.0
            if corr > best_corr:
                best_corr, best_root, best_mode = corr, root, mode

    confidence = max(0.0, min(1.0, (best_corr + 1.0) / 2.0))
    return _NOTE_NAMES[best_root], best_mode, confidence


# ── Public result type + orchestration ──────────────────────────────────────

@dataclass
class AnalysisResult:
    bpm: Optional[float] = None
    bpm_source: str = ""          # "tag" | "analyzed" | ""
    bpm_confidence: Optional[float] = None

    key_name: Optional[str] = None     # e.g. "C#"
    key_mode: Optional[str] = None     # "major" | "minor"
    key_camelot: Optional[str] = None  # e.g. "3B"
    key_source: str = ""
    key_confidence: Optional[float] = None

    pitch_note: Optional[str] = None
    pitch_freq: Optional[float] = None
    pitch_cents: Optional[float] = None
    pitch_confidence: Optional[float] = None

    @property
    def key_display(self) -> Optional[str]:
        if not self.key_name:
            return None
        suffix = "m" if self.key_mode == "minor" else ""
        camelot = f" ({self.key_camelot})" if self.key_camelot else ""
        return f"{self.key_name}{suffix}{camelot}"


class Analyzer:
    """Stateful analyzer with a per-path result cache (mirrors AudioEngine's
    waveform cache)."""

    def __init__(self, max_analysis_seconds: float = 30.0):
        self._cache: dict = {}
        self._max_samples_factor = max_analysis_seconds

    def analyze(self, path: str) -> AnalysisResult:
        cached = self._cache.get(path)
        if cached is not None:
            return cached

        result = AnalysisResult()
        name = os.path.basename(path)
        tag_bpm = parse_bpm_from_filename(name)
        tag_key = parse_key_from_filename(name)

        mono, sr = self._load_mono(path)

        acf_bpm = acf_conf = None
        key_name = key_mode = None
        key_conf = 0.0
        freq = None
        pitch_conf = 0.0

        if mono is not None and len(mono) > 0 and sr:
            env, frate = _onset_envelope(mono, sr)
            if len(env):
                acf_bpm, acf_conf = _acf_tempo(env, frate)
            chroma = _chroma(mono, sr)
            key_name, key_mode, key_conf = detect_key_from_chroma(chroma)
            freq, pitch_conf = estimate_pitch_track(mono, sr)

        if tag_bpm is not None:
            result.bpm, result.bpm_source, result.bpm_confidence = tag_bpm, "tag", 1.0
        elif acf_bpm is not None:
            result.bpm = round(acf_bpm, 1)
            result.bpm_source = "analyzed"
            result.bpm_confidence = round(acf_conf, 3)

        if tag_key is not None:
            result.key_name, result.key_mode = tag_key
            result.key_source, result.key_confidence = "tag", 1.0
        elif key_name is not None:
            result.key_name, result.key_mode = key_name, key_mode
            result.key_source = "analyzed"
            result.key_confidence = round(key_conf, 3)

        if result.key_name:
            table = CAMELOT_MINOR if result.key_mode == "minor" else CAMELOT_MAJOR
            result.key_camelot = table.get(result.key_name)

        if freq:
            note, cents = freq_to_note(freq)
            result.pitch_freq = round(freq, 2)
            result.pitch_note = note
            result.pitch_cents = round(cents, 1) if cents is not None else None
            result.pitch_confidence = round(pitch_conf, 3)

        self._cache[path] = result
        return result

    def analyze_async(self, path: str, callback: Callable[[AnalysisResult], None]):
        def _worker():
            result = self.analyze(path)
            callback(result)

        threading.Thread(target=_worker, daemon=True).start()

    def clear_cache(self):
        self._cache.clear()

    def _load_mono(self, path: str):
        if not _SF:
            return None, 0
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
            mono = data.mean(axis=1)
            max_samples = int(sr * self._max_samples_factor)
            if len(mono) > max_samples:
                mono = mono[:max_samples]
            return mono, sr
        except Exception:
            return None, 0
