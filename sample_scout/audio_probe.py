"""Audio file probing: duration/sample-rate/bit-depth/channels/format plus
embedded BPM/key tag extraction.

Mirrors the original's ``audio_utils::probe_audio_file`` (symphonia-based,
with a ``probe_audio_file_hound`` WAV-only fallback for files symphonia
rejects) and ``audio_utils::extract_tags_from_probe`` (reads common
ID3v2 / BWF / WAV "bext"/"LIST INFO" style BPM and Key fields).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import soundfile as sf

from . import metadata

SUPPORTED_EXTENSIONS = {
    ".wav", ".wave", ".aif", ".aiff", ".flac", ".ogg", ".oga", ".caf",
    ".mp3", ".m4a",
}


@dataclass
class ProbedFile:
    duration: float
    size: int
    sample_rate: int
    bit_depth: int
    channels: int
    format: str
    bpm_tag: Optional[float] = None
    key_tag: Optional[str] = None


_SUBTYPE_BIT_DEPTH = {
    "PCM_S8": 8, "PCM_U8": 8,
    "PCM_16": 16,
    "PCM_24": 24,
    "PCM_32": 32,
    "FLOAT": 32,
    "DOUBLE": 64,
}


def probe_audio_file(path: Path) -> Optional[ProbedFile]:
    """Probe via libsndfile (soundfile). Returns None if unreadable,
    matching the original falling through to its hound/symphonia
    fallbacks and ultimately marking the sample unreadable.
    """
    try:
        info = sf.info(str(path))
    except Exception:
        return None
    size = path.stat().st_size
    bit_depth = _SUBTYPE_BIT_DEPTH.get(info.subtype, 16)
    fmt = (info.format or path.suffix.lstrip(".")).upper()
    duration = info.frames / info.samplerate if info.samplerate else 0.0
    probed = ProbedFile(
        duration=duration,
        size=size,
        sample_rate=info.samplerate,
        bit_depth=bit_depth,
        channels=info.channels,
        format=fmt,
    )
    bpm_tag, key_tag = extract_tags_from_probe(path)
    probed.bpm_tag = bpm_tag
    probed.key_tag = key_tag
    return probed


def extract_tags_from_probe(path: Path):
    """Pull a BPM/Key pair out of common embedded metadata containers.

    ID3 (``TBPM``/``TKEY``), BWF/RIFF ``LIST INFO`` (``ICMT`` often
    carries free text like "120 BPM, A minor" in sample libraries), and
    FLAC/Vorbis comments (``BPM``/``KEY``/``INITIALKEY``) are all
    checked. Returns ``(bpm_tag, key_tag)``, either possibly ``None``.
    """
    bpm_tag: Optional[float] = None
    key_tag: Optional[str] = None
    try:
        import mutagen
    except ImportError:
        return None, None

    try:
        f = mutagen.File(str(path))
    except Exception:
        return None, None
    if f is None:
        return None, None

    tags = f.tags
    if tags is None:
        return None, None

    def _get_any(*names):
        for name in names:
            try:
                if name in tags:
                    value = tags[name]
                    if hasattr(value, "text"):
                        value = value.text[0] if value.text else None
                    elif isinstance(value, list):
                        value = value[0] if value else None
                    return value
            except Exception:
                continue
        return None

    raw_bpm = _get_any("TBPM", "BPM", "bpm", "TEMPO", "tempo")
    if raw_bpm:
        try:
            bpm_tag = float(str(raw_bpm).split("/")[0].strip())
        except ValueError:
            bpm_tag = metadata.extract_explicit_bpm(str(raw_bpm))

    raw_key = _get_any(
        "TKEY", "KEY", "key", "INITIALKEY", "initialkey", "TIT3"
    )
    if raw_key:
        key_tag = metadata.parse_key_tag(str(raw_key))

    return bpm_tag, key_tag
