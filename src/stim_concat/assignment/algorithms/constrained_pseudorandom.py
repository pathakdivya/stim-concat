"""Pseudorandom assignment under simple sequencing constraints."""

import re

NAME = "Pseudorandom with constraints"
DESCRIPTION = (
    "Balanced random assignment plus ordering constraints that are common in "
    "affective and perceptual experiments: no stimulus repeated within a "
    "participant, no more than N consecutive trials from the same category, "
    "and (optionally) no stimulus appearing in the same serial position as it "
    "did for the previous participant. Each row is reshuffled until the "
    "constraints hold or the attempt budget runs out."
)

PARAMS = [
    {
        "name": "category_pattern",
        "type": "str",
        "default": "",
        "label": "Regex with a 'group' capture identifying the category",
    },
    {
        "name": "max_same_category_run",
        "type": "int",
        "default": 2,
        "label": "Maximum consecutive trials from one category",
    },
    {
        "name": "avoid_previous_positions",
        "type": "bool",
        "default": True,
        "label": "Avoid reusing the previous participant's serial positions",
    },
    {
        "name": "max_attempts",
        "type": "int",
        "default": 2000,
        "label": "Reshuffle attempts per participant before giving up",
    },
]

LAST_NOTE = ""


def _category(stimulus, compiled):
    if compiled is None:
        return None
    match = compiled.search(str(stimulus))
    if not match:
        return "ungrouped"
    return match.groupdict().get("group") or (match.group(1) if match.groups() else match.group(0))


def _run_ok(row, compiled, max_run):
    if compiled is None or max_run <= 0:
        return True
    run = 1
    previous = _category(row[0], compiled)
    for stimulus in row[1:]:
        current = _category(stimulus, compiled)
        run = run + 1 if current == previous else 1
        if run > max_run:
            return False
        previous = current
    return True


def _positions_ok(row, previous_row, enabled):
    if not enabled or previous_row is None:
        return True
    return all(a != b for a, b in zip(row, previous_row))


def assign(stimuli, n_participants, n_per_participant, rng, params):
    global LAST_NOTE
    pool = list(stimuli)
    pattern = (params.get("category_pattern") or "").strip()
    compiled = re.compile(pattern) if pattern else None
    max_run = int(params.get("max_same_category_run", 2))
    avoid_positions = bool(params.get("avoid_previous_positions", True))
    attempts_budget = int(params.get("max_attempts", 2000))

    # Balanced bag, exactly as in 'Balanced random assignment'.
    total = n_participants * n_per_participant
    bag = []
    while len(bag) < total:
        cycle = list(pool)
        rng.shuffle(cycle)
        bag.extend(cycle)
    bag = bag[:total]

    rows = []
    relaxed = 0
    previous_row = None
    for i in range(n_participants):
        base = bag[i * n_per_participant:(i + 1) * n_per_participant]
        # Remove within-participant duplicates by borrowing from the pool.
        seen = set()
        cleaned = []
        for original in base:
            stimulus = original
            if stimulus in seen and n_per_participant <= len(pool):
                alternatives = [s for s in pool if s not in seen]
                stimulus = rng.choice(alternatives)
            seen.add(stimulus)
            cleaned.append(stimulus)

        row = list(cleaned)
        for _attempt in range(attempts_budget):
            rng.shuffle(row)
            if _run_ok(row, compiled, max_run) and _positions_ok(row, previous_row, avoid_positions):
                break
        else:
            relaxed += 1
        rows.append(row)
        previous_row = row

    if relaxed:
        LAST_NOTE = (
            "%d of %d participants could not satisfy every constraint within the "
            "attempt budget; their orders are random but unconstrained. Loosen the "
            "constraints or increase the budget." % (relaxed, n_participants)
        )
    else:
        LAST_NOTE = "All constraints satisfied for every participant."
    return rows
