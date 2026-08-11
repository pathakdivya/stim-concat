"""Serialisable configuration objects for the stimulus builder.

Everything the builder needs is expressed as plain dataclasses that round-trip
to JSON.  A saved ``ParticipantXXX_settings.json`` therefore fully describes how
a video was produced, which is what makes a build reproducible.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "ANCHORS",
    "Anchor",
    "BuildConfig",
    "FitMode",
    "FixationConfig",
    "InstructionConfig",
    "StimulusLayout",
    "TimelineConfig",
    "VideoConfig",
    "resolve_font",
]

Anchor = Literal[
    "top-left",
    "top-center",
    "top-right",
    "center-left",
    "center",
    "center-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
]

ANCHORS: tuple[str, ...] = (
    "top-left",
    "top-center",
    "top-right",
    "center-left",
    "center",
    "center-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
)

FitMode = Literal["contain", "cover", "stretch", "none"]

#: Fonts searched when the user has not chosen one explicitly.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
)


def resolve_font(preferred: str | None = None) -> str | None:
    """Return a usable TrueType font path.

    FFmpeg's ``drawtext`` filter needs a real font file.  We look at the user's
    choice first, then a bundled copy, then ``matplotlib``'s DejaVu (which is
    installed in most scientific Python environments), then the usual system
    locations.
    """
    if preferred and Path(preferred).exists():
        return str(preferred)

    bundled = Path(__file__).resolve().parent.parent / "resources" / "DejaVuSans.ttf"
    if bundled.exists():
        return str(bundled)

    try:  # matplotlib ships DejaVuSans and is a very common transitive dep
        import matplotlib

        candidate = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
        if candidate.exists():
            return str(candidate)
    except Exception:  # pragma: no cover - optional
        pass

    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


@dataclass
class FixationConfig:
    """Appearance of the fixation cross."""

    enabled: bool = True
    duration: float = 1.0
    size: int = 40  # arm-to-arm extent in pixels
    thickness: int = 4
    color: str = "#FFFFFF"
    background: str = "#000000"
    position: Anchor = "center"
    offset_x: int = 0
    offset_y: int = 0


@dataclass
class InstructionConfig:
    """Instruction screens shown around and between stimuli."""

    opening_enabled: bool = True
    opening_text: str = (
        "Welcome.\n\nYou will now see a series of short clips.\n"
        "Please keep your eyes on the screen."
    )
    opening_duration: float = 8.0

    closing_enabled: bool = True
    closing_text: str = "The experiment is complete.\n\nThank you for taking part."
    closing_duration: float = 5.0

    #: Shown before every stimulus when "instruction" is part of the trial sequence.
    interleaved_enabled: bool = True
    default_text: str = "Watch the next clip."
    default_duration: float = 3.0

    #: stimulus_id -> {"text": str, "duration": float}; overrides the default.
    per_stimulus: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Typography
    font_file: str = ""
    font_size: int = 48
    font_color: str = "#FFFFFF"
    background: str = "#000000"
    line_spacing: int = 12
    max_chars_per_line: int = 46
    align: Literal["center", "left"] = "center"

    def for_stimulus(self, stimulus_id: str) -> tuple[str, float]:
        """Return ``(text, duration)`` for the instruction preceding *stimulus_id*."""
        override = self.per_stimulus.get(str(stimulus_id))
        if override:
            text = override.get("text", self.default_text)
            duration = float(override.get("duration", self.default_duration))
            return text, duration
        return self.default_text, self.default_duration

    def has_override(self, stimulus_id: str) -> bool:
        return str(stimulus_id) in self.per_stimulus


@dataclass
class StimulusLayout:
    """Where and how the stimulus is drawn on the canvas."""

    fit: FitMode = "contain"
    position: Anchor = "center"
    offset_x: int = 0
    offset_y: int = 0
    background: str = "#000000"
    scale: float = 1.0  # extra scale factor applied after fitting
    #: Duration used for still images (seconds).
    image_duration: float = 4.0
    #: Canvas colour behind audio-only stimuli.
    audio_background: str = "#000000"
    #: Optional caption drawn over audio-only stimuli.
    audio_caption: str = ""


@dataclass
class VideoConfig:
    """Encoding parameters for every rendered segment and the final file."""

    width: int = 1280
    height: int = 720
    fps: float = 30.0
    video_codec: str = "libx264"
    pixel_format: str = "yuv420p"
    crf: int = 20
    preset: str = "medium"
    video_bitrate: str = ""  # e.g. "4M"; overrides CRF when set
    preserve_audio: bool = True
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    sample_rate: int = 48000
    audio_channels: int = 2
    container: str = "mp4"
    extra_output_args: list[str] = field(default_factory=list)
    threads: int = 0  # 0 = let FFmpeg decide

    @property
    def size(self) -> str:
        return f"{self.width}x{self.height}"

    def quantise(self, seconds: float) -> float:
        """Snap a duration to a whole number of frames.

        Every segment is encoded at a constant frame rate, so quantising here
        keeps the exported timeline exact rather than approximate.
        """
        if self.fps <= 0:
            return round(float(seconds), 6)
        frames = max(1, round(float(seconds) * self.fps))
        return round(frames / self.fps, 6)


@dataclass
class TimelineConfig:
    """Order of events in the generated video."""

    #: Elements repeated for every trial, in order.
    trial_sequence: list[str] = field(default_factory=lambda: ["fixation", "instruction", "stimulus"])
    #: Elements appended after the final trial (before the closing screen).
    trailing_sequence: list[str] = field(default_factory=lambda: ["fixation"])
    #: Optional blank screen duration, used when "blank" appears in a sequence.
    blank_duration: float = 0.5
    blank_background: str = "#000000"

    ALLOWED = ("fixation", "instruction", "stimulus", "blank")

    def validate(self) -> list[str]:
        problems = []
        for name, seq in (("trial", self.trial_sequence), ("trailing", self.trailing_sequence)):
            for element in seq:
                if element not in self.ALLOWED:
                    problems.append(f"Unknown {name} element {element!r}")
        if "stimulus" not in self.trial_sequence:
            problems.append("The trial sequence must contain 'stimulus'.")
        if self.trial_sequence.count("stimulus") > 1:
            problems.append("The trial sequence may contain 'stimulus' only once.")
        return problems


@dataclass
class BuildConfig:
    """Everything needed to turn an assignment row into a video."""

    video: VideoConfig = field(default_factory=VideoConfig)
    fixation: FixationConfig = field(default_factory=FixationConfig)
    instructions: InstructionConfig = field(default_factory=InstructionConfig)
    layout: StimulusLayout = field(default_factory=StimulusLayout)
    timeline: TimelineConfig = field(default_factory=TimelineConfig)
    #: Printf-style template for output filenames.
    filename_template: str = "{participant}"
    overwrite: bool = True
    keep_segments: bool = False

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: str | Path, *, extra: dict | None = None) -> Path:
        payload = self.to_dict()
        if extra:
            payload["_meta"] = extra
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: dict) -> BuildConfig:
        return _from_dict(cls, {k: v for k, v in data.items() if not k.startswith("_")})

    @classmethod
    def from_json(cls, path: str | Path) -> BuildConfig:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def validate(self) -> list[str]:
        problems = list(self.timeline.validate())
        if self.video.width % 2 or self.video.height % 2:
            problems.append("Output width and height must both be even for yuv420p.")
        if self.video.fps <= 0:
            problems.append("Frame rate must be positive.")
        if self.fixation.enabled and self.fixation.duration <= 0:
            problems.append("Fixation duration must be positive.")
        if resolve_font(self.instructions.font_file) is None and self._needs_text():
            problems.append(
                "No font file could be found for the instruction screens. "
                "Choose a .ttf file in the instruction settings."
            )
        return problems

    def _needs_text(self) -> bool:
        return (
            self.instructions.opening_enabled
            or self.instructions.closing_enabled
            or "instruction" in self.timeline.trial_sequence
        )


def _from_dict(cls, data: Any):
    """Recursively rebuild nested dataclasses from plain dictionaries."""
    if not is_dataclass(cls) or not isinstance(data, dict):
        return data
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        if is_dataclass(f.type) or (isinstance(f.type, type) and is_dataclass(f.type)):
            kwargs[f.name] = _from_dict(f.type, value)
        else:
            kwargs[f.name] = value
    obj = cls(**{k: v for k, v in kwargs.items() if not is_dataclass(v) or True})
    # Nested dataclass fields declared with string annotations need a second pass.
    for f in fields(cls):
        current = getattr(obj, f.name)
        if isinstance(current, dict) and f.name in ("video", "fixation", "instructions", "layout", "timeline"):
            mapping = {
                "video": VideoConfig,
                "fixation": FixationConfig,
                "instructions": InstructionConfig,
                "layout": StimulusLayout,
                "timeline": TimelineConfig,
            }
            setattr(obj, f.name, _from_dict(mapping[f.name], current))
    return obj
