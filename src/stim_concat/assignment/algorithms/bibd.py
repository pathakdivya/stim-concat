"""Balanced Incomplete Block Design (BIBD)."""

NAME = "Balanced Incomplete Block Design (BIBD)"
DESCRIPTION = (
    "Each participant (block) sees k distinct stimuli; every stimulus is shown "
    "to the same number of participants (r) and every PAIR of stimuli co-occurs "
    "in the same number of participants (lambda). An exact BIBD exists only when "
    "r = b*k/v and lambda = r*(k-1)/(v-1) are whole numbers; otherwise this "
    "script searches for the most balanced near-design and reports how close it "
    "got. Here v = pool size and b = number of participants. Replication is "
    "balanced by construction: the search only swaps stimuli between two "
    "participants, which cannot change how often a stimulus is used overall."
)

PARAMS = [
    {
        "name": "restarts",
        "type": "int",
        "default": 8,
        "label": "Independent search restarts (the best design is kept)",
    },
    {
        "name": "max_iterations",
        "type": "int",
        "default": 20000,
        "label": "Maximum swaps per restart",
    },
    {
        "name": "require_exact",
        "type": "bool",
        "default": False,
        "label": "Fail rather than fall back to a near-balanced design",
    },
]

#: Set by assign(); the application shows this to the user after generation.
LAST_NOTE = ""


def _key(a, b):
    return (a, b) if a < b else (b, a)


def _pair_counts(rows):
    counts = {}
    for row in rows:
        items = sorted(row)
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                key = (items[i], items[j])
                counts[key] = counts.get(key, 0) + 1
    return counts


def _cost(counts, n_pairs, target):
    """Sum of squared deviations from the target co-occurrence count."""
    observed = sum((c - target) ** 2 for c in counts.values())
    missing = (n_pairs - len(counts)) * target ** 2
    return observed + missing


def _deal(pool, b, k, rng):
    """Deal replication-balanced blocks of k distinct stimuli."""
    bag = []
    while len(bag) < b * k:
        cycle = list(pool)
        rng.shuffle(cycle)
        bag.extend(cycle)
    bag = bag[: b * k]
    rng.shuffle(bag)

    rows = [bag[i * k:(i + 1) * k] for i in range(b)]

    # Remove within-block duplicates using swaps, which preserve replication.
    for _ in range(200):
        dirty = False
        for i, row in enumerate(rows):
            if len(set(row)) == len(row):
                continue
            seen = set()
            for a, stimulus in enumerate(row):
                if stimulus not in seen:
                    seen.add(stimulus)
                    continue
                order = list(range(len(rows)))
                rng.shuffle(order)
                for j in order:
                    if j == i:
                        continue
                    if stimulus in rows[j]:
                        continue
                    for c, candidate in enumerate(rows[j]):
                        if candidate in row:
                            continue
                        rows[i][a], rows[j][c] = candidate, stimulus
                        seen.add(candidate)
                        dirty = True
                        break
                    else:
                        continue
                    break
        if not dirty:
            break
    return rows


def _search(pool, b, k, rng, iterations, target, n_pairs):
    """One randomised restart: deal, then swap while it improves pair balance."""
    rows = _deal(pool, b, k, rng)
    counts = _pair_counts(rows)
    cost = _cost(counts, n_pairs, target)

    for _ in range(iterations):
        if cost <= 1e-9:
            break
        i, j = rng.randrange(b), rng.randrange(b)
        if i == j:
            continue
        a, c = rng.randrange(k), rng.randrange(k)
        x, y = rows[i][a], rows[j][c]
        if x == y or y in rows[i] or x in rows[j]:
            continue

        # Only pairs inside blocks i and j change, so update them incrementally.
        touched = []
        for z in rows[i]:
            if z != x:
                touched.append((_key(x, z), -1))
                touched.append((_key(y, z), +1))
        for w in rows[j]:
            if w != y:
                touched.append((_key(y, w), -1))
                touched.append((_key(x, w), +1))

        delta = 0.0
        for key, change in touched:
            before = counts.get(key, 0)
            after = before + change
            delta += (after - target) ** 2 - (before - target) ** 2
            counts[key] = after

        if delta <= 0:  # accept improvements and lateral moves (escapes plateaus)
            rows[i][a], rows[j][c] = y, x
            cost += delta
            for key, _change in touched:
                if counts.get(key) == 0:
                    counts.pop(key, None)
        else:  # roll back
            for key, change in touched:
                counts[key] = counts.get(key, 0) - change
                if counts.get(key) == 0:
                    counts.pop(key, None)

    return rows, max(cost, 0.0)


def assign(stimuli, n_participants, n_per_participant, rng, params):
    global LAST_NOTE
    pool = list(stimuli)
    v, b, k = len(pool), n_participants, n_per_participant

    if k > v:
        raise ValueError("A BIBD requires k (%d) <= v (%d)." % (k, v))
    if k == v:
        LAST_NOTE = "k equals v, so every participant sees the whole pool (a complete design)."
        return [rng.sample(pool, k) for _ in range(b)]
    if k < 2:
        LAST_NOTE = "k = 1: pair balance is undefined; replication is balanced instead."
        return _deal(pool, b, k, rng)

    r_exact = b * k / v
    lam_exact = r_exact * (k - 1) / (v - 1)
    exact_possible = (
        abs(r_exact - round(r_exact)) < 1e-9 and abs(lam_exact - round(lam_exact)) < 1e-9
    )
    if not exact_possible and params.get("require_exact"):
        raise ValueError(
            "No exact BIBD exists for v=%d, b=%d, k=%d: r=%.3f and lambda=%.3f must both "
            "be whole numbers. Adjust the number of participants or stimuli per "
            "participant, or switch off 'require exact'." % (v, b, k, r_exact, lam_exact)
        )

    n_pairs = v * (v - 1) // 2
    target = lam_exact  # ideal co-occurrence count, whether or not it is an integer
    iterations = max(100, int(params.get("max_iterations", 20000)))
    restarts = max(1, int(params.get("restarts", 8)))

    best_rows, best_cost = None, float("inf")
    for _ in range(restarts):
        rows, cost = _search(pool, b, k, rng, iterations, target, n_pairs)
        if cost < best_cost:
            best_rows, best_cost = rows, cost
        if best_cost <= 1e-9:
            break

    rows = best_rows
    for row in rows:
        rng.shuffle(row)

    if exact_possible and best_cost <= 1e-9:
        LAST_NOTE = "Exact BIBD found: v=%d, b=%d, k=%d, r=%d, lambda=%d." % (
            v,
            b,
            k,
            round(r_exact),
            round(lam_exact),
        )
    elif exact_possible:
        LAST_NOTE = (
            "An exact BIBD (v=%d, b=%d, k=%d, r=%d, lambda=%d) exists but the search did not "
            "reach it; residual pair imbalance %.2f. Try more restarts or a different seed."
            % (v, b, k, round(r_exact), round(lam_exact), best_cost)
        )
    else:
        LAST_NOTE = (
            "No exact BIBD exists for v=%d, b=%d, k=%d (r=%.2f, lambda=%.2f), so the most "
            "balanced near-design found was used; residual pair imbalance %.2f. "
            "Replication is still balanced." % (v, b, k, r_exact, lam_exact, best_cost)
        )
    return rows
