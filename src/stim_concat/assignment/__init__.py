"""Participant-to-stimulus assignment: data model and pluggable algorithms."""

from .base import Assignment, AssignmentError, stimulus_fingerprint
from .registry import (
    AlgorithmSpec,
    builtin_dir,
    compile_algorithm,
    discover,
    get,
    run_algorithm,
    run_source,
    user_dir,
)

__all__ = [
    "AlgorithmSpec",
    "Assignment",
    "AssignmentError",
    "builtin_dir",
    "compile_algorithm",
    "discover",
    "get",
    "run_algorithm",
    "run_source",
    "stimulus_fingerprint",
    "user_dir",
]
