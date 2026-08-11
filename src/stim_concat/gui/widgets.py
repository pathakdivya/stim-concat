"""Small reusable widgets for the wizard."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Iterable, Sequence
from tkinter import colorchooser, ttk
from tkinter import font as tkfont
from typing import Callable

PAD = 8

__all__ = [
    "ColourField",
    "FormGrid",
    "ImagePreview",
    "ScrolledText",
    "Section",
    "StatusBar",
    "float_validator",
    "int_validator",
    "mono_font",
]


def mono_font(size: int = 10) -> tkfont.Font:
    for family in ("Menlo", "Consolas", "DejaVu Sans Mono", "Courier New", "TkFixedFont"):
        try:
            return tkfont.Font(family=family, size=size)
        except tk.TclError:  # pragma: no cover - platform dependent
            continue
    return tkfont.nametofont("TkFixedFont")  # pragma: no cover


def int_validator(root: tk.Misc) -> tuple[str, str]:
    def check(value: str) -> bool:
        return value in ("", "-") or value.lstrip("-").isdigit()

    return (root.register(check), "%P")


def float_validator(root: tk.Misc) -> tuple[str, str]:
    def check(value: str) -> bool:
        if value in ("", "-", ".", "-."):
            return True
        try:
            float(value)
            return True
        except ValueError:
            return False

    return (root.register(check), "%P")


class Section(ttk.LabelFrame):
    """A titled group of settings."""

    def __init__(self, master, title: str, **kwargs):
        super().__init__(master, text=f" {title} ", **kwargs)
        self.columnconfigure(0, weight=1)


class FormGrid(ttk.Frame):
    """Two-column label/widget grid with consistent spacing."""

    def __init__(self, master, label_width: int = 26, **kwargs):
        super().__init__(master, **kwargs)
        self.label_width = label_width
        self.columnconfigure(1, weight=1)
        self._row = 0

    def add(self, label: str, widget: tk.Widget, hint: str | None = None) -> tk.Widget:
        ttk.Label(self, text=label, width=self.label_width, anchor="w").grid(
            row=self._row, column=0, sticky="w", padx=(0, PAD), pady=3
        )
        widget.grid(row=self._row, column=1, sticky="ew", pady=3)
        self._row += 1
        if hint:
            ttk.Label(self, text=hint, foreground="#666666", wraplength=520).grid(
                row=self._row, column=1, sticky="w", pady=(0, 4)
            )
            self._row += 1
        return widget

    def add_row(self, widget: tk.Widget) -> tk.Widget:
        widget.grid(row=self._row, column=0, columnspan=2, sticky="ew", pady=3)
        self._row += 1
        return widget

    def separator(self) -> None:
        ttk.Separator(self, orient="horizontal").grid(
            row=self._row, column=0, columnspan=2, sticky="ew", pady=PAD
        )
        self._row += 1


class ColourField(ttk.Frame):
    """Hex entry plus a swatch that opens the system colour chooser."""

    def __init__(self, master, variable: tk.StringVar, on_change: Callable[[], None] | None = None):
        super().__init__(master)
        self.variable = variable
        self.on_change = on_change
        self.entry = ttk.Entry(self, textvariable=variable, width=10)
        self.entry.pack(side="left")
        self.swatch = tk.Canvas(self, width=26, height=20, highlightthickness=1, cursor="hand2")
        self.swatch.pack(side="left", padx=(6, 0))
        self.swatch.bind("<Button-1>", self._choose)
        ttk.Button(self, text="Pick...", width=7, command=self._choose).pack(side="left", padx=(6, 0))
        variable.trace_add("write", lambda *_: self._refresh())
        self._refresh()

    def _refresh(self) -> None:
        colour = self.variable.get().strip() or "#000000"
        try:
            self.swatch.configure(background=colour)
        except tk.TclError:
            self.swatch.configure(background="#000000")
        if self.on_change:
            self.on_change()

    def _choose(self, _event=None) -> None:
        current = self.variable.get().strip() or "#000000"
        try:
            _, hex_value = colorchooser.askcolor(color=current, parent=self)
        except tk.TclError:  # pragma: no cover - platform dependent
            return
        if hex_value:
            self.variable.set(hex_value.upper())


class ScrolledText(ttk.Frame):
    """Text widget with vertical and horizontal scrollbars."""

    def __init__(self, master, *, height: int = 20, width: int = 80, mono: bool = True, **kwargs):
        super().__init__(master)
        self.text = tk.Text(
            self,
            height=height,
            width=width,
            wrap="none" if mono else "word",
            undo=True,
            maxundo=-1,
            **kwargs,
        )
        if mono:
            self.text.configure(font=mono_font(10), tabs="1c")
        y = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        x = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def get_value(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set_value(self, value: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self.text.edit_reset()

    def append(self, value: str) -> None:
        self.text.insert("end", value)
        self.text.see("end")


class ImagePreview(ttk.Frame):
    """Displays a PIL image scaled to fit, with a caption."""

    def __init__(self, master, width: int = 320, height: int = 180, caption: str = ""):
        super().__init__(master)
        self.max_width, self.max_height = width, height
        self.canvas = tk.Canvas(
            self, width=width, height=height, background="#222222", highlightthickness=1
        )
        self.canvas.pack()
        self.caption = ttk.Label(self, text=caption, foreground="#666666")
        self.caption.pack(pady=(2, 0))
        self._photo = None

    def show(self, image, caption: str | None = None) -> None:
        try:
            from PIL import Image, ImageTk
        except ImportError:  # pragma: no cover - Pillow is a dependency
            self.canvas.create_text(
                self.max_width / 2, self.max_height / 2, text="Pillow not installed", fill="white"
            )
            return
        preview = image.copy()
        preview.thumbnail((self.max_width - 8, self.max_height - 8), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(preview)
        self.canvas.delete("all")
        self.canvas.create_image(self.max_width / 2, self.max_height / 2, image=self._photo)
        if caption is not None:
            self.caption.configure(text=caption)

    def show_message(self, message: str) -> None:
        self.canvas.delete("all")
        self.canvas.create_text(
            self.max_width / 2,
            self.max_height / 2,
            text=message,
            fill="#cccccc",
            width=self.max_width - 20,
            justify="center",
        )


class StatusBar(ttk.Frame):
    """One-line status message with an optional severity colour."""

    COLOURS = {"info": "#333333", "ok": "#166534", "warn": "#92400e", "error": "#991b1b"}

    def __init__(self, master):
        super().__init__(master)
        self.label = ttk.Label(self, text="", anchor="w")
        self.label.pack(fill="x")

    def set(self, message: str, level: str = "info") -> None:
        self.label.configure(text=message, foreground=self.COLOURS.get(level, "#333333"))

    def clear(self) -> None:
        self.label.configure(text="")


def fill_tree(tree: ttk.Treeview, rows: Iterable[Sequence], *, clear: bool = True) -> None:
    """Replace a Treeview's contents."""
    if clear:
        tree.delete(*tree.get_children())
    for row in rows:
        tree.insert("", "end", values=tuple(row))


def make_tree(
    master, columns: Sequence[tuple[str, str, int]], height: int = 10, stretch_last: bool = True
) -> tuple[ttk.Frame, ttk.Treeview]:
    """Create a Treeview with headings, widths and a vertical scrollbar."""
    frame = ttk.Frame(master)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height)
    for index, (key, heading, width) in enumerate(columns):
        tree.heading(key, text=heading)
        last = index == len(columns) - 1
        tree.column(
            key,
            width=width,
            anchor="w",
            stretch=stretch_last and last,
            minwidth=max(40, width // 2),
        )
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return frame, tree
