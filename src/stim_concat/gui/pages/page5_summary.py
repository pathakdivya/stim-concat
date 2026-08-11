"""Page 5 -- review what was produced."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ...core.exporters import write_summary_csv
from ..app import WizardPage
from ..widgets import PAD, ScrolledText, Section, make_tree


class SummaryPage(WizardPage):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._build()

    def _build(self) -> None:
        headline = Section(self, "Result")
        headline.pack(fill="x")
        inner = ttk.Frame(headline, padding=PAD)
        inner.pack(fill="x")
        self.headline_label = ttk.Label(inner, text="", font=("TkDefaultFont", 12, "bold"))
        self.headline_label.pack(anchor="w")
        self.detail_label = ttk.Label(inner, text="", foreground="#555555", wraplength=940)
        self.detail_label.pack(anchor="w", pady=(4, 0))

        table = Section(self, "Participants")
        table.pack(fill="both", expand=True, pady=(PAD, 0))
        holder = ttk.Frame(table, padding=PAD)
        holder.pack(fill="both", expand=True)

        frame, self.tree = make_tree(
            holder,
            [
                ("participant", "Participant", 110),
                ("status", "Status", 90),
                ("duration", "Duration (s)", 100),
                ("events", "Events", 70),
                ("stimuli", "Stimuli", 70),
                ("message", "Notes", 380),
            ],
            height=10,
        )
        frame.pack(fill="both", expand=True)
        self.tree.tag_configure("ok", background="#eefaf0")
        self.tree.tag_configure("failed", background="#fdeeee")
        self.tree.tag_configure("cancelled", background="#fff7e6")
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())

        files = Section(self, "Files written per participant")
        files.pack(fill="x", pady=(PAD, 0))
        self.files_text = ScrolledText(files, height=6, width=110)
        self.files_text.pack(fill="x", padx=PAD, pady=PAD)
        self.files_text.text.configure(state="disabled")

        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(PAD, 0))
        ttk.Button(actions, text="Open output folder", command=self.open_folder).pack(side="left")
        ttk.Button(actions, text="Play selected video", command=self.open_selected).pack(
            side="left", padx=PAD
        )
        ttk.Button(actions, text="Export summary as CSV...", command=self.export_summary).pack(
            side="left"
        )
        ttk.Button(actions, text="Build more participants", command=self.back_to_build).pack(
            side="right"
        )

    # -- population -------------------------------------------------------------
    def on_show(self) -> None:
        report = self.state.report
        self.tree.delete(*self.tree.get_children())
        if not report:
            self.headline_label.configure(text="Nothing has been built yet.")
            self.detail_label.configure(text="Go back to step 4 and build some videos.")
            return

        for result in report.results:
            self.tree.insert(
                "",
                "end",
                values=(
                    result.participant,
                    result.status,
                    f"{result.duration_s:.2f}" if result.duration_s else "",
                    result.n_events or "",
                    result.n_stimuli or "",
                    result.message,
                ),
                tags=(result.status,),
            )

        ok = report.n_ok
        total = len(report.results)
        self.headline_label.configure(
            text=f"{ok} of {total} participant videos built"
            + (f"  \u2022  {report.n_failed} failed" if report.n_failed else "")
        )
        self.detail_label.configure(
            text=f"Output folder: {report.output_folder}    "
            f"Total material: {report.total_duration / 60:.1f} min    "
            f"Summary: {Path(report.summary_csv).name if report.summary_csv else '-'} and "
            f"{Path(report.summary_md).name if report.summary_md else '-'}"
        )

        example = next((r for r in report.results if r.status == "ok"), None)
        self.files_text.text.configure(state="normal")
        self.files_text.text.delete("1.0", "end")
        if example:
            lines = [f"For each participant (example: {example.participant}):"]
            for label, path in example.outputs.items():
                lines.append(f"  {label:<14} {Path(path).name}")
            lines.append("")
            lines.append(
                "The timeline files list every event with exact start and end times, so "
                "eye-tracking, joystick or physiological recordings can be aligned to the "
                "presented stimuli."
            )
            self.files_text.text.insert("1.0", "\n".join(lines))
        self.files_text.text.configure(state="disabled")

        self.status(
            "Done. The wizard can be closed, or go back to build more participants.",
            "ok" if not report.n_failed else "warn",
        )

    # -- actions -------------------------------------------------------------------
    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif os.name == "nt":  # pragma: no cover - Windows only
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror("Could not open", f"{path}\n\n{exc}", parent=self)

    def open_folder(self) -> None:
        if self.state.report and self.state.report.output_folder:
            self._open_path(self.state.report.output_folder)

    def open_selected(self) -> None:
        selection = self.tree.selection()
        if not selection or not self.state.report:
            return
        participant = str(self.tree.item(selection[0])["values"][0])
        for result in self.state.report.results:
            if result.participant == participant and result.video:
                self._open_path(result.video)
                return

    def export_summary(self) -> None:
        if not self.state.report:
            return
        path = filedialog.asksaveasfilename(
            title="Export the build summary",
            defaultextension=".csv",
            initialfile="build_summary.csv",
            filetypes=[("CSV", "*.csv")],
        )
        if path:
            write_summary_csv([r.as_row() for r in self.state.report.results], path)
            self.status(f"Summary exported to {path}.", "ok")

    def back_to_build(self) -> None:
        self.app.goto(3)
