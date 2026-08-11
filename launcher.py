import sys
import time


# ---------------------------------------------------------
# Give stim-concat its own Windows application identity
# ---------------------------------------------------------

if sys.platform == "win32":
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "org.stimconcat.stimconcat"
    )


# ---------------------------------------------------------
# Import application
# ---------------------------------------------------------

from stim_concat.cli import main


# ---------------------------------------------------------
# Keep PyInstaller splash visible for at least 2 seconds
# ---------------------------------------------------------

try:
    import pyi_splash

    time.sleep(2.0)

    if pyi_splash.is_alive():
        pyi_splash.close()

except ImportError:
    # Normal when running from Python instead of packaged EXE
    pass


if __name__ == "__main__":
    raise SystemExit(main())