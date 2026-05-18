"""
Trie-based prefix autocomplete for actor names and movie titles.

Features:
- Diacritic normalization: "Timothée" → "timothee"
- Word-level indexing: typing "Chalamet" finds "Timothée Chalamet"
- Separate tries for actors and movies (built once at startup)
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


def normalize(text: str) -> str:
    """Lowercase, strip diacritics and punctuation, collapse whitespace."""
    nfkd = unicodedata.normalize("NFD", text)
    no_diacritics = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    alphanumeric = "".join(c if c.isalnum() or c.isspace() else " " for c in no_diacritics)
    return " ".join(alphanumeric.lower().split())


@dataclass
class TrieNode:
    children: dict[str, "TrieNode"] = field(default_factory=dict)
    # Items stored at this node (full items whose normalized form ends here)
    items: list[dict] = field(default_factory=list)


class Trie:
    def __init__(self) -> None:
        self.root = TrieNode()

    def insert(self, key: str, item: dict) -> None:
        """Insert item under the normalized key string."""
        node = self.root
        for ch in key:
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
        node.items.append(item)

    def search(self, prefix: str, max_results: int = 10) -> list[dict]:
        """Return up to max_results unique items whose key starts with prefix."""
        node = self.root
        for ch in prefix:
            if ch not in node.children:
                return []
            node = node.children[ch]
        # DFS to collect items, deduplicating by id
        results: list[dict] = []
        seen_ids: set[str] = set()
        stack = [node]
        while stack and len(results) < max_results:
            cur = stack.pop()
            for item in cur.items:
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    results.append(item)
                    if len(results) >= max_results:
                        break
            stack.extend(cur.children.values())
        return results


def build_trie(items: list[dict], label_key: str) -> Trie:
    """
    Build a Trie from a list of item dicts.

    Each item is inserted under two keys:
      1. The full normalized label (e.g. "timothee chalamet")
      2. Each individual word (e.g. "timothee", "chalamet")
    This lets users search by first name, last name, or full name.
    """
    trie = Trie()
    for item in items:
        label = item.get(label_key, "")
        norm = normalize(label)
        trie.insert(norm, item)
        # Also insert each word separately (skip duplicates of the full name)
        words = norm.split()
        for word in words:
            if word != norm:
                trie.insert(word, item)
    return trie


def query_autocomplete(
    trie: Trie, prefix: str, max_results: int = 10
) -> list[dict]:
    """Normalize prefix and search trie. Returns list of matching items."""
    norm = normalize(prefix)
    if not norm:
        return []
    return trie.search(norm, max_results)


def filter_neighbors(
    all_items: list[dict], neighbor_ids: set[str], id_key: str = "id"
) -> list[dict]:
    """Return items from all_items whose id is in neighbor_ids."""
    return [item for item in all_items if item.get(id_key) in neighbor_ids]
