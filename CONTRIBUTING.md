# Contributing

Thanks for considering a contribution.

## Getting set up

```bash
git clone https://github.com/stim-concat/stim-concat
cd stim-concat
pip install -e ".[dev]"
pytest
```

The rendering tests need an FFmpeg binary; they skip themselves if none is
found, but please run them before submitting anything that touches
`core/renderer.py`, `core/screens.py` or `core/timeline.py`.

## Adding an assignment algorithm

Drop a new file into `src/stim_concat/assignment/algorithms/`:

```python
NAME = "My design"
DESCRIPTION = "One paragraph a researcher can understand."
PARAMS = [{"name": "spread", "type": "int", "default": 2, "label": "Spread"}]

def assign(stimuli, n_participants, n_per_participant, rng, params):
    ...
    return rows
```

Rules:

* Draw randomness only from `rng`, never the global `random` module, or seeds
  will not reproduce.
* Return exactly `n_participants` rows of exactly `n_per_participant` IDs, all
  drawn from `stimuli`. The registry validates this and reports clearly if not.
* Raise `ValueError` with an actionable message when the request is impossible
  (see `random_without_replacement.py` for the tone to aim for).
* Set the module-level `LAST_NOTE` string if the user should be told something
  about the design that was produced.
* The script is displayed verbatim in the editor, so write it to be read: real
  docstrings, no clever one-liners.

Add tests to `tests/test_core.py::TestAlgorithms` covering shape, seed
reproducibility, and whatever property the design is supposed to guarantee.

## Adding a media format

`register_format(".mxf", "video")` in `core/scanner.py`, plus a case in
`renderer._render_stimulus` if it needs different handling.

## Style

`ruff check src tests`, line length 100. Comments should explain *why*, not
restate the code — particularly around the FFmpeg invocations, where several
arguments exist to prevent specific, non-obvious failures.
