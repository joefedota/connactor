"""
BFS + all-paths logic over the Connactor bipartite actor-movie graph.
from __future__ import annotations is used for Python 3.9 compatibility with | union types.

Graph structure: actor nodes (type="actor") and movie nodes (type="movie")
are connected by edges representing appearance. Paths always alternate:
actor → movie → actor → movie → actor ...

Path representation: list of node IDs (nconst/tconst strings), odd length.
"""
from __future__ import annotations

from collections import deque

import networkx as nx

MAX_PATHS = 10


def bfs_shortest_path_length(G: nx.Graph, source: str, target: str) -> int | None:
    """BFS from source to target. Returns edge-count of shortest path, or None."""
    if source == target:
        return 0
    visited = {source}
    queue = deque([(source, 0)])
    while queue:
        node, depth = queue.popleft()
        for neighbor in G.neighbors(node):
            if neighbor == target:
                return depth + 1
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
    return None


def find_all_shortest_paths(
    G: nx.Graph,
    source: str,
    target: str,
    max_paths: int = MAX_PATHS,
) -> list[list[str]]:
    """
    Return up to max_paths shortest paths from source to target.

    Algorithm:
    1. BFS from target → dist_from_target for every reachable node
    2. DFS from source, only following edges that reduce dist_from_target by 1
    3. Collect complete paths until max_paths reached

    Each returned path is a list of node IDs alternating actor/movie.
    """
    if source == target:
        return [[source]]

    # Step 1: BFS backward from target
    dist_from_target: dict[str, int] = {target: 0}
    queue: deque[str] = deque([target])
    while queue:
        node = queue.popleft()
        for neighbor in G.neighbors(node):
            if neighbor not in dist_from_target:
                dist_from_target[neighbor] = dist_from_target[node] + 1
                queue.append(neighbor)

    if source not in dist_from_target:
        return []

    # Step 2 & 3: DFS from source along optimal edges
    paths: list[list[str]] = []
    stack: list[tuple[str, list[str]]] = [(source, [source])]
    while stack and len(paths) < max_paths:
        node, path = stack.pop()
        if node == target:
            paths.append(path)
            continue
        remaining = dist_from_target.get(node)
        if remaining is None or remaining == 0:
            continue
        for neighbor in G.neighbors(node):
            if dist_from_target.get(neighbor) == remaining - 1:
                stack.append((neighbor, path + [neighbor]))

    return paths


def path_to_display(G: nx.Graph, path: list[str]) -> list[dict]:
    """Convert a raw node-ID path to a list of display dicts."""
    result = []
    for node_id in path:
        data = G.nodes[node_id]
        node_type = data.get("type")
        if node_type == "actor":
            result.append({"type": "actor", "id": node_id, "label": data["name"]})
        elif node_type == "movie":
            result.append({"type": "movie", "id": node_id, "label": data["title"], "year": data.get("year")})
    return result


def validate_path(
    G: nx.Graph,
    path: list[str],
    source: str,
    target: str,
) -> tuple[bool, str]:
    """
    Validate a user-submitted path.
    Returns (is_valid, error_message). error_message is empty string when valid.
    """
    if not path:
        return False, "Path is empty"
    if path[0] != source:
        return False, f"Path must start with source actor {source}"
    if len(path) < 3:
        return False, "Path must have at least 3 nodes (actor → movie → actor)"
    if len(path) % 2 == 0:
        return False, "Path length must be odd (actor → movie → actor → ...)"

    seen_movies: set[str] = set()
    for i, node_id in enumerate(path):
        if node_id not in G:
            return False, f"Unknown node: {node_id}"
        expected_type = "actor" if i % 2 == 0 else "movie"
        actual_type = G.nodes[node_id].get("type")
        if actual_type != expected_type:
            return False, f"Node {node_id} should be {expected_type}, got {actual_type}"
        if expected_type == "movie":
            if node_id in seen_movies:
                return False, f"Movie {node_id} appears twice in the path"
            seen_movies.add(node_id)
        if i > 0:
            if not G.has_edge(path[i - 1], node_id):
                prev_data = G.nodes[path[i - 1]]
                curr_data = G.nodes[node_id]
                prev_label = prev_data.get("name") or prev_data.get("title", path[i - 1])
                curr_label = curr_data.get("name") or curr_data.get("title", node_id)
                return False, f"{prev_label} and {curr_label} did not appear in the same movie"

    if path[-1] != target:
        # Path is valid so far but incomplete — caller checks is_complete separately
        return True, ""

    return True, ""


def neighbors_of_type(G: nx.Graph, node_id: str, node_type: str) -> list[str]:
    """Return all neighbors of node_id that have the given type."""
    return [
        n for n in G.neighbors(node_id)
        if G.nodes[n].get("type") == node_type
    ]
