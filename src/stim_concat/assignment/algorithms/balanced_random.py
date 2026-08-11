"""Balanced random assignment: equalise how often each stimulus is used."""

NAME = "Balanced random assignment"
DESCRIPTION = (
    "Deals stimuli from a shuffled bag that contains every stimulus the same "
    "number of times. Across the whole study each stimulus is presented either "
    "floor(N/v) or ceil(N/v) times, where N is the total number of trials and v "
    "the pool size -- the most even exposure achievable. Within a participant "
    "stimuli are never repeated (unless the pool is smaller than the number of "
    "trials)."
)

PARAMS = [
    {
        "name": "max_repair_passes",
        "type": "int",
        "default": 200,
        "label": "Maximum swap passes used to remove within-participant repeats",
    },
]


def assign(stimuli, n_participants, n_per_participant, rng, params):
    pool = list(stimuli)
    total = n_participants * n_per_participant

    # Build a bag with every stimulus repeated as evenly as possible.
    bag = []
    while len(bag) < total:
        cycle = list(pool)
        rng.shuffle(cycle)
        bag.extend(cycle)
    bag = bag[:total]
    rng.shuffle(bag)

    rows = [bag[i * n_per_participant:(i + 1) * n_per_participant] for i in range(n_participants)]

    # Repair within-participant duplicates by swapping with another row.
    if n_per_participant <= len(pool):
        passes = int(params.get("max_repair_passes", 200))
        for _ in range(passes):
            fixed_any = False
            for i, row in enumerate(rows):
                seen = set()
                for j, stimulus in enumerate(row):
                    if stimulus not in seen:
                        seen.add(stimulus)
                        continue
                    # Find a partner cell we can swap with without creating a
                    # new duplicate on either side.
                    order = list(range(len(rows)))
                    rng.shuffle(order)
                    for other in order:
                        if other == i:
                            continue
                        for col in range(n_per_participant):
                            candidate = rows[other][col]
                            if candidate in seen or stimulus in rows[other]:
                                continue
                            rows[i][j], rows[other][col] = candidate, stimulus
                            seen.add(candidate)
                            fixed_any = True
                            break
                        else:
                            continue
                        break
            if not fixed_any:
                break

    for row in rows:
        rng.shuffle(row)
    return rows
