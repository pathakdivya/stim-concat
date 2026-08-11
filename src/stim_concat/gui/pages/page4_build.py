"""Page 4 -- preview timelines and build the videos."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ...core.ffmpeg import FFmpegError
from ...core.pipeline import build_all
from ...core.timeline import build_timeline
from ..app import WizardPage
from ..widgets import PAD, ScrolledText, Section, make_tree


class BuildPage(WizardPage):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.is_building = False
        self.cancel_event = threading.Event()
        self.messages: queue.Queue = queue.Queue()
        self.output_var = tk.StringVar()
        self.progress_var = tk.DoubleVar(value=0.0)
        self._timelines: dict[str, object] = {}
        self._build()

    # -- layout ---------------------------------------------------------------
    def _build(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="both", expand=True)

        # --- participants ---------------------------------------------------
        left = Section(top, "Participants")
        left.pack(side="left", fill="y")
        holder = ttk.Frame(left, padding=PAD)
        holder.pack(fill="both", expand=True)

        self.participant_list = tk.Listbox(holder, selectmode="extended", height=18, width=18,
                                           exportselection=False)
        self.participant_list.pack(fill="both", expand=True)
        self.participant_list.bind("<<ListboxSelect>>", lambda _e: self.show_timeline())

        buttons = ttk.Frame(holder)
        buttons.pack(fill="x", pady=(PAD, 0))
        ttk.Button(buttons, text="All", width=6, command=self.select_all).pack(side="left")
        ttk.Button(buttons, text="None", width=6, command=self.select_none).pack(side="left", padx=4)

        # --- timeline ---------------------------------------------------------
        right = ttk.Frame(top)
        right.pack(side="left", fill="both", expand=True, padx=(PAD, 0))

        preview = Section(right, "Timeline preview")
        preview.pack(fill="both", expand=True)
        inner = ttk.Frame(preview, padding=PAD)
        inner.pack(fill="both", expand=True)

        frame, self.timeline_tree = make_tree(
            inner,
            [
                ("start", "Start (s)", 80),
                ("end", "End (s)", 80),
                ("duration", "Duration (s)", 90),
                ("type", "Event type", 100),
                ("trial", "Trial", 55),
                ("stimulus", "Stimulus ID", 110),
                ("description", "Description", 220),
            ],
            height=13,
        )
        frame.pack(fill="both", expand=True)
        for tag, colour in (
            ("instruction", "#fff7e6"),
            ("fixation", "#eefaf0"),
            ("stimulus", "#eaf2fd"),
            ("blank", "#f4f4f4"),
        ):
            self.timeline_tree.tag_configure(tag, background=colour)

        self.timeline_summary = ttk.Label(inner, text="", foreground="#555555")
        self.timeline_summary.pack(anchor="w", pady=(PAD, 0))

        # --- output + build ------------------------------------------------------
        bottom = Section(self, "Build")
        bottom.pack(fill="x", pady=(PAD, 0))
        build_frame = ttk.Frame(bottom, padding=PAD)
        build_frame.pack(fill="x")

        row = ttk.Frame(build_frame)
        row.pack(fill="x")
        ttk.Label(row, text="Output folder", width=14).pack(side="left")
        ttk.Entry(row, textvariable=self.output_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._browse_output).pack(side="left", padx=(PAD, 0))

        controls = ttk.Frame(build_frame)
        controls.pack(fill="x", pady=(PAD, 0))
        self.build_button = ttk.Button(
            controls, text="Build videos", style="Primary.TButton", command=self.start_build
        )
        self.build_button.pack(side="left")
        self.cancel_button = ttk.Button(
            controls, text="Cancel", command=self.cancel_build, state="disabled"
        )
        self.cancel_button.pack(side="left", padx=PAD)
        self.estimate_label = ttk.Label(controls, text="", foreground="#555555")
        self.estimate_label.pack(side="left", padx=PAD)

        self.progress = ttk.Progressbar(build_frame, variable=self.progress_var, maximum=1.0)
        self.progress.pack(fill="x", pady=(PAD, 4))
        self.progress_label = ttk.Label(build_frame, text="", foreground="#555555")
        self.progress_label.pack(anchor="w")

        self.log = ScrolledText(build_frame, height=7, width=110)
        self.log.pack(fill="both", expand=True, pady=(PAD, 0))
        self.log.text.configure(state="disabled")

    # -- participants -----------------------------------------------------------
    def select_all(self) -> None:
        self.participant_list.selection_set(0, "end")
        self.show_timeline()

    def select_none(self) -> None:
        self.participant_list.selection_clear(0, "end")

    def _selected(self) -> list[str]:
        indices = self.participant_list.curselection()
        return [self.participant_list.get(i) for i in indices]

    def _browse_output(self) -> None:
        initial = self.output_var.get() or (
            str(self.state.stimulus_folder.parent) if self.state.stimulus_folder else "."
        )
        folder = filedialog.askdirectory(title="Choose the output folder", initialdir=initial)
        if folder:
            self.output_var.set(folder)

    # -- timeline preview ---------------------------------------------------------
    def show_timeline(self) -> None:
        selected = self._selected()
        if not selected or not self.state.assignment or not self.state.stimuli:
            return
        participant = selected[0]
        try:
            row = self.state.assignment.row_for(participant)
            timeline = build_timeline(participant, row, self.state.stimuli, self.state.config)
        except (KeyError, ValueError, FFmpegError) as exc:
            self.timeline_tree.delete(*self.timeline_tree.get_children())
            self.timeline_summary.configure(text=f"Cannot build this timeline: {exc}")
            self.status(str(exc), "error")
            return

        self._timelines[participant] = timeline
        self.timeline_tree.delete(*self.timeline_tree.get_children())
        for event in timeline:
            self.timeline_tree.insert(
                "",
                "end",
                values=(
                    f"{event.start:.3f}",
                    f"{event.end:.3f}",
                    f"{event.duration:.3f}",
                    event.event_type,
                    event.trial if event.trial is not None else "",
                    event.stimulus_id or "",
                    event.description,
                ),
                tags=(event.event_type,),
            )
        summary = timeline.summary()
        self.timeline_summary.configure(
            text=f"{participant}: {summary['n_events']} events, {summary['n_stimuli']} stimuli, "
            f"{timeline.duration:.2f} s ({timeline.duration / 60:.1f} min)"
        )
        self._update_estimate(timeline.duration, len(selected))

    def _update_estimate(self, one_duration: float, n_selected: int) -> None:
        total = one_duration * max(1, n_selected)
        self.estimate_label.configure(
            text=f"{n_selected} participant(s) selected \u2022 roughly {total / 60:.1f} min of video to render"
        )

    # -- building -------------------------------------------------------------------
    def start_build(self) -> None:
        if self.is_building:
            return
        participants = self._selected()
        if not participants:
            self.status("Select at least one participant to build.", "warn")
            return
        folder = self.output_var.get().strip()
        if not folder:
            self.status("Choose an output folder first.", "warn")
            return

        output = Path(folder)
        try:
            output.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Cannot write there", str(exc), parent=self)
            return

        existing = [p for p in participants if (output / f"{p}.{self.state.config.video.container}").exists()]
        if existing and not messagebox.askyesno(
            "Overwrite existing videos?",
            f"{len(existing)} video(s) already exist in that folder and will be overwritten:\n"
            + ", ".join(existing[:8])
            + ("..." if len(existing) > 8 else ""),
            parent=self,
        ):
            return

        self.state.output_folder = output
        self.state.selected_participants = participants
        self.state.save_session()

        self._set_building(True)
        self._clear_log()
        self._append_log(f"Building {len(participants)} participant video(s) into {output}\n")
        self.cancel_event = threading.Event()

        worker = threading.Thread(
            target=self._run_build, args=(participants, output), daemon=True
        )
        worker.start()
        self.after(100, self._drain_queue)

    def _run_build(self, participants, output) -> None:
        try:
            report = build_all(
                self.state.assignment,
                self.state.stimuli,
                self.state.config,
                output,
                participants=participants,
                progress=lambda fraction, message: self.messages.put(("progress", (fraction, message))),
                log=lambda message: self.messages.put(("log", message + "\n")),
                cancel_event=self.cancel_event,
            )
            self.messages.put(("done", report))
        except Exception as exc:  # pragma: no cover - surfaced in the UI
            self.messages.put(("error", f"{type(exc).__name__}: {exc}"))

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "progress":
                    fraction, message = payload
                    self.progress_var.set(fraction)
                    self.progress_label.configure(text=message)
                elif kind == "log":
                    self._append_log(payload)
                elif kind == "done":
                    self._on_finished(payload)
                    return
                elif kind == "error":
                    self._append_log(f"\nERROR: {payload}\n")
                    self.status(payload, "error")
                    messagebox.showerror("Build failed", payload, parent=self)
                    self._set_building(False)
                    return
        except queue.Empty:
            pass
        if self.is_building:
            self.after(100, self._drain_queue)

    def _on_finished(self, report) -> None:
        self.state.report = report
        self._set_building(False)
        self.progress_var.set(1.0)
        message = (
            f"Built {report.n_ok} of {len(report.results)} videos "
            f"({report.total_duration / 60:.1f} min of material)."
        )
        if report.cancelled:
            message = "Build cancelled. " + message
            level = "warn"
        elif report.n_failed:
            message += f" {report.n_failed} failed."
            level = "error"
        else:
            level = "ok"
        self._append_log("\n" + message + "\n")
        self.progress_label.configure(text=message)
        self.status(message + "  Press Next to see the summary.", level)

    def cancel_build(self) -> None:
        if self.is_building:
            self.cancel_event.set()
            self._append_log("\nCancelling after the current segment...\n")
            self.status("Cancelling...", "warn")

    def _set_building(self, value: bool) -> None:
        self.is_building = value
        self.build_button.configure(state="disabled" if value else "normal")
        self.cancel_button.configure(state="normal" if value else "disabled")
        self.app.next_button.configure(state="disabled" if value else "normal")
        self.app.back_button.configure(state="disabled" if value else "normal")

    def _clear_log(self) -> None:
        self.log.text.configure(state="normal")
        self.log.text.delete("1.0", "end")
        self.log.text.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log.text.configure(state="normal")
        self.log.append(text)
        self.log.text.configure(state="disabled")

    # -- wizard hooks -------------------------------------------------------------------
    def on_show(self) -> None:
        assignment = self.state.assignment
        self.participant_list.delete(0, "end")
        if not assignment:
            return
        for participant in assignment.participants:
            self.participant_list.insert("end", participant)
        self.participant_list.selection_set(0, "end")

        if not self.output_var.get():
            if self.state.output_folder:
                self.output_var.set(str(self.state.output_folder))
            elif self.state.stimulus_folder:
                self.output_var.set(str(self.state.stimulus_folder.parent / "stim_concat_output"))

        missing = self.state.stimuli.missing(
            [s for row in assignment.rows for s in row]
        ) if self.state.stimuli else []
        if missing:
            self.status(
                f"{len(missing)} assigned stimulus ID(s) are not in the folder: "
                + ", ".join(missing[:6]),
                "error",
            )
        self.show_timeline()

    def validate(self) -> tuple[bool, str]:
        if self.is_building:
            return False, "Wait for the build to finish, or cancel it."
        if not self.state.report:
            return False, "Build at least one video before continuing."
        return True, ""
