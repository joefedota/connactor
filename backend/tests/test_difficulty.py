"""
Unit tests for game difficulty classification logic.
"""

import sys
from pathlib import Path

import networkx as nx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import classify_difficulty


@pytest.fixture
def G():
    graph = nx.Graph()
    # Add actor nodes with custom popularity scores
    graph.add_node("actor_super_famous_1", type="actor", name="Super Famous One", popularity=6.2)
    graph.add_node("actor_super_famous_2", type="actor", name="Super Famous Two", popularity=5.1)
    graph.add_node("actor_famous", type="actor", name="Famous Actor", popularity=4.3)
    graph.add_node("actor_known", type="actor", name="Moderately Known Actor", popularity=3.5)
    graph.add_node("actor_obscure", type="actor", name="Obscure Actor", popularity=2.1)
    return graph


def test_classify_difficulty_easy(G):
    # hops = 2, P_min = min(6.2, 5.1) = 5.1 >= 5.0 -> easy
    assert classify_difficulty(G, "actor_super_famous_1", "actor_super_famous_2", 2) == "easy"


def test_classify_difficulty_medium(G):
    # hops = 2, but P_min = min(6.2, 4.3) = 4.3 < 5.0 -> not easy. P_min >= 4.0 -> medium
    assert classify_difficulty(G, "actor_super_famous_1", "actor_famous", 2) == "medium"

    # hops = 4, P_min = min(4.3, 5.1) = 4.3 >= 4.0 -> medium
    assert classify_difficulty(G, "actor_famous", "actor_super_famous_2", 4) == "medium"


def test_classify_difficulty_hard(G):
    # hops = 2, P_min = min(4.3, 3.5) = 3.5 < 4.0 -> hard
    assert classify_difficulty(G, "actor_famous", "actor_known", 2) == "hard"

    # hops = 6, P_min = min(6.2, 3.5) = 3.5 >= 3.0 -> hard
    assert classify_difficulty(G, "actor_super_famous_1", "actor_known", 6) == "hard"


def test_classify_difficulty_expert(G):
    # hops = 2, but P_min = min(6.2, 2.1) = 2.1 < 3.0 -> expert
    assert classify_difficulty(G, "actor_super_famous_1", "actor_obscure", 2) == "expert"

    # hops = 8, any popularity -> expert
    assert classify_difficulty(G, "actor_super_famous_1", "actor_super_famous_2", 8) == "expert"
