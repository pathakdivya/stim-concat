"""The high-level build pipeline.

This is the single entry point used by both the GUI and the CLI, so a build
started from a wizard and a build started from a terminal are byte-for-byte the
same operation.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..assignment.base import Assignment
from .config import BuildConfig
from .exporters import (
    XlsxUnavailable,
    write_settings_json,
    write_summary_csv,
    write_summary_markdown,
    write_timeline_csv,
    write_timeline_xlsx,
)
from .ffmpeg import ffmpeg_version
from .renderer import BuildCancelled, VideoRenderer
from .scanner import StimulusSet
from .timeline import Timeline, build_timeline

__all__ = ["BuildReport", "ParticipantResult", "build_all", "preview_timelines"]

ProgressFn = Callable[[float, str], None]


@dataclass
class ParticipantResult:
    participant: str
    status: str = "ok"  # ok | failed | cancelled | skipped
    video: Path | None = None
    duration_s: float = 0.0
    n_events: int = 0
    n_stimuli: int = 0
    stimulus_ids: list[str] = field(default_factory=list)
    message: str = ""
    outputs: dict[str, Path] = field(default_factory=dict)

    def as_row(self) -> dict:
        return {
            "participant": self.participant,
            "status": self.status,
            "video": str(self.video) if self.video else "",
            "duration_s": round(self.duration_s, 3),
            "n_events": self.n_events,
            "n_stimuli": self.n_stimuli,
            "stimulus_ids": " ".join(self.stimulus_ids),
            "message": self.message,
        }


@dataclass
class BuildReport:
    results: list[ParticipantResult] = field(default_factory=list)
    summary_csv: Path | None = None
    summary_md: Path | None = None
    output_folder: Path | None = None
    cancelled: bool = False

    @property
    def n_ok(self) -> int:
        return sum(1 for r in self.results if r.status == "ok")

    @property
    def n_failed(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def total_duration(self) -> float:
        return round(sum(r.duration_s for r in self.results if r.status == "ok"), 3)

    def describe(self) -> str:
        lines = [
            f"Built {self.n_ok}/{len(self.results)} participant videos "
            f"({self.total_duration:.1f} s of material)."
        ]
        for result in self.results:
            if result.status != "ok":
                lines.append(f"  ! {result.participant}: {result.status} - {result.message}")
        if self.summary_csv:
            lines.append(f"Summary: {self.summary_csv}")
        return "\n".join(lines)


def preview_timelines(
    assignment: Assignment,
    stimuli: StimulusSet,
    config: BuildConfig,
    *,
    participants: Sequence[str] | None = None,
) -> dict[str, Timeline]:
    """Build timelines without rendering anything (fast; used by the preview page)."""
    wanted = set(participants) if participants else None
    out: dict[str, Timeline] = {}
    for participant, row in assignment:
        if wanted and participant not in wanted:
            continue
        out[participant] = build_timeline(participant, row, stimuli, config)
    return out


def build_all(
    assignment: Assignment,
    stimuli: StimulusSet,
    config: BuildConfig,
    output_folder: str | Path,
    *,
    participants: Sequence[str] | None = None,
    progress: ProgressFn | None = None,
    log: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
    write_summary: bool = True,
) -> BuildReport:
    """Render every participant's video plus its timeline and settings files."""
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    progress = progress or (lambda fraction, message: None)
    log = log or (lambda message: None)
    cancel_event = cancel_event or threading.Event()

    selected = [
        (participant, row)
        for participant, row in assignment
        if not participants or participant in set(participants)
    ]
    report = BuildReport(output_folder=output_folder)
    total = len(selected) or 1

    try:
        version = ffmpeg_version()
    except Exception:  # pragma: no cover - reported per participant instead
        version = "unknown"

    for i, (participant, row) in enumerate(selected):
        if cancel_event.is_set():
            report.cancelled = True
            report.results.append(
                ParticipantResult(participant=participant, status="cancelled", message="Cancelled before start")
            )
            continue

        result = ParticipantResult(participant=participant, stimulus_ids=[str(s) for s in row])
        stem = config.filename_template.format(participant=participant, index=i + 1)
        video_path = output_folder / f"{stem}.{config.video.container}"

        def scaled(fraction: float, message: str, _i: int = i) -> None:
            progress((_i + max(0.0, min(1.0, fraction))) / total, message)

        try:
            log(f"[{participant}] building timeline ({len(row)} stimuli)")
            timeline = build_timeline(participant, row, stimuli, config)

            renderer = VideoRenderer(config, progress=scaled, cancel_event=cancel_event, log=log)
            render = renderer.render(timeline, video_path)

            csv_path = write_timeline_csv(timeline, output_folder / f"{stem}_timeline.csv")
            result.outputs["timeline_csv"] = csv_path
            try:
                xlsx_path = write_timeline_xlsx(timeline, output_folder / f"{stem}_timeline.xlsx")
                result.outputs["timeline_xlsx"] = xlsx_path
            except XlsxUnavailable as exc:
                log(f"[{participant}] skipping .xlsx export: {exc}")

            settings_path = write_settings_json(
                config,
                output_folder / f"{stem}_settings.json",
                participant=participant,
                stimulus_ids=[str(s) for s in row],
                assignment_meta={
                    "algorithm": assignment.algorithm,
                    "seed": assignment.seed,
                    "params": assignment.params,
                    "created_utc": assignment.created,
                },
                ffmpeg_version=version,
            )
            result.outputs["settings"] = settings_path
            result.outputs["video"] = render.video

            result.video = render.video
            result.duration_s = render.duration
            result.n_events = len(timeline)
            result.n_stimuli = len(timeline.stimulus_events)
            log(f"[{participant}] done: {render.video.name} ({render.duration:.2f} s)")
        except BuildCancelled:
            report.cancelled = True
            cancel_event.set()
            result.status = "cancelled"
            result.message = "Cancelled by user"
            log(f"[{participant}] cancelled")
        except Exception as exc:
            result.status = "failed"
            result.message = f"{type(exc).__name__}: {exc}"
            log(f"[{participant}] FAILED: {result.message}")

        report.results.append(result)
        progress((i + 1) / total, f"{participant}: {result.status}")

    if write_summary:
        rows = [r.as_row() for r in report.results]
        report.summary_csv = write_summary_csv(rows, output_folder / "build_summary.csv")
        report.summary_md = write_summary_markdown(
            {
                "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "stimulus_folder": str(stimuli.root or ""),
                "assignment_csv": assignment.notes or "",
                "output_folder": str(output_folder),
                "n_built": report.n_ok,
                "n_total": len(report.results),
                "total_duration_s": report.total_duration,
                "ffmpeg": version,
                "participants": rows,
                "config": config.to_dict(),
            },
            output_folder / "build_summary.md",
        )
    return report
