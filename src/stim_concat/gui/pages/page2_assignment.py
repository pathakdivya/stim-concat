"""Page 2 -- generate the participant assignment sheet."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from ...assignment.base import AssignmentError
from ...assignment.registry import AlgorithmSpec, discover, run_source, user_dir
from ..app import WizardPage
from ..widgets import PAD, FormGrid, ScrolledText, Section, int_validator, make_tree


class AssignmentPage(WizardPage):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.specs: list[AlgorithmSpec] = []
        self.spec: AlgorithmSpec | None = None
        self.param_vars: dict[str, tk.Variable] = {}

        self.algorithm_var = tk.StringVar()
        self.participants_var = tk.StringVar(value="20")
        self.per_participant_var = tk.StringVar(value="8")
        self.seed_var = tk.StringVar(value="42")
        self.dirty = False
        self._build()

    # -- layout -------------------------------------------------------------
    def _build(self) -> None:
        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)

        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=2)
        panes.add(right, weight=3)

        # --- design ---------------------------------------------------------
        design = Section(left, "Design")
        design.pack(fill="x")
        form = FormGrid(design, label_width=20)
        form.pack(fill="x", padx=PAD, pady=PAD)

        self.algorithm_box = ttk.Combobox(form, textvariable=self.algorithm_var, state="readonly")
        self.algorithm_box.bind("<<ComboboxSelected>>", self._on_algorithm_change)
        form.add("Algorithm", self.algorithm_box)

        vint = int_validator(self)
        form.add(
            "Participants",
            ttk.Entry(form, textvariable=self.participants_var, validate="key", validatecommand=vint),
        )
        form.add(
            "Stimuli per participant",
            ttk.Entry(form, textvariable=self.per_participant_var, validate="key", validatecommand=vint),
        )
        form.add(
            "Random seed",
            ttk.Entry(form, textvariable=self.seed_var, validate="key", validatecommand=vint),
            hint="Leave blank for a different result every time. A fixed seed makes the "
            "sheet exactly reproducible.",
        )

        self.description = ttk.Label(design, text="", wraplength=380, foreground="#444444")
        self.description.pack(anchor="w", padx=PAD, pady=(0, PAD))

        # --- algorithm parameters -------------------------------------------
        self.params_section = Section(left, "Algorithm options")
        self.params_section.pack(fill="x", pady=(PAD, 0))
        self.params_frame = ttk.Frame(self.params_section, padding=PAD)
        self.params_frame.pack(fill="x")

        # --- result ----------------------------------------------------------
        result = Section(left, "Assignment sheet")
        result.pack(fill="both", expand=True, pady=(PAD, 0))
        holder = ttk.Frame(result, padding=PAD)
        holder.pack(fill="both", expand=True)

        buttons = ttk.Frame(holder)
        buttons.pack(fill="x")
        ttk.Button(
            buttons, text="Generate assignments", style="Primary.TButton", command=self.generate
        ).pack(side="left")
        ttk.Button(buttons, text="Export CSV...", command=self.export).pack(side="left", padx=PAD)
        ttk.Button(buttons, text="Import CSV...", command=self.import_csv).pack(side="left")

        self.tree_frame, self.tree = make_tree(holder, [("participant", "Participant", 110)], height=9)
        self.tree_frame.pack(fill="both", expand=True, pady=(PAD, 0))

        self.balance_label = ttk.Label(holder, text="", foreground="#555555", wraplength=380)
        self.balance_label.pack(anchor="w", pady=(PAD, 0))

        # --- script editor ----------------------------------------------------
        editor = Section(right, "Assignment script (this exact code is what runs)")
        editor.pack(fill="both", expand=True)
        editor_inner = ttk.Frame(editor, padding=PAD)
        editor_inner.pack(fill="both", expand=True)

        bar = ttk.Frame(editor_inner)
        bar.pack(fill="x")
        ttk.Button(bar, text="Reset to built-in", command=self.reload_script).pack(side="left")
        ttk.Button(bar, text="Load...", command=self.load_script).pack(side="left", padx=PAD)
        ttk.Button(bar, text="Save as...", command=self.save_script).pack(side="left")
        ttk.Button(bar, text="Save to my algorithms", command=self.save_to_user_dir).pack(
            side="left", padx=PAD
        )
        self.dirty_label = ttk.Label(bar, text="", foreground="#92400e")
        self.dirty_label.pack(side="right")

        self.editor = ScrolledText(editor_inner, height=26, width=88)
        self.editor.pack(fill="both", expand=True, pady=(PAD, 0))
        self.editor.text.bind("<<Modified>>", self._on_modified)

        ttk.Label(
            editor_inner,
            text="Edit freely, then press Generate. The script that runs is stored in the "
            "sheet's metadata file, so any result can be reproduced later.",
            foreground="#777777",
            wraplength=560,
        ).pack(anchor="w", pady=(PAD, 0))

    # -- algorithm handling ---------------------------------------------------
    def _refresh_algorithms(self) -> None:
        self.specs = discover()
        labels = [f"{s.name}{'' if s.builtin else '  (mine)'}" for s in self.specs]
        self.algorithm_box.configure(values=labels)
        keys = [s.key for s in self.specs]
        if self.state.algorithm_key in keys:
            index = keys.index(self.state.algorithm_key)
        else:
            index = 0
        if self.specs:
            self.algorithm_var.set(labels[index])
            self._select_spec(self.specs[index])

    def _current_spec(self) -> AlgorithmSpec | None:
        label = self.algorithm_var.get()
        for spec, text in zip(self.specs, self.algorithm_box.cget("values")):
            if text == label:
                return spec
        return self.specs[0] if self.specs else None

    def _on_algorithm_change(self, _event=None) -> None:
        spec = self._current_spec()
        if not spec:
            return
        if self.dirty and not messagebox.askyesno(
            "Discard edits?",
            "You have edited the current script. Switching algorithms will discard those "
            "changes. Continue?",
            parent=self,
        ):
            return
        self._select_spec(spec)

    def _select_spec(self, spec: AlgorithmSpec) -> None:
        self.spec = spec
        self.state.algorithm_key = spec.key
        self.description.configure(text=spec.description)
        self.editor.set_value(spec.source())
        self._set_dirty(False)
        self._build_params(spec)

    def _build_params(self, spec: AlgorithmSpec) -> None:
        for child in self.params_frame.winfo_children():
            child.destroy()
        self.param_vars.clear()

        if not spec.params:
            ttk.Label(
                self.params_frame, text="This algorithm has no options.", foreground="#777777"
            ).pack(anchor="w")
            return

        grid = FormGrid(self.params_frame, label_width=1)
        grid.pack(fill="x")
        for param in spec.params:
            name = param["name"]
            kind = param.get("type", "str")
            default = self.state.params.get(name, param.get("default"))
            label = param.get("label", name)

            if kind == "bool":
                var = tk.BooleanVar(value=bool(default))
                widget = ttk.Checkbutton(grid, text=label, variable=var)
                grid.add_row(widget)
            elif kind == "choice":
                var = tk.StringVar(value=str(default))
                widget = ttk.Combobox(
                    grid, textvariable=var, values=[str(c) for c in param.get("choices", [])],
                    state="readonly",
                )
                grid.add(label, widget)
            else:
                var = tk.StringVar(value="" if default is None else str(default))
                widget = ttk.Entry(grid, textvariable=var)
                grid.add(label, widget)
            self.param_vars[name] = var

    def _collect_params(self) -> dict:
        if not self.spec:
            return {}
        values: dict = {}
        for param in self.spec.params:
            name = param["name"]
            var = self.param_vars.get(name)
            if var is None:
                continue
            raw = var.get()
            kind = param.get("type", "str")
            try:
                if kind == "bool":
                    values[name] = bool(raw)
                elif kind == "int":
                    values[name] = int(raw) if str(raw).strip() else param.get("default")
                elif kind == "float":
                    values[name] = float(raw) if str(raw).strip() else param.get("default")
                else:
                    values[name] = raw
            except ValueError as exc:
                raise AssignmentError(
                    f"Option '{param.get('label', name)}' must be a number."
                ) from exc
        return values

    # -- script editing --------------------------------------------------------
    def _on_modified(self, _event=None) -> None:
        if self.editor.text.edit_modified():
            self._set_dirty(True)
            self.editor.text.edit_modified(False)

    def _set_dirty(self, value: bool) -> None:
        self.dirty = value
        self.dirty_label.configure(text="edited \u2022 not saved to file" if value else "")
        self.editor.text.edit_modified(False)

    def reload_script(self) -> None:
        if self.spec:
            self.editor.set_value(self.spec.source())
            self._set_dirty(False)
            self.status("Reloaded the built-in script.", "ok")

    def load_script(self) -> None:
        path = filedialog.askopenfilename(
            title="Load an assignment script", filetypes=[("Python", "*.py"), ("All files", "*.*")]
        )
        if path:
            self.editor.set_value(Path(path).read_text(encoding="utf-8"))
            self._set_dirty(True)
            self.status(f"Loaded {Path(path).name}.", "ok")

    def save_script(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save the assignment script",
            defaultextension=".py",
            initialfile=f"{self.spec.key if self.spec else 'assignment'}_edited.py",
            filetypes=[("Python", "*.py")],
        )
        if path:
            Path(path).write_text(self.editor.get_value(), encoding="utf-8")
            self._set_dirty(False)
            self.status(f"Saved to {path}.", "ok")

    def save_to_user_dir(self) -> None:
        """Install the edited script so it appears in the algorithm list."""
        folder = user_dir()
        folder.mkdir(parents=True, exist_ok=True)
        name = simpledialog.askstring(
            "Save algorithm",
            "File name (without .py):",
            initialvalue=f"{self.spec.key if self.spec else 'custom'}_edited",
            parent=self,
        )
        if not name:
            return
        path = folder / f"{name}.py"
        path.write_text(self.editor.get_value(), encoding="utf-8")
        self._set_dirty(False)
        self._refresh_algorithms()
        self.status(f"Saved to {path}. It now appears in the algorithm list.", "ok")

    # -- generation ------------------------------------------------------------
    def _read_int(self, var: tk.StringVar, label: str, minimum: int = 1) -> int:
        try:
            value = int(var.get())
        except ValueError as exc:
            raise AssignmentError(f"{label} must be a whole number.") from exc
        if value < minimum:
            raise AssignmentError(f"{label} must be at least {minimum}.")
        return value

    def generate(self) -> None:
        if not self.state.stimuli:
            self.status("Go back and choose a stimulus folder first.", "warn")
            return
        try:
            n = self._read_int(self.participants_var, "Participants")
            k = self._read_int(self.per_participant_var, "Stimuli per participant")
            seed_text = self.seed_var.get().strip()
            seed = int(seed_text) if seed_text else None
            params = self._collect_params()

            assignment = run_source(
                self.editor.get_value(),
                self.state.stimuli.ids,
                n,
                k,
                seed=seed,
                params=params,
                key=self.spec.key if self.spec else "custom",
                name=(self.spec.name if self.spec else "custom") + (" (edited)" if self.dirty else ""),
            )
        except AssignmentError as exc:
            self.status(str(exc), "error")
            messagebox.showerror("Assignment failed", str(exc), parent=self)
            return
        except Exception as exc:  # pragma: no cover - user scripts can do anything
            self.status(f"{type(exc).__name__}: {exc}", "error")
            messagebox.showerror("Assignment failed", f"{type(exc).__name__}: {exc}", parent=self)
            return

        self.state.assignment = assignment
        self.state.n_participants = n
        self.state.n_per_participant = k
        self.state.seed = seed
        self.state.params = params
        self.state.selected_participants = list(assignment.participants)
        self._show_assignment(assignment)
        self.status(
            f"Generated {assignment.n_participants} x {assignment.n_trials} assignments.", "ok"
        )

    def _show_assignment(self, assignment) -> None:
        self.tree_frame.destroy()
        columns = [("participant", "Participant", 100)] + [
            (f"t{i}", f"trial {i}", 70) for i in range(1, assignment.n_trials + 1)
        ]
        self.tree_frame, self.tree = make_tree(
            self.tree_frame.master, columns, height=9, stretch_last=False
        )
        self.tree_frame.pack(fill="both", expand=True, pady=(PAD, 0))
        for participant, row in assignment:
            self.tree.insert("", "end", values=(participant, *row))
        # keep the balance label at the bottom
        self.balance_label.pack_forget()
        self.balance_label.pack(anchor="w", pady=(PAD, 0))

        report = assignment.balance_report()
        text = (
            f"Each stimulus is used {report['min_uses']}\u2013{report['max_uses']} times "
            f"(mean {report['mean_uses']}); {report['coverage']:.0%} of the pool is used."
        )
        if report["unused_stimuli"]:
            text += f" {len(report['unused_stimuli'])} stimuli are never shown."
        if report["participants_with_repeats"]:
            text += f" {report['participants_with_repeats']} participant(s) see a repeated stimulus."
        if assignment.notes:
            text += f"\n{assignment.notes}"
        self.balance_label.configure(text=text)

    def export(self) -> None:
        if not self.state.assignment:
            self.status("Generate an assignment first.", "warn")
            return
        initial = str(self.state.stimulus_folder.parent) if self.state.stimulus_folder else "."
        path = filedialog.asksaveasfilename(
            title="Export the assignment sheet",
            defaultextension=".csv",
            initialfile="participant_assignments.csv",
            initialdir=initial,
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        self.state.assignment.to_csv(path)
        self.state.assignment_path = Path(path)
        self.status(f"Exported to {path} (with a metadata sidecar).", "ok")

    def import_csv(self) -> None:
        from ...assignment.base import Assignment

        path = filedialog.askopenfilename(
            title="Import an assignment sheet", filetypes=[("CSV", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            assignment = Assignment.from_csv(path)
        except (AssignmentError, OSError) as exc:
            messagebox.showerror("Could not read the sheet", str(exc), parent=self)
            return
        problems = assignment.validate(self.state.stimuli.ids if self.state.stimuli else None)
        if problems:
            messagebox.showwarning("Sheet warnings", "\n".join(problems), parent=self)
        self.state.assignment = assignment
        self.state.assignment_path = Path(path)
        self.state.selected_participants = list(assignment.participants)
        self._show_assignment(assignment)
        self.status(f"Imported {Path(path).name}.", "ok")

    # -- wizard hooks ------------------------------------------------------------
    def on_show(self) -> None:
        if not self.specs:
            self._refresh_algorithms()
        self.participants_var.set(str(self.state.n_participants))
        self.per_participant_var.set(str(self.state.n_per_participant))
        if self.state.seed is not None:
            self.seed_var.set(str(self.state.seed))
        if self.state.assignment:
            self._show_assignment(self.state.assignment)

    def validate(self) -> tuple[bool, str]:
        if not self.state.assignment:
            return False, "Generate or import an assignment sheet before continuing."
        return True, ""
