"""Recursive folder scan: probes every audio file, runs Tier-1 metadata
and (fast) analysis, and upserts the result into ``samples``.

The upsert mirrors the ``INSERT ... ON CONFLICT(path) DO UPDATE`` found
verbatim in the binary, including its exact column-priority semantics::

    bpm           = COALESCE(bpm_tag, bpm_filename, bpm_beatthis, bpm_acf)
    key_name      = COALESCE(key_tag, key_cnn)
    key_numerical = COALESCE(<camelot(key_tag)>, key_cnn_numerical)

i.e. an explicit tag/filename value always beats anything the analyzers
inferred, and a fresh scan never clobbers a key/key_cnn value that a
previous Tier-2 analysis pass already wrote for this path.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import soundfile as sf

from . import audio_probe, camelot, metadata
from .analysis import autocorrelation, pitch

METADATA_VERSION = "py-recreation-1"
BPM_VERSION = "acf-1"
PITCH_VERSION = "pyin-1"


def iter_audio_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in audio_probe.SUPPORTED_EXTENSIONS:
            yield path


def _load_mono_for_analysis(path: Path, max_seconds: float = 30.0) -> Optional[tuple[np.ndarray, int]]:
    try:
        data, sr = sf.read(str(path), always_2d=True, frames=int(max_seconds * sf.info(str(path)).samplerate))
    except Exception:
        return None
    mono = data.mean(axis=1).astype(np.float32)
    return mono, sr


def scan_file(conn: sqlite3.Connection, path: Path, collection_id: Optional[int] = None, relative_path: Optional[str] = None) -> bool:
    probed = audio_probe.probe_audio_file(path)
    if probed is None:
        return False

    filename_meta = metadata.parse_filename_metadata(path)
    key_tag = probed.key_tag or filename_meta.key_tag
    bpm_tag = probed.bpm_tag
    bpm_filename = filename_meta.bpm_filename

    bpm_acf = None
    pitch_note = pitch_freq = pitch_cents = pitch_confidence = None
    loaded = _load_mono_for_analysis(path)
    if loaded is not None:
        mono, sr = loaded
        acf_result = autocorrelation.detect_acf_tempo(mono, sr)
        if acf_result is not None:
            bpm_acf = acf_result.bpm
        pitch_result = pitch.detect_pitch(mono, sr)
        if pitch_result is not None:
            pitch_note = pitch_result.note
            pitch_freq = pitch_result.freq
            pitch_cents = pitch_result.cents
            pitch_confidence = pitch_result.confidence

    key_tag_camelot = camelot.key_name_to_camelot(key_tag) if key_tag else None

    conn.execute(
        """
        INSERT INTO samples (
            name, path, duration, size, sample_rate, bit_depth, channels,
            format, bpm, bpm_tag, bpm_filename, bpm_acf, bpm_version,
            key_name, key_tag, key_numerical, metadata_version,
            pitch_note, pitch_freq, pitch_cents, pitch_confidence,
            pitch_version, collection_id, relative_path, status
        ) VALUES (
            :name, :path, :duration, :size, :sample_rate, :bit_depth,
            :channels, :format, COALESCE(:bpm_tag, :bpm_filename, :bpm_acf),
            :bpm_tag, :bpm_filename, :bpm_acf, :bpm_version,
            :key_tag, :key_tag, :key_tag_camelot, :metadata_version,
            :pitch_note, :pitch_freq, :pitch_cents, :pitch_confidence,
            :pitch_version, :collection_id, :relative_path, 'normal'
        )
        ON CONFLICT(path) DO UPDATE SET
            name = :name,
            duration = :duration,
            size = :size,
            sample_rate = :sample_rate,
            bit_depth = :bit_depth,
            channels = :channels,
            format = :format,
            bpm_tag = :bpm_tag,
            bpm_filename = :bpm_filename,
            bpm_acf = :bpm_acf,
            bpm_version = :bpm_version,
            metadata_version = :metadata_version,
            bpm = COALESCE(:bpm_tag, :bpm_filename, bpm_beatthis, :bpm_acf),
            key_name = COALESCE(:key_tag, key_cnn),
            key_tag = :key_tag,
            key_numerical = COALESCE(:key_tag_camelot,
                CASE WHEN key_cnn IS NOT NULL THEN key_cnn_numerical END),
            pitch_note = :pitch_note,
            pitch_freq = :pitch_freq,
            pitch_cents = :pitch_cents,
            pitch_confidence = :pitch_confidence,
            pitch_version = :pitch_version,
            collection_id = :collection_id,
            relative_path = :relative_path,
            status = 'normal'
        """,
        {
            "name": path.name,
            "path": str(path),
            "duration": probed.duration,
            "size": probed.size,
            "sample_rate": probed.sample_rate,
            "bit_depth": probed.bit_depth,
            "channels": probed.channels,
            "format": probed.format,
            "bpm_tag": bpm_tag,
            "bpm_filename": bpm_filename,
            "bpm_acf": bpm_acf,
            "bpm_version": BPM_VERSION if bpm_acf is not None else None,
            "key_tag": key_tag,
            "key_tag_camelot": key_tag_camelot,
            "metadata_version": METADATA_VERSION,
            "pitch_note": pitch_note,
            "pitch_freq": pitch_freq,
            "pitch_cents": pitch_cents,
            "pitch_confidence": pitch_confidence,
            "pitch_version": PITCH_VERSION if pitch_note is not None else None,
            "collection_id": collection_id,
            "relative_path": relative_path,
        },
    )
    return True


def scan_folder(conn: sqlite3.Connection, root: Path) -> dict:
    added = 0
    failed = 0
    for path in iter_audio_files(root):
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = None
        if scan_file(conn, path, relative_path=rel):
            added += 1
        else:
            failed += 1
    conn.commit()
    return {"total": added + failed, "copied": added, "failed": failed}
