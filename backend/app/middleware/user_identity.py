"""Anonymous user identity middleware.

Sets request.state.user_id to a stable UUID per browser, backed by a signed
HTTPOnly cookie. Creates a users row on first visit.
"""
from __future__ import annotations

import logging
import uuid

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.pg import get_session
from settings import settings

logger = logging.getLogger(__name__)

_COOKIE_NAME = "uid"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 2  # 2 years


def _get_signer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.cookie_secret, salt="user-identity")


def _sign(user_id: str) -> str:
    return _get_signer().dumps(user_id)


def _unsign(value: str) -> str | None:
    try:
        return _get_signer().loads(value)
    except BadSignature:
        return None


class UserIdentityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        raw = request.cookies.get(_COOKIE_NAME)
        user_id: str | None = _unsign(raw) if raw else None
        new_user = user_id is None

        if new_user:
            user_id = str(uuid.uuid4())

        request.state.user_id = user_id

        response: Response = await call_next(request)

        if new_user:
            try:
                async with get_session() as session:
                    await session.execute(
                        text(
                            "INSERT INTO users (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"
                        ),
                        {"uid": user_id},
                    )
                    await session.commit()
            except Exception:
                logger.exception("Failed to upsert user row for %s", user_id)

            response.set_cookie(
                _COOKIE_NAME,
                _sign(user_id),
                max_age=_COOKIE_MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=False,  # set to True in prod (HTTPS only)
            )

        return response
