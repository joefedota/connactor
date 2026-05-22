import pytest

pytestmark = pytest.mark.anyio


# --- Pathfinding & Solve Endpoint Tests ---


async def test_same_node(client):
    response = await client.post("/solve", json={"source_id": "-1", "target_id": "-1"})
    assert response.status_code == 200
    data = response.json()
    assert data["hop_count"] == 0
    assert len(data["paths"]) == 1
    assert data["paths"][0][0]["id"] == "-1"
    assert data["paths"][0][0]["label"] == "Alice"


async def test_direct_connection(client):
    # Alice (-1) and Bob (-2) share Film One (-10) -> 2 hops
    response = await client.post("/solve", json={"source_id": "-1", "target_id": "-2"})
    assert response.status_code == 200
    data = response.json()
    assert data["hop_count"] == 2
    assert len(data["paths"]) == 1
    assert [node["id"] for node in data["paths"][0]] == ["-1", "-10", "-2"]


async def test_two_hop_actor(client):
    # Alice (-1) -> Carol (-3): shortest is 4 hops via Bob (-2)
    response = await client.post("/solve", json={"source_id": "-1", "target_id": "-3"})
    assert response.status_code == 200
    data = response.json()
    assert data["hop_count"] == 4
    # Two paths are possible:
    # 1. Alice -> Film One -> Bob -> Film Two -> Carol
    # 2. Alice -> Film One -> Bob -> Film Three -> Carol
    assert len(data["paths"]) == 2
    for path in data["paths"]:
        assert path[0]["id"] == "-1"
        assert path[2]["id"] == "-2"
        assert path[4]["id"] == "-3"
        assert len(path) == 5


async def test_disconnected(client):
    # Alice (-1) and Eve (-5) are disconnected
    response = await client.post("/solve", json={"source_id": "-1", "target_id": "-5"})
    assert response.status_code == 404
    assert "No path exists" in response.json()["detail"]


async def test_symmetric(client):
    response_ab = await client.post("/solve", json={"source_id": "-2", "target_id": "-1"})
    response_ba = await client.post("/solve", json={"source_id": "-1", "target_id": "-2"})
    assert response_ab.status_code == 200
    assert response_ba.status_code == 200
    assert response_ab.json()["hop_count"] == response_ba.json()["hop_count"]


# --- Path Validation Endpoint Tests ---


async def test_validate_valid_path(client):
    body = {
        "source_id": "-1",
        "target_id": "-2",
        "path": ["-1", "-10", "-2"],
    }
    response = await client.post("/validate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"]
    assert data["is_complete"]
    assert data["is_optimal"]


async def test_validate_valid_incomplete_path(client):
    # Valid so far, but doesn't reach target Carol (-3)
    body = {
        "source_id": "-1",
        "target_id": "-3",
        "path": ["-1", "-10", "-2"],
    }
    response = await client.post("/validate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"]
    assert not data["is_complete"]
    assert data["is_optimal"] is None


async def test_validate_empty_path(client):
    body = {
        "source_id": "-1",
        "target_id": "-2",
        "path": [],
    }
    response = await client.post("/validate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert not data["valid"]
    assert "empty" in data["error"].lower()


async def test_validate_too_short(client):
    body = {
        "source_id": "-1",
        "target_id": "-2",
        "path": ["-1", "-10"],
    }
    response = await client.post("/validate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert not data["valid"]
    assert "at least 3 nodes" in data["error"].lower()


async def test_validate_even_length(client):
    body = {
        "source_id": "-1",
        "target_id": "-3",
        "path": ["-1", "-10", "-2", "-20"],
    }
    response = await client.post("/validate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert not data["valid"]
    assert "must be odd" in data["error"].lower()


async def test_validate_nonexistent_edge(client):
    # Alice (-1) is not in Film Two (-20)
    body = {
        "source_id": "-1",
        "target_id": "-3",
        "path": ["-1", "-20", "-3"],
    }
    response = await client.post("/validate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert not data["valid"]
    assert "did not appear" in data["error"].lower()


async def test_validate_wrong_start(client):
    body = {
        "source_id": "-1",
        "target_id": "-2",
        "path": ["-2", "-10", "-1"],
    }
    response = await client.post("/validate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert not data["valid"]
    assert "must start with source" in data["error"].lower()


async def test_validate_repeated_movie(client):
    # Valid layout, but reuses Film Three (-30)
    body = {
        "source_id": "-2",
        "target_id": "-4",
        "path": ["-2", "-30", "-3", "-30", "-4"],
    }
    response = await client.post("/validate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert not data["valid"]
    assert "appears twice" in data["error"].lower()


# --- Autocomplete Neighbors Endpoint Tests ---


async def test_neighbors_of_actor(client):
    # Bob's movies
    response = await client.get("/autocomplete/neighbors?node_id=-2&type=movie")
    assert response.status_code == 200
    data = response.json()
    results = data["results"]
    assert len(results) == 3
    movie_ids = {node["id"] for node in results}
    assert movie_ids == {"-10", "-20", "-30"}
    # Verify descending vote count order
    assert results[0]["id"] == "-10"  # 1000 votes
    assert results[1]["id"] == "-20"  # 500 votes
    assert results[2]["id"] == "-30"  # 200 votes


async def test_neighbors_of_movie(client):
    # Film Three's actors
    response = await client.get("/autocomplete/neighbors?node_id=-30&type=actor")
    assert response.status_code == 200
    data = response.json()
    results = data["results"]
    assert len(results) == 3
    actor_ids = {node["id"] for node in results}
    assert actor_ids == {"-2", "-3", "-4"}
    # Verify descending popularity order
    assert results[0]["id"] == "-2"  # Bob (5.1)
    assert results[1]["id"] == "-3"  # Carol (4.3)
    assert results[2]["id"] == "-4"  # Dave (3.5)


# --- Connected Endpoint Tests ---


async def test_connected_valid(client):
    response = await client.get("/connected?a=-1&b=-10")
    assert response.status_code == 200
    assert response.json()["connected"]

    # Symmetric check
    response_rev = await client.get("/connected?a=-10&b=-1")
    assert response_rev.status_code == 200
    assert response_rev.json()["connected"]


async def test_connected_invalid(client):
    response = await client.get("/connected?a=-1&b=-20")
    assert response.status_code == 200
    assert not response.json()["connected"]
