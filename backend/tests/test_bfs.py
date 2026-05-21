"""
Unit tests for bfs.py using a hand-crafted 5-actor fixture graph.

Graph topology:
    nmA -- tt1 -- nmB -- tt2 -- nmC
                   |             |
                  tt3 ----------+
                   |
                  nmD

nmE is isolated (no edges).

Hop counts (edge count = number of steps in path):
  nmA → nmB : 2  (nmA-tt1-nmB)
  nmA → nmC : 4  (nmA-tt1-nmB-tt2-nmC  OR  nmA-tt1-nmB-tt3-nmC)
  nmA → nmD : 4  (nmA-tt1-nmB-tt3-nmD)
  nmA → nmE : None (disconnected)
"""

import sys
from pathlib import Path

import networkx as nx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.bfs import (
    bfs_shortest_path_length,
    find_all_shortest_paths,
    neighbors_of_type,
    path_to_display,
    validate_path,
)


@pytest.fixture
def G():
    graph = nx.Graph()
    # Actor nodes
    for nconst, name in [
        ("nmA", "Alice"),
        ("nmB", "Bob"),
        ("nmC", "Carol"),
        ("nmD", "Dave"),
        ("nmE", "Eve"),
    ]:
        graph.add_node(nconst, type="actor", name=name, birth_year=None)
    # Movie nodes
    for tconst, title in [
        ("tt1", "Film One"),
        ("tt2", "Film Two"),
        ("tt3", "Film Three"),
    ]:
        graph.add_node(tconst, type="movie", title=title)
    # Edges
    graph.add_edges_from([
        ("nmA", "tt1"),
        ("nmB", "tt1"),
        ("nmB", "tt2"),
        ("nmC", "tt2"),
        ("nmB", "tt3"),
        ("nmC", "tt3"),
        ("nmD", "tt3"),
    ])
    return graph


# --- bfs_shortest_path_length ---

def test_same_node(G):
    assert bfs_shortest_path_length(G, "nmA", "nmA") == 0


def test_direct_connection(G):
    # nmA and nmB share tt1 → 2 hops
    assert bfs_shortest_path_length(G, "nmA", "nmB") == 2


def test_two_hop_actor(G):
    # nmA → nmC: shortest is 4 hops (via nmB)
    assert bfs_shortest_path_length(G, "nmA", "nmC") == 4


def test_disconnected(G):
    assert bfs_shortest_path_length(G, "nmA", "nmE") is None


def test_symmetric(G):
    assert bfs_shortest_path_length(G, "nmB", "nmA") == 2
    assert bfs_shortest_path_length(G, "nmC", "nmA") == 4


# --- find_all_shortest_paths ---

def test_direct_path_contents(G):
    paths = find_all_shortest_paths(G, "nmA", "nmB")
    assert len(paths) == 1
    assert paths[0] == ["nmA", "tt1", "nmB"]


def test_multiple_paths(G):
    # nmA → nmC has 2 shortest paths: via tt2 and via tt3
    paths = find_all_shortest_paths(G, "nmA", "nmC")
    assert len(paths) == 2
    for p in paths:
        assert p[0] == "nmA"
        assert p[-1] == "nmC"
        assert len(p) == 5  # actor, movie, actor, movie, actor

    movie_ids = {p[3] for p in paths}  # second movie in each path
    assert movie_ids == {"tt2", "tt3"}


def test_disconnected_returns_empty(G):
    assert find_all_shortest_paths(G, "nmA", "nmE") == []


def test_same_node_returns_single_path(G):
    paths = find_all_shortest_paths(G, "nmA", "nmA")
    assert paths == [["nmA"]]


def test_path_cap():
    # Build a star: nmSRC shares 15 movies with nmTGT
    star = nx.Graph()
    star.add_node("nmSRC", type="actor", name="Source", birth_year=None)
    star.add_node("nmTGT", type="actor", name="Target", birth_year=None)
    for i in range(15):
        tconst = f"tt{i}"
        star.add_node(tconst, type="movie", title=f"Film {i}")
        star.add_edge("nmSRC", tconst)
        star.add_edge("nmTGT", tconst)

    paths = find_all_shortest_paths(star, "nmSRC", "nmTGT", max_paths=10)
    assert len(paths) == 10  # capped at 10 even though 15 exist


def test_all_paths_are_optimal(G):
    paths = find_all_shortest_paths(G, "nmA", "nmC")
    lengths = {len(p) for p in paths}
    assert len(lengths) == 1, "All returned paths should be the same (minimum) length"


# --- validate_path ---

def test_validate_valid_path(G):
    valid, msg = validate_path(G, ["nmA", "tt1", "nmB"], "nmA", "nmB")
    assert valid
    assert msg == ""


def test_validate_valid_incomplete_path(G):
    # Valid so far but doesn't reach target
    valid, msg = validate_path(G, ["nmA", "tt1", "nmB"], "nmA", "nmC")
    assert valid  # structurally valid, just not complete yet


def test_validate_empty_path(G):
    valid, msg = validate_path(G, [], "nmA", "nmB")
    assert not valid


def test_validate_too_short(G):
    valid, msg = validate_path(G, ["nmA", "tt1"], "nmA", "nmB")
    assert not valid


def test_validate_even_length(G):
    valid, msg = validate_path(G, ["nmA", "tt1", "nmB", "tt2"], "nmA", "nmC")
    assert not valid


def test_validate_nonexistent_edge(G):
    # nmA and tt2 are not connected
    valid, msg = validate_path(G, ["nmA", "tt2", "nmC"], "nmA", "nmC")
    assert not valid
    assert "did not appear" in msg


def test_validate_wrong_start(G):
    valid, msg = validate_path(G, ["nmB", "tt1", "nmA"], "nmA", "nmA")
    assert not valid
    assert "start" in msg.lower()


def test_validate_repeated_movie(G):
    # Construct a path that reuses tt3
    valid, msg = validate_path(
        G,
        ["nmB", "tt3", "nmC", "tt3", "nmD"],
        "nmB",
        "nmD",
    )
    assert not valid
    assert "twice" in msg.lower()


def test_validate_wrong_type_order(G):
    # Start with a movie node (violates actor-first rule)
    valid, msg = validate_path(G, ["tt1", "nmB", "tt2"], "tt1", "tt2")
    assert not valid


# --- neighbors_of_type ---

def test_neighbors_of_actor(G):
    # nmB's movie neighbors
    movies = set(neighbors_of_type(G, "nmB", "movie"))
    assert movies == {"tt1", "tt2", "tt3"}


def test_neighbors_of_movie(G):
    # tt3's actor neighbors
    actors = set(neighbors_of_type(G, "tt3", "actor"))
    assert actors == {"nmB", "nmC", "nmD"}


# --- path_to_display ---

def test_path_to_display(G):
    result = path_to_display(G, ["nmA", "tt1", "nmB"])
    assert result == [
        {"type": "actor", "id": "nmA", "label": "Alice"},
        {"type": "movie", "id": "tt1", "label": "Film One", "year": None},
        {"type": "actor", "id": "nmB", "label": "Bob"},
    ]
