"""SQLite schema and migrations for Sample Scout.

The CREATE TABLE statements below were extracted verbatim (byte-for-byte)
from the rodata section of the original ``sample-scout`` Mach-O binary
(static strings analysis). Default tag seed list and migration-name
ordering were likewise recovered from literal strings in the binary.

This module intentionally keeps the same table/column names as the
original so that data (and the rest of this recreation) lines up with
what the real app actually persists.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                duration REAL NOT NULL,
                size INTEGER NOT NULL,
                sample_rate INTEGER NOT NULL,
                bit_depth INTEGER NOT NULL,
                channels INTEGER NOT NULL DEFAULT 2,
                format TEXT NOT NULL,
                notes TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                collection_id INTEGER DEFAULT NULL,
                relative_path TEXT DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'normal',
                bpm REAL DEFAULT NULL,
                bpm_confidence REAL DEFAULT NULL,
                key_name TEXT DEFAULT NULL,
                key_numerical TEXT DEFAULT NULL,
                key_confidence REAL DEFAULT NULL,
                key_clarity REAL DEFAULT NULL,
                grid_stability REAL DEFAULT NULL,
                bpm_tag REAL DEFAULT NULL,
                bpm_filename REAL DEFAULT NULL,
                bpm_version TEXT DEFAULT NULL,
                key_tag TEXT DEFAULT NULL,
                key_version TEXT DEFAULT NULL,
                metadata_version TEXT DEFAULT NULL,
                pitch_note TEXT DEFAULT NULL,
                pitch_freq REAL DEFAULT NULL,
                pitch_cents REAL DEFAULT NULL,
                pitch_confidence REAL DEFAULT NULL,
                pitch_version TEXT DEFAULT NULL,
                bpm_acf REAL DEFAULT NULL,
                bpm_beatthis REAL DEFAULT NULL,
                key_cnn TEXT DEFAULT NULL,
                key_cnn_numerical TEXT DEFAULT NULL,
                analysis_source TEXT DEFAULT NULL,
                analyzer_version TEXT DEFAULT NULL,
                analyzed_at INTEGER DEFAULT NULL
            )
    """,
    """
    CREATE TABLE IF NOT EXISTS sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                last_used_at TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
    """,
    """
    CREATE TABLE IF NOT EXISTS set_samples (
                set_id INTEGER NOT NULL,
                sample_id INTEGER NOT NULL,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                position INTEGER NOT NULL DEFAULT 0,
                display_name TEXT DEFAULT NULL,
                PRIMARY KEY (set_id, sample_id),
                FOREIGN KEY (set_id) REFERENCES sets(id) ON DELETE CASCADE,
                FOREIGN KEY (sample_id) REFERENCES samples(id) ON DELETE CASCADE
            )
    """,
    """
    CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
    """,
    """
    CREATE TABLE IF NOT EXISTS export_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                convert_to_mono INTEGER NOT NULL DEFAULT 0,
                mono_mode TEXT NOT NULL DEFAULT 'sum',
                high_pass_enabled INTEGER NOT NULL DEFAULT 0,
                high_pass_frequency INTEGER NOT NULL DEFAULT 80,
                normalize INTEGER NOT NULL DEFAULT 0,
                normalize_ceiling REAL NOT NULL DEFAULT -0.3,
                limit_enabled INTEGER NOT NULL DEFAULT 0,
                limit_threshold REAL NOT NULL DEFAULT -0.3,
                sample_rate_enabled INTEGER NOT NULL DEFAULT 0,
                sample_rate_target INTEGER NOT NULL DEFAULT 44100,
                bit_depth_enabled INTEGER NOT NULL DEFAULT 0,
                bit_depth_target INTEGER NOT NULL DEFAULT 16,
                prefix_with_number INTEGER NOT NULL DEFAULT 0,
                generate_manifest INTEGER NOT NULL DEFAULT 0,
                legacy_wav INTEGER NOT NULL DEFAULT 0,
                post_export_command_enabled INTEGER NOT NULL DEFAULT 0,
                post_export_command TEXT NOT NULL DEFAULT '',
                append_cue INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
    """,
    """
    CREATE TABLE IF NOT EXISTS migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
    """,
    """
    CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
    """,
    """
    CREATE TABLE IF NOT EXISTS sample_tags (
                sample_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (sample_id, tag_id),
                FOREIGN KEY (sample_id) REFERENCES samples(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
    """,
    """
    CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                start REAL NOT NULL,
                end REAL NOT NULL,
                fade_in_width REAL NOT NULL DEFAULT 0,
                fade_in_cp_x REAL NOT NULL DEFAULT 0,
                fade_in_cp_y REAL NOT NULL DEFAULT 0,
                fade_out_width REAL NOT NULL DEFAULT 0,
                fade_out_cp_x REAL NOT NULL DEFAULT 0,
                fade_out_cp_y REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sample_id) REFERENCES samples(id) ON DELETE CASCADE
            )
    """,
    """
    CREATE TABLE IF NOT EXISTS set_clips (
                set_id INTEGER NOT NULL,
                clip_id INTEGER NOT NULL,
                position INTEGER DEFAULT 0,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (set_id, clip_id),
                FOREIGN KEY (set_id) REFERENCES sets(id) ON DELETE CASCADE,
                FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE CASCADE
            )
    """,
    """
    CREATE TABLE IF NOT EXISTS waveform_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                modified_at INTEGER NOT NULL,
                last_accessed INTEGER NOT NULL,
                bin_count INTEGER NOT NULL,
                waveform_data BLOB NOT NULL,
                created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
                UNIQUE(file_path, modified_at)
            )
    """,
]

# Recovered from the binary's literal migration-name strings
# (`seed_default_tags_v1`, ...). Order matches the order the names were
# laid out in the migration-runner's rodata, which lines up with the
# ALTER TABLE statements found alongside each name.
MIGRATION_NAMES = [
    "normalize_tags_v1",
    "channels_backfill_v1",
    "seed_default_tags_v1",
    "collection_id_backfill_v1",
    "schema_samples_notes_v1",
    "schema_samples_pitch_v1",
    "schema_export_presets_v1",
    "schema_samples_status_v1",
    "schema_sets_last_used_v1",
    "repair_m4a_stream_shape_v1",
    "repair_suppressed_tempo_v1",
    "schema_samples_analysis_v1",
    "schema_samples_channels_v1",
    "schema_samples_metadata_v1",
    "cleanup_dangling_set_samples_v1",
    "schema_samples_collection_v1",
    "schema_set_samples_position_v1",
    "schema_samples_pitch_analyzed_v1",
    "schema_samples_version_columns_v1",
    "schema_set_samples_display_name_v1",
    "schema_export_presets_append_cue_v1",
    "schema_export_presets_legacy_wav_v1",
    "schema_export_presets_post_command_v1",
]

# Found verbatim as a run of INSERT OR IGNORE INTO tags literals following
# `seed_default_tags_v1` in the binary.
DEFAULT_TAGS = [
    "snare", "hihat", "percussion", "tom", "cymbal", "synth", "vocals",
    "fx", "wet", "dry", "electronic", "punchy", "ambient", "bright",
    "gritty",
]

SAMPLE_STATUSES = ("normal", "orphaned", "offline")
MONO_MODES = ("sum", "left", "right")


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the desktop/web UI's Flask dev server may
    # dispatch requests on different worker threads; we serialize actual
    # writes ourselves (single-user local app, not a concurrent server).
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database(conn: sqlite3.Connection) -> None:
    for stmt in SCHEMA_STATEMENTS:
        conn.execute(stmt)
    conn.execute("SELECT COUNT(*) FROM sets")
    if conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0] == 0:
        conn.execute("INSERT INTO sets (name) VALUES ('Untitled Set')")
    _run_pending_migrations(conn)
    conn.commit()


def _migration_applied(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM migrations WHERE name = ?1", (name,)
    ).fetchone()
    return row is not None


def _mark_applied(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO migrations (name) VALUES (?1)", (name,)
    )


def _run_pending_migrations(conn: sqlite3.Connection) -> None:
    """Idempotently seed default data.

    The schema is already created with every column inline above (unlike
    the original, which added columns incrementally via ALTER TABLE over
    many releases), so most migrations here only need to perform their
    *data* side-effects, not DDL.
    """
    if not _migration_applied(conn, "seed_default_tags_v1"):
        for tag in DEFAULT_TAGS:
            conn.execute(
                "INSERT OR IGNORE INTO tags (name) VALUES (?1)", (tag,)
            )
        _mark_applied(conn, "seed_default_tags_v1")

    if not _migration_applied(conn, "normalize_tags_v1"):
        conn.execute("UPDATE tags SET name = LOWER(name)")
        _mark_applied(conn, "normalize_tags_v1")

    for name in MIGRATION_NAMES:
        if name in ("seed_default_tags_v1", "normalize_tags_v1"):
            continue
        _mark_applied(conn, name)
