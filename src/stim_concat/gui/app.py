"""The wizard shell: window, step indicator and navigation."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .. import __version__
from .state import AppState
from .widgets import PAD, StatusBar

__all__ = ["WizardApp", "launch"]


STEPS = [
    ("Stimuli", "Choose the folder of stimulus files"),
    ("Assignment", "Generate the participant assignment sheet"),
    ("Settings", "Configure fixation, instructions and video"),
    ("Build", "Preview timelines and render the videos"),
    ("Summary", "Review and export what was produced"),
]



class WizardApp(tk.Tk):
    """Five-page wizard mirroring the two stages of the pipeline."""

    def __init__(self, state: AppState | None = None):
        super().__init__()

        # ---------------------------------------------------------
        # Application icons
        # ---------------------------------------------------------

        if getattr(sys, "frozen", False):
            png_icon = Path(sys._MEIPASS) / "assets" / "1.png"
            ico_icon = (
                Path(sys._MEIPASS)
                / "stim_concat"
                / "resources"
                / "stim-concat.ico"
            )
        else:
            project_root = Path(__file__).resolve().parents[3]
            png_icon = project_root / "assets" / "1.png"
            ico_icon = (
                Path(__file__).resolve().parent.parent
                / "resources"
                / "stim-concat.ico"
            )
        # Main Tk icon: title bar + taskbar
        if png_icon.exists():
            try:
                self._app_icon = tk.PhotoImage(file=str(png_icon))
                self.iconphoto(True, self._app_icon)
            except tk.TclError:
                pass
          
        # Windows ICO fallback
        if sys.platform == "win32" and ico_icon.exists():
            try:
                self.iconbitmap(default=str(ico_icon))
            except tk.TclError:
                pass

        self.title(f"stim-concat {__version__}")


        self.minsize(1000, 720)
        self.geometry("1120x800")

        self.state_data = state or AppState()
        self.state_data.load_session()

        self._configure_style()
        self._build_chrome()
        self._build_pages()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show_page(0)

    # -- chrome -------------------------------------------------------------
    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if sys.platform == "darwin":
            preferred = ("aqua", "clam")
        elif sys.platform.startswith("win"):
            preferred = ("vista", "clam")
        else:
            preferred = ("clam",)
        for theme in preferred:
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("Header.TLabel", font=("TkDefaultFont", 15, "bold"))
        style.configure("Sub.TLabel", foreground="#555555")
        style.configure("Step.TLabel", padding=(10, 6))
        style.configure("StepActive.TLabel", padding=(10, 6), font=("TkDefaultFont", 10, "bold"))
        style.configure("Primary.TButton", font=("TkDefaultFont", 10, "bold"))


    def _build_chrome(self) -> None:
    # -----------------------------------------------------
    # Header
    # -----------------------------------------------------
        header = ttk.Frame(
            self,
            padding=(PAD * 2, PAD, PAD * 2, 0)
        )
        header.pack(side="top", fill="x")

        self.title_label = ttk.Label(
            header,
            text="",
            style="Header.TLabel"
        )
        self.title_label.pack(anchor="w")

        self.subtitle_label = ttk.Label(
            header,
            text="",
            style="Sub.TLabel"
        )
        self.subtitle_label.pack(
            anchor="w",
            pady=(0, PAD)
        )

        # -----------------------------------------------------
        # Step indicator
        # -----------------------------------------------------
        self.steps_frame = ttk.Frame(
            self,
            padding=(PAD * 2, 0)
        )
        self.steps_frame.pack(side="top", fill="x")

        self.step_labels: list[ttk.Label] = []

        for index, (name, _) in enumerate(STEPS):
            label = ttk.Label(
                self.steps_frame,
                text=f"{index + 1}. {name}",
                style="Step.TLabel"
            )

            label.pack(side="left")
            self.step_labels.append(label)

            if index < len(STEPS) - 1:
                ttk.Label(
                    self.steps_frame,
                    text="\u203a",
                    foreground="#999999"
                ).pack(side="left")

        ttk.Separator(
            self,
            orient="horizontal"
        ).pack(
            side="top",
            fill="x",
            pady=(PAD, 0)
        )

        # -----------------------------------------------------
        # Fixed footer
        # -----------------------------------------------------
        footer = ttk.Frame(
            self,
            padding=(PAD * 2, PAD, PAD * 2, PAD)
        )

        footer.pack(
            side="bottom",
            fill="x"
        )

        ttk.Separator(
            footer,
            orient="horizontal"
        ).pack(
            fill="x",
            pady=(0, PAD)
        )

        self.status = StatusBar(footer)
        self.status.pack(
            side="left",
            fill="x",
            expand=True
        )

        self.next_button = ttk.Button(
            footer,
            text="Next \u203a",
            style="Primary.TButton",
            command=self.next_page
        )

        self.next_button.pack(side="right")

        self.back_button = ttk.Button(
            footer,
            text="\u2039 Back",
            command=self.previous_page
        )

        self.back_button.pack(
            side="right",
            padx=(0, PAD)
        )

        ttk.Button(
            footer,
            text="Quit",
            command=self._on_close
        ).pack(
            side="right",
            padx=(0, PAD * 2)
        )

        # -----------------------------------------------------
        # Expanding page area
        # -----------------------------------------------------
        self.container = ttk.Frame(
            self,
            padding=PAD * 2
        )

        self.container.pack(
            side="top",
            fill="both",
            expand=True
        )

    # def _build_chrome(self) -> None:
    #     header = ttk.Frame(self, padding=(PAD * 2, PAD, PAD * 2, 0))
    #     header.pack(fill="x")
    #     self.title_label = ttk.Label(header, text="", style="Header.TLabel")
    #     self.title_label.pack(anchor="w")
    #     self.subtitle_label = ttk.Label(header, text="", style="Sub.TLabel")
    #     self.subtitle_label.pack(anchor="w", pady=(0, PAD))

    #     self.steps_frame = ttk.Frame(self, padding=(PAD * 2, 0))
    #     self.steps_frame.pack(fill="x")
    #     self.step_labels: list[ttk.Label] = []
    #     for index, (name, _) in enumerate(STEPS):
    #         label = ttk.Label(self.steps_frame, text=f"{index + 1}. {name}", style="Step.TLabel")
    #         label.pack(side="left")
    #         self.step_labels.append(label)
    #         if index < len(STEPS) - 1:
    #             ttk.Label(self.steps_frame, text="\u203a", foreground="#999999").pack(side="left")

    #     ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(PAD, 0))

    #     self.container = ttk.Frame(self, padding=PAD * 2)
    #     self.container.pack(fill="both", expand=True)

    #     footer = ttk.Frame(self, padding=(PAD * 2, 0, PAD * 2, PAD))
    #     footer.pack(fill="x")
    #     ttk.Separator(footer, orient="horizontal").pack(fill="x", pady=(0, PAD))
    #     self.status = StatusBar(footer)
    #     self.status.pack(side="left", fill="x", expand=True)
    #     self.next_button = ttk.Button(
    #         footer, text="Next \u203a", style="Primary.TButton", command=self.next_page
    #     )
    #     self.next_button.pack(side="right")
    #     self.back_button = ttk.Button(footer, text="\u2039 Back", command=self.previous_page)
    #     self.back_button.pack(side="right", padx=(0, PAD))
    #     ttk.Button(footer, text="Quit", command=self._on_close).pack(side="right", padx=(0, PAD * 2))

    def _build_pages(self) -> None:
        from .pages.page1_stimuli import StimuliPage
        from .pages.page2_assignment import AssignmentPage
        from .pages.page3_settings import SettingsPage
        from .pages.page4_build import BuildPage
        from .pages.page5_summary import SummaryPage

        self.pages = [
            StimuliPage(self.container, self),
            AssignmentPage(self.container, self),
            SettingsPage(self.container, self),
            BuildPage(self.container, self),
            SummaryPage(self.container, self),
        ]
        self.current = 0

    # -- navigation ---------------------------------------------------------
    def show_page(self, index: int) -> None:
        index = max(0, min(len(self.pages) - 1, index))
        for page in self.pages:
            page.pack_forget()
        self.current = index
        page = self.pages[index]
        page.pack(fill="both", expand=True)
        page.on_show()

        name, subtitle = STEPS[index]
        self.title_label.configure(text=f"Step {index + 1} of {len(STEPS)}: {name}")
        self.subtitle_label.configure(text=subtitle)
        for i, label in enumerate(self.step_labels):
            if i == index:
                label.configure(style="StepActive.TLabel", foreground="#1d4ed8")
            elif i < index:
                label.configure(style="Step.TLabel", foreground="#166534")
            else:
                label.configure(style="Step.TLabel", foreground="#999999")

        self.back_button.configure(state="normal" if index > 0 else "disabled")
        self.next_button.configure(
            text="Finish" if index == len(self.pages) - 1 else "Next \u203a"
        )
        self.status.clear()

    def next_page(self) -> None:
        page = self.pages[self.current]
        if self.current == len(self.pages) - 1:
            self._on_close()
            return
        ok, message = page.validate()
        if not ok:
            self.status.set(message, "warn")
            return
        page.on_leave()
        self.show_page(self.current + 1)

    def previous_page(self) -> None:
        self.pages[self.current].on_leave()
        self.show_page(self.current - 1)

    def goto(self, index: int) -> None:
        self.show_page(index)

    # -- shutdown -----------------------------------------------------------
    def _on_close(self) -> None:
        build_page = self.pages[3]
        if getattr(build_page, "is_building", False):
            if not messagebox.askyesno(
                "Build in progress",
                "A build is still running. Cancel it and quit?",
                parent=self,
            ):
                return
            build_page.cancel_build()
        self.state_data.save_session()
        self.destroy()


class WizardPage(ttk.Frame):
    """Base class for wizard pages."""

    def __init__(self, master, app: WizardApp):
        super().__init__(master)
        self.app = app

    @property
    def state(self) -> AppState:
        return self.app.state_data

    def on_show(self) -> None:
        """Called every time the page becomes visible."""

    def on_leave(self) -> None:
        """Called when navigating away; persist widget values into the state."""

    def validate(self) -> tuple[bool, str]:
        """Return ``(ok, message)``; a false result blocks navigation."""
        return True, ""

    def status(self, message: str, level: str = "info") -> None:
        self.app.status.set(message, level)


def launch() -> int:
    """Start the wizard. Returns a process exit code."""
    try:
        app = WizardApp()
    except tk.TclError as exc:  # pragma: no cover - headless environments
        print(
            f"Could not open a window ({exc}). If you are on a headless machine, "
            "use the command line interface instead: stim-concat --help",
            file=sys.stderr,
        )
        return 1
    app.mainloop()
    return 0
