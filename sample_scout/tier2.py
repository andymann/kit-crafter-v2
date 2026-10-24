"""Tier-2 (ONNX) analysis pass: runs the bundled key/tempo models over
already-scanned samples and folds the results back in with the same
COALESCE-based priority rules used by the original (recovered verbatim
for the tempo side; mirrored symmetrically for key, matching the
``key_name = COALESCE(key_tag, key_cnn)`` rule already confirmed in the
scan-time upsert).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from .analysis.key_cnn import KeyAnalyzer
from .analysis.tempo_cnn import TempoAnalyzer

KEY_VERSION = "key-cnn-1"
TEMPO_VERSION = "beat-this-small0-1"


def _load_mono(path: Path, max_seconds: float = 60.0) -> Optional[tuple[np.ndarray, int]]:
    try:
        info = sf.info(str(path))
        data, sr = sf.read(
            str(path), always_2d=True,
            frames=int(max_seconds * info.samplerate),
        )
    except Exception:
        return None
    return data.mean(axis=1).astype(np.float32), sr


class Tier2Analyzer:
    def __init__(self, resources_dir: Path):
        self.resources_dir = resources_dir
        self._key_analyzer: Optional[KeyAnalyzer] = None
        self._tempo_analyzer: Optional[TempoAnalyzer] = None

    @property
    def key_analyzer(self) -> KeyAnalyzer:
        if self._key_analyzer is None:
            self._key_analyzer = KeyAnalyzer(self.resources_dir)
        return self._key_analyzer

    @property
    def tempo_analyzer(self) -> TempoAnalyzer:
        if self._tempo_analyzer is None:
            self._tempo_analyzer = TempoAnalyzer(self.resources_dir)
        return self._tempo_analyzer

    def analyze_sample(self, conn: sqlite3.Connection, path: str) -> dict:
        loaded = _load_mono(Path(path))
        if loaded is None:
            return {"path": path, "ok": False, "reason": "unreadable"}
        mono, sr = loaded
        result: dict = {"path": path, "ok": True}

        tempo_result = self.tempo_analyzer.detect(mono, sr)
        if tempo_result is not None:
            conn.execute(
                """
                UPDATE samples SET
                    bpm_beatthis = :bpm, grid_stability = :grid_stability,
                    bpm_confidence = :grid_stability, bpm_version = :version,
                    bpm = COALESCE(bpm_tag, bpm_filename, :bpm, bpm_acf)
                WHERE path = :path
                """,
                {
                    "bpm": tempo_result.bpm,
                    "grid_stability": tempo_result.grid_stability,
                    "version": TEMPO_VERSION,
                    "path": path,
                },
            )
            result["bpm_beatthis"] = tempo_result.bpm
            result["grid_stability"] = tempo_result.grid_stability

        key_result = self.key_analyzer.detect(mono, sr)
        if key_result is not None:
            conn.execute(
                """
                UPDATE samples SET
                    key_cnn = :key_cnn, key_cnn_numerical = :key_cnn_numerical,
                    key_confidence = :confidence, key_clarity = :clarity,
                    key_version = :version,
                    key_name = COALESCE(key_tag, :key_cnn),
                    key_numerical = COALESCE(
                        CASE WHEN key_tag IS NOT NULL THEN key_numerical END,
                        :key_cnn_numerical
                    )
                WHERE path = :path
                """,
                {
                    "key_cnn": key_result.key_name,
                    "key_cnn_numerical": key_result.key_numerical,
                    "confidence": key_result.confidence,
                    "clarity": key_result.clarity,
                    "version": KEY_VERSION,
                    "path": path,
                },
            )
            result["key_cnn"] = key_result.key_name
            result["key_cnn_numerical"] = key_result.key_numerical

        conn.commit()
        return result

    def analyze_pending(self, conn: sqlite3.Connection, limit: Optional[int] = None) -> list[dict]:
        query = (
            "SELECT path FROM samples WHERE status = 'normal' "
            "AND (bpm_beatthis IS NULL OR key_cnn IS NULL)"
        )
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = conn.execute(query).fetchall()
        return [self.analyze_sample(conn, row["path"]) for row in rows]
