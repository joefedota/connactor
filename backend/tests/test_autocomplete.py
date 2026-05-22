import pytest

pytestmark = pytest.mark.anyio


async def test_autocomplete_actor_valid(client):
    # Search for Alice ("Ali")
    response = await client.get("/autocomplete?q=Ali&type=actor")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    results = data["results"]
    assert len(results) > 0
    # The first or matched node should be Alice
    actor_names = {node["label"] for node in results}
    assert "Alice" in actor_names
    assert results[0]["type"] == "actor"


async def test_autocomplete_movie_valid(client):
    # Search for "TestFilm"
    response = await client.get("/autocomplete?q=TestFilm&type=movie")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    results = data["results"]
    assert len(results) == 3
    # Check that it returns our test films, ordered by vote count
    assert results[0]["label"] == "TestFilm One"  # 1000 votes
    assert results[1]["label"] == "TestFilm Two"  # 500 votes
    assert results[2]["label"] == "TestFilm Three"  # 200 votes
    for node in results:
        assert node["type"] == "movie"


async def test_autocomplete_too_short(client):
    # Minimum query length is 2 characters
    response = await client.get("/autocomplete?q=A&type=actor")
    assert response.status_code == 422


async def test_autocomplete_invalid_type(client):
    # Type must be actor or movie
    response = await client.get("/autocomplete?q=Alice&type=director")
    assert response.status_code == 422
