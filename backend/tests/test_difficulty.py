import pytest
from app.main import _classify_difficulty

pytestmark = pytest.mark.anyio


# --- Unit Tests for _classify_difficulty ---


def test_classify_difficulty_easy():
    # hops = 2, max_rank < 50 -> easy
    assert _classify_difficulty(10, 20, 2) == "easy"
    assert _classify_difficulty(49, 10, 2) == "easy"


def test_classify_difficulty_medium():
    # hops = 2, max_rank >= 50 but < 200 -> medium
    assert _classify_difficulty(20, 100, 2) == "medium"
    # hops = 4, max_rank < 200 -> medium
    assert _classify_difficulty(10, 20, 4) == "medium"
    assert _classify_difficulty(10, 199, 4) == "medium"


def test_classify_difficulty_hard():
    # hops = 2, max_rank >= 200 but < 1000 -> hard
    assert _classify_difficulty(20, 500, 2) == "hard"
    # hops = 4, max_rank >= 200 but < 1000 -> hard
    assert _classify_difficulty(10, 500, 4) == "hard"
    # hops = 6, max_rank < 1000 -> hard
    assert _classify_difficulty(10, 20, 6) == "hard"
    assert _classify_difficulty(999, 10, 6) == "hard"


def test_classify_difficulty_expert():
    # hops = 2, max_rank >= 1000 -> expert
    assert _classify_difficulty(20, 1200, 2) == "expert"
    # hops = 8, any rank -> expert
    assert _classify_difficulty(10, 20, 8) == "expert"


# --- Integration Tests for /game Endpoint ---


async def test_get_game_no_difficulty(client):
    # Generating a game with no specific difficulty should pick a valid pair
    response = await client.get("/game")
    assert response.status_code == 200
    data = response.json()
    assert "game_id" in data
    assert data["source"]["type"] == "actor"
    assert data["target"]["type"] == "actor"
    assert data["difficulty"] in ["easy", "medium", "hard", "expert"]


async def test_get_game_easy(client):
    # Easy selection restricts actors to rank < 50
    # Available mock actors: Alice (rank 10), Bob (rank 20).
    response = await client.get("/game?difficulty=easy")
    assert response.status_code == 200
    data = response.json()
    assert data["difficulty"] == "easy"
    assert "game_id" in data
    assert data["source"]["label"] is not None
    assert data["target"]["label"] is not None


async def test_get_game_medium(client):
    # Medium restricts rank < 200.
    response = await client.get("/game?difficulty=medium")
    assert response.status_code == 200
    data = response.json()
    assert data["difficulty"] == "medium"
    assert "game_id" in data
    assert data["source"]["label"] is not None
    assert data["target"]["label"] is not None
