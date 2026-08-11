"""Locating, invoking and probing with FFmpeg.

``stim-concat`` never asks the end user to install FFmpeg.  Binaries are
resolved in the following order:

1. ``STIM_CONCAT_FFMPEG`` / ``STIM_CONCAT_FFPROBE`` environment variables.
2. Binaries bundled next to the frozen application (PyInstaller ``_MEIPASS``).
3. Binaries shipped inside the ``imageio-ffmpeg`` wheel (a hard dependency, so
   this always succeeds for a normal ``pip install``).
4. A system-wide ``ffmpeg`` on ``PATH``.

``ffprobe`` is *not* shipped by ``imageio-ffmpeg``.  When it is unavailable we
fall back to parsing the banner that ``ffmpeg -i`` writes to stderr, which is
enough to recover duration, resolution, frame rate and the presence of audio.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

__all__ = [
    "FFmpegError",
    "FFmpegNotFound",
    "MediaInfo",
    "ffmpeg_path",
    "ffmpeg_version",
    "ffprobe_path",
    "probe",
    "run",
]


class FFmpegError(RuntimeError):
    """Raised when an FFmpeg invocation fails."""

    def __init__(self, message: str, *, command: Sequence[str] | None = None, stderr: str = ""):
        super().__init__(message)
        self.command = list(command or [])
        self.stderr = stderr

    def __str__(self) -> str:  # pragma: no cover - formatting only
        base = super().__str__()
        tail = "\n".join(self.stderr.strip().splitlines()[-12:])
        if tail:
            return f"{base}\n--- ffmpeg output ---\n{tail}"
        return base


class FFmpegNotFound(FFmpegError):
    """Raised when no usable FFmpeg binary can be located."""


def _frozen_dir() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def _candidate(name: str) -> str | None:
    exe = name + (".exe" if os.name == "nt" else "")

    env = os.environ.get(f"STIM_CONCAT_{name.upper()}")
    if env and Path(env).exists():
        return env

    frozen = _frozen_dir()
    if frozen:
        for candidate in (frozen / exe, frozen / "ffmpeg" / exe, frozen / "bin" / exe):
            if candidate.exists():
                return str(candidate)

    if name == "ffmpeg":
        try:
            import imageio_ffmpeg

            path = imageio_ffmpeg.get_ffmpeg_exe()
            if path and Path(path).exists():
                return path
        except Exception:  # pragma: no cover - optional dependency
            pass

    found = shutil.which(name)
    if found:
        return found

    # imageio-ffmpeg keeps ffprobe-less builds; some distributions ship both
    # binaries side by side, so look next to a resolved ffmpeg as a last resort.
    if name == "ffprobe":
        try:
            sibling = Path(ffmpeg_path()).with_name(exe)
            if sibling.exists():
                return str(sibling)
        except FFmpegNotFound:
            pass
    return None


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    """Absolute path to a usable ``ffmpeg`` binary."""
    path = _candidate("ffmpeg")
    if not path:
        raise FFmpegNotFound(
            "No FFmpeg binary could be found. Install the 'imageio-ffmpeg' "
            "package, put ffmpeg on your PATH, or set STIM_CONCAT_FFMPEG."
        )
    return path


@lru_cache(maxsize=1)
def ffprobe_path() -> str | None:
    """Absolute path to ``ffprobe``, or ``None`` if unavailable."""
    return _candidate("ffprobe")


@lru_cache(maxsize=1)
def ffmpeg_version() -> str:
    out = run([ffmpeg_path(), "-hide_banner", "-version"], check=False).stdout
    first = out.splitlines()[0] if out else "unknown"
    return first.strip()


def _no_window_kwargs() -> dict:
    if os.name == "nt":  # pragma: no cover - Windows only
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": startupinfo, "creationflags": 0x08000000}
    return {}


def run(
    args: Sequence[str],
    *,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Run a command, capturing text output. Raises :class:`FFmpegError`."""
    try:
        proc = subprocess.run(
            list(args),
            capture_output=True,
            check=False,
            text=True,
            errors="replace",
            timeout=timeout,
            **_no_window_kwargs(),
        )
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        raise FFmpegNotFound(f"Executable not found: {args[0]}") from exc
    if check and proc.returncode != 0:
        raise FFmpegError(
            f"Command failed with exit code {proc.returncode}: {Path(args[0]).name}",
            command=args,
            stderr=proc.stderr,
        )
    return proc


@dataclass
class MediaInfo:
    """Structural information about a media file."""

    path: Path
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_video: bool = False
    has_audio: bool = False
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def aspect_ratio(self) -> float | None:
        if self.width and self.height:
            return self.width / self.height
        return None


def _parse_fraction(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else None
        return float(value)
    except (TypeError, ValueError):
        return None


def _probe_with_ffprobe(path: Path, exe: str) -> MediaInfo:
    proc = run(
        [
            exe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    data = json.loads(proc.stdout or "{}")
    info = MediaInfo(path=path, raw=data)
    duration = _parse_fraction((data.get("format") or {}).get("duration"))
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind == "video" and not info.has_video:
            info.has_video = True
            info.width = stream.get("width")
            info.height = stream.get("height")
            info.fps = _parse_fraction(stream.get("avg_frame_rate")) or _parse_fraction(
                stream.get("r_frame_rate")
            )
            if duration is None:
                duration = _parse_fraction(stream.get("duration"))
        elif kind == "audio":
            info.has_audio = True
            if duration is None:
                duration = _parse_fraction(stream.get("duration"))
    # Still images report a nominal duration of a single frame or none at all.
    info.duration = duration
    return info


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?: Video:.*?(\d{2,5})x(\d{2,5})")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s+fps")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio:")


def _probe_with_ffmpeg(path: Path) -> MediaInfo:
    proc = run(
        [ffmpeg_path(), "-hide_banner", "-i", str(path), "-f", "null", "-"],
        check=False,
    )
    text = proc.stderr or ""
    info = MediaInfo(path=path, raw={"stderr": text})
    match = _DURATION_RE.search(text)
    if match:
        hours, minutes, seconds = match.groups()
        info.duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    vmatch = _VIDEO_RE.search(text)
    if vmatch:
        info.has_video = True
        info.width, info.height = int(vmatch.group(1)), int(vmatch.group(2))
        fmatch = _FPS_RE.search(text[vmatch.start() : vmatch.start() + 400])
        if fmatch:
            info.fps = float(fmatch.group(1))
    info.has_audio = bool(_AUDIO_RE.search(text))
    if not info.has_video and not info.has_audio and "Invalid data" in text:
        raise FFmpegError(f"Could not decode media file: {path}", stderr=text)
    return info


_PROBE_CACHE: dict[tuple[str, float, int], MediaInfo] = {}


def probe(path: str | os.PathLike[str], *, use_cache: bool = True) -> MediaInfo:
    """Return :class:`MediaInfo` for *path*.

    Results are cached on (path, mtime, size) so repeated timeline previews are
    cheap even for large stimulus sets.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime, stat.st_size)
    if use_cache and key in _PROBE_CACHE:
        return _PROBE_CACHE[key]

    exe = ffprobe_path()
    info = _probe_with_ffprobe(path, exe) if exe else _probe_with_ffmpeg(path)
    if use_cache:
        _PROBE_CACHE[key] = info
    return info


def clear_probe_cache() -> None:
    _PROBE_CACHE.clear()


def iter_progress(stderr_lines: Iterable[str]) -> Iterable[float]:  # pragma: no cover
    """Yield elapsed output seconds parsed from ``-progress`` output."""
    for line in stderr_lines:
        if line.startswith("out_time_ms="):
            try:
                yield int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue
