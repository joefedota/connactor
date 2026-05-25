"""Unit tests for the Discover-based candidate-list builder (#91)."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Mirror bootstrap.py's path setup so `ingest.*` imports work in tests.
_PIPELINE = (Path(__file__).resolve().parent.parent / "pipeline").resolve()
sys.path.insert(0, str(_PIPELINE))
sys.path.insert(0, str(_PIPELINE.parent))

from ingest.build_candidate_list import _build_async, _fetch_year  # noqa: E402

pytestmark = pytest.mark.anyio


def _make_response(year: int, page: int, total_pages: int, ids: list[int]) -> dict:
    return {
        "page": page,
        "total_pages": total_pages,
        "results": [
            {
                "id": mid,
                "title": f"Movie {mid}",
                "original_title": f"Movie {mid}",
                "popularity": float(100 - i),
                "vote_count": 500 + i,
            }
            for i, mid in enumerate(ids)
        ],
    }


async def test_fetch_year_single_page():
    """A year with one page of results returns just those movies, no extra fetches."""
    with patch("ingest.build_candidate_list._fetch_page", new_callable=AsyncMock) as mp:
        mp.return_value = _make_response(2013, 1, 1, [100, 200, 300])
        result = await _fetch_year(client=None, year=2013, limiter=None, sem=None)
        assert mp.call_count == 1
        assert [m["id"] for m in result] == [100, 200, 300]


async def test_fetch_year_paginates_through_all_pages():
    """Multi-page year fetches every page and concatenates."""
    pages = {
        1: _make_response(2014, 1, 3, [1, 2]),
        2: _make_response(2014, 2, 3, [3, 4]),
        3: _make_response(2014, 3, 3, [5, 6]),
    }
    async def fake_fetch(client, year, page, limiter, sem):
        return pages[page]

    with patch("ingest.build_candidate_list._fetch_page", side_effect=fake_fetch):
        result = await _fetch_year(client=None, year=2014, limiter=None, sem=None)
        assert sorted(m["id"] for m in result) == [1, 2, 3, 4, 5, 6]


async def test_fetch_year_respects_500_page_cap():
    """Even if TMDb reports total_pages > 500, we stop at 500 (their hard cap)."""
    page1 = _make_response(2015, 1, 999, [42])

    async def fake_fetch(client, year, page, limiter, sem):
        return _make_response(year, page, 999, [page * 1000])

    with patch("ingest.build_candidate_list._fetch_page", side_effect=fake_fetch) as mp:
        # Pre-populate page 1 with the actual first-page response shape.
        await _fetch_year(client=None, year=2015, limiter=None, sem=None)
        # call_count = 1 (the initial page 1 fetch) + (500 - 1) additional pages = 500 total
        assert mp.call_count == 500


async def test_build_dedups_across_years():
    """A movie that appears in multiple year shards is only kept once."""
    by_year_page = {
        (2013, 1): _make_response(2013, 1, 1, [100, 200]),
        (2014, 1): _make_response(2014, 1, 1, [200, 300]),  # 200 dup
        (2015, 1): _make_response(2015, 1, 1, [300, 400]),  # 300 dup
    }
    async def fake_fetch(client, year, page, limiter, sem):
        return by_year_page.get((year, page), _make_response(year, page, 1, []))

    with patch("ingest.build_candidate_list._fetch_page", side_effect=fake_fetch), \
         patch("ingest.build_candidate_list.MIN_YEAR", 2013), \
         patch("ingest.build_candidate_list.settings.tmdb_api_read_token", "dummy"):
        result = await _build_async(end_year=2014)  # +2 in code → years 2013-2016
        ids = sorted(m["id"] for m in result)
        # 100, 200, 300, 400 unique — no dups
        assert ids == [100, 200, 300, 400]


async def test_build_sorts_by_popularity_desc():
    """Final candidate list is ordered by popularity descending."""
    page = {
        "page": 1, "total_pages": 1,
        "results": [
            {"id": 1, "title": "Low",  "original_title": "Low",  "popularity": 2.0, "vote_count": 200},
            {"id": 2, "title": "High", "original_title": "High", "popularity": 99.0, "vote_count": 200},
            {"id": 3, "title": "Mid",  "original_title": "Mid",  "popularity": 50.0, "vote_count": 200},
        ],
    }
    async def fake_fetch(client, year, page_num, limiter, sem):
        return page if year == 2020 else _make_response(year, page_num, 1, [])

    with patch("ingest.build_candidate_list._fetch_page", side_effect=fake_fetch), \
         patch("ingest.build_candidate_list.MIN_YEAR", 2020), \
         patch("ingest.build_candidate_list.settings.tmdb_api_read_token", "dummy"):
        result = await _build_async(end_year=2019)  # +2 in code → 2020-2021
        assert [m["id"] for m in result] == [2, 3, 1]
