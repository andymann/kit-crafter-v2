import tkinter as tk
from tkinter import ttk

# Module-level colour globals — mutated by apply()
BG = PANEL = SURFACE = BORDER = SEL = SEL_FG = FG = FG2 = FG3 = ""
GREEN = ORANGE = RED = HOVER = PRESSED = SEL_HOVER = ""
FONT = ("Menlo", 11)
FONT_S = ("Menlo", 10)
FONT_XS = ("Menlo", 9)

_PALETTES = {
    "Classic": {
        "BG": "#1a1a1a",
        "PANEL": "#222222",
        "SURFACE": "#2a2a2a",
        "BORDER": "#383838",
        "SEL": "#1e3a5f",
        "SEL_FG": "#5aadff",
        "FG": "#dddddd",
        "FG2": "#999999",
        "FG3": "#555555",
        "GREEN": "#4aff88",
        "ORANGE": "#ffaa44",
        "RED": "#ff5555",
        "HOVER": "#333333",
        "PRESSED": "#404040",
        "SEL_HOVER": "#2a4a70",
    },
    "Amethyst": {
        "BG": "#0d0c10",
        "PANEL": "#14121a",
        "SURFACE": "#1c1924",
        "BORDER": "#2d2840",
        "SEL": "#2a1f4e",
        "SEL_FG": "#a78bfa",
        "FG": "#e0d8f8",
        "FG2": "#8878b8",
        "FG3": "#443860",
        "GREEN": "#6ee7b7",
        "ORANGE": "#fbbf24",
        "RED": "#f87171",
        "HOVER": "#221e30",
        "PRESSED": "#2e2842",
        "SEL_HOVER": "#3a2e60",
    },
    "Neon": {
        "BG": "#090812",
        "PANEL": "#100e1a",
        "SURFACE": "#17142a",
        "BORDER": "#281f40",
        "SEL": "#200a3e",
        "SEL_FG": "#f72585",
        "FG": "#f0e8ff",
        "FG2": "#9070c0",
        "FG3": "#3d2860",
        "GREEN": "#4cc9f0",
        "ORANGE": "#f4a261",
        "RED": "#ff4d6d",
        "HOVER": "#1e1535",
        "PRESSED": "#2a1e48",
        "SEL_HOVER": "#300c52",
    },
    "Midnight": {
        "BG": "#0b0f1c",
        "PANEL": "#111828",
        "SURFACE": "#172035",
        "BORDER": "#243050",
        "SEL": "#1a2e4a",
        "SEL_FG": "#58b8f8",
        "FG": "#c6d8ee",
        "FG2": "#6a90b8",
        "FG3": "#304060",
        "GREEN": "#3ddbb8",
        "ORANGE": "#f4a261",
        "RED": "#ff6b6b",
        "HOVER": "#1a2540",
        "PRESSED": "#243050",
        "SEL_HOVER": "#1e3860",
    },
}

_PALETTE_ORDER = list(_PALETTES.keys())
_current_palette = "Classic"


def _load_palette(name: str):
    global BG, PANEL, SURFACE, BORDER, SEL, SEL_FG, FG, FG2, FG3
    global GREEN, ORANGE, RED, HOVER, PRESSED, SEL_HOVER, _current_palette
    p = _PALETTES[name]
    BG = p["BG"]
    PANEL = p["PANEL"]
    SURFACE = p["SURFACE"]
    BORDER = p["BORDER"]
    SEL = p["SEL"]
    SEL_FG = p["SEL_FG"]
    FG = p["FG"]
    FG2 = p["FG2"]
    FG3 = p["FG3"]
    GREEN = p["GREEN"]
    ORANGE = p["ORANGE"]
    RED = p["RED"]
    HOVER = p["HOVER"]
    PRESSED = p["PRESSED"]
    SEL_HOVER = p["SEL_HOVER"]
    _current_palette = name


def apply(root: tk.Tk):
    _load_palette(_current_palette)
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("Surface.TFrame", background=SURFACE)

    style.configure("TLabel", background=BG, foreground=FG, font=FONT)
    style.configure("Muted.TLabel", background=BG, foreground=FG2, font=FONT_S)
    style.configure("Hint.TLabel", background=BG, foreground=FG3, font=FONT_XS)
    style.configure("Accent.TLabel", background=BG, foreground=SEL_FG, font=FONT)
    style.configure("Green.TLabel", background=BG, foreground=GREEN, font=FONT_S)

    style.configure(
        "TButton",
        background=SURFACE,
        foreground=FG,
        bordercolor=BORDER,
        focuscolor=BORDER,
        font=FONT_S,
        relief="flat",
        padding=(6, 3),
    )
    style.map(
        "TButton",
        background=[("active", HOVER), ("pressed", PRESSED)],
        foreground=[("active", FG)],
    )
    style.configure(
        "Accent.TButton",
        background=SEL,
        foreground=SEL_FG,
        bordercolor=SEL,
        font=FONT_S,
        padding=(8, 4),
    )
    style.map(
        "Accent.TButton",
        background=[("active", SEL_HOVER), ("pressed", SEL)],
        foreground=[("active", SEL_FG)],
    )

    style.configure(
        "TEntry",
        fieldbackground=SURFACE,
        foreground=FG,
        insertcolor=FG,
        bordercolor=BORDER,
        font=FONT_S,
    )
    style.configure(
        "Placeholder.TEntry",
        fieldbackground=SURFACE,
        foreground=FG3,
        insertcolor=FG,
        bordercolor=BORDER,
        font=FONT_S,
    )

    style.configure(
        "TScrollbar",
        background=SURFACE,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=FG3,
        gripcount=0,
    )
    style.map("TScrollbar", background=[("active", HOVER)])

    style.configure(
        "Treeview",
        background=PANEL,
        foreground=FG,
        fieldbackground=PANEL,
        bordercolor=BORDER,
        font=FONT_S,
        rowheight=22,
    )
    style.configure("Treeview.Heading", background=SURFACE, foreground=FG2, font=FONT_XS)
    style.map(
        "Treeview",
        background=[("selected", SEL)],
        foreground=[("selected", SEL_FG)],
    )

    style.configure("TSeparator", background=BORDER)

    style.configure(
        "TCheckbutton",
        background=BG,
        foreground=FG,
        font=FONT_S,
        indicatorcolor=SURFACE,
    )
    style.map("TCheckbutton", background=[("active", BG)], indicatorcolor=[("selected", SEL_FG)])

    style.configure(
        "TCombobox",
        fieldbackground=SURFACE,
        foreground=FG,
        background=SURFACE,
        arrowcolor=FG2,
        bordercolor=BORDER,
        font=FONT_S,
    )
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE)])

    style.configure(
        "TLabelframe",
        background=BG,
        bordercolor=BORDER,
        foreground=FG2,
    )
    style.configure("TLabelframe.Label", background=BG, foreground=FG2, font=FONT_S)


def cycle(root: tk.Tk) -> str:
    global _current_palette
    idx = _PALETTE_ORDER.index(_current_palette)
    _current_palette = _PALETTE_ORDER[(idx + 1) % len(_PALETTE_ORDER)]
    apply(root)
    return _current_palette


def set_theme(name: str, root: tk.Tk):
    if name in _PALETTES:
        global _current_palette
        _current_palette = name
        apply(root)


def current_name() -> str:
    return _current_palette


def kbd_label(parent, text: str) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        bg=SURFACE,
        fg=FG2,
        font=FONT_XS,
        padx=3,
        pady=1,
        relief="flat",
    )
