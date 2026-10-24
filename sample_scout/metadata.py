"""Filename / tag based BPM and musical-key extraction ("Tier 0/1" metadata).

All five regular expressions below are copied verbatim (character for
character) from the rodata of the original binary, where they appear as
plain string literals right next to the Rust `regex` crate's pattern
compilation machinery:

    (?i)^([A-G])([#b])?\\s*(m(?:in(?:or)?)?|maj(?:or)?)?$
    (?i)(?:^|[_\\s\\-.])((\\d{2,3})(?:[_\\s\\-.]|$))
    (?i)bpm\\s*[_\\-]?\\s*(\\d{2,3})
    (?i)(\\d{2,3})\\s*[_\\-]?\\s*bpm
    (?i)tempo\\s*[_\\-]?\\s*(\\d{2,3})

The surrounding function names recovered from the binary's mangled Rust
symbols (`metadata::parse_key_tag`, `metadata::extract_explicit_bpm`,
`metadata::extract_bpm_from_path`, `metadata::extract_bare_number_bpm`,
`metadata::is_bare_number_sequence`, `metadata::build_sequence_context`,
`metadata::extract_bare_number_for_sequence`) describe the shape of the
pipeline implemented here:

1. An *explicit* "123bpm" / "bpm123" / "tempo123" token always wins
   (``extract_explicit_bpm``).
2. Failing that, a bare 2-3 digit number surrounded by separators is
   considered a BPM candidate only if it falls in a plausible tempo
   range and doesn't look like a sequence/track number, i.e. a small
   left-padded counter shared by sibling files in the same folder
   (``extract_bare_number_bpm`` / ``is_bare_number_sequence`` /
   ``build_sequence_context``). The exact disambiguation heuristic used
   by the original could not be recovered without full decompilation;
   the version here is a best-effort reconstruction documented at each
   step.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

KEY_TAG_RE = re.compile(
    r"^([A-G])([#b])?\s*(m(?:in(?:or)?)?|maj(?:or)?)?$", re.IGNORECASE
)
BARE_NUMBER_RE = re.compile(
    r"(?:^|[_\s\-.])((\d{2,3})(?:[_\s\-.]|$))", re.IGNORECASE
)
BPM_PREFIX_RE = re.compile(r"bpm\s*[_\-]?\s*(\d{2,3})", re.IGNORECASE)
BPM_SUFFIX_RE = re.compile(r"(\d{2,3})\s*[_\-]?\s*bpm", re.IGNORECASE)
TEMPO_PREFIX_RE = re.compile(r"tempo\s*[_\-]?\s*(\d{2,3})", re.IGNORECASE)

MIN_PLAUSIBLE_BPM = 40
MAX_PLAUSIBLE_BPM = 220

_SHARP_TO_FLAT = {
    "C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab", "A#": "Bb",
}


def parse_key_tag(raw: Optional[str]) -> Optional[str]:
    """Parse a free-form key string (e.g. from an ID3/BWF tag) into the
    canonical ``"<Letter>[#] major|minor"`` form stored in ``key_tag``.
    """
    if not raw:
        return None
    raw = raw.strip()
    m = KEY_TAG_RE.match(raw)
    if not m:
        return None
    letter = m.group(1).upper()
    accidental = m.group(2)
    mode_token = (m.group(3) or "").lower()
    mode = "minor" if mode_token.startswith("m") and not mode_token.startswith(
        "maj"
    ) else "major"
    name = letter + (accidental if accidental else "")
    if accidental == "b":
        name = letter + "b"
    elif accidental == "#":
        name = letter + "#"
    return f"{name} {mode}"


def extract_explicit_bpm(text: str) -> Optional[float]:
    """Return a BPM value only when it is unambiguously tagged as such
    in the text, i.e. adjacent to the literal word "bpm" or "tempo".
    """
    for pattern in (BPM_PREFIX_RE, BPM_SUFFIX_RE, TEMPO_PREFIX_RE):
        m = pattern.search(text)
        if m:
            value = float(m.group(1))
            if MIN_PLAUSIBLE_BPM <= value <= MAX_PLAUSIBLE_BPM:
                return value
    return None


def is_bare_number_sequence(number: str, siblings: Iterable[str]) -> bool:
    """Heuristic: a bare number looks like a sequence/track index (not a
    BPM) when sibling filenames in the same folder share the same
    zero-padded width and form a short run of consecutive integers
    (e.g. ``Kick_01.wav``, ``Kick_02.wav``, ...).
    """
    width = len(number)
    if width not in (1, 2):
        return False
    try:
        value = int(number)
    except ValueError:
        return False
    sibling_numbers = set()
    for sib in siblings:
        for m in BARE_NUMBER_RE.finditer(sib):
            candidate = m.group(2)
            if len(candidate) == width:
                try:
                    sibling_numbers.add(int(candidate))
                except ValueError:
                    pass
    if len(sibling_numbers) < 3:
        return False
    ordered = sorted(sibling_numbers)
    consecutive_run = sum(
        1 for a, b in zip(ordered, ordered[1:]) if b - a == 1
    )
    return consecutive_run >= len(ordered) - 2 and value in sibling_numbers


def build_sequence_context(path: Path) -> list[str]:
    """Collect sibling filenames (same directory) used to disambiguate
    bare numbers from sequence indices.
    """
    try:
        return [p.name for p in path.parent.iterdir() if p.is_file()]
    except OSError:
        return []


def extract_bare_number_bpm(
    text: str, siblings: Optional[Iterable[str]] = None
) -> Optional[float]:
    siblings = list(siblings or [])
    for m in BARE_NUMBER_RE.finditer(text):
        number = m.group(2)
        value = float(number)
        if not (MIN_PLAUSIBLE_BPM <= value <= MAX_PLAUSIBLE_BPM):
            continue
        if is_bare_number_sequence(number, siblings):
            continue
        return value
    return None


def extract_bare_number_for_sequence(text: str) -> Optional[int]:
    """Return the first bare number found, treated as a sequence index
    rather than a BPM candidate (used for e.g. default track ordering).
    """
    m = BARE_NUMBER_RE.search(text)
    return int(m.group(2)) if m else None


def extract_bpm_from_path(path: Path) -> Optional[float]:
    """Full filename BPM extraction pipeline: explicit token first, then
    a disambiguated bare number, scanning the stem (and parent folder
    name as a weaker fallback, matching the original's path-wide scan).
    """
    stem = path.stem
    explicit = extract_explicit_bpm(stem)
    if explicit is not None:
        return explicit
    explicit = extract_explicit_bpm(path.parent.name)
    if explicit is not None:
        return explicit
    siblings = build_sequence_context(path)
    bare = extract_bare_number_bpm(stem, siblings)
    if bare is not None:
        return bare
    return None


@dataclass
class ParsedFilenameMetadata:
    bpm_filename: Optional[float]
    key_tag: Optional[str]


def parse_filename_metadata(path: Path) -> ParsedFilenameMetadata:
    bpm = extract_bpm_from_path(path)
    key = None
    for token in re.split(r"[_\s\-.]+", path.stem):
        candidate = parse_key_tag(token)
        if candidate:
            key = candidate
            break
    return ParsedFilenameMetadata(bpm_filename=bpm, key_tag=key)
