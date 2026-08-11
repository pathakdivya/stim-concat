"""Page 3 -- configure fixation, instructions, presentation and video settings."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ...core.config import ANCHORS, BuildConfig, resolve_font
from ...core.screens import (
    PillowUnavailable,
    render_blank_screen,
    render_fixation_screen,
    render_text_screen,
)
from ..app import WizardPage
from ..widgets import (
    PAD,
    ColourField,
    FormGrid,
    ImagePreview,
    ScrolledText,
    Section,
    float_validator,
    int_validator,
    make_tree,
)

RESOLUTIONS = {
    "1920 x 1080 (Full HD)": (1920, 1080),
    "1280 x 720 (HD)": (1280, 720),
    "1024 x 768 (4:3)": (1024, 768),
    "800 x 600 (4:3)": (800, 600),
    "3840 x 2160 (4K)": (3840, 2160),
    "Custom": (0, 0),
}

FIT_MODES = {
    "contain -- fit inside, keep aspect ratio": "contain",
    "cover -- fill the screen, crop overflow": "cover",
    "stretch -- distort to fill the screen": "stretch",
    "none -- original pixel size": "none",
}

SEQUENCE_ELEMENTS = ("fixation", "instruction", "stimulus", "blank")


class SettingsPage(WizardPage):
    """A tabbed settings page; every control writes straight into BuildConfig."""

    def __init__(self, master, app):
        super().__init__(master, app)
        self.vars: dict[str, tk.Variable] = {}
        self._preview_job: str | None = None
        self._build()

    # -- helpers -------------------------------------------------------------
    def _var(self, key: str, value, kind=tk.StringVar) -> tk.Variable:
        var = kind(value=value)
        var.trace_add("write", lambda *_: self._schedule_preview())
        self.vars[key] = var
        return var

    def _get_int(self, key: str, fallback: int) -> int:
        try:
            return int(str(self.vars[key].get()).strip())
        except (ValueError, KeyError):
            return fallback

    def _get_float(self, key: str, fallback: float) -> float:
        try:
            return float(str(self.vars[key].get()).strip())
        except (ValueError, KeyError):
            return fallback

    # -- layout ---------------------------------------------------------------
    def _build(self) -> None:
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(side="left", fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self._schedule_preview())

        side = ttk.Frame(outer, padding=(PAD * 2, 0, 0, 0))
        side.pack(side="right", fill="y")
        ttk.Label(side, text="Live preview", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.preview = ImagePreview(side, width=330, height=186)
        self.preview.pack(pady=(PAD, 0))
        self.preview_choice = tk.StringVar(value="Fixation cross")
        chooser = ttk.Combobox(
            side,
            textvariable=self.preview_choice,
            values=["Fixation cross", "Opening instructions", "Default instruction", "Closing screen", "Blank"],
            state="readonly",
            width=28,
        )
        chooser.pack(pady=(PAD, 0))
        chooser.bind("<<ComboboxSelected>>", lambda _e: self._schedule_preview())
        ttk.Label(
            side,
            text="Screens are drawn exactly as they will appear in the video.",
            wraplength=250,
            foreground="#777777",
        ).pack(anchor="w", pady=(PAD, 0))

        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=PAD * 2)
        ttk.Label(side, text="Settings file", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        ttk.Button(side, text="Save settings...", command=self.save_settings).pack(
            fill="x", pady=(PAD, 4)
        )
        ttk.Button(side, text="Load settings...", command=self.load_settings).pack(fill="x")
        ttk.Button(side, text="Reset to defaults", command=self.reset_settings).pack(
            fill="x", pady=(4, 0)
        )

        self._build_sequence_tab()
        self._build_fixation_tab()
        self._build_instruction_tab()
        self._build_presentation_tab()
        self._build_video_tab()

    # -- tab: trial sequence ---------------------------------------------------
    def _build_sequence_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text="Trial order")

        ttk.Label(
            tab,
            text="Each trial plays the elements below in order. The opening and closing "
            "screens are added once, around the whole session.",
            wraplength=560,
        ).pack(anchor="w", pady=(0, PAD))

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True)

        left = Section(body, "Repeated for every trial")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, PAD))
        right = Section(body, "After the last trial")
        right.grid(row=0, column=1, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self.trial_list = self._sequence_editor(left)
        self.trailing_list = self._sequence_editor(right)

        self.sequence_hint = ttk.Label(tab, text="", foreground="#555555", wraplength=560)
        self.sequence_hint.pack(anchor="w", pady=(PAD, 0))

    def _sequence_editor(self, parent) -> tk.Listbox:
        holder = ttk.Frame(parent, padding=PAD)
        holder.pack(fill="both", expand=True)
        listbox = tk.Listbox(holder, height=7, exportselection=False)
        listbox.pack(fill="both", expand=True)

        controls = ttk.Frame(holder)
        controls.pack(fill="x", pady=(PAD, 0))
        adder = ttk.Combobox(controls, values=list(SEQUENCE_ELEMENTS), state="readonly", width=12)
        adder.set("fixation")
        adder.pack(side="left")

        def add() -> None:
            listbox.insert("end", adder.get())
            self._update_sequence_hint()

        def remove() -> None:
            for index in reversed(listbox.curselection()):
                listbox.delete(index)
            self._update_sequence_hint()

        def move(delta: int) -> None:
            selection = listbox.curselection()
            if not selection:
                return
            index = selection[0]
            target = index + delta
            if not 0 <= target < listbox.size():
                return
            value = listbox.get(index)
            listbox.delete(index)
            listbox.insert(target, value)
            listbox.selection_set(target)
            self._update_sequence_hint()

        ttk.Button(controls, text="Add", width=5, command=add).pack(side="left", padx=(4, 0))
        ttk.Button(controls, text="Remove", width=7, command=remove).pack(side="left", padx=(4, 0))
        ttk.Button(controls, text="\u2191", width=3, command=lambda: move(-1)).pack(side="left", padx=(4, 0))
        ttk.Button(controls, text="\u2193", width=3, command=lambda: move(1)).pack(side="left")
        return listbox

    def _update_sequence_hint(self) -> None:
        trial = list(self.trial_list.get(0, "end"))
        trailing = list(self.trailing_list.get(0, "end"))
        preview = " \u2192 ".join(trial) or "(empty)"
        text = f"Trial 1: {preview}   |   Trial 2: {preview}   |   after the last trial: "
        text += " \u2192 ".join(trailing) or "(nothing)"
        if "stimulus" not in trial:
            text += "\n\u26a0 The trial sequence must include 'stimulus'."
        self.sequence_hint.configure(text=text)

    # -- tab: fixation ----------------------------------------------------------
    def _build_fixation_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text="Fixation")
        form = FormGrid(tab, label_width=24)
        form.pack(fill="x")

        vint, vfloat = int_validator(self), float_validator(self)
        form.add_row(
            ttk.Checkbutton(
                form, text="Show a fixation cross", variable=self._var("fix_enabled", True, tk.BooleanVar)
            )
        )
        form.add("Duration (s)", ttk.Entry(form, textvariable=self._var("fix_duration", "1.0"),
                                           validate="key", validatecommand=vfloat, width=12))
        form.add("Size (px)", ttk.Entry(form, textvariable=self._var("fix_size", "40"),
                                        validate="key", validatecommand=vint, width=12))
        form.add("Line thickness (px)", ttk.Entry(form, textvariable=self._var("fix_thickness", "4"),
                                                  validate="key", validatecommand=vint, width=12))
        form.add("Colour", ColourField(form, self._var("fix_colour", "#FFFFFF")))
        form.add("Background", ColourField(form, self._var("fix_background", "#000000")))
        form.add("Screen position",
                 ttk.Combobox(form, textvariable=self._var("fix_position", "center"),
                              values=list(ANCHORS), state="readonly", width=16))
        offsets = ttk.Frame(form)
        ttk.Label(offsets, text="x").pack(side="left")
        ttk.Entry(offsets, textvariable=self._var("fix_offset_x", "0"), width=7,
                  validate="key", validatecommand=vint).pack(side="left", padx=(4, PAD))
        ttk.Label(offsets, text="y").pack(side="left")
        ttk.Entry(offsets, textvariable=self._var("fix_offset_y", "0"), width=7,
                  validate="key", validatecommand=vint).pack(side="left", padx=(4, 0))
        form.add("Nudge from position (px)", offsets)

    # -- tab: instructions --------------------------------------------------------
    def _build_instruction_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text="Instructions")

        notebook = ttk.Notebook(tab)
        notebook.pack(fill="both", expand=True)

        vfloat, vint = float_validator(self), int_validator(self)

        # opening / closing / interleaved --------------------------------------
        for key, label, default_text, default_duration, enabled_label in (
            ("opening", "Opening", "Welcome.", "8.0", "Show opening instructions"),
            ("closing", "Closing", "Thank you.", "5.0", "Show a closing screen"),
        ):
            frame = ttk.Frame(notebook, padding=PAD)
            notebook.add(frame, text=label)
            ttk.Checkbutton(
                frame, text=enabled_label, variable=self._var(f"instr_{key}_enabled", True, tk.BooleanVar)
            ).pack(anchor="w")
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=(PAD, 0))
            ttk.Label(row, text="Duration (s)").pack(side="left")
            ttk.Entry(row, textvariable=self._var(f"instr_{key}_duration", default_duration),
                      width=8, validate="key", validatecommand=vfloat).pack(side="left", padx=(PAD, 0))
            editor = ScrolledText(frame, height=9, width=64, mono=False)
            editor.pack(fill="both", expand=True, pady=(PAD, 0))
            editor.set_value(default_text)
            editor.text.bind("<KeyRelease>", lambda _e: self._schedule_preview())
            setattr(self, f"{key}_editor", editor)

        frame = ttk.Frame(notebook, padding=PAD)
        notebook.add(frame, text="Before each stimulus")
        ttk.Checkbutton(
            frame,
            text="Show an instruction before every stimulus "
            "(only used when 'instruction' is in the trial order)",
            variable=self._var("instr_interleaved_enabled", True, tk.BooleanVar),
        ).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(PAD, 0))
        ttk.Label(row, text="Duration (s)").pack(side="left")
        ttk.Entry(row, textvariable=self._var("instr_default_duration", "3.0"), width=8,
                  validate="key", validatecommand=vfloat).pack(side="left", padx=(PAD, 0))
        self.default_editor = ScrolledText(frame, height=6, width=64, mono=False)
        self.default_editor.pack(fill="both", expand=True, pady=(PAD, 0))
        self.default_editor.set_value("Watch the next clip.")
        self.default_editor.text.bind("<KeyRelease>", lambda _e: self._schedule_preview())

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=PAD)
        ttk.Label(
            frame,
            text="Per-stimulus overrides replace the default text for individual stimuli.",
            foreground="#555555",
        ).pack(anchor="w")
        override_row = ttk.Frame(frame)
        override_row.pack(fill="both", expand=True, pady=(4, 0))
        tree_frame, self.override_tree = make_tree(
            override_row,
            [("stimulus", "Stimulus", 120), ("duration", "Duration", 80), ("text", "Text", 360)],
            height=5,
        )
        tree_frame.pack(side="left", fill="both", expand=True)
        buttons = ttk.Frame(override_row)
        buttons.pack(side="left", fill="y", padx=(PAD, 0))
        ttk.Button(buttons, text="Add / edit...", command=self.edit_override).pack(fill="x")
        ttk.Button(buttons, text="Remove", command=self.remove_override).pack(fill="x", pady=(4, 0))
        self.override_tree.bind("<Double-1>", lambda _e: self.edit_override())

        # typography ------------------------------------------------------------
        frame = ttk.Frame(notebook, padding=PAD)
        notebook.add(frame, text="Appearance")
        form = FormGrid(frame, label_width=22)
        form.pack(fill="x")
        form.add("Text colour", ColourField(form, self._var("instr_colour", "#FFFFFF")))
        form.add("Background", ColourField(form, self._var("instr_background", "#000000")))
        form.add("Font size (px)", ttk.Entry(form, textvariable=self._var("instr_font_size", "48"),
                                             width=10, validate="key", validatecommand=vint))
        form.add("Line spacing (px)", ttk.Entry(form, textvariable=self._var("instr_line_spacing", "12"),
                                                width=10, validate="key", validatecommand=vint))
        form.add("Wrap after (characters)", ttk.Entry(form, textvariable=self._var("instr_wrap", "46"),
                                                      width=10, validate="key", validatecommand=vint))
        form.add("Alignment", ttk.Combobox(form, textvariable=self._var("instr_align", "center"),
                                           values=["center", "left"], state="readonly", width=10))
        font_row = ttk.Frame(form)
        ttk.Entry(font_row, textvariable=self._var("instr_font_file", "")).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(font_row, text="Browse...", command=self._choose_font).pack(side="left", padx=(4, 0))
        form.add("Font file (.ttf)", font_row,
                 hint=f"Leave blank to use the bundled default ({Path(resolve_font() or '(none found)').name}).")

    def _choose_font(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a font", filetypes=[("TrueType font", "*.ttf *.ttc *.otf"), ("All", "*.*")]
        )
        if path:
            self.vars["instr_font_file"].set(path)

    def edit_override(self) -> None:
        stimuli = self.state.stimuli
        if not stimuli:
            return
        selection = self.override_tree.selection()
        current_id = self.override_tree.item(selection[0])["values"][0] if selection else ""
        dialog = OverrideDialog(self, stimuli.ids, self.state.config, str(current_id))
        self.wait_window(dialog)
        if dialog.result:
            stimulus_id, text, duration = dialog.result
            self.state.config.instructions.per_stimulus[stimulus_id] = {
                "text": text,
                "duration": duration,
            }
            self._refresh_overrides()

    def remove_override(self) -> None:
        for item in self.override_tree.selection():
            stimulus_id = str(self.override_tree.item(item)["values"][0])
            self.state.config.instructions.per_stimulus.pop(stimulus_id, None)
        self._refresh_overrides()

    def _refresh_overrides(self) -> None:
        self.override_tree.delete(*self.override_tree.get_children())
        for stimulus_id, data in sorted(self.state.config.instructions.per_stimulus.items()):
            text = str(data.get("text", "")).replace("\n", " / ")
            self.override_tree.insert(
                "", "end", values=(stimulus_id, f"{float(data.get('duration', 3)):.1f} s", text[:120])
            )

    # -- tab: presentation ----------------------------------------------------------
    def _build_presentation_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text="Stimulus presentation")
        form = FormGrid(tab, label_width=26)
        form.pack(fill="x")
        vint, vfloat = int_validator(self), float_validator(self)

        form.add("Scaling behaviour",
                 ttk.Combobox(form, textvariable=self._var("fit_label", next(iter(FIT_MODES))),
                              values=list(FIT_MODES), state="readonly", width=40))
        form.add("Position on screen",
                 ttk.Combobox(form, textvariable=self._var("layout_position", "center"),
                              values=list(ANCHORS), state="readonly", width=16))
        offsets = ttk.Frame(form)
        ttk.Label(offsets, text="x").pack(side="left")
        ttk.Entry(offsets, textvariable=self._var("layout_offset_x", "0"), width=7,
                  validate="key", validatecommand=vint).pack(side="left", padx=(4, PAD))
        ttk.Label(offsets, text="y").pack(side="left")
        ttk.Entry(offsets, textvariable=self._var("layout_offset_y", "0"), width=7,
                  validate="key", validatecommand=vint).pack(side="left", padx=(4, 0))
        form.add("Nudge from position (px)", offsets)
        form.add("Extra scale factor",
                 ttk.Entry(form, textvariable=self._var("layout_scale", "1.0"), width=10,
                           validate="key", validatecommand=vfloat),
                 hint="Applied after fitting; 0.5 shows the stimulus at half size.")
        form.add("Background colour", ColourField(form, self._var("layout_background", "#000000")))
        form.separator()
        form.add("Still image duration (s)",
                 ttk.Entry(form, textvariable=self._var("layout_image_duration", "4.0"), width=10,
                           validate="key", validatecommand=vfloat))
        form.add("Audio-only background", ColourField(form, self._var("layout_audio_background", "#000000")))
        form.add("Audio-only caption",
                 ttk.Entry(form, textvariable=self._var("layout_audio_caption", "")),
                 hint="Text shown on screen while an audio-only stimulus plays. Leave blank for none.")
        form.separator()
        form.add("Blank screen duration (s)",
                 ttk.Entry(form, textvariable=self._var("blank_duration", "0.5"), width=10,
                           validate="key", validatecommand=vfloat))
        form.add("Blank screen colour", ColourField(form, self._var("blank_background", "#000000")))

    # -- tab: video --------------------------------------------------------------------
    def _build_video_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text="Video")
        form = FormGrid(tab, label_width=24)
        form.pack(fill="x")
        vint, vfloat = int_validator(self), float_validator(self)

        resolution = ttk.Combobox(form, textvariable=self._var("resolution", "1280 x 720 (HD)"),
                                  values=list(RESOLUTIONS), state="readonly", width=26)
        resolution.bind("<<ComboboxSelected>>", self._apply_resolution)
        form.add("Output resolution", resolution)
        size_row = ttk.Frame(form)
        ttk.Entry(size_row, textvariable=self._var("width", "1280"), width=8,
                  validate="key", validatecommand=vint).pack(side="left")
        ttk.Label(size_row, text="\u00d7").pack(side="left", padx=4)
        ttk.Entry(size_row, textvariable=self._var("height", "720"), width=8,
                  validate="key", validatecommand=vint).pack(side="left")
        form.add("Width \u00d7 height (px)", size_row, hint="Both must be even numbers.")
        form.add("Frame rate (fps)",
                 ttk.Entry(form, textvariable=self._var("fps", "30"), width=10,
                           validate="key", validatecommand=vfloat))
        form.separator()
        form.add("Video codec",
                 ttk.Combobox(form, textvariable=self._var("video_codec", "libx264"),
                              values=["libx264", "libx265", "mpeg4"], width=14))
        form.add("Quality (CRF, lower = better)",
                 ttk.Entry(form, textvariable=self._var("crf", "20"), width=10,
                           validate="key", validatecommand=vint))
        form.add("Encoding preset",
                 ttk.Combobox(form, textvariable=self._var("preset", "medium"),
                              values=["ultrafast", "veryfast", "fast", "medium", "slow", "veryslow"],
                              state="readonly", width=14))
        form.add("Bitrate (overrides CRF)",
                 ttk.Entry(form, textvariable=self._var("video_bitrate", ""), width=14),
                 hint="For example 4M. Leave blank to use constant quality.")
        form.separator()
        form.add_row(ttk.Checkbutton(form, text="Preserve the original stimulus audio",
                                     variable=self._var("preserve_audio", True, tk.BooleanVar)))
        form.add("Audio codec",
                 ttk.Combobox(form, textvariable=self._var("audio_codec", "aac"),
                              values=["aac", "libmp3lame", "pcm_s16le"], width=14))
        form.add("Audio bitrate", ttk.Entry(form, textvariable=self._var("audio_bitrate", "192k"), width=14))
        form.add("Sample rate (Hz)",
                 ttk.Combobox(form, textvariable=self._var("sample_rate", "48000"),
                              values=["44100", "48000"], width=14))
        form.add("Channels",
                 ttk.Combobox(form, textvariable=self._var("audio_channels", "2"),
                              values=["1", "2"], state="readonly", width=14))
        form.separator()
        form.add_row(ttk.Checkbutton(form, text="Keep the intermediate segment files (for debugging)",
                                     variable=self._var("keep_segments", False, tk.BooleanVar)))

    def _apply_resolution(self, _event=None) -> None:
        width, height = RESOLUTIONS.get(self.vars["resolution"].get(), (0, 0))
        if width:
            self.vars["width"].set(str(width))
            self.vars["height"].set(str(height))

    # -- config <-> widgets -----------------------------------------------------------
    def load_from_config(self) -> None:
        config = self.state.config
        v, fx, ins, lay, tl = (
            config.video, config.fixation, config.instructions, config.layout, config.timeline
        )
        setters = {
            "fix_enabled": fx.enabled, "fix_duration": fx.duration, "fix_size": fx.size,
            "fix_thickness": fx.thickness, "fix_colour": fx.color, "fix_background": fx.background,
            "fix_position": fx.position, "fix_offset_x": fx.offset_x, "fix_offset_y": fx.offset_y,
            "instr_opening_enabled": ins.opening_enabled, "instr_opening_duration": ins.opening_duration,
            "instr_closing_enabled": ins.closing_enabled, "instr_closing_duration": ins.closing_duration,
            "instr_interleaved_enabled": ins.interleaved_enabled,
            "instr_default_duration": ins.default_duration,
            "instr_colour": ins.font_color, "instr_background": ins.background,
            "instr_font_size": ins.font_size, "instr_line_spacing": ins.line_spacing,
            "instr_wrap": ins.max_chars_per_line, "instr_align": ins.align,
            "instr_font_file": ins.font_file,
            "layout_position": lay.position, "layout_offset_x": lay.offset_x,
            "layout_offset_y": lay.offset_y, "layout_scale": lay.scale,
            "layout_background": lay.background, "layout_image_duration": lay.image_duration,
            "layout_audio_background": lay.audio_background, "layout_audio_caption": lay.audio_caption,
            "blank_duration": tl.blank_duration, "blank_background": tl.blank_background,
            "width": v.width, "height": v.height, "fps": v.fps, "video_codec": v.video_codec,
            "crf": v.crf, "preset": v.preset, "video_bitrate": v.video_bitrate,
            "preserve_audio": v.preserve_audio, "audio_codec": v.audio_codec,
            "audio_bitrate": v.audio_bitrate, "sample_rate": v.sample_rate,
            "audio_channels": v.audio_channels, "keep_segments": config.keep_segments,
        }
        for key, value in setters.items():
            if key in self.vars:
                self.vars[key].set(value if isinstance(self.vars[key], tk.BooleanVar) else str(value))

        for label, mode in FIT_MODES.items():
            if mode == lay.fit:
                self.vars["fit_label"].set(label)
        for label, (width, height) in RESOLUTIONS.items():
            if (width, height) == (v.width, v.height):
                self.vars["resolution"].set(label)
                break
        else:
            self.vars["resolution"].set("Custom")

        self.opening_editor.set_value(ins.opening_text)
        self.closing_editor.set_value(ins.closing_text)
        self.default_editor.set_value(ins.default_text)

        for listbox, values in (
            (self.trial_list, tl.trial_sequence),
            (self.trailing_list, tl.trailing_sequence),
        ):
            listbox.delete(0, "end")
            for value in values:
                listbox.insert("end", value)
        self._update_sequence_hint()
        self._refresh_overrides()

    def save_to_config(self) -> BuildConfig:
        config = self.state.config
        v, fx, ins, lay, tl = (
            config.video, config.fixation, config.instructions, config.layout, config.timeline
        )

        fx.enabled = bool(self.vars["fix_enabled"].get())
        fx.duration = self._get_float("fix_duration", 1.0)
        fx.size = self._get_int("fix_size", 40)
        fx.thickness = self._get_int("fix_thickness", 4)
        fx.color = self.vars["fix_colour"].get()
        fx.background = self.vars["fix_background"].get()
        fx.position = self.vars["fix_position"].get()
        fx.offset_x = self._get_int("fix_offset_x", 0)
        fx.offset_y = self._get_int("fix_offset_y", 0)

        ins.opening_enabled = bool(self.vars["instr_opening_enabled"].get())
        ins.opening_text = self.opening_editor.get_value()
        ins.opening_duration = self._get_float("instr_opening_duration", 8.0)
        ins.closing_enabled = bool(self.vars["instr_closing_enabled"].get())
        ins.closing_text = self.closing_editor.get_value()
        ins.closing_duration = self._get_float("instr_closing_duration", 5.0)
        ins.interleaved_enabled = bool(self.vars["instr_interleaved_enabled"].get())
        ins.default_text = self.default_editor.get_value()
        ins.default_duration = self._get_float("instr_default_duration", 3.0)
        ins.font_color = self.vars["instr_colour"].get()
        ins.background = self.vars["instr_background"].get()
        ins.font_size = self._get_int("instr_font_size", 48)
        ins.line_spacing = self._get_int("instr_line_spacing", 12)
        ins.max_chars_per_line = self._get_int("instr_wrap", 46)
        ins.align = self.vars["instr_align"].get()
        ins.font_file = self.vars["instr_font_file"].get().strip()

        lay.fit = FIT_MODES.get(self.vars["fit_label"].get(), "contain")
        lay.position = self.vars["layout_position"].get()
        lay.offset_x = self._get_int("layout_offset_x", 0)
        lay.offset_y = self._get_int("layout_offset_y", 0)
        lay.scale = self._get_float("layout_scale", 1.0)
        lay.background = self.vars["layout_background"].get()
        lay.image_duration = self._get_float("layout_image_duration", 4.0)
        lay.audio_background = self.vars["layout_audio_background"].get()
        lay.audio_caption = self.vars["layout_audio_caption"].get()

        tl.blank_duration = self._get_float("blank_duration", 0.5)
        tl.blank_background = self.vars["blank_background"].get()
        tl.trial_sequence = list(self.trial_list.get(0, "end"))
        tl.trailing_sequence = list(self.trailing_list.get(0, "end"))

        v.width = self._get_int("width", 1280)
        v.height = self._get_int("height", 720)
        v.fps = self._get_float("fps", 30.0)
        v.video_codec = self.vars["video_codec"].get()
        v.crf = self._get_int("crf", 20)
        v.preset = self.vars["preset"].get()
        v.video_bitrate = self.vars["video_bitrate"].get().strip()
        v.preserve_audio = bool(self.vars["preserve_audio"].get())
        v.audio_codec = self.vars["audio_codec"].get()
        v.audio_bitrate = self.vars["audio_bitrate"].get()
        v.sample_rate = self._get_int("sample_rate", 48000)
        v.audio_channels = self._get_int("audio_channels", 2)
        config.keep_segments = bool(self.vars["keep_segments"].get())
        return config

    # -- preview -------------------------------------------------------------------
    def _schedule_preview(self) -> None:
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(220, self._render_preview)

    def _render_preview(self) -> None:
        self._preview_job = None
        self._update_sequence_hint()
        try:
            config = self.save_to_config()
        except Exception:  # a half-typed value; wait for the next keystroke
            return
        choice = self.preview_choice.get()
        try:
            if choice == "Fixation cross":
                image = render_fixation_screen(config.video, config.fixation)
            elif choice == "Blank":
                image = render_blank_screen(config.video, config.timeline.blank_background)
            else:
                text = {
                    "Opening instructions": config.instructions.opening_text,
                    "Default instruction": config.instructions.default_text,
                    "Closing screen": config.instructions.closing_text,
                }[choice]
                image = render_text_screen(text, config.video, config.instructions)
        except PillowUnavailable as exc:
            self.preview.show_message(str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive
            self.preview.show_message(f"Preview unavailable: {exc}")
            return
        self.preview.show(image, f"{config.video.width} \u00d7 {config.video.height}")

    # -- settings files ----------------------------------------------------------------
    def save_settings(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save settings", defaultextension=".json",
            initialfile="stim_concat_settings.json", filetypes=[("JSON", "*.json")],
        )
        if path:
            self.save_to_config().to_json(path)
            self.status(f"Settings saved to {path}.", "ok")

    def load_settings(self) -> None:
        path = filedialog.askopenfilename(title="Load settings", filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            self.state.config = BuildConfig.from_json(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not load settings", str(exc), parent=self)
            return
        self.load_from_config()
        self.status(f"Loaded settings from {Path(path).name}.", "ok")

    def reset_settings(self) -> None:
        if messagebox.askyesno("Reset settings", "Restore all settings to their defaults?", parent=self):
            self.state.config = BuildConfig()
            self.load_from_config()

    # -- wizard hooks --------------------------------------------------------------------
    def on_show(self) -> None:
        self.load_from_config()
        self._schedule_preview()

    def on_leave(self) -> None:
        self.save_to_config()

    def validate(self) -> tuple[bool, str]:
        config = self.save_to_config()
        problems = config.validate()
        if problems:
            return False, problems[0]
        return True, ""


class OverrideDialog(tk.Toplevel):
    """Small editor for a per-stimulus instruction override."""

    def __init__(self, master, stimulus_ids, config: BuildConfig, current: str = ""):
        super().__init__(master)
        self.title("Per-stimulus instruction")
        self.transient(master)
        self.grab_set()
        self.result = None

        body = ttk.Frame(self, padding=PAD * 2)
        body.pack(fill="both", expand=True)

        existing = config.instructions.per_stimulus.get(current, {})
        self.stimulus_var = tk.StringVar(value=current or (stimulus_ids[0] if stimulus_ids else ""))
        self.duration_var = tk.StringVar(
            value=str(existing.get("duration", config.instructions.default_duration))
        )

        form = FormGrid(body, label_width=16)
        form.pack(fill="x")
        form.add("Stimulus",
                 ttk.Combobox(form, textvariable=self.stimulus_var, values=list(stimulus_ids),
                              state="readonly", width=24))
        form.add("Duration (s)", ttk.Entry(form, textvariable=self.duration_var, width=10))

        ttk.Label(body, text="Instruction text").pack(anchor="w", pady=(PAD, 2))
        self.editor = ScrolledText(body, height=7, width=56, mono=False)
        self.editor.pack(fill="both", expand=True)
        self.editor.set_value(existing.get("text", config.instructions.default_text))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(PAD, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save", style="Primary.TButton", command=self._save).pack(
            side="right", padx=(0, PAD)
        )
        self.bind("<Escape>", lambda _e: self.destroy())

    def _save(self) -> None:
        try:
            duration = float(self.duration_var.get())
        except ValueError:
            messagebox.showerror("Invalid duration", "Duration must be a number.", parent=self)
            return
        self.result = (self.stimulus_var.get(), self.editor.get_value(), duration)
        self.destroy()
