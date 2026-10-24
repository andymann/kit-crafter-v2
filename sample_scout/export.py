"""Export pipeline: turns a set's samples into processed files on disk
per an ``export_presets`` row, plus an optional ``manifest.txt`` and
post-export shell command — matching ``export::export_single_item`` /
``export::start_export_async`` / ``chain_export::build_chain`` and
``export::stop_post_export_command``.

The manifest text format (header lines + a tab-indented source list) is
copied from the literal format string found in the binary::

    Sample Scout Export Manifest
    Set: {set}
    Exported: {n} samples
    Date: {date "%Y-%m-%d %H:%M:%S"}
    Preset: {preset}
    DSP: {dsp}

        Source
    {filenames}

and the "Normalize (%s dB)" / "Limiter (%s dB)" / "-- no processing --"
substrings for the ``DSP:`` line are likewise copied verbatim.
"""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from . import dsp

DEFAULT_EXPORT_FOLDER_NAME = "Sample Scout Exports"


@dataclass
class ExportPreset:
    name: str = "Default"
    convert_to_mono: bool = False
    mono_mode: str = "sum"
    high_pass_enabled: bool = False
    high_pass_frequency: int = 80
    normalize: bool = False
    normalize_ceiling: float = -0.3
    limit_enabled: bool = False
    limit_threshold: float = -0.3
    sample_rate_enabled: bool = False
    sample_rate_target: int = 44100
    bit_depth_enabled: bool = False
    bit_depth_target: int = 16
    prefix_with_number: bool = False
    generate_manifest: bool = False
    legacy_wav: bool = False
    post_export_command_enabled: bool = False
    post_export_command: str = ""
    append_cue: bool = False


@dataclass
class ExportSourceItem:
    source_path: Path
    display_name: Optional[str] = None
    clip_start: Optional[float] = None
    clip_end: Optional[float] = None


@dataclass
class ExportResult:
    destination: Path
    copied: int = 0
    failed: list[tuple[Path, str]] = field(default_factory=list)


def dsp_description(preset: ExportPreset) -> str:
    parts = []
    if preset.convert_to_mono:
        parts.append(f"Mono ({preset.mono_mode.capitalize()})")
    if preset.high_pass_enabled:
        parts.append(f"High-pass ({preset.high_pass_frequency} Hz)")
    if preset.normalize:
        parts.append(f"Normalize ({preset.normalize_ceiling} dB)")
    if preset.limit_enabled:
        parts.append(f"Limiter ({preset.limit_threshold} dB)")
    if preset.sample_rate_enabled:
        parts.append(f"Resample ({preset.sample_rate_target} Hz)")
    if preset.bit_depth_enabled:
        parts.append(f"Bit depth ({preset.bit_depth_target}-bit)")
    return "\t".join(parts) if parts else "-- no processing --"


def _effective_filename(index: int, preset: ExportPreset, name: str) -> str:
    if preset.prefix_with_number:
        return f"{index + 1:02d}_{name}"
    return name


def _process_audio(
    samples: np.ndarray, sr: int, preset: ExportPreset
) -> tuple[np.ndarray, int]:
    if preset.convert_to_mono:
        samples = dsp.convert_channels(samples, preset.mono_mode)  # type: ignore[arg-type]
    if preset.high_pass_enabled:
        samples = dsp.apply_high_pass(samples, sr, preset.high_pass_frequency)
    if preset.normalize:
        samples = dsp.normalize_to_ceiling(samples, preset.normalize_ceiling)
    if preset.limit_enabled:
        samples = dsp.apply_limiter(samples, preset.limit_threshold)
    if preset.sample_rate_enabled:
        samples, sr = dsp.resample_to(samples, sr, preset.sample_rate_target)
    return samples, sr


def export_single_item(
    item: ExportSourceItem,
    destination_dir: Path,
    preset: ExportPreset,
    index: int,
) -> Path:
    data, sr = sf.read(str(item.source_path), always_2d=True)
    samples = data.T.astype(np.float32)  # (channels, n)

    if item.clip_start is not None and item.clip_end is not None:
        samples = dsp.trim_to_clip(samples, sr, item.clip_start, item.clip_end)

    samples, sr = _process_audio(samples, sr, preset)

    bit_depth = preset.bit_depth_target if preset.bit_depth_enabled else 16

    name = item.display_name or item.source_path.name
    if not name.lower().endswith(".wav"):
        name = Path(name).stem + ".wav"
    name = _effective_filename(index, preset, name)
    out_path = destination_dir / name

    cue_points = None
    if preset.append_cue:
        cue_points = [(0, "Start")]

    dsp.write_wav(
        out_path, samples, sr, bit_depth,
        legacy=preset.legacy_wav, cue_points=cue_points,
    )
    return out_path


def write_manifest(
    destination_dir: Path,
    set_name: str,
    preset: ExportPreset,
    exported_names: list[str],
) -> Path:
    lines = [
        "Sample Scout Export Manifest",
        f"Set: {set_name}",
        f"Exported: {len(exported_names)} samples",
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Preset: {preset.name}",
        f"DSP: {dsp_description(preset)}",
        "",
        "\tSource",
    ]
    lines.extend(exported_names)
    manifest_path = destination_dir / "manifest.txt"
    manifest_path.write_text("\n".join(lines) + "\n")
    return manifest_path


def run_post_export_command(preset: ExportPreset, destination_dir: Path) -> tuple[int, str]:
    if not preset.post_export_command_enabled or not preset.post_export_command.strip():
        return 0, ""
    args = shlex.split(preset.post_export_command.replace("{{destination}}", str(destination_dir)))
    proc = subprocess.run(args, cwd=str(destination_dir), capture_output=True, text=True, timeout=300)
    return proc.returncode, proc.stdout + proc.stderr


def start_export(
    items: list[ExportSourceItem],
    destination_dir: Path,
    preset: ExportPreset,
    set_name: str = "Untitled Set",
) -> ExportResult:
    destination_dir.mkdir(parents=True, exist_ok=True)
    result = ExportResult(destination=destination_dir)
    exported_names: list[str] = []
    for index, item in enumerate(items):
        try:
            out_path = export_single_item(item, destination_dir, preset, index)
            exported_names.append(out_path.name)
            result.copied += 1
        except Exception as exc:  # noqa: BLE001 - surfaced per-item
            result.failed.append((item.source_path, str(exc)))

    if preset.generate_manifest:
        write_manifest(destination_dir, set_name, preset, exported_names)

    if preset.post_export_command_enabled:
        run_post_export_command(preset, destination_dir)

    return result


def default_export_destination() -> Path:
    return Path.home() / "Documents" / DEFAULT_EXPORT_FOLDER_NAME
