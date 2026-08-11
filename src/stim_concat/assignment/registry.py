"""Discovery and execution of assignment algorithms.

Each algorithm is a standalone Python file that defines::

    NAME = "Human readable name"
    DESCRIPTION = "One paragraph explaining the design."
    PARAMS = [{"name": "...", "type": "bool|int|float|str|choice",
               "default": ..., "label": "...", "choices": [...]}]

    def assign(stimuli, n_participants, n_per_participant, rng, params):
        return [[...], ...]   # one list of stimulus IDs per participant

Because the algorithm *is* the script, the text shown in the editor is exactly
what runs.  Researchers can modify it, run it, and the modified source is stored
in the assignment metadata so the result can always be reproduced.

.. warning::
   Running an algorithm executes Python code.  Only run scripts you trust --
   the same caution that applies to any analysis script.
"""

from __future__ import annotations

import random
import types
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import Assignment, AssignmentError

__all__ = [
    "AlgorithmSpec",
    "builtin_dir",
    "compile_algorithm",
    "discover",
    "get",
    "load_source",
    "run_algorithm",
    "run_source",
    "user_dir",
]

_REQUIRED_ATTR = "assign"


def builtin_dir() -> Path:
    return Path(__file__).resolve().parent / "algorithms"


def user_dir() -> Path:
    """Directory where researchers can drop their own algorithm scripts."""
    path = Path.home() / ".stim-concat" / "algorithms"
    return path


@dataclass
class AlgorithmSpec:
    """A discovered algorithm script."""

    key: str
    name: str
    description: str
    path: Path
    params: list[dict] = field(default_factory=list)
    builtin: bool = True

    def source(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def default_params(self) -> dict[str, Any]:
        return {p["name"]: p.get("default") for p in self.params}

    def __str__(self) -> str:  # pragma: no cover
        return self.name


def _exec_module(source: str, name: str, path: Path | None = None) -> types.ModuleType:
    module = types.ModuleType(f"stim_concat_algorithm_{name}")
    module.__file__ = str(path) if path else f"<{name}>"
    try:
        code = compile(source, module.__file__, "exec")
        exec(code, module.__dict__)
    except SyntaxError as exc:
        raise AssignmentError(
            f"Syntax error in algorithm script (line {exc.lineno}): {exc.msg}"
        ) from exc
    except Exception as exc:  # pragma: no cover - depends on user script
        raise AssignmentError(f"Error while loading algorithm script: {exc}") from exc
    return module


def compile_algorithm(source: str, key: str = "custom", path: Path | None = None) -> types.ModuleType:
    """Compile *source* into a module and check it satisfies the protocol."""
    module = _exec_module(source, key, path)
    if not callable(getattr(module, _REQUIRED_ATTR, None)):
        raise AssignmentError(
            "The algorithm script must define a function called "
            "assign(stimuli, n_participants, n_per_participant, rng, params)."
        )
    return module


def load_source(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _spec_from_path(path: Path, builtin: bool) -> AlgorithmSpec | None:
    try:
        module = compile_algorithm(path.read_text(encoding="utf-8"), path.stem, path)
    except AssignmentError:
        return None
    return AlgorithmSpec(
        key=path.stem,
        name=getattr(module, "NAME", path.stem.replace("_", " ").title()),
        description=(getattr(module, "DESCRIPTION", "") or "").strip(),
        path=path,
        params=list(getattr(module, "PARAMS", [])),
        builtin=builtin,
    )


def discover(include_user: bool = True) -> list[AlgorithmSpec]:
    """All available algorithms, built-ins first, then user scripts."""
    specs: list[AlgorithmSpec] = []
    seen: set[str] = set()
    sources = [(builtin_dir(), True)]
    if include_user:
        sources.append((user_dir(), False))
    for folder, builtin in sources:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.py")):
            if path.name.startswith("_"):
                continue
            spec = _spec_from_path(path, builtin)
            if spec and spec.key not in seen:
                seen.add(spec.key)
                specs.append(spec)
    return specs


def get(key: str) -> AlgorithmSpec:
    for spec in discover():
        if spec.key == key or spec.name == key:
            return spec
    available = ", ".join(s.key for s in discover())
    raise KeyError(f"Unknown assignment algorithm {key!r}. Available: {available}")


def _coerce_params(spec_params: Sequence[dict], params: dict | None) -> dict:
    merged = {p["name"]: p.get("default") for p in spec_params}
    for key, value in (params or {}).items():
        merged[key] = value
    return merged


def _validate_output(
    result: Any, n_participants: int, n_per_participant: int, pool: Sequence[str]
) -> list[list[str]]:
    if not isinstance(result, (list, tuple)):
        raise AssignmentError(
            f"assign() must return a list of lists, got {type(result).__name__}."
        )
    rows = [list(map(str, row)) for row in result]
    if len(rows) != n_participants:
        raise AssignmentError(
            f"assign() returned {len(rows)} rows but {n_participants} participants were requested."
        )
    bad = [i for i, row in enumerate(rows, 1) if len(row) != n_per_participant]
    if bad:
        raise AssignmentError(
            f"assign() returned the wrong number of trials for participant(s) "
            f"{bad[:5]}; expected {n_per_participant}."
        )
    known = {str(s) for s in pool}
    unknown = sorted({s for row in rows for s in row} - known)
    if unknown:
        raise AssignmentError(
            f"assign() returned stimulus IDs that are not in the folder: {unknown[:8]}"
        )
    return rows


def run_algorithm(
    spec_or_key: AlgorithmSpec | str,
    stimuli: Sequence[str],
    n_participants: int,
    n_per_participant: int,
    *,
    seed: int | None = None,
    params: dict | None = None,
    source: str | None = None,
    participant_labels: Sequence[str] | None = None,
) -> Assignment:
    """Execute an algorithm and return a validated :class:`Assignment`.

    Passing *source* runs edited script text instead of the file on disk; the
    text that actually ran is stored in the assignment metadata.
    """
    spec = get(spec_or_key) if isinstance(spec_or_key, str) else spec_or_key
    script = source if source is not None else spec.source()
    return run_source(
        script,
        stimuli,
        n_participants,
        n_per_participant,
        seed=seed,
        params=_coerce_params(spec.params, params),
        key=spec.key,
        name=spec.name,
        participant_labels=participant_labels,
    )


def run_source(
    source: str,
    stimuli: Sequence[str],
    n_participants: int,
    n_per_participant: int,
    *,
    seed: int | None = None,
    params: dict | None = None,
    key: str = "custom",
    name: str | None = None,
    participant_labels: Sequence[str] | None = None,
) -> Assignment:
    """Compile and run algorithm *source*, validating the result."""
    pool = [str(s) for s in stimuli]
    if not pool:
        raise AssignmentError("There are no stimuli to assign.")
    if n_participants < 1:
        raise AssignmentError("The number of participants must be at least 1.")
    if n_per_participant < 1:
        raise AssignmentError("The number of stimuli per participant must be at least 1.")

    module = compile_algorithm(source, key)
    rng = random.Random(seed)
    params = dict(params or {})

    try:
        raw = module.assign(list(pool), int(n_participants), int(n_per_participant), rng, params)
    except AssignmentError:
        raise
    except Exception as exc:
        raise AssignmentError(f"The algorithm raised {type(exc).__name__}: {exc}") from exc

    rows = _validate_output(raw, n_participants, n_per_participant, pool)
    labels = (
        list(participant_labels)
        if participant_labels
        else [f"P{i:03d}" for i in range(1, n_participants + 1)]
    )
    if len(labels) != len(rows):
        raise AssignmentError("The number of participant labels does not match the number of rows.")

    return Assignment(
        participants=labels,
        rows=rows,
        algorithm=name or getattr(module, "NAME", key),
        seed=seed,
        params=params,
        stimulus_pool=pool,
        script=source,
        notes=getattr(module, "LAST_NOTE", "") if isinstance(getattr(module, "LAST_NOTE", ""), str) else "",
    )
