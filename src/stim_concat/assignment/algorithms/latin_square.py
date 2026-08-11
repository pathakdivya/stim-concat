"""Latin square / Williams design counterbalancing of presentation order."""

NAME = "Latin square (Williams design)"
DESCRIPTION = (
    "Counterbalances presentation ORDER rather than stimulus selection. Each "
    "stimulus appears exactly once per participant and, across a full set of "
    "rows, once in every serial position. The Williams variant additionally "
    "balances immediate carry-over effects: each stimulus follows every other "
    "stimulus equally often. The pool is split into sets of k = stimuli per "
    "participant; participants cycle through the square's rows, so it is "
    "cleanest when the number of participants is a multiple of k."
)

PARAMS = [
    {
        "name": "williams",
        "type": "bool",
        "default": True,
        "label": "Use a Williams square (balanced for carry-over effects)",
    },
    {
        "name": "randomise_sets",
        "type": "bool",
        "default": True,
        "label": "Randomly allocate stimuli to the square's positions",
    },
]


def williams_square(k):
    """Rows of a Williams square of order k (2k rows when k is odd)."""
    rows = []
    for i in range(k):
        row = []
        for j in range(k):
            if j % 2 == 0:
                value = (j // 2 + i) % k
            else:
                value = (k - 1 - j // 2 + i) % k
            row.append(value)
        rows.append(row)
    if k % 2:  # odd orders need the mirrored square to balance carry-over
        rows.extend([list(reversed(row)) for row in rows])
    return rows


def cyclic_square(k):
    """Rows of a simple cyclic Latin square of order k."""
    return [[(i + j) % k for j in range(k)] for i in range(k)]


def assign(stimuli, n_participants, n_per_participant, rng, params):
    pool = list(stimuli)
    k = n_per_participant
    if k > len(pool):
        raise ValueError(
            "A Latin square needs at least as many stimuli (%d) as trials (%d)."
            % (len(pool), k)
        )

    square = williams_square(k) if params.get("williams", True) else cyclic_square(k)

    # Split the pool into as many disjoint sets of size k as it allows.
    working = list(pool)
    if params.get("randomise_sets", True):
        rng.shuffle(working)
    sets = [working[i:i + k] for i in range(0, len(working) - k + 1, k)] or [working[:k]]

    rows = []
    for participant in range(n_participants):
        stimulus_set = sets[(participant // len(square)) % len(sets)]
        pattern = square[participant % len(square)]
        rows.append([stimulus_set[index] for index in pattern])
    return rows
