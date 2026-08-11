"""Block randomisation: sample one stimulus per block, shuffle block order."""

import re

NAME = "Block randomisation"
DESCRIPTION = (
    "Partitions the pool into blocks (conditions) and gives every participant "
    "the same number of stimuli from each block, with block order randomised "
    "per participant. Blocks can be derived from the filenames -- e.g. a "
    "pattern of ^(?P<group>[a-zA-Z]+) turns 'sad_012.mp4' and 'happy_003.mp4' "
    "into groups 'sad' and 'happy' -- or the pool can simply be split into a "
    "fixed number of equal blocks."
)

PARAMS = [
    {
        "name": "group_pattern",
        "type": "str",
        "default": "",
        "label": "Regex with a 'group' capture to read the condition from the ID",
    },
    {
        "name": "n_blocks",
        "type": "int",
        "default": 0,
        "label": "Number of blocks when no pattern is given (0 = one block per trial)",
    },
    {
        "name": "sample_without_replacement",
        "type": "bool",
        "default": True,
        "label": "Never repeat a stimulus within a participant",
    },
]


def _blocks(stimuli, params):
    pattern = (params.get("group_pattern") or "").strip()
    if pattern:
        groups = {}
        compiled = re.compile(pattern)
        for stimulus in stimuli:
            match = compiled.search(str(stimulus))
            key = "ungrouped"
            if match:
                key = (match.groupdict().get("group") or (match.group(1) if match.groups() else match.group(0)))
            groups.setdefault(key, []).append(stimulus)
        return [groups[k] for k in sorted(groups)]

    n = int(params.get("n_blocks") or 0)
    if n <= 0:
        return None  # caller falls back to one block per trial
    size = max(1, len(stimuli) // n)
    return [stimuli[i:i + size] for i in range(0, len(stimuli), size)][:n] or [list(stimuli)]


def assign(stimuli, n_participants, n_per_participant, rng, params):
    pool = list(stimuli)
    blocks = _blocks(pool, params)
    if blocks is None:
        # Default design: as many blocks as there are trials, so each trial
        # samples from a different, equally sized slice of the pool.
        n = n_per_participant
        size = max(1, len(pool) // n)
        blocks = [pool[i * size:(i + 1) * size] for i in range(n)]
        leftover = pool[n * size:]
        for i, stimulus in enumerate(leftover):
            blocks[i % n].append(stimulus)

    blocks = [b for b in blocks if b]
    if not blocks:
        raise ValueError("No non-empty blocks could be formed from the stimulus pool.")

    per_block, remainder = divmod(n_per_participant, len(blocks))
    without_replacement = bool(params.get("sample_without_replacement", True))

    rows = []
    for _ in range(n_participants):
        order = list(range(len(blocks)))
        rng.shuffle(order)
        row = []
        for position, index in enumerate(order):
            block = blocks[index]
            take = per_block + (1 if position < remainder else 0)
            if take == 0:
                continue
            if take <= len(block) and without_replacement:
                row.extend(rng.sample(block, take))
            else:
                row.extend(rng.choice(block) for _ in range(take))
        rng.shuffle(row)
        rows.append(row[:n_per_participant])
    return rows
