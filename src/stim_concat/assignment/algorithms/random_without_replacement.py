"""Random sampling without replacement within each participant."""

NAME = "Random sampling without replacement"
DESCRIPTION = (
    "Each participant receives a random sample of distinct stimuli, so nobody "
    "sees the same item twice. Samples are drawn independently for each "
    "participant, which means stimuli are still not guaranteed to be used "
    "equally often across the study -- use 'Balanced random assignment' if "
    "that matters."
)

PARAMS = [
    {
        "name": "shuffle_order",
        "type": "bool",
        "default": True,
        "label": "Randomise presentation order within each participant",
    },
]


def assign(stimuli, n_participants, n_per_participant, rng, params):
    pool = list(stimuli)
    if n_per_participant > len(pool):
        raise ValueError(
            "Cannot draw %d distinct stimuli from a pool of %d. Reduce the "
            "number of stimuli per participant, add more files, or choose "
            "'Simple random sampling'." % (n_per_participant, len(pool))
        )

    rows = []
    for _ in range(n_participants):
        row = rng.sample(pool, n_per_participant)
        if not params.get("shuffle_order", True):
            row.sort(key=pool.index)
        rows.append(row)
    return rows
