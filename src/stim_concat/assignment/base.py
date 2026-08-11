"""Data model for participant assignments."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ["Assignment", "AssignmentError", "stimulus_fingerprint"]


class AssignmentError(RuntimeError):
    """Raised when an assignment algorithm misbehaves or its output is invalid."""


def stimulus_fingerprint(stimulus_ids: Iterable[str]) -> str:
    """Short, order-independent hash of a stimulus pool.

    Recorded alongside an assignment so a later build can verify that the
    stimulus folder still contains the same material.
    """
    digest = hashlib.sha256("\u0000".join(sorted(map(str, stimulus_ids))).encode("utf-8"))
    return digest.hexdigest()[:16]


@dataclass
class Assignment:
    """Which stimuli each participant sees, and in which order."""

    participants: list[str]
    rows: list[list[str]]
    algorithm: str = "unknown"
    seed: int | None = None
    params: dict[str, Any] = field(default_factory=dict)
    stimulus_pool: list[str] = field(default_factory=list)
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    notes: str = ""
    script: str = ""  # the exact source used, for full reproducibility

    # -- basic properties ---------------------------------------------------
    @property
    def n_participants(self) -> int:
        return len(self.rows)

    @property
    def n_trials(self) -> int:
        return len(self.rows[0]) if self.rows else 0

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(zip(self.participants, self.rows))

    def row_for(self, participant: str) -> list[str]:
        try:
            return self.rows[self.participants.index(participant)]
        except ValueError as exc:
            raise KeyError(f"Unknown participant: {participant}") from exc

    # -- validation ---------------------------------------------------------
    def validate(self, known_ids: Sequence[str] | None = None) -> list[str]:
        problems: list[str] = []
        if not self.rows:
            problems.append("The assignment is empty.")
            return problems
        if len(self.participants) != len(self.rows):
            problems.append("Participant labels and assignment rows have different lengths.")
        widths = {len(row) for row in self.rows}
        if len(widths) > 1:
            problems.append(f"Participants have different trial counts: {sorted(widths)}")
        if len(set(self.participants)) != len(self.participants):
            problems.append("Participant labels are not unique.")
        if known_ids is not None:
            pool = {str(i) for i in known_ids}
            unknown = sorted({str(s) for row in self.rows for s in row} - pool)
            if unknown:
                shown = ", ".join(unknown[:8]) + (" ..." if len(unknown) > 8 else "")
                problems.append(f"{len(unknown)} assigned stimuli are not in the folder: {shown}")
        return problems

    # -- diagnostics --------------------------------------------------------
    def usage_counts(self) -> dict[str, int]:
        """How many times each stimulus is presented across all participants."""
        counts: dict[str, int] = {str(s): 0 for s in self.stimulus_pool}
        for row in self.rows:
            for stimulus in row:
                counts[str(stimulus)] = counts.get(str(stimulus), 0) + 1
        return counts

    def position_counts(self) -> dict[str, list[int]]:
        """Per-stimulus counts of the serial positions it occupies."""
        out: dict[str, list[int]] = {}
        for row in self.rows:
            for position, stimulus in enumerate(row):
                slots = out.setdefault(str(stimulus), [0] * self.n_trials)
                slots[position] += 1
        return out

    def balance_report(self) -> dict:
        counts = self.usage_counts()
        values = list(counts.values()) or [0]
        used = [v for v in values if v]
        repeats = sum(1 for row in self.rows if len(set(row)) != len(row))
        return {
            "n_participants": self.n_participants,
            "n_trials": self.n_trials,
            "pool_size": len(self.stimulus_pool),
            "min_uses": min(values),
            "max_uses": max(values),
            "mean_uses": round(sum(values) / len(values), 3),
            "unused_stimuli": [k for k, v in counts.items() if v == 0],
            "coverage": round(len(used) / len(values), 3) if values else 0.0,
            "participants_with_repeats": repeats,
        }

    # -- serialisation ------------------------------------------------------
    def to_rows(self) -> list[dict]:
        return [
            {"participant": p, **{f"trial_{i + 1}": s for i, s in enumerate(row)}}
            for p, row in zip(self.participants, self.rows)
        ]

    def to_csv(self, path: str | Path, *, write_metadata: bool = True) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = ["participant"] + [f"trial_{i + 1}" for i in range(self.n_trials)]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for participant, row in zip(self.participants, self.rows):
                writer.writerow([participant, *row])
        if write_metadata:
            self.metadata_path(path).write_text(
                json.dumps(self.metadata(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return path

    @staticmethod
    def metadata_path(csv_path: str | Path) -> Path:
        csv_path = Path(csv_path)
        return csv_path.with_name(csv_path.stem + "_metadata.json")

    def metadata(self) -> dict:
        return {
            "algorithm": self.algorithm,
            "seed": self.seed,
            "params": self.params,
            "created_utc": self.created,
            "n_participants": self.n_participants,
            "n_trials": self.n_trials,
            "stimulus_pool": self.stimulus_pool,
            "stimulus_fingerprint": stimulus_fingerprint(self.stimulus_pool),
            "balance": self.balance_report(),
            "notes": self.notes,
            "script": self.script,
            "generator": "stim-concat",
        }

    @classmethod
    def from_csv(cls, path: str | Path) -> Assignment:
        """Read an assignment sheet, picking up sidecar metadata when present."""
        path = Path(path)
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise AssignmentError(f"{path.name} is empty.") from exc
            data = [row for row in reader if any(cell.strip() for cell in row)]

        if not header:
            raise AssignmentError(f"{path.name} has no header row.")

        first = header[0].strip().lower()
        has_labels = first in ("participant", "participant_id", "subject", "id", "pid")
        participants: list[str] = []
        rows: list[list[str]] = []
        for i, raw in enumerate(data, start=1):
            cells = [cell.strip() for cell in raw]
            if has_labels:
                participants.append(cells[0] or f"P{i:03d}")
                rows.append([c for c in cells[1:] if c != ""])
            else:
                participants.append(f"P{i:03d}")
                rows.append([c for c in cells if c != ""])
        if not rows:
            raise AssignmentError(f"{path.name} contains no participant rows.")

        assignment = cls(
            participants=participants,
            rows=rows,
            stimulus_pool=sorted({s for row in rows for s in row}),
            algorithm="imported",
        )

        meta_file = cls.metadata_path(path)
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                assignment.algorithm = meta.get("algorithm", "imported")
                assignment.seed = meta.get("seed")
                assignment.params = meta.get("params", {})
                assignment.created = meta.get("created_utc", assignment.created)
                assignment.script = meta.get("script", "")
                if meta.get("stimulus_pool"):
                    assignment.stimulus_pool = [str(s) for s in meta["stimulus_pool"]]
            except (ValueError, OSError):  # pragma: no cover - tolerate bad sidecars
                pass
        return assignment
