import tkinter as tk
from tkinter import ttk

from ui import theme

SHORTCUTS = [
    ("Navigation", [
        ("↑ ↓", "move in list"),
        ("→", "expand / enter dir"),
        ("←", "collapse / go up"),
        ("Enter", "jump to file list"),
        ("F", "focus search"),
        ("V", "toggle flat view"),
        ("Esc", "close overlay"),
    ]),
    ("Playback", [
        ("Space", "play / stop"),
        ("Tab", "toggle autoplay"),
    ]),
    ("Set management", [
        ("E", "add to active set"),
        ("Shift+E", "quick-add (pick set)"),
        ("N", "new set"),
        ("Q", "cycle set"),
        ("Delete", "remove from set"),
    ]),
    ("Panels", [
        ("C", "toggle clip editor"),
        ("X", "open export"),
        ("Ctrl+T", "cycle theme"),
        ("?", "this overlay"),
        ("Esc", "close editor"),
    ]),
]


class ShortcutsOverlay(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Keyboard Shortcuts")
        self.configure(bg=theme.BG)
        self.geometry("460x480")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        ttk.Label(self, text="Keyboard Shortcuts", style="Accent.TLabel", font=theme.FONT).pack(padx=12, pady=(10, 8))

        content = ttk.Frame(self)
        content.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)

        for i, (section, entries) in enumerate(SHORTCUTS):
            col = i % 2
            row_base = i // 2 * 20

            sec_frame = ttk.Frame(content)
            sec_frame.grid(row=row_base, column=col, sticky="nw", padx=(0 if col == 0 else 16, 0), pady=(8, 4))

            ttk.Label(sec_frame, text=section.upper(), style="Hint.TLabel").pack(anchor="w", pady=(0, 4))
            for key, desc in entries:
                row_frame = ttk.Frame(sec_frame)
                row_frame.pack(fill="x", pady=1)
                kl = theme.kbd_label(row_frame, key)
                kl.pack(side="left", padx=(0, 6))
                ttk.Label(row_frame, text=desc, style="Hint.TLabel").pack(side="left")

        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_set()
