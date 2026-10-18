"""Deterministic, code-generated synthetic profiles; no model calls."""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
import math
import random

from contracts.models import AudienceSpec, MAX_USERS, SyntheticUser


def generate_users(run_id: str, audience: AudienceSpec, count: int, seed: int) -> list[SyntheticUser]:
    if type(count) is not int or not 1 <= count <= MAX_USERS:
        raise ValueError("count must be an integer from 1 to 10,000")
    audience = AudienceSpec.model_validate(audience)
    for segment in audience.segments:
        if not math.isfinite(segment.weight):
            raise ValueError("segment weights must be finite")
        if not segment.languages or any(not options for options in segment.attributes.values()):
            raise ValueError("each segment needs languages and nonempty attribute options")
    weights = [Fraction(str(s.weight)) for s in audience.segments]
    total = sum(weights)
    quotas = [count * weight / total for weight in weights]
    sizes = [q.numerator // q.denominator for q in quotas]
    order = sorted(range(len(quotas)), key=lambda i: (-(quotas[i] - sizes[i]), i))
    for i in order[:count - sum(sizes)]:
        sizes[i] += 1
    rng = random.Random(seed)
    users = []
    for segment, size in zip(audience.segments, sizes):
        for _ in range(size):
            profile = {key: rng.choice(options) for key, options in segment.attributes.items()}
            if "language" not in profile:
                profile["language"] = rng.choice(segment.languages)
            users.append(SyntheticUser(
                user_id=f"{run_id}-u{len(users) + 1:05d}", run_id=run_id,
                segment=segment.name, profile=profile,
                sourced_facts=list(segment.sourced_facts),
                authored_assumptions=list(segment.authored_assumptions),
                generator_version="personas-1.0",
            ))
    assert len(users) == count
    return users


def diversity_report(users: list[SyntheticUser]) -> dict:
    unique = len({tuple(sorted(user.profile.items())) for user in users})
    return {"unique_profiles": unique, "duplicate_profiles": len(users) - unique,
            "per_segment": dict(Counter(user.segment for user in users))}
