"""Audio DSP primitives used by both the export pipeline and clip editing.

Named after (and matching the responsibilities of) the original's ``dsp``
module: ``trim_to_clip``, ``process_audio``, ``apply_fade_curves``,
``decode_audio_file``, ``quantize_pcm_bytes``, ``write_wav`` — plus
``audio_utils::convert_channels`` for mono conversion.
"""
from __future__ import annotations

import struct
import wave
from pathlib import Path
from typing import Literal

import numpy as np
from scipy.signal import butter, sosfilt, resample_poly

MonoMode = Literal["sum", "left", "right"]


def trim_to_clip(samples: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    """``samples`` is (channels, n) float32 in [-1, 1]. ``start``/``end``
    are seconds.
    """
    start_idx = max(0, int(round(start * sr)))
    end_idx = min(samples.shape[-1], int(round(end * sr)))
    if end_idx <= start_idx:
        return samples[..., 0:0]
    return samples[..., start_idx:end_idx]


def bezier_ease(t: np.ndarray, cp_x: float, cp_y: float) -> np.ndarray:
    """Quadratic-bezier easing curve through (0,0), (cp_x, cp_y), (1,1),
    matching the clip editor's fade-curve control point model
    (``fade_in_cp_x/y`` / ``fade_out_cp_x/y`` columns on ``clips``).
    """
    t = np.clip(t, 0.0, 1.0)
    # Solve for the bezier parameter u such that the x-coordinate equals
    # t (quadratic bezier: x(u) = 2(1-u)u*cp_x + u^2), via Newton's method,
    # then evaluate y(u) = 2(1-u)u*cp_y + u^2.
    u = t.copy()
    for _ in range(6):
        x = 2 * (1 - u) * u * cp_x + u ** 2
        dx = 2 * cp_x * (1 - 2 * u) + 2 * u
        dx = np.where(np.abs(dx) < 1e-6, 1e-6, dx)
        u = np.clip(u - (x - t) / dx, 0.0, 1.0)
    y = 2 * (1 - u) * u * cp_y + u ** 2
    return y


def apply_fade_curves(
    samples: np.ndarray,
    sr: int,
    fade_in_width: float,
    fade_in_cp: tuple[float, float],
    fade_out_width: float,
    fade_out_cp: tuple[float, float],
) -> np.ndarray:
    samples = samples.copy()
    n = samples.shape[-1]
    if fade_in_width > 0:
        count = min(n, int(round(fade_in_width * sr)))
        if count > 0:
            t = np.linspace(0, 1, count, endpoint=True)
            curve = bezier_ease(t, *fade_in_cp)
            samples[..., :count] *= curve
    if fade_out_width > 0:
        count = min(n, int(round(fade_out_width * sr)))
        if count > 0:
            t = np.linspace(1, 0, count, endpoint=True)
            curve = bezier_ease(t, *fade_out_cp)
            samples[..., n - count:] *= curve
    return samples


def convert_channels(samples: np.ndarray, mono_mode: MonoMode) -> np.ndarray:
    """``samples`` is (channels, n). Returns (1, n) mono mixdown."""
    if samples.shape[0] == 1:
        return samples
    if mono_mode == "left":
        return samples[0:1, :]
    if mono_mode == "right":
        return samples[-1:, :]
    # "sum": average all channels down to one (equal-power-ish sum avoids
    # clipping on stereo material that's already near full scale).
    return samples.mean(axis=0, keepdims=True)


def apply_high_pass(samples: np.ndarray, sr: int, frequency: float) -> np.ndarray:
    sos = butter(2, frequency, btype="highpass", fs=sr, output="sos")
    return sosfilt(sos, samples, axis=-1)


def normalize_to_ceiling(samples: np.ndarray, ceiling_db: float) -> np.ndarray:
    peak = np.max(np.abs(samples)) if samples.size else 0.0
    if peak <= 1e-9:
        return samples
    target_linear = 10 ** (ceiling_db / 20.0)
    return samples * (target_linear / peak)


def apply_limiter(samples: np.ndarray, threshold_db: float) -> np.ndarray:
    threshold_linear = 10 ** (threshold_db / 20.0)
    return np.clip(samples, -threshold_linear, threshold_linear)


def resample_to(samples: np.ndarray, sr: int, target_sr: int) -> tuple[np.ndarray, int]:
    if sr == target_sr:
        return samples, sr
    from math import gcd

    g = gcd(sr, target_sr)
    up, down = target_sr // g, sr // g
    resampled = resample_poly(samples, up, down, axis=-1)
    return resampled, target_sr


def quantize_pcm_bytes(samples: np.ndarray, bit_depth: int) -> bytes:
    """``samples`` is (channels, n) float32 in [-1, 1], interleaved on
    output (standard PCM WAV layout).
    """
    interleaved = reinterleave(samples)
    clipped = np.clip(interleaved, -1.0, 1.0)
    if bit_depth == 16:
        ints = (clipped * 32767.0).astype("<i2")
    elif bit_depth == 24:
        ints32 = (clipped * 8388607.0).astype(np.int32)
        packed = bytearray()
        for v in ints32:
            packed += struct.pack("<i", int(v))[0:3]
        return bytes(packed)
    elif bit_depth == 32:
        ints = (clipped * 2147483647.0).astype("<i4")
    else:
        raise ValueError(f"Unsupported bit depth: {bit_depth}")
    return ints.tobytes()


def deinterleave(data: np.ndarray, channels: int) -> np.ndarray:
    return data.reshape(-1, channels).T


def reinterleave(samples: np.ndarray) -> np.ndarray:
    return samples.T.reshape(-1)


def write_wav(
    path: Path,
    samples: np.ndarray,
    sr: int,
    bit_depth: int,
    legacy: bool = False,
    cue_points: list[tuple[int, str]] | None = None,
) -> None:
    """Write a PCM WAV file.

    ``legacy=True`` matches ``export_presets.legacy_wav``: write a
    minimal canonical 44-byte-header ``WAVE``/``fmt `` (not
    ``WAVE_FORMAT_EXTENSIBLE``) file for maximum compatibility with old
    hardware samplers, the scenario the "(Hound fallback: ...)" string
    in the binary refers to.

    ``cue_points`` (sample offset, label) pairs add a standard RIFF
    ``cue `` chunk, matching ``export_presets.append_cue``.
    """
    channels = samples.shape[0]
    pcm_bytes = quantize_pcm_bytes(samples, bit_depth)

    if not cue_points:
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(bit_depth // 8)
            wf.setframerate(sr)
            wf.writeframes(pcm_bytes)
        return

    _write_wav_with_cue(path, pcm_bytes, channels, sr, bit_depth, cue_points)


def _write_wav_with_cue(
    path: Path,
    pcm_bytes: bytes,
    channels: int,
    sr: int,
    bit_depth: int,
    cue_points: list[tuple[int, str]],
) -> None:
    block_align = channels * (bit_depth // 8)
    byte_rate = sr * block_align
    fmt_chunk = struct.pack(
        "<HHIIHH", 1, channels, sr, byte_rate, block_align, bit_depth
    )

    cue_chunk = struct.pack("<I", len(cue_points))
    for idx, (sample_offset, _label) in enumerate(cue_points):
        cue_chunk += struct.pack(
            "<II4sIII", idx + 1, sample_offset, b"data", 0, 0, sample_offset
        )

    def chunk(fourcc: bytes, payload: bytes) -> bytes:
        if len(payload) % 2 == 1:
            payload += b"\x00"
        return fourcc + struct.pack("<I", len(payload)) + payload

    riff_body = (
        b"WAVE"
        + chunk(b"fmt ", fmt_chunk)
        + chunk(b"data", pcm_bytes)
        + chunk(b"cue ", cue_chunk)
    )
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(riff_body)) + riff_body)
