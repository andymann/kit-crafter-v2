"""Camelot-wheel key numbering.

The binary stores two 24-entry const string tables: one with Camelot
codes ("1A".."12A","1B".."12B" — recovered as the literal run
``...B12B11B10B9B8B7B6B5B4B3B2B1B12A11A10A9A8A7A6A5A4A3A2A1A`` in
rodata, consistent with LLVM's byte-suffix string merging of the
individual "<n>A"/"<n>B" literals) and one with key names such as
``"G# minor"`` / ``"A major"``. Those confirm the app uses the
industry-standard Camelot wheel (the same one used by Mixed In Key,
Rekordbox, Serato, etc.) rather than a bespoke numbering, so the table
below is the well-known standard mapping rather than a guess.

``key_name`` is stored in the ``"<Letter>[#] major|minor"`` form (see
``metadata.parse_key_tag``); ``key_numerical`` stores the Camelot code.
"""
from __future__ import annotations

# (letter form used in key_name) -> camelot code
CAMELOT_BY_KEY = {
    "G# minor": "1A", "D# minor": "2A", "A# minor": "3A", "F minor": "4A",
    "C minor": "5A", "G minor": "6A", "D minor": "7A", "A minor": "8A",
    "E minor": "9A", "B minor": "10A", "F# minor": "11A", "C# minor": "12A",
    "B major": "1B", "F# major": "2B", "C# major": "3B", "G# major": "4B",
    "D# major": "5B", "A# major": "6B", "F major": "7B", "C major": "8B",
    "G major": "9B", "D major": "10B", "A major": "11B", "E major": "12B",
}

# Enharmonic equivalents so lookups work regardless of sharp/flat spelling.
_ENHARMONIC = {
    "Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
}

CAMELOT_TO_KEY = {v: k for k, v in CAMELOT_BY_KEY.items()}

# Order used by the key-CNN classifier: 12 major keys (chromatic, C..B)
# followed by 12 minor keys (chromatic, C..B). This is the conventional
# class ordering for pitch-class-based key classifiers (incl. the public
# key-cnn architecture this model's input/output shape matches) and is
# used to map the model's 24 logits back to a key name.
_CHROMATIC = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
KEY_CNN_CLASSES = [f"{n} major" for n in _CHROMATIC] + [
    f"{n} minor" for n in _CHROMATIC
]


def normalize_key_name(name: str) -> str:
    letter_part, _, mode = name.partition(" ")
    if letter_part in _ENHARMONIC:
        letter_part = _ENHARMONIC[letter_part]
    return f"{letter_part} {mode}"


def key_name_to_camelot(name: str) -> str | None:
    return CAMELOT_BY_KEY.get(normalize_key_name(name))


def camelot_to_key_name(code: str) -> str | None:
    return CAMELOT_TO_KEY.get(code)
