"""Tests for the daily puzzle picker's actor-exclusion logic (#149)."""
from __future__ import annotations

import pytest

from pipeline.generate_daily_puzzle import (
    FAME_RANK_MAX,
    FAME_RANK_MIN,
    pick_pair,
)


async def _pool_ids(neo4j_driver) -> list[int]:
    """All person_ids in the daily-pick fame band."""
    async with neo4j_driver.session() as session:
        result = await session.run(
            "MATCH (a:Actor) WHERE a.fame_rank >= $lo AND a.fame_rank < $hi "
            "RETURN collect(a.person_id) AS ids",
            lo=FAME_RANK_MIN,
            hi=FAME_RANK_MAX,
        )
        record = await result.single()
    return [int(i) for i in record["ids"]]


@pytest.mark.anyio
async def test_pick_pair_no_exclusions(neo4j_driver):
    result = await pick_pair(neo4j_driver, excluded_pairs=set())
    assert result is not None
    src, tgt, hops = result
    pool = set(await _pool_ids(neo4j_driver))
    assert src in pool
    assert tgt in pool
    assert src != tgt
    assert hops > 0


@pytest.mark.anyio
async def test_pick_pair_never_returns_excluded_actor(neo4j_driver):
    pool = await _pool_ids(neo4j_driver)
    # Exclude all but two actors — the pick must come from the remainder.
    excluded = set(pool[:-2])
    result = await pick_pair(
        neo4j_driver, excluded_pairs=set(), excluded_actors=excluded
    )
    assert result is not None
    src, tgt, _ = result
    assert src not in excluded
    assert tgt not in excluded


@pytest.mark.anyio
async def test_pick_pair_returns_none_when_pool_exhausted(neo4j_driver):
    pool = set(await _pool_ids(neo4j_driver))
    result = await pick_pair(
        neo4j_driver, excluded_pairs=set(), excluded_actors=pool
    )
    assert result is None
