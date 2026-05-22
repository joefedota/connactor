import sys
from pathlib import Path

import httpx
import pytest
from neo4j import AsyncGraphDatabase

# Add backend directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app
from settings import settings


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def neo4j_driver():
    # Connect to the Neo4j instance
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    # Verify connectivity
    await driver.verify_connectivity()

    # Ensure migrations/schema exist
    async with driver.session() as session:
        await session.run("CREATE CONSTRAINT actor_id IF NOT EXISTS FOR (a:Actor) REQUIRE a.person_id IS UNIQUE")
        await session.run("CREATE CONSTRAINT movie_id IF NOT EXISTS FOR (m:Movie) REQUIRE m.movie_id IS UNIQUE")
        await session.run("CREATE INDEX actor_rank IF NOT EXISTS FOR (a:Actor) ON (a.rank)")
        await session.run("CREATE INDEX movie_votes IF NOT EXISTS FOR (m:Movie) ON (m.vote_count)")
        await session.run("CREATE FULLTEXT INDEX actorNames IF NOT EXISTS FOR (n:Actor) ON EACH [n.name]")
        await session.run("CREATE FULLTEXT INDEX movieTitles IF NOT EXISTS FOR (n:Movie) ON EACH [n.title]")

    yield driver
    await driver.close()


@pytest.fixture(autouse=True)
async def setup_test_data(neo4j_driver):
    # Setup test data with negative IDs
    # Two actors per tier so the bucketed /game query can pick a pair from any
    # difficulty. fame_rank mirrors rank in test data — prod computes fame_rank
    # from movie vote_counts, but the tier semantics are identical.
    actors = [
        # easy (fame_rank < 50)
        {"person_id": -1, "name": "Alice",  "popularity": 6.2, "rank": 10,   "fame_rank": 10},
        {"person_id": -2, "name": "Bob",    "popularity": 5.1, "rank": 20,   "fame_rank": 20},
        # medium (50 <= fame_rank < 200)
        {"person_id": -3, "name": "Carol",  "popularity": 4.3, "rank": 100,  "fame_rank": 100},
        {"person_id": -6, "name": "Frank",  "popularity": 4.0, "rank": 150,  "fame_rank": 150},
        # hard (200 <= fame_rank < 1000)
        {"person_id": -4, "name": "Dave",   "popularity": 3.5, "rank": 500,  "fame_rank": 500},
        {"person_id": -7, "name": "Grace",  "popularity": 3.0, "rank": 700,  "fame_rank": 700},
        # expert (1000 <= fame_rank < 5000)
        {"person_id": -5, "name": "Eve",    "popularity": 2.1, "rank": 2000, "fame_rank": 2000},
        {"person_id": -8, "name": "Henry",  "popularity": 1.5, "rank": 3000, "fame_rank": 3000},
    ]
    movies = [
        {"movie_id": -10, "title": "TestFilm One",   "year": 2020, "vote_count": 1000},
        {"movie_id": -20, "title": "TestFilm Two",   "year": 2021, "vote_count": 500},
        {"movie_id": -30, "title": "TestFilm Three", "year": 2022, "vote_count": 200},
        {"movie_id": -40, "title": "TestFilm Four",  "year": 2023, "vote_count": 100},
        {"movie_id": -50, "title": "TestFilm Five",  "year": 2024, "vote_count": 50},
    ]
    edges = [
        {"person_id": -1, "movie_id": -10},  # Alice (easy)
        {"person_id": -2, "movie_id": -10},  # Bob (easy)   — easy pair connected
        {"person_id": -2, "movie_id": -20},
        {"person_id": -3, "movie_id": -20},  # Carol (medium)
        {"person_id": -6, "movie_id": -20},  # Frank (medium) — medium pair connected via TestFilm Two
        {"person_id": -2, "movie_id": -30},
        {"person_id": -3, "movie_id": -30},
        {"person_id": -4, "movie_id": -30},  # Dave (hard)
        {"person_id": -7, "movie_id": -30},  # Grace (hard)  — hard pair connected via TestFilm Three
        {"person_id": -4, "movie_id": -40},
        {"person_id": -5, "movie_id": -40},  # Eve (expert)
        {"person_id": -8, "movie_id": -50},  # Henry (expert)
        {"person_id": -5, "movie_id": -50},  # expert pair (Eve + Henry) connected via TestFilm Five
    ]

    async with neo4j_driver.session() as session:
        # First clean up just in case
        await session.run("MATCH (a:Actor) WHERE a.person_id < 0 DETACH DELETE a")
        await session.run("MATCH (m:Movie) WHERE m.movie_id < 0 DETACH DELETE m")

        # Insert actors
        await session.run(
            """
            UNWIND $actors AS actor
            CREATE (a:Actor {
                person_id: actor.person_id,
                name: actor.name,
                popularity: actor.popularity,
                rank: actor.rank,
                fame_rank: actor.fame_rank
            })
            """,
            actors=actors,
        )

        # Insert movies
        await session.run(
            """
            UNWIND $movies AS movie
            CREATE (m:Movie {movie_id: movie.movie_id, title: movie.title, year: movie.year, vote_count: movie.vote_count})
            """,
            movies=movies,
        )

        # Insert relationships
        await session.run(
            """
            UNWIND $edges AS edge
            MATCH (a:Actor {person_id: edge.person_id})
            MATCH (m:Movie {movie_id: edge.movie_id})
            CREATE (a)-[:APPEARED_IN]->(m)
            """,
            edges=edges,
        )

    yield

    # Cleanup after test finishes
    async with neo4j_driver.session() as session:
        await session.run("MATCH (a:Actor) WHERE a.person_id < 0 DETACH DELETE a")
        await session.run("MATCH (m:Movie) WHERE m.movie_id < 0 DETACH DELETE m")


@pytest.fixture
async def client(neo4j_driver):
    async with httpx.AsyncClient(app=app, base_url="http://test") as ac:
        app.state.neo4j = neo4j_driver
        yield ac
