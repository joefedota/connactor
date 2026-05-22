from __future__ import annotations

from neo4j import AsyncGraphDatabase

from settings import settings


def get_driver():
    return AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
