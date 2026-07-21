"""
Core bracket/pairing math, kept free of Flask/DB so it's easy to test in isolation.
"""
import random


def next_pow2(n):
    """Smallest power of 2 >= n (min 1)."""
    p = 1
    while p < n:
        p *= 2
    return p


def seed_order(n):
    """
    Standard single-elimination bracket seeding order.
    Returns a list of seed numbers (1..n) in the order they should occupy
    bracket slots, so that seed 1 and seed 2 can only meet in the final,
    seeds 1-4 can't meet before the semis, etc.
    n must be a power of 2.
    """
    if n & (n - 1) != 0:
        raise ValueError("seed_order requires a power of 2")
    if n == 1:
        return [1]
    prev = seed_order(n // 2)
    result = []
    for s in prev:
        result.append(s)
        result.append(n + 1 - s)
    return result


def random_pairs(team_ids, rng=None):
    """
    Randomly pair up a list of team ids.
    Returns (pairs, bye) where pairs is a list of (team_a, team_b) tuples
    and bye is a single team_id that drew a bye this round (or None if
    the count was even).
    """
    rng = rng or random
    ids = list(team_ids)
    rng.shuffle(ids)
    bye = None
    if len(ids) % 2 == 1:
        bye = ids.pop()
    pairs = [(ids[i], ids[i + 1]) for i in range(0, len(ids), 2)]
    return pairs, bye


def build_bracket_slots(qualifiers_ordered):
    """
    qualifiers_ordered: list of team_id, best-seeded first
    (e.g. all 2-0 teams, in whatever order you rank them, followed by
    decider-round winners). Byes go to the top seeds automatically.

    Returns a flat list of length `next_pow2(len(qualifiers))`, where
    each pair of consecutive entries (0,1), (2,3), ... is a first-round
    match. An entry of None means BYE (the other team in that pair
    advances automatically).
    """
    n = len(qualifiers_ordered)
    if n == 0:
        return []
    size = next_pow2(n)
    order = seed_order(size)
    slots = []
    for seed in order:
        if seed <= n:
            slots.append(qualifiers_ordered[seed - 1])
        else:
            slots.append(None)
    return slots


def round_pairs_from_slots(slots):
    """Group a flat slot list into (team_a, team_b) match pairs."""
    return [(slots[i], slots[i + 1]) for i in range(0, len(slots), 2)]
