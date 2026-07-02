"""Tests for UserIdentityMiddleware cookie behavior."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.middleware.user_identity import _COOKIE_MAX_AGE, _sign, _unsign


def _mock_pg():
    """Patch the middleware's get_session with a recording mock."""
    session = AsyncMock()
    calls = []

    @asynccontextmanager
    async def _get_session():
        calls.append(1)
        yield session

    patcher = patch("app.middleware.user_identity.get_session", _get_session)
    return patcher, session, calls


@pytest.mark.anyio
async def test_new_user_gets_cookie_and_users_row(client):
    patcher, session, calls = _mock_pg()
    with patcher:
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert "uid" in resp.cookies
    # Cookie value round-trips to a valid UUID.
    user_id = _unsign(resp.cookies["uid"])
    uuid.UUID(user_id)
    # A users row insert was attempted for the new identity.
    assert calls
    session.execute.assert_awaited()
    assert f"max-age={_COOKIE_MAX_AGE}" in resp.headers["set-cookie"].lower()


@pytest.mark.anyio
async def test_returning_user_cookie_is_refreshed(client):
    """The uid cookie must be re-set on every response, not just first visit.

    Safari ITP caps cookies from CNAME-cloaked hosts to 7 days per set;
    refreshing on each request slides that window (#147).
    """
    user_id = str(uuid.uuid4())
    client.cookies.set("uid", _sign(user_id))

    patcher, session, calls = _mock_pg()
    with patcher:
        resp = await client.get("/health")

    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "uid=" in set_cookie
    assert f"max-age={_COOKIE_MAX_AGE}" in set_cookie.lower()
    # Same identity is preserved, no new users row is inserted.
    assert _unsign(resp.cookies["uid"]) == user_id
    assert not calls


@pytest.mark.anyio
async def test_bad_signature_mints_new_user(client):
    client.cookies.set("uid", "tampered-value")

    patcher, session, calls = _mock_pg()
    with patcher:
        resp = await client.get("/health")

    assert resp.status_code == 200
    new_id = _unsign(resp.cookies["uid"])
    uuid.UUID(new_id)
    assert calls
