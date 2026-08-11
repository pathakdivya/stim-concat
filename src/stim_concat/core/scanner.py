"""Discovery of stimulus files and extraction of stimulus IDs.

The set of recognised formats lives in a small registry so that supporting a
new container is a one-line change (or a runtime call from a plugin)::

    from stim_concat.core.scanner import register_format
    register_format(".webm", "video")
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from re import error as RegexError

__all__ = [
    "DEFAULT_ID_PATTERN",
    "NUMERIC_ID_PATTERN",
    "MediaKind",
    "StimulusFile",
    "StimulusSet",
    "kind_for",
    "register_format",
    "scan_folder",
    "supported_extensions",
]

MediaKind = str  # one of: "video", "image", "audio", "text"

#: extension -> media kind
_FORMATS: dict[str, MediaKind] = {}


def register_format(extension: str, kind: MediaKind) -> None:
    """Register (or override) an extension so the scanner picks it up."""
    if kind not in ("video", "image", "audio", "text"):
        raise ValueError(f"Unknown media kind: {kind!r}")
    if not extension.startswith("."):
        extension = "." + extension
    _FORMATS[extension.lower()] = kind


for _ext in (".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm", ".mpg", ".mpeg", ".wmv"):
    register_format(_ext, "video")
for _ext in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".gif"):
    register_format(_ext, "image")
for _ext in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"):
    register_format(_ext, "audio")
for _ext in (".txt", ".md"):
    register_format(_ext, "text")


def supported_extensions() -> Mapping[str, MediaKind]:
    """A read-only view of the extension registry."""
    return dict(_FORMATS)


def kind_for(path: str | Path) -> MediaKind | None:
    """Media kind for *path*, or ``None`` if the extension is unknown."""
    return _FORMATS.get(Path(path).suffix.lower())


#: Use the whole filename stem as the stimulus ID.
DEFAULT_ID_PATTERN = r"(?P<id>.+)"
#: Use the first run of digits in the filename (``clip_070_sad.mp4`` -> ``070``).
NUMERIC_ID_PATTERN = r"(?P<id>\d+)"


@dataclass(frozen=True)
class StimulusFile:
    """A single stimulus on disk."""

    path: Path
    stimulus_id: str
    kind: MediaKind

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def extension(self) -> str:
        return self.path.suffix.lower()

    def as_dict(self) -> dict:
        return {
            "stimulus_id": self.stimulus_id,
            "filename": self.path.name,
            "path": str(self.path),
            "kind": self.kind,
        }


class StimulusSet(Sequence[StimulusFile]):
    """An ordered, ID-indexed collection of stimulus files."""

    def __init__(self, files: Iterable[StimulusFile], root: Path | None = None):
        self._files: list[StimulusFile] = list(files)
        self.root = Path(root) if root else None
        self._by_id: dict[str, StimulusFile] = {}
        self.duplicates: dict[str, list[Path]] = {}
        for item in self._files:
            if item.stimulus_id in self._by_id:
                self.duplicates.setdefault(item.stimulus_id, [self._by_id[item.stimulus_id].path])
                self.duplicates[item.stimulus_id].append(item.path)
            else:
                self._by_id[item.stimulus_id] = item

    # -- Sequence protocol -------------------------------------------------
    def __len__(self) -> int:
        return len(self._files)

    def __getitem__(self, index):  # type: ignore[override]
        return self._files[index]

    def __iter__(self) -> Iterator[StimulusFile]:
        return iter(self._files)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StimulusSet n={len(self._files)} root={self.root}>"

    # -- Lookup ------------------------------------------------------------
    @property
    def ids(self) -> list[str]:
        return [item.stimulus_id for item in self._files]

    def get(self, stimulus_id: str) -> StimulusFile | None:
        """Look up by ID, tolerating zero-padding differences (``7`` vs ``007``)."""
        key = str(stimulus_id).strip()
        if key in self._by_id:
            return self._by_id[key]
        if key.isdigit():
            for candidate_id, item in self._by_id.items():
                if candidate_id.isdigit() and int(candidate_id) == int(key):
                    return item
        lowered = key.lower()
        for candidate_id, item in self._by_id.items():
            if candidate_id.lower() == lowered:
                return item
        return None

    def require(self, stimulus_id: str) -> StimulusFile:
        item = self.get(stimulus_id)
        if item is None:
            raise KeyError(
                f"Stimulus {stimulus_id!r} is referenced by the assignment sheet "
                f"but was not found in the stimulus folder."
            )
        return item

    def missing(self, stimulus_ids: Iterable[str]) -> list[str]:
        """IDs in *stimulus_ids* that this set cannot resolve (order preserved)."""
        out: list[str] = []
        for sid in stimulus_ids:
            if self.get(sid) is None and sid not in out:
                out.append(sid)
        return out

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self._files:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return counts

    def filter_kinds(self, kinds: Iterable[str]) -> StimulusSet:
        allowed = set(kinds)
        return StimulusSet([f for f in self._files if f.kind in allowed], self.root)


# def _natural_key(text: str) -> tuple:
#     return tuple(
#         int(part) if part.isdigit() else part.lower()
#         for part in re.split(r"(\d+)", text)
#         if part != ""
#     )

def _natural_key(value: str):
    parts = re.split(r"(\d+)", value)

    key = []

    for part in parts:
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.lower()))

    return key


def extract_id(filename: str, pattern: str = DEFAULT_ID_PATTERN) -> str | None:
    """Extract a stimulus ID from a filename stem using *pattern*.

    The pattern may use a named group ``id``; otherwise group 1, otherwise the
    whole match is used.
    """
    stem = Path(filename).stem
    if not pattern:
        return stem
    match = re.search(pattern, stem)
    if not match:
        return None
    try:
        return match.group("id")
    except (IndexError, RegexError):
        pass
    if match.groups():
        return match.group(1)
    return match.group(0)


def scan_folder(
    folder: str | Path,
    *,
    id_pattern: str = DEFAULT_ID_PATTERN,
    recursive: bool = False,
    kinds: Iterable[str] | None = None,
) -> StimulusSet:
    """Scan *folder* and return the stimuli it contains.

    Parameters
    ----------
    folder:
        Directory to scan.
    id_pattern:
        Regular expression applied to each filename stem to derive the
        stimulus ID.  Defaults to the whole stem.
    recursive:
        Descend into sub-directories.
    kinds:
        Restrict results to these media kinds.
    """
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a folder: {root}")

    paths = root.rglob("*") if recursive else root.glob("*")
    wanted = set(kinds) if kinds else None

    found: list[StimulusFile] = []
    for path in sorted(paths, key=lambda p: _natural_key(str(p.relative_to(root)))):
        if not path.is_file() or path.name.startswith("."):
            continue
        kind = kind_for(path)
        if kind is None or (wanted is not None and kind not in wanted):
            continue
        stimulus_id = extract_id(path.name, id_pattern)
        if stimulus_id is None:
            continue
        found.append(StimulusFile(path=path, stimulus_id=stimulus_id, kind=kind))

    return StimulusSet(found, root=root)
