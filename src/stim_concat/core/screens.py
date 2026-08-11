"""Rendering of synthetic screens (instructions, fixation cross, blanks).

These screens are drawn with Pillow rather than FFmpeg's ``drawtext`` filter.
That choice matters in practice: many FFmpeg builds -- including the static
binaries shipped inside ``imageio-ffmpeg`` -- are compiled without libfreetype
and have no ``drawtext`` filter at all.  Drawing here instead means

* the application works with *any* FFmpeg build, so it can stay self-contained;
* text metrics are measured before drawing, so lines are truly centred;
* the very same function can produce a still preview for the wizard.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from pathlib import Path

from .config import BuildConfig, FixationConfig, InstructionConfig, VideoConfig, resolve_font

__all__ = [
    "PillowUnavailable",
    "hex_to_rgb",
    "render_blank_screen",
    "render_event_screen",
    "render_fixation_screen",
    "render_text_screen",
]


class PillowUnavailable(RuntimeError):
    """Raised when Pillow is not installed."""

    MESSAGE = (
        "Pillow is required to draw instruction and fixation screens. "
        "Install it with 'pip install Pillow'."
    )

    def __init__(self, message: str | None = None):
        super().__init__(message or self.MESSAGE)


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont

        return Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover - optional at runtime
        raise PillowUnavailable() from exc


def hex_to_rgb(value: str, default: tuple[int, int, int] = (0, 0, 0)) -> tuple[int, int, int]:
    """``#RRGGBB`` / ``#RGB`` / a few colour names -> an RGB triple."""
    text = (value or "").strip()
    if not text:
        return default
    named = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "red": (255, 0, 0),
        "green": (0, 128, 0),
        "blue": (0, 0, 255),
        "grey": (128, 128, 128),
        "gray": (128, 128, 128),
        "yellow": (255, 255, 0),
    }
    if text.lower() in named:
        return named[text.lower()]
    digits = text.lstrip("#")
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    if len(digits) != 6:
        return default
    try:
        return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return default


def _load_font(instructions: InstructionConfig, size: int | None = None):
    _, _, ImageFont = _pil()
    path = resolve_font(instructions.font_file)
    if not path:
        raise PillowUnavailable(
            "No font file could be found for instruction text. Choose a .ttf file "
            "in the instruction settings."
        )
    try:
        return ImageFont.truetype(path, int(size or instructions.font_size))
    except OSError as exc:
        raise PillowUnavailable(f"Could not load the font {path}: {exc}") from exc


def _wrap_lines(text: str, width: int) -> list[str]:
    """Character-count wrapping (used only as an upper bound)."""
    lines: list[str] = []
    for paragraph in (text or "").replace("\r\n", "\n").split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(paragraph, width=max(8, width)) or [""])
    return lines


def _wrap_to_width(text: str, draw, font, max_width: float, max_chars: int) -> list[str]:
    """Wrap text to a pixel width using real font metrics.

    Character counts are a poor proxy for width in a proportional font, and a
    line that is too wide is silently clipped by the canvas. Measuring instead
    means the configured resolution is always respected.
    """
    lines: list[str] = []
    for paragraph in (text or "").replace("\r\n", "\n").split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            fits = draw.textlength(candidate, font=font) <= max_width and len(candidate) <= max_chars
            if fits or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines or [""]


def _fit_text(draw, instructions: InstructionConfig, text: str, max_width: float, max_height: float):
    """Choose the largest font size (up to the configured one) that fits.

    Returns ``(font, lines, line_height, shrunk_to)``.
    """
    size = max(8, int(instructions.font_size))
    minimum = 10
    while True:
        font = _load_font(instructions, size)
        lines = _wrap_to_width(text, draw, font, max_width, instructions.max_chars_per_line)
        ascent, descent = font.getmetrics()
        line_height = ascent + descent
        block = len(lines) * line_height + max(0, len(lines) - 1) * instructions.line_spacing
        widest = max((draw.textlength(line, font=font) for line in lines), default=0)
        if (block <= max_height and widest <= max_width) or size <= minimum:
            return font, lines, line_height, (size if size != instructions.font_size else None)
        size -= 2


def render_text_screen(
    text: str,
    video: VideoConfig,
    instructions: InstructionConfig,
    *,
    background: str | None = None,
):
    """Draw a centred, word-wrapped text screen and return a PIL image."""
    Image, ImageDraw, _ = _pil()

    canvas = Image.new(
        "RGB",
        (video.width, video.height),
        hex_to_rgb(background if background is not None else instructions.background),
    )
    draw = ImageDraw.Draw(canvas)
    colour = hex_to_rgb(instructions.font_color, (255, 255, 255))

    margin_x = video.width * 0.08
    font, lines, line_height, _shrunk = _fit_text(
        draw, instructions, text, video.width - 2 * margin_x, video.height * 0.9
    )
    step = line_height + instructions.line_spacing
    block_height = len(lines) * line_height + max(0, len(lines) - 1) * instructions.line_spacing
    top = (video.height - block_height) / 2.0
    margin = int(video.width * 0.08)

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        y = top + i * step
        if instructions.align == "center":
            width = draw.textlength(line, font=font)
            x = (video.width - width) / 2.0
        else:
            x = margin
        draw.text((x, y), line, font=font, fill=colour)
    return canvas


def render_fixation_screen(video: VideoConfig, fixation: FixationConfig):
    """Draw a fixation cross and return a PIL image."""
    Image, ImageDraw, _ = _pil()
    canvas = Image.new("RGB", (video.width, video.height), hex_to_rgb(fixation.background))
    draw = ImageDraw.Draw(canvas)
    colour = hex_to_rgb(fixation.color, (255, 255, 255))

    vertical, _, horizontal = fixation.position.partition("-")
    if not horizontal:
        vertical = horizontal = fixation.position
    half = max(1, fixation.size) / 2.0
    cx = {"left": half, "center": video.width / 2.0, "right": video.width - half}.get(
        horizontal, video.width / 2.0
    ) + fixation.offset_x
    cy = {"top": half, "center": video.height / 2.0, "bottom": video.height - half}.get(
        vertical, video.height / 2.0
    ) + fixation.offset_y

    thickness = max(1, fixation.thickness)
    draw.rectangle(
        [cx - half, cy - thickness / 2.0, cx + half, cy + thickness / 2.0], fill=colour
    )
    draw.rectangle(
        [cx - thickness / 2.0, cy - half, cx + thickness / 2.0, cy + half], fill=colour
    )
    return canvas


def render_blank_screen(video: VideoConfig, background: str):
    Image, _, _ = _pil()
    return Image.new("RGB", (video.width, video.height), hex_to_rgb(background))


def render_event_screen(event, config: BuildConfig):
    """Draw the still image for a non-stimulus timeline event."""
    if event.event_type == "instruction":
        return render_text_screen(
            event.spec.get("text", ""), config.video, config.instructions
        )
    if event.event_type == "fixation":
        return render_fixation_screen(config.video, config.fixation)
    if event.event_type == "blank":
        return render_blank_screen(config.video, config.timeline.blank_background)
    raise ValueError(f"{event.event_type} is not a synthetic screen")


def save_screen(image, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def available() -> bool:
    """Whether Pillow can be imported (used by ``stim-concat doctor``)."""
    try:
        _pil()
        return True
    except PillowUnavailable:
        return False


def font_sample(instructions: InstructionConfig, video: VideoConfig, text: str = "Sample") -> Sequence[int]:
    """Pixel size of *text* in the configured font (used for GUI hints)."""
    _, ImageDraw, _ = _pil()
    from PIL import Image

    font = _load_font(instructions)
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]
