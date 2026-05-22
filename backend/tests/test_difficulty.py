import pytest
from app.main import _classify_difficulty

pytestmark = pytest.mark.anyio


# --- Unit Tests for _classify_difficulty (popularity-only) ---


def test_classify_difficulty_easy():
    assert _classify_difficulty(10, 20) == "easy"
    assert _classify_difficulty(49, 10) == "easy"


def test_classify_difficulty_medium():
    assert _classify_difficulty(20, 100) == "medium"
    assert _classify_difficulty(50, 199) == "medium"
    assert _classify_difficulty(199, 199) == "medium"


def test_classify_difficulty_hard():
    assert _classify_difficulty(20, 500) == "hard"
    assert _classify_difficulty(200, 999) == "hard"
    assert _classify_difficulty(999, 0) == "hard"


def test_classify_difficulty_expert():
    assert _classify_difficulty(20, 1200) == "expert"
    assert _classify_difficulty(1000, 1000) == "expert"
    assert _classify_difficulty(5000, 5000) == "expert"


# --- Integration Tests for /game Endpoint ---


async def test_get_game_no_difficulty(client):
    response = await client.get("/game")
    assert response.status_code == 200
    data = response.json()
    assert "game_id" in data
    assert data["source"]["type"] == "actor"
    assert data["target"]["type"] == "actor"
    assert data["difficulty"] in ["easy", "medium", "hard", "expert"]


async def test_get_game_easy(client):
    # Alice (rank 10) + Bob (rank 20) — connected via TestFilm One
    response = await client.get("/game?difficulty=easy")
    assert response.status_code == 200
    data = response.json()
    assert data["difficulty"] == "easy"


async def test_get_game_medium(client):
    # Carol (rank 100) + Frank (rank 150) — connected via TestFilm Two
    response = await client.get("/game?difficulty=medium")
    assert response.status_code == 200
    data = response.json()
    assert data["difficulty"] == "medium"


async def test_get_game_hard(client):
    # Dave (rank 500) + Grace (rank 700) — connected via TestFilm Three
    response = await client.get("/game?difficulty=hard")
    assert response.status_code == 200
    data = response.json()
    assert data["difficulty"] == "hard"


async def test_get_game_expert(client):
    # Eve (rank 2000) + Henry (rank 3000) — connected via TestFilm Five
    response = await client.get("/game?difficulty=expert")
    assert response.status_code == 200
    data = response.json()
    assert data["difficulty"] == "expert"
