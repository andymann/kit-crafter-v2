"""Flask backend for the Sample Scout UI recreation.

This is the HTTP API the frontend (static/app.js) talks to. It wraps the
reverse-engineered engine in ``sample_scout/`` (db, scanner, metadata,
dsp, export, tier2) and adds live filesystem browsing, waveform-peak
extraction and audio streaming so the UI can faithfully mirror the real
app's "browse your actual folders, play/preview instantly" workflow
(seen in the real screenshots as ``Collections / Sound Ideas Series
6000 General / 6035`` breadcrumbs over a live file listing).
"""
from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

import numpy as np
import soundfile as sf
from flask import Flask, jsonify, request, send_file, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sample_scout import audio_probe, camelot, db, export, metadata, scanner, tier2  # noqa: E402
from sample_scout.analysis import autocorrelation, pitch  # noqa: E402

APP_ROOT = Path(__file__).resolve().parent
RESOURCES_DIR = APP_ROOT.parent / "resources"
DB_PATH = Path.home() / ".sample-scout-py" / "database.db"

app = Flask(__name__, static_folder=str(APP_ROOT / "static"), static_url_path="/static")

_conn = db.connect(DB_PATH)
db.initialize_database(_conn)
_tier2 = tier2.Tier2Analyzer(RESOURCES_DIR)

# "Active root" the browser pane is currently rooted at — the closest
# analogue to the original's "Collections" concept without needing a
# full collection-management UI.
_state = {"root": str(Path.home()), "active_set_id": 1}


# ---------------------------------------------------------------- pages

@app.route("/")
def index():
    return send_from_directory(APP_ROOT / "templates", "index.html")


@app.route("/api/meta")
def api_meta():
    return jsonify({"db_path": str(DB_PATH)})


# --------------------------------------------------------------- browse

def _folder_entry(path: Path) -> dict:
    return {"kind": "folder", "name": path.name, "path": str(path)}


def _file_entry(path: Path, index: int) -> dict | None:
    probed = audio_probe.probe_audio_file(path)
    if probed is None:
        return None
    row = _conn.execute(
        "SELECT id, bpm, key_name, key_numerical, key_confidence FROM samples WHERE path = ?1",
        (str(path),),
    ).fetchone()
    in_active_set = False
    if row is not None:
        member = _conn.execute(
            "SELECT 1 FROM set_samples WHERE set_id = ?1 AND sample_id = ?2",
            (_state["active_set_id"], row["id"]),
        ).fetchone()
        in_active_set = member is not None
    return {
        "kind": "file",
        "index": index,
        "name": path.name,
        "path": str(path),
        "duration": round(probed.duration, 2),
        "size": probed.size,
        "sample_id": row["id"] if row else None,
        "bpm": row["bpm"] if row else None,
        "key_name": row["key_name"] if row else None,
        "in_active_set": in_active_set,
    }


@app.route("/api/browse")
def api_browse():
    root = Path(request.args.get("path", _state["root"]))
    if not root.exists() or not root.is_dir():
        return jsonify({"error": f"not a directory: {root}"}), 400
    _state["root"] = str(root)

    folders, files = [], []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        return jsonify({"error": str(exc)}), 400

    index = 0
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            folders.append(_folder_entry(entry))
        elif entry.suffix.lower() in audio_probe.SUPPORTED_EXTENSIONS:
            file_entry = _file_entry(entry, index)
            if file_entry:
                files.append(file_entry)
                index += 1

    breadcrumbs = [{"name": p.name or str(p), "path": str(p)} for p in reversed([root, *root.parents])]
    breadcrumbs.reverse()
    return jsonify({
        "path": str(root),
        "breadcrumbs": breadcrumbs,
        "folders": folders,
        "files": files,
        "total": len(folders) + len(files),
    })


@app.route("/api/filter")
def api_filter():
    root = Path(request.args.get("path", _state["root"]))
    query = request.args.get("q", "").lower()
    matches = []
    index = 0
    if query:
        for entry in sorted(root.rglob("*")):
            if entry.is_file() and entry.suffix.lower() in audio_probe.SUPPORTED_EXTENSIONS:
                if query in entry.name.lower():
                    file_entry = _file_entry(entry, index)
                    if file_entry:
                        matches.append(file_entry)
                        index += 1
            if len(matches) >= 500:
                break
    return jsonify({"files": matches, "total": len(matches)})


# --------------------------------------------------------------- scan

@app.route("/api/scan", methods=["POST"])
def api_scan():
    folder = request.json.get("path")
    stats = scanner.scan_folder(_conn, Path(folder))
    return jsonify(stats)


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    limit = request.json.get("limit") if request.is_json else None
    results = _tier2.analyze_pending(_conn, limit=limit)
    return jsonify(results)


# -------------------------------------------------------------- samples

def _sample_detail_for_path(path: str) -> dict:
    p = Path(path)
    row = _conn.execute("SELECT * FROM samples WHERE path = ?1", (path,)).fetchone()
    if row is None:
        scanner.scan_file(_conn, p)
        _conn.commit()
        row = _conn.execute("SELECT * FROM samples WHERE path = ?1", (path,)).fetchone()
    if row is None:
        return {"error": "unreadable"}

    data = dict(row)
    tags = [
        r["name"] for r in _conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN sample_tags st ON st.tag_id = t.id
            WHERE st.sample_id = ?1 ORDER BY t.name
            """,
            (row["id"],),
        )
    ]
    sets = [
        r["name"] for r in _conn.execute(
            """
            SELECT s.name FROM sets s
            JOIN set_samples ss ON ss.set_id = s.id
            WHERE ss.sample_id = ?1 ORDER BY s.name
            """,
            (row["id"],),
        )
    ]
    data["tags"] = tags
    data["sets"] = sets
    data["relative_display_path"] = str(p)
    return data


@app.route("/api/sample")
def api_sample():
    path = request.args.get("path")
    return jsonify(_sample_detail_for_path(path))


@app.route("/api/sample/notes", methods=["POST"])
def api_sample_notes():
    body = request.json
    _conn.execute(
        "UPDATE samples SET notes = ?1 WHERE path = ?2", (body.get("notes", ""), body.get("path"))
    )
    _conn.commit()
    return jsonify({"ok": True})


@app.route("/api/sample/tag", methods=["POST"])
def api_sample_tag():
    body = request.json
    path = body["path"]
    tag_name = body["tag"].strip().lower()
    remove = body.get("remove", False)
    row = _conn.execute("SELECT id FROM samples WHERE path = ?1", (path,)).fetchone()
    if row is None:
        return jsonify({"error": "unknown sample"}), 404
    sample_id = row["id"]
    _conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?1)", (tag_name,))
    tag_row = _conn.execute("SELECT id FROM tags WHERE name = ?1", (tag_name,)).fetchone()
    if remove:
        _conn.execute(
            "DELETE FROM sample_tags WHERE sample_id = ?1 AND tag_id = ?2",
            (sample_id, tag_row["id"]),
        )
    else:
        _conn.execute(
            "INSERT OR IGNORE INTO sample_tags (sample_id, tag_id) VALUES (?1, ?2)",
            (sample_id, tag_row["id"]),
        )
    _conn.commit()
    return jsonify({"ok": True})


@app.route("/api/sample/waveform")
def api_waveform():
    path = request.args.get("path")
    bins = int(request.args.get("bins", 600))
    try:
        data, sr = sf.read(path, always_2d=True)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400
    mono = data.mean(axis=1)
    n = len(mono)
    bins = max(1, min(bins, n or 1))
    edges = np.linspace(0, n, bins + 1).astype(int)
    peaks = []
    for i in range(bins):
        chunk = mono[edges[i]:edges[i + 1]]
        if chunk.size == 0:
            peaks.append([0.0, 0.0])
        else:
            peaks.append([float(chunk.min()), float(chunk.max())])
    return jsonify({"peaks": peaks, "duration": n / sr if sr else 0, "sample_rate": sr})


@app.route("/api/audio")
def api_audio():
    path = request.args.get("path")
    p = Path(path)
    if p.suffix.lower() in (".wav", ".wave", ".flac", ".ogg", ".oga", ".mp3"):
        return send_file(str(p))
    # Transcode anything the <audio> tag may not handle natively (caf, aiff
    # edge cases, m4a without the right codec) to a temporary WAV.
    data, sr = sf.read(str(p), always_2d=True)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(data.shape[1])
        wf.setsampwidth(2)
        wf.setframerate(sr)
        clipped = np.clip(data, -1.0, 1.0)
        wf.writeframes((clipped * 32767.0).astype("<i2").tobytes())
    buf.seek(0)
    return send_file(buf, mimetype="audio/wav")


# ----------------------------------------------------------------- sets

@app.route("/api/sets")
def api_sets():
    rows = _conn.execute(
        """
        SELECT s.id, s.name,
               (SELECT COUNT(*) FROM set_samples ss WHERE ss.set_id = s.id) AS count
        FROM sets s ORDER BY s.id
        """
    ).fetchall()
    return jsonify({
        "sets": [dict(r) for r in rows],
        "active_set_id": _state["active_set_id"],
    })


@app.route("/api/sets", methods=["POST"])
def api_create_set():
    name = request.json.get("name", "Untitled Set")
    cur = _conn.execute("INSERT INTO sets (name) VALUES (?1)", (name,))
    _conn.commit()
    return jsonify({"id": cur.lastrowid, "name": name})


@app.route("/api/sets/active", methods=["POST"])
def api_set_active():
    _state["active_set_id"] = int(request.json["set_id"])
    return jsonify({"active_set_id": _state["active_set_id"]})


@app.route("/api/sets/<int:set_id>/members")
def api_set_members(set_id: int):
    sample_rows = _conn.execute(
        """
        SELECT ss.sample_id, sam.name, sam.path, sam.duration, sam.size,
               ss.display_name, ss.position
        FROM set_samples ss JOIN samples sam ON sam.id = ss.sample_id
        WHERE ss.set_id = ?1
        """,
        (set_id,),
    ).fetchall()
    clip_rows = _conn.execute(
        """
        SELECT c.id AS clip_id, c.name, c.start, c.end, c.sample_id,
               sam.path AS path, sc.position
        FROM set_clips sc
        JOIN clips c ON c.id = sc.clip_id
        JOIN samples sam ON sam.id = c.sample_id
        WHERE sc.set_id = ?1
        """,
        (set_id,),
    ).fetchall()

    members = []
    for r in sample_rows:
        d = dict(r)
        d["kind"] = "sample"
        members.append(d)
    for r in clip_rows:
        d = dict(r)
        d["kind"] = "clip"
        d["duration"] = d["end"] - d["start"]
        members.append(d)
    members.sort(key=lambda m: m.get("position") or 0)
    return jsonify({"members": members})


@app.route("/api/sets/toggle_member", methods=["POST"])
def api_toggle_member():
    body = request.json
    path = body["path"]
    set_id = int(body.get("set_id", _state["active_set_id"]))
    row = _conn.execute("SELECT id FROM samples WHERE path = ?1", (path,)).fetchone()
    if row is None:
        scanner.scan_file(_conn, Path(path))
        _conn.commit()
        row = _conn.execute("SELECT id FROM samples WHERE path = ?1", (path,)).fetchone()
    sample_id = row["id"]
    existing = _conn.execute(
        "SELECT 1 FROM set_samples WHERE set_id = ?1 AND sample_id = ?2", (set_id, sample_id)
    ).fetchone()
    if existing:
        _conn.execute(
            "DELETE FROM set_samples WHERE set_id = ?1 AND sample_id = ?2", (set_id, sample_id)
        )
        added = False
    else:
        position = _conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM set_samples WHERE set_id = ?1", (set_id,)
        ).fetchone()[0]
        _conn.execute(
            "INSERT INTO set_samples (set_id, sample_id, position) VALUES (?1, ?2, ?3)",
            (set_id, sample_id, position),
        )
        added = True
    _conn.commit()
    return jsonify({"added": added})


# ---------------------------------------------------------------- clips

CLIP_FIELDS = (
    "name", "start", "end", "fade_in_width", "fade_in_cp_x", "fade_in_cp_y",
    "fade_out_width", "fade_out_cp_x", "fade_out_cp_y",
)


@app.route("/api/clips")
def api_clips():
    sample_id = int(request.args["sample_id"])
    rows = _conn.execute(
        "SELECT * FROM clips WHERE sample_id = ?1 ORDER BY id", (sample_id,)
    ).fetchall()
    return jsonify({"clips": [dict(r) for r in rows]})


@app.route("/api/clips/<int:clip_id>")
def api_get_clip(clip_id: int):
    row = _conn.execute("SELECT * FROM clips WHERE id = ?1", (clip_id,)).fetchone()
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))


@app.route("/api/clips", methods=["POST"])
def api_create_clip():
    b = request.json
    cur = _conn.execute(
        """
        INSERT INTO clips (
            sample_id, name, start, end, fade_in_width, fade_in_cp_x, fade_in_cp_y,
            fade_out_width, fade_out_cp_x, fade_out_cp_y
        ) VALUES (:sample_id, :name, :start, :end, :fade_in_width, :fade_in_cp_x,
                  :fade_in_cp_y, :fade_out_width, :fade_out_cp_x, :fade_out_cp_y)
        """,
        {
            "sample_id": int(b["sample_id"]),
            "name": b.get("name", "Clip"),
            "start": b.get("start", 0.0),
            "end": b.get("end", 0.0),
            "fade_in_width": b.get("fade_in_width", 0.0),
            "fade_in_cp_x": b.get("fade_in_cp_x", 0.5),
            "fade_in_cp_y": b.get("fade_in_cp_y", 0.5),
            "fade_out_width": b.get("fade_out_width", 0.0),
            "fade_out_cp_x": b.get("fade_out_cp_x", 0.5),
            "fade_out_cp_y": b.get("fade_out_cp_y", 0.5),
        },
    )
    _conn.commit()
    return jsonify({"id": cur.lastrowid})


@app.route("/api/clips/<int:clip_id>", methods=["PATCH"])
def api_update_clip(clip_id: int):
    b = request.json
    fields = {k: v for k, v in b.items() if k in CLIP_FIELDS}
    if not fields:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = clip_id
    _conn.execute(f"UPDATE clips SET {set_clause} WHERE id = :id", fields)
    _conn.commit()
    return jsonify({"ok": True})


@app.route("/api/clips/<int:clip_id>", methods=["DELETE"])
def api_delete_clip(clip_id: int):
    _conn.execute("DELETE FROM clips WHERE id = ?1", (clip_id,))
    _conn.commit()
    return jsonify({"ok": True})


@app.route("/api/sets/toggle_clip_member", methods=["POST"])
def api_toggle_clip_member():
    b = request.json
    clip_id = int(b["clip_id"])
    set_id = int(b.get("set_id", _state["active_set_id"]))
    existing = _conn.execute(
        "SELECT 1 FROM set_clips WHERE set_id = ?1 AND clip_id = ?2", (set_id, clip_id)
    ).fetchone()
    if existing:
        _conn.execute(
            "DELETE FROM set_clips WHERE set_id = ?1 AND clip_id = ?2", (set_id, clip_id)
        )
        added = False
    else:
        position = _conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM set_clips WHERE set_id = ?1", (set_id,)
        ).fetchone()[0]
        _conn.execute(
            "INSERT INTO set_clips (set_id, clip_id, position) VALUES (?1, ?2, ?3)",
            (set_id, clip_id, position),
        )
        added = True
    _conn.commit()
    return jsonify({"added": added})


# --------------------------------------------------------------- export

def _preset_from_row(row) -> export.ExportPreset:
    d = dict(row)
    d.pop("id", None)
    d.pop("created_at", None)
    return export.ExportPreset(**d)


def _preset_from_body(body: dict) -> export.ExportPreset:
    return export.ExportPreset(
        name=body.get("preset_name", "Default"),
        convert_to_mono=body.get("mono", False),
        mono_mode=body.get("mono_mode", "sum"),
        high_pass_enabled=body.get("high_pass_enabled", False),
        high_pass_frequency=body.get("high_pass_frequency", 80),
        normalize=body.get("normalize", False),
        normalize_ceiling=body.get("normalize_ceiling", -0.3),
        limit_enabled=body.get("limit_enabled", False),
        limit_threshold=body.get("limit_threshold", -0.3),
        sample_rate_enabled=body.get("sample_rate_enabled", False),
        sample_rate_target=body.get("sample_rate_target", 44100),
        bit_depth_enabled=body.get("bit_depth_enabled", False),
        bit_depth_target=body.get("bit_depth_target", 16),
        prefix_with_number=body.get("prefix_with_number", False),
        generate_manifest=body.get("manifest", True),
        legacy_wav=body.get("legacy_wav", False),
        post_export_command_enabled=body.get("post_export_command_enabled", False),
        post_export_command=body.get("post_export_command", ""),
        append_cue=body.get("cue", False),
    )


@app.route("/api/export", methods=["POST"])
def api_export():
    body = request.json
    set_id = int(body["set_id"])
    row = _conn.execute("SELECT name FROM sets WHERE id = ?1", (set_id,)).fetchone()

    sample_members = _conn.execute(
        "SELECT sam.path, ss.display_name, ss.position FROM set_samples ss "
        "JOIN samples sam ON sam.id = ss.sample_id WHERE ss.set_id = ?1",
        (set_id,),
    ).fetchall()
    clip_members = _conn.execute(
        """
        SELECT sam.path, c.name AS display_name, c.start, c.end, sc.position
        FROM set_clips sc
        JOIN clips c ON c.id = sc.clip_id
        JOIN samples sam ON sam.id = c.sample_id
        WHERE sc.set_id = ?1
        """,
        (set_id,),
    ).fetchall()
    combined = sorted(
        [dict(m, _kind="sample") for m in sample_members]
        + [dict(m, _kind="clip") for m in clip_members],
        key=lambda m: m.get("position") or 0,
    )
    items = [
        export.ExportSourceItem(
            source_path=Path(m["path"]),
            display_name=m["display_name"],
            clip_start=m.get("start"),
            clip_end=m.get("end"),
        )
        for m in combined
    ]

    preset_id = body.get("preset_id")
    if preset_id:
        preset_row = _conn.execute(
            "SELECT * FROM export_presets WHERE id = ?1", (int(preset_id),)
        ).fetchone()
        preset = _preset_from_row(preset_row) if preset_row else _preset_from_body(body)
    else:
        preset = _preset_from_body(body)

    destination = Path(body["destination"]) if body.get("destination") else export.default_export_destination() / row["name"]
    result = export.start_export(items, destination, preset, set_name=row["name"])
    return jsonify({
        "destination": str(result.destination),
        "copied": result.copied,
        "failed": [{"path": str(p), "reason": r} for p, r in result.failed],
    })


@app.route("/api/export_clip", methods=["POST"])
def api_export_clip():
    body = request.json
    item = export.ExportSourceItem(
        source_path=Path(body["path"]),
        display_name=body.get("name"),
        clip_start=body.get("start"),
        clip_end=body.get("end"),
    )
    destination = Path(body["destination"]) if body.get("destination") else export.default_export_destination() / "Clips"
    preset = export.ExportPreset(generate_manifest=False)
    result = export.start_export([item], destination, preset, set_name="Clip Export")
    return jsonify({
        "destination": str(result.destination),
        "copied": result.copied,
        "failed": [{"path": str(p), "reason": r} for p, r in result.failed],
    })


# ------------------------------------------------------------- presets

PRESET_FIELDS = (
    "name", "convert_to_mono", "mono_mode", "high_pass_enabled", "high_pass_frequency",
    "normalize", "normalize_ceiling", "limit_enabled", "limit_threshold",
    "sample_rate_enabled", "sample_rate_target", "bit_depth_enabled", "bit_depth_target",
    "prefix_with_number", "generate_manifest", "legacy_wav",
    "post_export_command_enabled", "post_export_command", "append_cue",
)
PRESET_DEFAULTS = {
    "name": "New Preset", "convert_to_mono": False, "mono_mode": "sum",
    "high_pass_enabled": False, "high_pass_frequency": 80, "normalize": False,
    "normalize_ceiling": -0.3, "limit_enabled": False, "limit_threshold": -0.3,
    "sample_rate_enabled": False, "sample_rate_target": 44100,
    "bit_depth_enabled": False, "bit_depth_target": 16, "prefix_with_number": False,
    "generate_manifest": False, "legacy_wav": False,
    "post_export_command_enabled": False, "post_export_command": "", "append_cue": False,
}


@app.route("/api/presets")
def api_list_presets():
    rows = _conn.execute("SELECT * FROM export_presets ORDER BY name").fetchall()
    return jsonify({"presets": [dict(r) for r in rows]})


@app.route("/api/presets", methods=["POST"])
def api_create_preset():
    b = {**PRESET_DEFAULTS, **(request.json or {})}
    fields = {k: b[k] for k in PRESET_FIELDS}
    cols = ", ".join(fields)
    placeholders = ", ".join(f":{k}" for k in fields)
    cur = _conn.execute(
        f"INSERT INTO export_presets ({cols}) VALUES ({placeholders})", fields
    )
    _conn.commit()
    return jsonify({"id": cur.lastrowid})


@app.route("/api/presets/<int:preset_id>", methods=["PATCH"])
def api_update_preset(preset_id: int):
    b = request.json or {}
    fields = {k: v for k, v in b.items() if k in PRESET_FIELDS}
    if fields:
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = preset_id
        _conn.execute(f"UPDATE export_presets SET {set_clause} WHERE id = :id", fields)
        _conn.commit()
    return jsonify({"ok": True})


@app.route("/api/presets/<int:preset_id>", methods=["DELETE"])
def api_delete_preset(preset_id: int):
    _conn.execute("DELETE FROM export_presets WHERE id = ?1", (preset_id,))
    _conn.commit()
    return jsonify({"ok": True})


# --------------------------------------------------------- preferences

@app.route("/api/preferences")
def api_get_preferences():
    rows = _conn.execute("SELECT key, value FROM app_preferences").fetchall()
    return jsonify({r["key"]: r["value"] for r in rows})


@app.route("/api/preferences", methods=["POST"])
def api_set_preference():
    b = request.json
    _conn.execute(
        """
        INSERT INTO app_preferences (key, value) VALUES (?1, ?2)
        ON CONFLICT(key) DO UPDATE SET value = ?2, updated_at = CURRENT_TIMESTAMP
        """,
        (b["key"], str(b["value"])),
    )
    _conn.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- tags

@app.route("/api/tags")
def api_tags():
    rows = _conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
    return jsonify({"tags": [r["name"] for r in rows]})


def create_app() -> Flask:
    return app


if __name__ == "__main__":
    app.run(port=5177, debug=False, threaded=False)
