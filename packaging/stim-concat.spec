# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for a self-contained stim-concat application.

    pyinstaller packaging/stim-concat.spec

The end user installs nothing else: FFmpeg and a font are collected into the
bundle, so no separate Python, FFmpeg or font installation is required.
"""

from pathlib import Path

from PyInstaller.building.splash import Splash
from PyInstaller.utils.hooks import collect_data_files

datas = [
    ("../src/stim_concat/resources/stim-concat.ico", "stim_concat/resources"),
    ("../assets/1.png", "assets"),
]
binaries = []

# --- the assignment algorithm scripts (loaded from disk at runtime) ---------
# datas += collect_data_files("stim_concat", includes=["assignment/algorithms/*.py"])

algorithm_dir = Path("../src/stim_concat/assignment/algorithms")

for algorithm_file in algorithm_dir.glob("*.py"):
    if not algorithm_file.name.startswith("_"):
        datas.append(
            (
                str(algorithm_file),
                "stim_concat/assignment/algorithms"
            )
        )

# --- FFmpeg ------------------------------------------------------------------
try:
    import imageio_ffmpeg

    ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if ffmpeg.exists():
        # core/ffmpeg.py looks for the binary next to the bundle first.
        binaries.append((str(ffmpeg), "."))
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"imageio-ffmpeg is required to build the bundle: {exc}")

# --- a font, so instruction screens work on a machine with none -------------
def _find_font():
    try:
        import matplotlib

        candidate = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
        if candidate.exists():
            return candidate
    except Exception:
        pass
    for candidate in (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ):
        if candidate.exists():
            return candidate
    return None


font = _find_font()
if font:
    # core/config.resolve_font() checks resources/ before anything else.
    datas.append((str(font), "stim_concat/resources"))
else:
    print("WARNING: no font found to bundle; instruction screens will need one at runtime.")

a = Analysis(
    ["../launcher.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=["tkinter", "PIL._tkinter_finder", "openpyxl"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "pandas", "scipy", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

splash = Splash(
    "../assets/1.png",
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(20, 20),
    text_size=11,
    text_color="black",
    text_default="Starting stim-concat..."
)

exe = EXE(
    pyz,
    splash,
    a.scripts,
    [],
    exclude_binaries=True,
    name="stim-concat",
    console=False,          # a windowed application
    disable_windowed_traceback=False,
    argv_emulation=True,    # macOS: accept dropped folders
    target_arch=None,
    icon="../src/stim_concat/resources/stim-concat.ico",
)

coll = COLLECT(
    exe,
    splash.binaries,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,              # UPX corrupts the FFmpeg binary on some platforms
    name="stim-concat",
)

app = BUNDLE(
    coll,
    name="stim-concat.app",
    bundle_identifier="org.stim-concat.app",
    info_plist={"NSHighResolutionCapable": True},
)
