"""Page 1 -- select the stimulus folder."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ...core.ffmpeg import FFmpegError, probe
from ...core.scanner import (
    DEFAULT_ID_PATTERN,
    NUMERIC_ID_PATTERN,
    scan_folder,
    supported_extensions,
)
from ..app import WizardPage
from ..widgets import PAD, FormGrid, Section, make_tree

ID_PRESETS = {
    "Whole filename (clip_070_sad -> clip_070_sad)": DEFAULT_ID_PATTERN,
    "First number (clip_070_sad -> 070)": NUMERIC_ID_PATTERN,
    "Text before first underscore (sad_070 -> sad)": r"(?P<id>[^_]+)",
    "Text after last underscore (clip_070 -> 070)": r"(?P<id>[^_]+)$",
}


class StimuliPage(WizardPage):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.folder_var = tk.StringVar()
        self.pattern_var = tk.StringVar(value=DEFAULT_ID_PATTERN)
        self.preset_var = tk.StringVar(value=next(iter(ID_PRESETS)))
        self.recursive_var = tk.BooleanVar(value=False)
        self.durations_var = tk.BooleanVar(value=True)
        self._build()

    def _build(self) -> None:
        chooser = Section(self, "Stimulus folder")
        chooser.pack(fill="x")
        inner = ttk.Frame(chooser, padding=PAD)
        inner.pack(fill="x")
        inner.columnconfigure(0, weight=1)

        row = ttk.Frame(inner)
        row.pack(fill="x")
        entry = ttk.Entry(row, textvariable=self.folder_var)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._browse).pack(side="left", padx=(PAD, 0))
        ttk.Button(row, text="Rescan", command=self.rescan).pack(side="left", padx=(PAD, 0))

        form = FormGrid(inner, label_width=22)
        form.pack(fill="x", pady=(PAD, 0))

        preset = ttk.Combobox(
            form, textvariable=self.preset_var, values=list(ID_PRESETS), state="readonly"
        )
        preset.bind("<<ComboboxSelected>>", self._apply_preset)
        form.add("Stimulus ID from filename", preset)
        form.add(
            "Custom pattern",
            ttk.Entry(form, textvariable=self.pattern_var),
            hint="Regular expression with an 'id' capture group, applied to the filename "
            "without its extension.",
        )
        options = ttk.Frame(form)
        ttk.Checkbutton(
            options, text="Include sub-folders", variable=self.recursive_var, command=self.rescan
        ).pack(side="left")
        ttk.Checkbutton(
            options,
            text="Read media durations (slower for very large sets)",
            variable=self.durations_var,
            command=self.rescan,
        ).pack(side="left", padx=(PAD * 2, 0))
        form.add_row(options)

        listing = Section(self, "Detected stimuli")
        listing.pack(fill="both", expand=True, pady=(PAD, 0))
        holder = ttk.Frame(listing, padding=PAD)
        holder.pack(fill="both", expand=True)

        frame, self.tree = make_tree(
            holder,
            [
                ("id", "Stimulus ID", 180),
                ("kind", "Type", 80),
                ("duration", "Duration", 90),
                ("size", "Size", 110),
                ("file", "File", 320),
            ],
            height=14,
        )
        frame.pack(fill="both", expand=True)

        self.summary_label = ttk.Label(holder, text="", foreground="#555555")
        self.summary_label.pack(anchor="w", pady=(PAD, 0))
        self.warning_label = ttk.Label(holder, text="", foreground="#92400e", wraplength=940)
        self.warning_label.pack(anchor="w")

        formats = ", ".join(sorted(supported_extensions()))
        ttk.Label(
            self,
            text=f"Recognised formats: {formats}",
            foreground="#777777",
            wraplength=980,
        ).pack(anchor="w", pady=(PAD, 0))

    # -- actions ------------------------------------------------------------
    def _apply_preset(self, _event=None) -> None:
        self.pattern_var.set(ID_PRESETS[self.preset_var.get()])
        self.rescan()

    def _browse(self) -> None:
        initial = self.folder_var.get() or str(Path.home())
        folder = filedialog.askdirectory(title="Select the stimulus folder", initialdir=initial)
        if folder:
            self.folder_var.set(folder)
            self.rescan()

    def rescan(self) -> None:
        folder = self.folder_var.get().strip()
        if not folder:
            return
        try:
            stimuli = scan_folder(
                folder,
                id_pattern=self.pattern_var.get() or DEFAULT_ID_PATTERN,
                recursive=self.recursive_var.get(),
            )
        except (NotADirectoryError, FileNotFoundError) as exc:
            self.status(str(exc), "error")
            return
        except Exception as exc:  # invalid regex, permission errors, ...
            self.status(f"Could not scan the folder: {exc}", "error")
            return

        self.state.stimulus_folder = Path(folder)
        self.state.id_pattern = self.pattern_var.get()
        self.state.recursive = self.recursive_var.get()
        self.state.stimuli = stimuli
        self._fill_tree(stimuli)

    def _fill_tree(self, stimuli) -> None:
        self.tree.delete(*self.tree.get_children())
        show_durations = self.durations_var.get()
        total = 0.0
        unreadable = []

        for item in stimuli:
            duration = ""
            if show_durations and item.kind in ("video", "audio"):
                try:
                    info = probe(item.path)
                    if info.duration:
                        duration = f"{info.duration:.2f} s"
                        total += info.duration
                except (FFmpegError, FileNotFoundError, OSError):
                    duration = "unreadable"
                    unreadable.append(item.name)
            elif item.kind == "image":
                duration = "(still)"
            size = item.path.stat().st_size / 1_048_576
            self.tree.insert(
                "",
                "end",
                values=(item.stimulus_id, item.kind, duration, f"{size:.1f} MB", item.name),
            )

        counts = stimuli.counts_by_kind()
        parts = [f"{n} {kind}" for kind, n in sorted(counts.items())]
        summary = f"{len(stimuli)} stimuli" + (f"  ({', '.join(parts)})" if parts else "")
        if total:
            summary += f"  \u2022  {total / 60:.1f} min of material"
        self.summary_label.configure(text=summary)

        warnings = []
        if stimuli.duplicates:
            examples = ", ".join(list(stimuli.duplicates)[:5])
            warnings.append(
                f"{len(stimuli.duplicates)} duplicate stimulus ID(s) -- only the first file of "
                f"each is used: {examples}. Try a different ID pattern."
            )
        if unreadable:
            warnings.append(f"{len(unreadable)} file(s) could not be read: {', '.join(unreadable[:4])}")
        if not len(stimuli):
            warnings.append("No supported media files were found in this folder.")
        self.warning_label.configure(text="  ".join(warnings))

        if len(stimuli):
            self.status(f"Found {len(stimuli)} stimuli.", "ok")

    # -- wizard hooks -------------------------------------------------------
    def on_show(self) -> None:
        if self.state.stimulus_folder and not self.folder_var.get():
            self.folder_var.set(str(self.state.stimulus_folder))
            self.pattern_var.set(self.state.id_pattern)
            self.recursive_var.set(self.state.recursive)
            self.rescan()

    def validate(self) -> tuple[bool, str]:
        if not self.folder_var.get().strip():
            return False, "Choose a folder containing your stimulus files."
        if not self.state.stimuli or not len(self.state.stimuli):
            return False, "No stimuli were found in that folder."
        return True, ""
