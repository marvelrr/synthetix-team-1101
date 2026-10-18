from collections import Counter

import pytest

from contracts.models import AudienceSpec, Segment
from engine.personas import diversity_report, generate_users


@pytest.mark.parametrize("count", [1, 10, 100, 1000, 10000])
def test_counts_ids_and_determinism(audience, count):
    users = generate_users("r", audience, count, 42)
    assert len(users) == len({u.user_id for u in users}) == count
    assert users == generate_users("r", audience, count, 42)
    assert users[0].user_id == "r-u00001"
    assert users[-1].user_id == f"r-u{count:05d}"
    assert all(u.generator_version == "personas-1.0" for u in users)
    assert all(u.sourced_facts == audience.segments[0].sourced_facts for u in users if u.segment == "a")


@pytest.mark.parametrize("count", [0, 10001, 1.5, "10", True])
def test_bad_counts_rejected(audience, count):
    with pytest.raises(ValueError):
        generate_users("r", audience, count, 42)


def test_largest_remainder_tie_and_diversity():
    spec = AudienceSpec(spec_version="1", description="fixture", segments=[
        Segment(name=name, weight=1, attributes={"same": ["profile"]}) for name in ["a", "b", "c"]])
    users = generate_users("r", spec, 5, 1)
    assert Counter(u.segment for u in users) == {"a": 2, "b": 2, "c": 1}
    assert diversity_report(users) == {"unique_profiles": 1, "duplicate_profiles": 4,
                                       "per_segment": {"a": 2, "b": 2, "c": 1}}


def test_empty_sampling_options_rejected():
    spec = AudienceSpec(spec_version="1", description="fixture", segments=[Segment(name="a", weight=1, attributes={"x": []})])
    with pytest.raises(ValueError, match="nonempty"):
        generate_users("r", spec, 1, 42)
