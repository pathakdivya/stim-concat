"""Rendering a :class:`~stim_concat.core.timeline.Timeline` into an MP4.

Strategy
--------
Every timeline event is rendered to its own intermediate segment using
*identical* encoder settings (codec, resolution, frame rate, pixel format,
sample rate, channel layout).  The segments are then joined with FFmpeg's
concat *demuxer* and ``-c copy``, so the join is a stream copy: fast, and with
no second generation of lossy encoding.

Because all segments share a frame rate and every duration was snapped to a
whole number of frames when the timeline was built, event boundaries in the
finished file match the exported timeline exactly.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import BuildConfig
from .ffmpeg import FFmpegError, ffmpeg_path
from .screens import render_event_screen, render_text_screen, save_screen
from .timeline import Timeline, TimelineEvent

__all__ = ["BuildCancelled", "RenderResult", "VideoRenderer", "hex_to_ffmpeg_color"]

ProgressFn = Callable[[float, str], None]

#: Intermediate segments hold uncompressed audio in a container with a fine
#: timebase, so both streams can be cut exactly. The final file is normal MP4.
SEGMENT_SUFFIX = ".mov"
SEGMENT_AUDIO_CODEC = "pcm_s16le"


class BuildCancelled(RuntimeError):
    """Raised when a build is cancelled through its cancel event."""


def hex_to_ffmpeg_color(value: str, alpha: float | None = None) -> str:
    """``#RRGGBB`` (or a colour name) -> an FFmpeg colour string."""
    value = (value or "").strip()
    if not value:
        return "black"
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        colour = f"0x{digits.upper()}"
    else:
        colour = value
    if alpha is not None:
        colour = f"{colour}@{alpha:g}"
    return colour


def _escape_filter_path(path: Path | str) -> str:
    """Escape a path for use inside an FFmpeg filter argument."""
    text = str(path).replace("\\", "/")
    text = text.replace(":", r"\:")
    text = text.replace("'", r"\'")
    return text


def _even(value: float) -> int:
    """Round to the nearest positive even integer (yuv420p requires even sizes)."""
    n = round(value / 2.0) * 2
    return max(2, n)


def _anchor_offset(
    canvas_w: int, canvas_h: int, item_w: float, item_h: float, anchor: str
) -> tuple[float, float]:
    """Top-left coordinate placing an item of the given size at *anchor*."""
    vertical, _, horizontal = anchor.partition("-")
    if not horizontal:  # e.g. "center"
        vertical = horizontal = anchor
    x = {"left": 0.0, "center": (canvas_w - item_w) / 2.0, "right": canvas_w - item_w}.get(
        horizontal, (canvas_w - item_w) / 2.0
    )
    y = {"top": 0.0, "center": (canvas_h - item_h) / 2.0, "bottom": canvas_h - item_h}.get(
        vertical, (canvas_h - item_h) / 2.0
    )
    return x, y


@dataclass
class RenderResult:
    """Outcome of one participant build."""

    participant: str
    video: Path
    timeline: Timeline
    duration: float
    segments: int
    outputs: dict[str, Path]


class VideoRenderer:
    """Renders timelines to video files."""

    def __init__(
        self,
        config: BuildConfig,
        *,
        progress: ProgressFn | None = None,
        cancel_event: threading.Event | None = None,
        log: Callable[[str], None] | None = None,
    ):
        self.config = config
        self.progress = progress or (lambda fraction, message: None)
        self.cancel_event = cancel_event or threading.Event()
        self.log = log or (lambda message: None)

    # -- process handling --------------------------------------------------
    def _run(self, args: Sequence[str]) -> None:
        self._check_cancel()
        self.log("$ ffmpeg " + " ".join(str(a) for a in args[1:]))
        proc = subprocess.Popen(
            [str(a) for a in args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
        stderr_chunks: list[str] = []
        try:
            while True:
                try:
                    _, stderr = proc.communicate(timeout=0.5)
                    stderr_chunks.append(stderr or "")
                    break
                except subprocess.TimeoutExpired:
                    if self.cancel_event.is_set():
                        proc.kill()
                        proc.wait(timeout=5)
                        raise BuildCancelled("Build cancelled by user.") from None
        finally:
            if proc.poll() is None:  # pragma: no cover - defensive
                proc.kill()
        if proc.returncode != 0:
            raise FFmpegError(
                f"FFmpeg exited with code {proc.returncode}",
                command=args,
                stderr="".join(stderr_chunks),
            )

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise BuildCancelled("Build cancelled by user.")

    # -- shared encoder arguments -----------------------------------------
    def frame_count(self, duration: float) -> int:
        """Exact number of frames a segment of *duration* seconds must contain."""
        return max(1, round(duration * self.config.video.fps))

    def _encode_args(self, duration: float) -> list[str]:
        """Encoder settings shared by every segment.

        Two details make the result frame-exact:

        ``-frames:v N``
            pins the video stream to exactly the number of frames the timeline
            promised, instead of letting ``-t`` round independently in each
            segment (which accumulated several frames of drift across a build).
        ``-c:a pcm_s16le``
            keeps segment audio uncompressed, so it can be cut at an exact
            sample boundary. Lossy codecs pad to their own frame size (~21 ms
            for AAC), which would desynchronise audio and video a little more
            with every segment. The audio is encoded once, at the end.
        """
        v = self.config.video
        args = [
            "-frames:v",
            str(self.frame_count(duration)),
            "-t",
            f"{duration:.6f}",
            "-r",
            f"{v.fps:g}",
            "-c:v",
            v.video_codec,
            "-pix_fmt",
            v.pixel_format,
        ]
        if v.video_bitrate:
            args += ["-b:v", v.video_bitrate]
        elif v.video_codec in ("libx264", "libx265"):
            args += ["-crf", str(v.crf)]
        if v.video_codec in ("libx264", "libx265") and v.preset:
            args += ["-preset", v.preset]
        args += [
            "-c:a",
            SEGMENT_AUDIO_CODEC,
            "-ar",
            str(v.sample_rate),
            "-ac",
            str(v.audio_channels),
            "-video_track_timescale",
            "90000",
        ]
        if v.threads:
            args += ["-threads", str(v.threads)]
        args += list(v.extra_output_args)
        return args

    def _silent_audio_input(self) -> list[str]:
        v = self.config.video
        layout = "stereo" if v.audio_channels == 2 else "mono"
        return [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout={layout}:sample_rate={v.sample_rate}",
        ]

    def _colour_input(self, colour: str, duration: float) -> list[str]:
        v = self.config.video
        spec = (
            f"color=c={hex_to_ffmpeg_color(colour)}:s={v.width}x{v.height}"
            f":r={v.fps:g}:d={duration:.6f}"
        )
        return ["-f", "lavfi", "-i", spec]

    # -- synthetic screens --------------------------------------------------
    def _still_segment(self, image_path: Path, out: Path, duration: float) -> None:
        """Encode a still PNG as a segment of *duration* seconds with silent audio."""
        v = self.config.video
        args = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error"]
        args += ["-loop", "1", "-framerate", f"{v.fps:g}", "-i", str(image_path)]
        args += self._silent_audio_input()
        args += [
            "-filter_complex",
            f"[0:v]scale={v.width}:{v.height},setsar=1,fps={v.fps:g},format={v.pixel_format}[v]",
            "-map",
            "[v]",
            "-map",
            "1:a",
        ]
        args += self._encode_args(duration)
        args += [str(out)]
        self._run(args)

    def _render_screen(self, event: TimelineEvent, out: Path, workdir: Path) -> None:
        image = render_event_screen(event, self.config)
        png = save_screen(image, workdir / f"screen_{event.index:04d}.png")
        self._still_segment(png, out, event.duration)

    def _scaled_size(self, src_w: int | None, src_h: int | None) -> tuple[int, int]:
        v = self.config.video
        layout = self.config.layout
        if not src_w or not src_h:
            return v.width, v.height
        if layout.fit == "stretch":
            tw, th = v.width, v.height
        elif layout.fit == "none":
            tw, th = src_w, src_h
        else:
            ratios = (v.width / src_w, v.height / src_h)
            factor = min(ratios) if layout.fit == "contain" else max(ratios)
            tw, th = src_w * factor, src_h * factor
        tw *= layout.scale
        th *= layout.scale
        return _even(tw), _even(th)

    def _render_stimulus(self, event: TimelineEvent, out: Path, workdir: Path) -> None:
        """Render one stimulus onto the canvas, preserving its audio by default."""
        v = self.config.video
        layout = self.config.layout
        kind = event.spec.get("kind", "video")
        source = event.source
        assert source is not None
        duration = f"{event.duration:.6f}"

        # A text stimulus is just a text screen made from the file's contents.
        if kind == "text":
            text = source.read_text(encoding="utf-8", errors="replace")
            image = render_text_screen(text, v, self.config.instructions)
            png = save_screen(image, workdir / f"screen_{event.index:04d}.png")
            self._still_segment(png, out, event.duration)
            return

        keep_audio = bool(event.spec.get("has_audio")) and v.preserve_audio
        inputs: list[str] = []
        video_index = 0

        if kind == "audio":
            # Audio-only stimulus: still backdrop (optionally captioned) + its audio.
            backdrop = render_text_screen(
                layout.audio_caption,
                v,
                self.config.instructions,
                background=layout.audio_background,
            )
            png = save_screen(backdrop, workdir / f"screen_{event.index:04d}.png")
            inputs += ["-loop", "1", "-framerate", f"{v.fps:g}", "-i", str(png)]
            inputs += ["-i", str(source)]
            audio_index = 1 if keep_audio else None
            filter_complex = (
                f"[0:v]scale={v.width}:{v.height},setsar=1,fps={v.fps:g},"
                f"format={v.pixel_format}[v]"
            )
            next_index = 2
        else:
            if kind == "image":
                inputs += ["-loop", "1", "-framerate", f"{v.fps:g}", "-i", str(source)]
            else:
                inputs += ["-i", str(source)]
            audio_index = video_index if keep_audio else None
            next_index = 1

            target_w, target_h = self._scaled_size(
                event.spec.get("width"), event.spec.get("height")
            )
            x, y = _anchor_offset(v.width, v.height, target_w, target_h, layout.position)
            x += layout.offset_x
            y += layout.offset_y
            background = hex_to_ffmpeg_color(layout.background)
            filter_complex = (
                f"color=c={background}:s={v.width}x{v.height}:r={v.fps:g}:d={duration}[bg];"
                f"[{video_index}:v]scale={target_w}:{target_h}:flags=bicubic,setsar=1[fg];"
                f"[bg][fg]overlay=x={x:.2f}:y={y:.2f}:shortest=0,"
                f"fps={v.fps:g},format={v.pixel_format},"
                # clone the last frame if rounding leaves us a frame short, so
                # -frames:v always has exactly as many frames as it needs
                f"tpad=stop_mode=clone:stop_duration=1[v]"
            )

        if audio_index is None:
            inputs += self._silent_audio_input()
            audio_map = f"{next_index}:a"
        else:
            # Pad short audio so the track never ends before the video does.
            filter_complex += (
                f";[{audio_index}:a]aresample={v.sample_rate},apad,"
                f"aformat=sample_rates={v.sample_rate}[a]"
            )
            audio_map = "[a]"

        args = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error"]
        args += inputs
        args += ["-filter_complex", filter_complex, "-map", "[v]", "-map", audio_map]
        args += self._encode_args(event.duration)
        args += [str(out)]
        self._run(args)

    def render_event(self, event: TimelineEvent, out: Path, workdir: Path) -> Path:
        """Render a single timeline event to *out*."""
        if event.event_type in ("instruction", "fixation", "blank"):
            self._render_screen(event, out, workdir)
        elif event.event_type == "stimulus":
            self._render_stimulus(event, out, workdir)
        else:  # pragma: no cover - guarded by the timeline builder
            raise ValueError(f"Unknown event type: {event.event_type}")
        if not out.exists() or out.stat().st_size == 0:
            raise FFmpegError(f"Segment {event.index} produced no output ({event.event_type}).")
        return out

    # -- the whole thing ----------------------------------------------------
    def render(self, timeline: Timeline, output: Path) -> RenderResult:
        """Render *timeline* to *output* (an .mp4 path)."""
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and not self.config.overwrite:
            raise FileExistsError(f"{output} already exists and overwrite is disabled.")

        segments_root = (
            output.parent / f".{output.stem}_segments"
            if self.config.keep_segments
            else Path(tempfile.mkdtemp(prefix="stimconcat_"))
        )
        segments_root.mkdir(parents=True, exist_ok=True)

        try:
            total = len(timeline)
            paths: list[Path] = []
            for i, event in enumerate(timeline):
                label = f"{event.event_type}"
                if event.stimulus_id:
                    label += f" {event.stimulus_id}"
                self.progress(
                    i / max(total + 1, 1),
                    f"{timeline.participant}: segment {i + 1}/{total} ({label})",
                )
                seg = segments_root / f"seg_{event.index:04d}_{event.event_type}{SEGMENT_SUFFIX}"
                self.render_event(event, seg, segments_root)
                paths.append(seg)

            self.progress(total / (total + 1), f"{timeline.participant}: joining segments")
            self._concat(paths, output, segments_root)
            self.progress(1.0, f"{timeline.participant}: done")
        finally:
            if not self.config.keep_segments:
                shutil.rmtree(segments_root, ignore_errors=True)

        return RenderResult(
            participant=timeline.participant,
            video=output,
            timeline=timeline,
            duration=timeline.duration,
            segments=len(timeline),
            outputs={"video": output},
        )

    def _concat(self, segments: Sequence[Path], output: Path, workdir: Path) -> None:
        v = self.config.video
        listing = workdir / "concat.txt"
        listing.write_text(
            "\n".join(f"file '{str(p.resolve()).replace(chr(39), chr(39) * 3)}'" for p in segments)
            + "\n",
            encoding="utf-8",
        )
        args = [
            ffmpeg_path(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            # Video is copied, so it is never re-encoded a second time; audio is
            # encoded once here from the exact uncompressed segment audio.
            "-c:v",
            "copy",
            "-c:a",
            v.audio_codec,
            "-b:a",
            v.audio_bitrate,
            "-ar",
            str(v.sample_rate),
            "-ac",
            str(v.audio_channels),
        ]
        if output.suffix.lower() in (".mp4", ".m4v", ".mov"):
            args += ["-movflags", "+faststart"]
        args += [str(output)]
        self._run(args)
