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
    assert len(results) == 5
    # Check that it returns our test films, ordered by vote count
    assert results[0]["label"] == "TestFilm One"    # 1000 votes
    assert results[1]["label"] == "TestFilm Two"    # 500 votes
    assert results[2]["label"] == "TestFilm Three"  # 200 votes
    assert results[3]["label"] == "TestFilm Four"   # 100 votes
    assert results[4]["label"] == "TestFilm Five"   # 50 votes
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


async def test_autocomplete_movie_multi_term_and_semantics(client):
    # Regression for #38: multi-term queries must require ALL terms to match.
    # Pre-fix, "TestFilm Three" returned all 5 TestFilms ordered by vote_count
    # because "TestFilm" alone matched everything and "Three" was OR'd.
    response = await client.get("/autocomplete?q=TestFilm%20Three&type=movie")
    assert response.status_code == 200
    labels = [r["label"] for r in response.json()["results"]]
    assert labels == ["TestFilm Three"]


async def test_autocomplete_movie_relevance_beats_votes(client):
    # Regression for #38: a low-vote-count exact match should still surface
    # ahead of high-vote-count near-misses. "Solo Film" has 10 votes; the 5
    # TestFilms have 50–1000. Pre-fix, "Solo" returned the popular TestFilms.
    response = await client.get("/autocomplete?q=Solo&type=movie")
    assert response.status_code == 200
    labels = [r["label"] for r in response.json()["results"]]
    assert labels == ["Solo Film"]
