"""Construction of the event timeline for one participant.

The timeline is built *before* any rendering happens.  Because every segment is
encoded at a constant frame rate and every duration is snapped to a whole
number of frames, the exported timeline is an exact description of the final
video rather than an estimate -- which is what makes it usable for aligning
eye-tracking, joystick or physiological recordings.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import BuildConfig
from .ffmpeg import probe
from .scanner import StimulusFile, StimulusSet

__all__ = ["TIMELINE_COLUMNS", "Timeline", "TimelineEvent", "build_timeline"]

TIMELINE_COLUMNS = (
    "event_index",
    "start_s",
    "end_s",
    "duration_s",
    "event_type",
    "trial",
    "stimulus_id",
    "description",
    "source_file",
)


@dataclass
class TimelineEvent:
    """One segment of the final video."""

    index: int
    start: float
    end: float
    event_type: str  # instruction | fixation | stimulus | blank
    description: str = ""
    stimulus_id: str | None = None
    trial: int | None = None
    source: Path | None = None
    #: Renderer payload (text, colours, media kind, ...).
    spec: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 6)

    def as_row(self) -> dict:
        return {
            "event_index": self.index,
            "start_s": round(self.start, 3),
            "end_s": round(self.end, 3),
            "duration_s": round(self.duration, 3),
            "event_type": self.event_type,
            "trial": self.trial if self.trial is not None else "",
            "stimulus_id": self.stimulus_id if self.stimulus_id is not None else "",
            "description": self.description,
            "source_file": self.source.name if self.source else "",
        }


class Timeline(Sequence[TimelineEvent]):
    """An ordered list of :class:`TimelineEvent` for one participant."""

    def __init__(self, participant: str, events: Iterable[TimelineEvent] | None = None):
        self.participant = participant
        self._events: list[TimelineEvent] = list(events or [])
        self.warnings: list[str] = []

    # -- Sequence protocol -------------------------------------------------
    def __len__(self) -> int:
        return len(self._events)

    def __getitem__(self, index):  # type: ignore[override]
        return self._events[index]

    def __iter__(self) -> Iterator[TimelineEvent]:
        return iter(self._events)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Timeline {self.participant} events={len(self._events)} dur={self.duration:.2f}s>"

    # -- Helpers -----------------------------------------------------------
    @property
    def duration(self) -> float:
        return round(self._events[-1].end, 6) if self._events else 0.0

    @property
    def stimulus_events(self) -> list[TimelineEvent]:
        return [e for e in self._events if e.event_type == "stimulus"]

    def append(self, event: TimelineEvent) -> None:
        self._events.append(event)

    def rows(self) -> list[dict]:
        return [event.as_row() for event in self._events]

    def to_dataframe(self):
        """Return the timeline as a :class:`pandas.DataFrame` (pandas required)."""
        import pandas as pd

        return pd.DataFrame(self.rows(), columns=list(TIMELINE_COLUMNS))

    def summary(self) -> dict:
        by_type: dict[str, int] = {}
        for event in self._events:
            by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
        return {
            "participant": self.participant,
            "n_events": len(self._events),
            "n_stimuli": len(self.stimulus_events),
            "duration_s": round(self.duration, 3),
            "events_by_type": by_type,
        }

    def describe(self) -> str:
        """A compact human-readable preview (used by the CLI and GUI)."""
        lines = [
            f"{'start':>9}  {'end':>9}  {'dur':>8}  {'type':<12} {'stim':<10} description",
            "-" * 78,
        ]
        for event in self._events:
            lines.append(
                f"{event.start:9.3f}  {event.end:9.3f}  {event.duration:8.3f}  "
                f"{event.event_type:<12} {event.stimulus_id or '-'!s:<10} "
                f"{event.description[:34]}"
            )
        lines.append("-" * 78)
        lines.append(f"total: {self.duration:.3f} s over {len(self._events)} events")
        return "\n".join(lines)


def _stimulus_duration(item: StimulusFile, config: BuildConfig) -> tuple[float, dict]:
    """Duration and renderer metadata for one stimulus."""
    if item.kind == "image":
        return config.video.quantise(config.layout.image_duration), {"has_audio": False}
    if item.kind == "text":
        return config.video.quantise(config.instructions.default_duration), {"has_audio": False}

    info = probe(item.path)
    if not info.duration or info.duration <= 0:
        raise ValueError(
            f"Could not determine the duration of {item.path.name}. "
            "The file may be corrupt or in an unsupported codec."
        )
    return config.video.quantise(info.duration), {
        "has_audio": bool(info.has_audio),
        "width": info.width,
        "height": info.height,
        "source_fps": info.fps,
    }


def build_timeline(
    participant: str,
    stimulus_ids: Sequence[str],
    stimuli: StimulusSet,
    config: BuildConfig,
) -> Timeline:
    """Build the full event timeline for one participant.

    Parameters
    ----------
    participant:
        Participant label, e.g. ``"P001"``.
    stimulus_ids:
        The stimulus IDs assigned to this participant, in presentation order.
    stimuli:
        The scanned stimulus folder.
    config:
        Build configuration.
    """
    problems = config.validate()
    if problems:
        raise ValueError("Invalid configuration:\n- " + "\n- ".join(problems))

    timeline = Timeline(participant)
    clock = 0.0
    index = 0
    video = config.video
    instructions = config.instructions

    def add(event_type: str, duration: float, **kwargs) -> None:
        nonlocal clock, index
        duration = video.quantise(duration)
        event = TimelineEvent(
            index=index,
            start=round(clock, 6),
            end=round(clock + duration, 6),
            event_type=event_type,
            **kwargs,
        )
        timeline.append(event)
        clock = event.end
        index += 1

    # --- opening ----------------------------------------------------------
    if instructions.opening_enabled and instructions.opening_text.strip():
        add(
            "instruction",
            instructions.opening_duration,
            description="Opening instructions",
            spec={"text": instructions.opening_text, "role": "opening"},
        )

    # --- trials -----------------------------------------------------------
    def emit_element(element: str, trial_no: int | None, item: StimulusFile | None) -> None:
        if element == "fixation":
            if not config.fixation.enabled:
                return
            add(
                "fixation",
                config.fixation.duration,
                description="Fixation cross",
                trial=trial_no,
                spec={"role": "fixation"},
            )
        elif element == "blank":
            add(
                "blank",
                config.timeline.blank_duration,
                description="Blank screen",
                trial=trial_no,
                spec={"role": "blank"},
            )
        elif element == "instruction":
            if not instructions.interleaved_enabled or item is None:
                return
            text, duration = instructions.for_stimulus(item.stimulus_id)
            if not text.strip():
                return
            label = (
                "Per-stimulus instruction"
                if instructions.has_override(item.stimulus_id)
                else "Default instruction"
            )
            add(
                "instruction",
                duration,
                description=label,
                trial=trial_no,
                stimulus_id=item.stimulus_id,
                spec={"text": text, "role": "interleaved"},
            )
        elif element == "stimulus" and item is not None:
            duration, meta = _stimulus_duration(item, config)
            add(
                "stimulus",
                duration,
                description=item.kind.capitalize(),
                trial=trial_no,
                stimulus_id=item.stimulus_id,
                source=item.path,
                spec={"role": "stimulus", "kind": item.kind, **meta},
            )

    for trial_no, stimulus_id in enumerate(stimulus_ids, start=1):
        item = stimuli.require(str(stimulus_id))
        for element in config.timeline.trial_sequence:
            emit_element(element, trial_no, item)

    for element in config.timeline.trailing_sequence:
        emit_element(element, None, None)

    # --- closing ----------------------------------------------------------
    if instructions.closing_enabled and instructions.closing_text.strip():
        add(
            "instruction",
            instructions.closing_duration,
            description="Closing screen",
            spec={"text": instructions.closing_text, "role": "closing"},
        )

    if not timeline.stimulus_events:
        timeline.warnings.append("This timeline contains no stimuli.")
    return timeline
