"""Command-line front end.

The original ships a Tauri (Rust + native webview) desktop app whose UI
talks to the Rust backend over ~90 IPC "commands" (``scan``, ``browse``,
``create_set``, ``export_single_item``, ...) recovered from the
binary's mangled symbol table. Reproducing the exact native webview UI
pixel-for-pixel is out of scope for this recreation (it would require
decompiling/recompiling the bundled, presumably-compressed frontend
JS bundle, not the backend logic this skill is for); this CLI exposes
the same underlying operations instead, one subcommand per IPC command
family, backed by the same SQLite schema and processing pipeline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db, export, scanner, tier2

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
DEFAULT_DB_PATH = Path.home() / ".sample-scout-py" / "database.db"


def cmd_init(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    db.initialize_database(conn)
    print(f"Initialized database at {args.db}")


def cmd_scan(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    db.initialize_database(conn)
    stats = scanner.scan_folder(conn, Path(args.folder))
    print(json.dumps(stats, indent=2))


def cmd_analyze(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    db.initialize_database(conn)
    analyzer = tier2.Tier2Analyzer(RESOURCES_DIR)
    results = analyzer.analyze_pending(conn, limit=args.limit)
    print(json.dumps(results, indent=2))


def cmd_search(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    like = f"%{args.query}%"
    rows = conn.execute(
        "SELECT id, name, path, bpm, key_name, key_numerical, duration "
        "FROM samples WHERE status = 'normal' AND name LIKE ?1 ORDER BY name",
        (like,),
    ).fetchall()
    for row in rows:
        print(
            f"{row['id']:>5} {row['name']:<40} bpm={row['bpm']} "
            f"key={row['key_name']} ({row['key_numerical']}) "
            f"{row['duration']:.2f}s"
        )


def cmd_tags(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    db.initialize_database(conn)
    rows = conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
    for row in rows:
        print(row["name"])


def cmd_tag_add(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?1)", (args.tag.lower(),))
    tag_id = conn.execute(
        "SELECT id FROM tags WHERE name = ?1", (args.tag.lower(),)
    ).fetchone()["id"]
    conn.execute(
        "INSERT OR IGNORE INTO sample_tags (sample_id, tag_id) VALUES (?1, ?2)",
        (args.sample_id, tag_id),
    )
    conn.commit()
    print(f"Tagged sample {args.sample_id} with '{args.tag}'")


def cmd_sets(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    db.initialize_database(conn)
    rows = conn.execute(
        """
        SELECT s.id, s.name,
               (SELECT COUNT(*) FROM set_samples ss WHERE ss.set_id = s.id) AS count
        FROM sets s ORDER BY s.name
        """
    ).fetchall()
    for row in rows:
        print(f"{row['id']:>3} {row['name']:<30} {row['count']} samples")


def cmd_create_set(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    conn.execute("INSERT INTO sets (name) VALUES (?1)", (args.name,))
    conn.commit()
    print(f"Created set '{args.name}'")


def cmd_add_to_set(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    position = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM set_samples WHERE set_id = ?1",
        (args.set_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO set_samples (set_id, sample_id, position) VALUES (?1, ?2, ?3)",
        (args.set_id, args.sample_id, position),
    )
    conn.commit()
    print(f"Added sample {args.sample_id} to set {args.set_id}")


def cmd_export(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    row = conn.execute("SELECT id, name FROM sets WHERE id = ?1", (args.set_id,)).fetchone()
    if row is None:
        print(f"No such set: {args.set_id}", file=sys.stderr)
        sys.exit(1)
    sample_rows = conn.execute(
        """
        SELECT sam.path, ss.display_name
        FROM set_samples ss
        JOIN samples sam ON sam.id = ss.sample_id
        WHERE ss.set_id = ?1
        ORDER BY ss.position
        """,
        (args.set_id,),
    ).fetchall()
    items = [
        export.ExportSourceItem(
            source_path=Path(r["path"]), display_name=r["display_name"]
        )
        for r in sample_rows
    ]
    preset = export.ExportPreset(
        name=args.preset_name,
        convert_to_mono=args.mono,
        mono_mode=args.mono_mode,
        normalize=args.normalize,
        normalize_ceiling=args.normalize_ceiling,
        sample_rate_enabled=args.sample_rate is not None,
        sample_rate_target=args.sample_rate or 44100,
        bit_depth_enabled=args.bit_depth is not None,
        bit_depth_target=args.bit_depth or 16,
        generate_manifest=args.manifest,
        legacy_wav=args.legacy_wav,
        append_cue=args.cue,
    )
    destination = Path(args.destination) if args.destination else export.default_export_destination() / row["name"]
    result = export.start_export(items, destination, preset, set_name=row["name"])
    print(f"Exported {result.copied} file(s) to {result.destination}")
    for path, reason in result.failed:
        print(f"  FAILED {path}: {reason}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sample-scout", description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create/upgrade the database").set_defaults(func=cmd_init)

    p = sub.add_parser("scan", help="Recursively scan a folder into the library")
    p.add_argument("folder")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("analyze", help="Run Tier-2 ONNX key/tempo analysis on pending samples")
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("search", help="Search samples by name")
    p.add_argument("query")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("tags", help="List all tags")
    p.set_defaults(func=cmd_tags)

    p = sub.add_parser("tag", help="Tag a sample")
    p.add_argument("sample_id", type=int)
    p.add_argument("tag")
    p.set_defaults(func=cmd_tag_add)

    p = sub.add_parser("sets", help="List sets")
    p.set_defaults(func=cmd_sets)

    p = sub.add_parser("create-set", help="Create a new set")
    p.add_argument("name")
    p.set_defaults(func=cmd_create_set)

    p = sub.add_parser("add-to-set", help="Add a sample to a set")
    p.add_argument("set_id", type=int)
    p.add_argument("sample_id", type=int)
    p.set_defaults(func=cmd_add_to_set)

    p = sub.add_parser("export", help="Export a set using an export preset")
    p.add_argument("set_id", type=int)
    p.add_argument("--preset-name", default="Default")
    p.add_argument("--destination", default=None)
    p.add_argument("--mono", action="store_true")
    p.add_argument("--mono-mode", choices=db.MONO_MODES, default="sum")
    p.add_argument("--normalize", action="store_true")
    p.add_argument("--normalize-ceiling", type=float, default=-0.3)
    p.add_argument("--sample-rate", type=int, default=None)
    p.add_argument("--bit-depth", type=int, choices=(16, 24, 32), default=None)
    p.add_argument("--manifest", action="store_true")
    p.add_argument("--legacy-wav", action="store_true")
    p.add_argument("--cue", action="store_true")
    p.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
