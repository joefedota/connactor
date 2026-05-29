"""Tests for /daily, /complete endpoints and _compute_streak logic."""
from __future__ import annotations

import datetime
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import _compute_streak


# ── helpers ───────────────────────────────────────────────────────────────


def _streak_session(dates: list[datetime.date]) -> AsyncMock:
    """Mock AsyncSession whose execute() returns the given date list."""
    session = AsyncMock()
    rows = [(d,) for d in dates]
    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter(rows)
    session.execute.return_value = mock_result
    return session


def _mock_pg(*sessions):
    """Return a get_session patcher that yields sessions from the given list in order."""
    it = iter(sessions)

    @asynccontextmanager
    async def _get_session():
        yield next(it)

    return patch("app.main.get_session", _get_session)


# ── _compute_streak ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_streak_empty():
    assert await _compute_streak(_streak_session([]), "u") == 0


@pytest.mark.anyio
async def test_streak_today_only():
    today = datetime.date.today()
    assert await _compute_streak(_streak_session([today]), "u") == 1


@pytest.mark.anyio
async def test_streak_today_and_yesterday():
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    assert await _compute_streak(_streak_session([today, yesterday]), "u") == 2


@pytest.mark.anyio
async def test_streak_yesterday_only_not_yet_played_today():
    # Player completed yesterday; today's puzzle not yet played.
    # Streak must remain 1 (not drop to 0) until midnight.
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    assert await _compute_streak(_streak_session([yesterday]), "u") == 1


@pytest.mark.anyio
async def test_streak_breaks_on_gap():
    today = datetime.date.today()
    two_days_ago = today - datetime.timedelta(days=2)
    # Completed today and 2 days ago; yesterday missed — streak is 1.
    assert await _compute_streak(_streak_session([today, two_days_ago]), "u") == 1


@pytest.mark.anyio
async def test_streak_older_than_yesterday_returns_zero():
    three_days_ago = datetime.date.today() - datetime.timedelta(days=3)
    assert await _compute_streak(_streak_session([three_days_ago]), "u") == 0


# ── GET /daily ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_daily_no_puzzle_returns_404(client):
    """404 when no daily puzzle has been generated for today."""
    session = AsyncMock()
    result = MagicMock()
    result.first.return_value = None
    session.execute.return_value = result

    with _mock_pg(session):
        resp = await client.get("/daily")

    assert resp.status_code == 404


@pytest.mark.anyio
async def test_daily_already_completed(client):
    """already_completed=true when the user has a completion for today's puzzle."""
    import uuid as _uuid

    puzzle_id = _uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    today = datetime.date.today()

    # Session 1: puzzle lookup
    session1 = AsyncMock()
    puzzle_row = MagicMock()
    puzzle_row.puzzle_id = puzzle_id
    puzzle_row.source_id = -3   # Carol (medium tier, in test data)
    puzzle_row.target_id = -6   # Frank (medium tier, in test data)
    puzzle_row.optimal_hops = 2
    puzzle_row_result = MagicMock()
    puzzle_row_result.first.return_value = puzzle_row
    session1.execute.return_value = puzzle_row_result

    # Session 2: completion + streak
    session2 = AsyncMock()
    comp_row = MagicMock()
    comp_row.hops = 2
    comp_row.time_ms = 15000
    comp_row.completed_at = datetime.datetime(2026, 5, 24, 12, 0, 0)
    comp_row.path_ids = None
    # execute call 1 → completion row; execute call 2 → streak (today only)
    streak_result = MagicMock()
    streak_result.__iter__ = lambda self: iter([(today,)])
    comp_result = MagicMock()
    comp_result.first.return_value = comp_row
    session2.execute.side_effect = [comp_result, streak_result]

    # Session 3: today_stats percentile query — counts here are OTHER players only
    # (the user themselves is excluded by `user_id != :uid` in the WHERE clause).
    session3 = AsyncMock()
    stats_row = MagicMock()
    stats_row.total = 10        # 10 other players
    stats_row.better_than = 7   # 7 of them had more hops than the user
    stats_row.has_time = 8
    stats_row.slower_than = 5
    stats_row.same_path = 2
    stats_result = MagicMock()
    stats_result.first.return_value = stats_row
    session3.execute.return_value = stats_result

    with _mock_pg(session1, session2, session3):
        resp = await client.get("/daily")

    assert resp.status_code == 200
    body = resp.json()
    assert body["already_completed"] is True
    assert body["completion"]["hops"] == 2
    assert body["current_streak"] == 1
    assert body["source"]["id"] == str(-3)
    assert body["target"]["id"] == str(-6)
    assert body["today_stats"]["other_players_today"] == 10
    assert body["today_stats"]["answer_percentile"] == 70  # floor(7/10 * 100)


@pytest.mark.anyio
async def test_daily_stats_two_player_winner_sees_100_percent(client):
    """In a 2-player puzzle, the winner sees 100% — not 50% — because the user is
    excluded from both numerator and denominator. Regression test for #144."""
    import uuid as _uuid

    puzzle_id = _uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
    today = datetime.date.today()

    session1 = AsyncMock()
    puzzle_row = MagicMock(
        puzzle_id=puzzle_id, source_id=-3, target_id=-6, optimal_hops=2
    )
    puzzle_row_result = MagicMock()
    puzzle_row_result.first.return_value = puzzle_row
    session1.execute.return_value = puzzle_row_result

    session2 = AsyncMock()
    comp_row = MagicMock(
        hops=2,
        time_ms=10000,
        completed_at=datetime.datetime(2026, 5, 24, 12, 0, 0),
        path_ids=None,
    )
    streak_result = MagicMock()
    streak_result.__iter__ = lambda self: iter([(today,)])
    comp_result = MagicMock()
    comp_result.first.return_value = comp_row
    session2.execute.side_effect = [comp_result, streak_result]

    # One other player, who did worse on both hops and time.
    session3 = AsyncMock()
    stats_row = MagicMock(
        total=1, better_than=1, has_time=1, slower_than=1, same_path=0
    )
    stats_result = MagicMock()
    stats_result.first.return_value = stats_row
    session3.execute.return_value = stats_result

    with _mock_pg(session1, session2, session3):
        resp = await client.get("/daily")

    body = resp.json()
    assert body["today_stats"]["other_players_today"] == 1
    assert body["today_stats"]["answer_percentile"] == 100
    assert body["today_stats"]["speed_percentile"] == 100


@pytest.mark.anyio
async def test_daily_stats_user_alone_returns_no_stats(client):
    """When the user is the only completion, today_stats is None — no peers to compare."""
    import uuid as _uuid

    puzzle_id = _uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003")
    today = datetime.date.today()

    session1 = AsyncMock()
    puzzle_row = MagicMock(
        puzzle_id=puzzle_id, source_id=-3, target_id=-6, optimal_hops=2
    )
    puzzle_row_result = MagicMock()
    puzzle_row_result.first.return_value = puzzle_row
    session1.execute.return_value = puzzle_row_result

    session2 = AsyncMock()
    comp_row = MagicMock(
        hops=2,
        time_ms=10000,
        completed_at=datetime.datetime(2026, 5, 24, 12, 0, 0),
        path_ids=None,
    )
    streak_result = MagicMock()
    streak_result.__iter__ = lambda self: iter([(today,)])
    comp_result = MagicMock()
    comp_result.first.return_value = comp_row
    session2.execute.side_effect = [comp_result, streak_result]

    # Zero other players.
    session3 = AsyncMock()
    stats_row = MagicMock(
        total=0, better_than=0, has_time=0, slower_than=0, same_path=0
    )
    stats_result = MagicMock()
    stats_result.first.return_value = stats_row
    session3.execute.return_value = stats_result

    with _mock_pg(session1, session2, session3):
        resp = await client.get("/daily")

    body = resp.json()
    assert body["today_stats"] is None


# ── POST /complete ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_complete_missing_params_returns_422(client):
    """422 when puzzle_id absent and source/target/optimal_hops not all provided."""
    resp = await client.post("/complete", json={"hops": 3})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_complete_missing_optimal_hops_returns_422(client):
    resp = await client.post(
        "/complete", json={"source_id": "1", "target_id": "2", "hops": 3}
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_complete_unknown_puzzle_id_returns_404(client):
    """404 when an explicit puzzle_id doesn't exist in the DB."""
    fake_pid = "00000000-0000-0000-0000-000000000000"
    session = AsyncMock()
    result = MagicMock()
    result.first.return_value = None
    session.execute.return_value = result

    with _mock_pg(session):
        resp = await client.post("/complete", json={"puzzle_id": fake_pid, "hops": 3})

    assert resp.status_code == 404


@pytest.mark.anyio
async def test_complete_random_game_records_completion(client):
    """Random game: upserts puzzle row and records completion, returns 200."""
    import uuid as _uuid
    import datetime as _dt

    puzzle_id = str(_uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002"))
    completion_id = str(_uuid.UUID("cccccccc-0000-0000-0000-000000000003"))

    session = AsyncMock()
    insert_puzzle_result = MagicMock()                        # INSERT ... ON CONFLICT DO NOTHING
    select_puzzle_result = MagicMock()
    select_puzzle_result.scalar_one.return_value = puzzle_id  # SELECT puzzle_id
    no_existing = MagicMock()
    no_existing.first.return_value = None                     # no prior completion
    inserted = MagicMock()
    inserted.first.return_value = MagicMock(
        completion_id=completion_id,
        completed_at=_dt.datetime(2026, 5, 24, 12, 0, 0),
    )
    session.execute.side_effect = [
        insert_puzzle_result,
        select_puzzle_result,
        no_existing,
        inserted,
    ]

    with _mock_pg(session):
        resp = await client.post(
            "/complete",
            json={
                "source_id": "123",
                "target_id": "456",
                "optimal_hops": 4,
                "hops": 5,
                "time_ms": 30000,
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["puzzle_id"] == puzzle_id
    assert body["hops"] == 5
    assert body["time_ms"] == 30000


@pytest.mark.anyio
async def test_complete_idempotent(client):
    """Second POST /complete for the same user+puzzle returns the original record."""
    import uuid as _uuid
    import datetime as _dt

    puzzle_id = str(_uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002"))
    completion_id = str(_uuid.UUID("cccccccc-0000-0000-0000-000000000003"))

    session = AsyncMock()
    found_puzzle = MagicMock()
    found_puzzle.first.return_value = MagicMock()             # puzzle exists
    existing_completion = MagicMock()
    existing_completion.first.return_value = MagicMock(
        completion_id=completion_id,
        hops=3,
        time_ms=12000,
        completed_at=_dt.datetime(2026, 5, 24, 10, 0, 0),
    )
    session.execute.side_effect = [found_puzzle, existing_completion]

    with _mock_pg(session):
        resp = await client.post(
            "/complete",
            json={"puzzle_id": puzzle_id, "hops": 5, "time_ms": 99999},
        )

    assert resp.status_code == 200
    body = resp.json()
    # Returns original hops (3), not the new submission (5)
    assert body["hops"] == 3
    assert body["time_ms"] == 12000
