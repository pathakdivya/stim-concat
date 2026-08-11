"""State shared between wizard pages."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..assignment.base import Assignment
from ..assignment.registry import AlgorithmSpec, discover
from ..core.config import BuildConfig
from ..core.pipeline import BuildReport
from ..core.scanner import DEFAULT_ID_PATTERN, StimulusSet

SETTINGS_DIR = Path.home() / ".stim-concat"
SESSION_FILE = SETTINGS_DIR / "last_session.json"


@dataclass
class AppState:
    """Everything the wizard carries from page to page."""

    stimulus_folder: Path | None = None
    id_pattern: str = DEFAULT_ID_PATTERN
    recursive: bool = False
    stimuli: StimulusSet | None = None

    algorithm_key: str = "balanced_random"
    script: str = ""
    n_participants: int = 20
    n_per_participant: int = 8
    seed: int | None = 42
    params: dict = field(default_factory=dict)

    assignment: Assignment | None = None
    assignment_path: Path | None = None

    config: BuildConfig = field(default_factory=BuildConfig)
    output_folder: Path | None = None
    selected_participants: list[str] = field(default_factory=list)

    report: BuildReport | None = None

    # -- helpers ------------------------------------------------------------
    def algorithms(self) -> list[AlgorithmSpec]:
        return discover()

    def ready_for_assignment(self) -> bool:
        return bool(self.stimuli and len(self.stimuli))

    def ready_for_settings(self) -> bool:
        return self.assignment is not None

    def ready_for_build(self) -> bool:
        return bool(self.assignment and self.stimuli and self.output_folder)

    # -- session persistence -------------------------------------------------
    def save_session(self) -> None:
        """Remember the last-used folders and settings between launches."""
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(
                json.dumps(
                    {
                        "stimulus_folder": str(self.stimulus_folder or ""),
                        "output_folder": str(self.output_folder or ""),
                        "id_pattern": self.id_pattern,
                        "recursive": self.recursive,
                        "algorithm_key": self.algorithm_key,
                        "n_participants": self.n_participants,
                        "n_per_participant": self.n_per_participant,
                        "seed": self.seed,
                        "config": self.config.to_dict(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:  # pragma: no cover - best effort only
            pass

    def load_session(self) -> None:
        if not SESSION_FILE.exists():
            return
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # pragma: no cover
            return
        folder = data.get("stimulus_folder")
        if folder and Path(folder).is_dir():
            self.stimulus_folder = Path(folder)
        out = data.get("output_folder")
        if out:
            self.output_folder = Path(out)
        self.id_pattern = data.get("id_pattern", self.id_pattern)
        self.recursive = bool(data.get("recursive", False))
        self.algorithm_key = data.get("algorithm_key", self.algorithm_key)
        self.n_participants = int(data.get("n_participants", self.n_participants))
        self.n_per_participant = int(data.get("n_per_participant", self.n_per_participant))
        seed = data.get("seed")
        self.seed = int(seed) if seed is not None else None
        if isinstance(data.get("config"), dict):
            try:
                self.config = BuildConfig.from_dict(data["config"])
            except Exception:  # pragma: no cover - tolerate old formats
                self.config = BuildConfig()
