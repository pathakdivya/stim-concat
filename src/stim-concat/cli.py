"""Command line interface for stim-concat.

The CLI exposes the same pipeline as the wizard, which makes builds scriptable
and reproducible on machines without a display::

    stim-concat scan stimuli/
    stim-concat algorithms
    stim-concat assign stimuli/ -n 24 -k 8 --algorithm balanced_random --seed 42
    stim-concat preview participant_assignments.csv stimuli/ --participant P001
    stim-concat build participant_assignments.csv stimuli/ output/
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

from . import __version__
from .assignment.base import Assignment, AssignmentError
from .assignment.registry import discover, get, run_algorithm
from .core.config import BuildConfig
from .core.ffmpeg import FFmpegError, ffmpeg_path, ffmpeg_version, ffprobe_path
from .core.pipeline import build_all, preview_timelines
from .core.scanner import DEFAULT_ID_PATTERN, scan_folder, supported_extensions


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _load_config(path: str | None) -> BuildConfig:
    if not path:
        return BuildConfig()
    return BuildConfig.from_json(path)


def _scan(args) -> object:
    return scan_folder(
        args.stimulus_folder,
        id_pattern=args.id_pattern,
        recursive=args.recursive,
    )


def _progress_printer(quiet: bool):
    state = {"last": ""}

    def progress(fraction: float, message: str) -> None:
        if quiet:
            return
        bar_len = 28
        filled = int(bar_len * max(0.0, min(1.0, fraction)))
        bar = "#" * filled + "-" * (bar_len - filled)
        line = f"\r[{bar}] {fraction * 100:5.1f}%  {message[:60]:<60}"
        sys.stdout.write(line)
        sys.stdout.flush()
        state["last"] = line

    return progress


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_scan(args) -> int:
    stimuli = _scan(args)
    if args.json:
        print(json.dumps([item.as_dict() for item in stimuli], indent=2))
        return 0
    print(f"{len(stimuli)} stimuli in {stimuli.root}")
    counts = stimuli.counts_by_kind()
    if counts:
        print("  " + ", ".join(f"{kind}: {n}" for kind, n in sorted(counts.items())))
    for item in stimuli:
        print(f"  {item.stimulus_id:<16} {item.kind:<6} {item.name}")
    if stimuli.duplicates:
        print("\nWarning: duplicate stimulus IDs (only the first is used):")
        for stimulus_id, paths in stimuli.duplicates.items():
            print(f"  {stimulus_id}: {', '.join(p.name for p in paths)}")
    if not len(stimuli):
        known = ", ".join(sorted(supported_extensions()))
        print(f"\nNo supported files found. Recognised extensions: {known}")
    return 0


def cmd_algorithms(args) -> int:
    specs = discover()
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "key": s.key,
                        "name": s.name,
                        "description": s.description,
                        "params": s.params,
                        "builtin": s.builtin,
                        "path": str(s.path),
                    }
                    for s in specs
                ],
                indent=2,
            )
        )
        return 0
    for spec in specs:
        origin = "built-in" if spec.builtin else "user"
        print(f"{spec.key:<28} {spec.name}  [{origin}]")
        if args.verbose:
            for line in spec.description.split(". "):
                if line.strip():
                    print(f"    {line.strip().rstrip('.')}.")
            for param in spec.params:
                print(f"    - {param['name']} ({param.get('type')}) = {param.get('default')!r}")
            print()
    return 0


def cmd_show(args) -> int:
    spec = get(args.algorithm)
    print(spec.source())
    return 0


def cmd_assign(args) -> int:
    stimuli = _scan(args)
    if not len(stimuli):
        print("No stimuli found; nothing to assign.", file=sys.stderr)
        return 2

    params: dict = {}
    for item in args.param or []:
        if "=" not in item:
            print(f"Invalid --param {item!r}; expected name=value", file=sys.stderr)
            return 2
        key, _, value = item.partition("=")
        try:
            params[key] = json.loads(value)
        except ValueError:
            params[key] = value

    source = Path(args.script).read_text(encoding="utf-8") if args.script else None

    try:
        assignment = run_algorithm(
            args.algorithm,
            stimuli.ids,
            args.participants,
            args.per_participant,
            seed=args.seed,
            params=params,
            source=source,
        )
    except (AssignmentError, KeyError, ValueError) as exc:
        print(f"Assignment failed: {exc}", file=sys.stderr)
        return 1

    out = Path(args.output)
    assignment.to_csv(out)
    print(f"Wrote {out} ({assignment.n_participants} participants x {assignment.n_trials} trials)")
    print(f"Metadata: {Assignment.metadata_path(out)}")
    if assignment.notes:
        print(f"Note: {assignment.notes}")

    report = assignment.balance_report()
    print(
        "Balance: each stimulus used {min_uses}-{max_uses} times "
        "(mean {mean_uses}), coverage {coverage:.0%}".format(**report)
    )
    if report["unused_stimuli"]:
        print(f"  Unused stimuli: {len(report['unused_stimuli'])}")
    return 0


def cmd_preview(args) -> int:
    stimuli = _scan(args)
    assignment = Assignment.from_csv(args.assignment_csv)
    config = _load_config(args.config)

    problems = assignment.validate(stimuli.ids)
    for problem in problems:
        print(f"Warning: {problem}", file=sys.stderr)

    wanted = [args.participant] if args.participant else assignment.participants[: args.limit]
    timelines = preview_timelines(assignment, stimuli, config, participants=wanted)

    for participant, timeline in timelines.items():
        print(f"\n=== {participant} ===")
        print(timeline.describe())
    if len(timelines) > 1:
        total = sum(t.duration for t in timelines.values())
        print(f"\n{len(timelines)} participants previewed, {total / 60:.1f} min total.")
    return 0


def cmd_build(args) -> int:
    stimuli = _scan(args)
    assignment = Assignment.from_csv(args.assignment_csv)
    assignment.notes = str(Path(args.assignment_csv).resolve())
    config = _load_config(args.config)

    problems = assignment.validate(stimuli.ids)
    if problems:
        for problem in problems:
            print(f"Error: {problem}", file=sys.stderr)
        if not args.force:
            print("Refusing to build. Re-run with --force to continue anyway.", file=sys.stderr)
            return 2

    config_problems = config.validate()
    if config_problems:
        for problem in config_problems:
            print(f"Config error: {problem}", file=sys.stderr)
        return 2

    cancel = threading.Event()
    progress = _progress_printer(args.quiet)
    log = (lambda message: print(f"\n{message}")) if args.verbose else (lambda message: None)

    try:
        report = build_all(
            assignment,
            stimuli,
            config,
            args.output_folder,
            participants=args.participant or None,
            progress=progress,
            log=log,
            cancel_event=cancel,
        )
    except KeyboardInterrupt:  # pragma: no cover - interactive
        cancel.set()
        print("\nCancelled.", file=sys.stderr)
        return 130
    except FFmpegError as exc:
        print(f"\nFFmpeg error: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print()
    print(report.describe())
    return 0 if report.n_failed == 0 else 1


def cmd_config(args) -> int:
    config = BuildConfig()
    path = Path(args.output)
    config.to_json(path)
    print(f"Wrote default settings to {path}")
    return 0


def cmd_doctor(args) -> int:
    print(f"stim-concat {__version__}")
    print(f"python      {sys.version.split()[0]} ({sys.executable})")
    ok = True
    try:
        print(f"ffmpeg      {ffmpeg_path()}")
        print(f"            {ffmpeg_version()}")
    except FFmpegError as exc:
        ok = False
        print(f"ffmpeg      NOT FOUND: {exc}")
    probe = ffprobe_path()
    print(f"ffprobe     {probe or 'not found (durations read from ffmpeg output instead)'}")
    try:
        import openpyxl  # noqa: F401

        print("openpyxl    available (.xlsx export enabled)")
    except ImportError:
        print("openpyxl    missing (.xlsx export disabled)")
    try:
        import tkinter  # noqa: F401

        print("tkinter     available (GUI enabled)")
    except ImportError:
        print("tkinter     missing (GUI disabled; on Debian/Ubuntu: apt install python3-tk)")
    from .core.config import resolve_font

    font = resolve_font()
    print(f"font        {font or 'NONE FOUND - set one in the instruction settings'}")
    ok = ok and font is not None
    print(f"algorithms  {len(discover())} available")
    return 0 if ok else 1


def cmd_gui(args) -> int:
    try:
        from .gui.app import launch
    except ImportError as exc:  # pragma: no cover - depends on environment
        print(
            f"The graphical interface needs tkinter, which is not available ({exc}).\n"
            "On Debian/Ubuntu install it with: sudo apt install python3-tk",
            file=sys.stderr,
        )
        return 1
    return launch()


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stim-concat",
        description="Build participant-specific concatenated stimulus videos.",
    )
    parser.add_argument("--version", action="version", version=f"stim-concat {__version__}")
    sub = parser.add_subparsers(dest="command")

    def add_scan_args(sp):
        sp.add_argument("stimulus_folder", help="Folder containing the stimulus files")
        sp.add_argument(
            "--id-pattern",
            default=DEFAULT_ID_PATTERN,
            help="Regex (with an 'id' group) used to read stimulus IDs from filenames",
        )
        sp.add_argument("--recursive", action="store_true", help="Include sub-folders")

    p = sub.add_parser("scan", help="List the stimuli found in a folder")
    add_scan_args(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("algorithms", help="List available assignment algorithms")
    p.add_argument("--json", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_algorithms)

    p = sub.add_parser("show", help="Print an algorithm's source so you can edit it")
    p.add_argument("algorithm")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("assign", help="Generate a participant assignment sheet")
    add_scan_args(p)
    p.add_argument("-n", "--participants", type=int, required=True)
    p.add_argument("-k", "--per-participant", type=int, required=True)
    p.add_argument("-a", "--algorithm", default="balanced_random")
    p.add_argument("-s", "--seed", type=int, default=None)
    p.add_argument("-o", "--output", default="participant_assignments.csv")
    p.add_argument("--param", action="append", metavar="NAME=VALUE")
    p.add_argument("--script", help="Run this edited algorithm script instead of the built-in file")
    p.set_defaults(func=cmd_assign)

    p = sub.add_parser("preview", help="Print the timeline without rendering video")
    p.add_argument("assignment_csv")
    add_scan_args(p)
    p.add_argument("--config", help="Settings JSON")
    p.add_argument("--participant")
    p.add_argument("--limit", type=int, default=1)
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("build", help="Render participant videos")
    p.add_argument("assignment_csv")
    add_scan_args(p)
    p.add_argument("output_folder")
    p.add_argument("--config", help="Settings JSON")
    p.add_argument("--participant", action="append", help="Build only these participants")
    p.add_argument("--force", action="store_true", help="Build despite validation problems")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("config", help="Write a default settings JSON you can edit")
    p.add_argument("-o", "--output", default="stim_concat_settings.json")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("doctor", help="Check that FFmpeg, fonts and optional extras are present")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("gui", help="Launch the graphical wizard")
    p.set_defaults(func=cmd_gui)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        # No sub-command: launch the wizard, which is what double-clicking does.
        return cmd_gui(args)
    try:
        return args.func(args)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except AssignmentError as exc:
        print(f"Assignment error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
