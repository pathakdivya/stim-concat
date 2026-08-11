"""stim-concat: participant-specific concatenated stimulus videos for behavioural experiments.

Typical library use::

    from stim_concat import scan_folder, run_algorithm, BuildConfig, build_all

    stimuli = scan_folder("stimuli/")
    assignment = run_algorithm("balanced_random", stimuli.ids, 20, 8, seed=42)
    assignment.to_csv("participant_assignments.csv")
    build_all(assignment, stimuli, BuildConfig(), "output/")
"""

from __future__ import annotations

__version__ = "0.1.0"
__author__ = "stim-concat contributors"
__license__ = "MIT"

from .assignment.base import Assignment, AssignmentError
from .assignment.registry import discover, get, run_algorithm, run_source
from .core.config import (
    BuildConfig,
    FixationConfig,
    InstructionConfig,
    StimulusLayout,
    TimelineConfig,
    VideoConfig,
)
from .core.pipeline import BuildReport, build_all, preview_timelines
from .core.scanner import StimulusFile, StimulusSet, register_format, scan_folder
from .core.timeline import Timeline, TimelineEvent, build_timeline

__all__ = [
    "Assignment",
    "AssignmentError",
    "BuildConfig",
    "BuildReport",
    "FixationConfig",
    "InstructionConfig",
    "StimulusFile",
    "StimulusLayout",
    "StimulusSet",
    "Timeline",
    "TimelineConfig",
    "TimelineEvent",
    "VideoConfig",
    "__version__",
    "build_all",
    "build_timeline",
    "discover",
    "get",
    "preview_timelines",
    "register_format",
    "run_algorithm",
    "run_source",
    "scan_folder",
]
