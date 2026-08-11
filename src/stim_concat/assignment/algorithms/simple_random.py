"""Simple random sampling (with replacement)."""

NAME = "Simple random sampling"
DESCRIPTION = (
    "Every trial is an independent draw from the whole stimulus pool. "
    "A participant may therefore see the same stimulus more than once, and "
    "stimuli are not used equally often. This is the least constrained design; "
    "use it as a baseline or when your pool is very large relative to the "
    "number of trials."
)

PARAMS = [
    {
        "name": "shuffle_pool",
        "type": "bool",
        "default": False,
        "label": "Shuffle the pool before sampling (cosmetic only)",
    },
]


def assign(stimuli, n_participants, n_per_participant, rng, params):
    """Return one list of stimulus IDs per participant.

    Parameters
    ----------
    stimuli : list of str
        All stimulus IDs found in the folder.
    n_participants : int
        Number of participants (rows) to generate.
    n_per_participant : int
        Number of trials (columns) per participant.
    rng : random.Random
        Seeded generator. Always use this -- never the global ``random``
        module -- so that a given seed reproduces the sheet exactly.
    params : dict
        Values of the PARAMS declared above.
    """
    pool = list(stimuli)
    if params.get("shuffle_pool"):
        rng.shuffle(pool)

    rows = []
    for _ in range(n_participants):
        rows.append([rng.choice(pool) for _ in range(n_per_participant)])
    return rows
