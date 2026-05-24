"""Unit tests for the ingest-time vote_count filter (#65)."""
from pipeline.ingest.load_neo4j import _should_load_movie


def test_keeps_decayed_catalog_hit():
    # The Internship case: 4,471 votes, popularity decayed to 0.2 — must stay.
    assert _should_load_movie(vote_count=4471, popularity=0.2) is True


def test_drops_obscure_new_movie_with_inflated_popularity():
    # Recent release with high TMDB popularity but no real audience yet.
    assert _should_load_movie(vote_count=50, popularity=2.0) is False


def test_keeps_brand_new_movie_with_no_votes_yet():
    # vote_count not crawled yet AND popularity high — grace window.
    assert _should_load_movie(vote_count=None, popularity=2.5) is True


def test_drops_obscure_unvoted_movie():
    # No votes and not currently trending — long-tail noise.
    assert _should_load_movie(vote_count=None, popularity=0.5) is False


def test_drops_decayed_obscure_movie():
    # Low votes and decayed popularity — also long-tail noise.
    assert _should_load_movie(vote_count=50, popularity=0.2) is False


def test_threshold_boundary():
    # vote_count == threshold should be excluded (we use strict >).
    assert _should_load_movie(vote_count=100, popularity=0.2) is False
    assert _should_load_movie(vote_count=101, popularity=0.2) is True


def test_handles_zero_popularity():
    # Defensive: vote_count drives the decision, popularity=0 shouldn't break grace logic.
    assert _should_load_movie(vote_count=500, popularity=0.0) is True
    assert _should_load_movie(vote_count=None, popularity=0.0) is False
