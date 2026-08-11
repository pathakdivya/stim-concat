"""Allow ``python -m stim_concat`` to launch the CLI (and thus the GUI)."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
