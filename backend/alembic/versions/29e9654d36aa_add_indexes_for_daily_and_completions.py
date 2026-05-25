"""add indexes for daily puzzle lookup and completion queries

Revision ID: 29e9654d36aa
Revises: a226acbf2368
Create Date: 2026-05-24

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op

revision: str = "29e9654d36aa"
down_revision: Union[str, Sequence[str], None] = "a226acbf2368"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # GET /daily filters on (is_daily, scheduled_date) on every request.
    op.create_index("ix_puzzles_daily_date", "puzzles", ["is_daily", "scheduled_date"])
    # _compute_streak and completion lookup both filter game_completions by user_id.
    op.create_index("ix_game_completions_user_id", "game_completions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_game_completions_user_id", table_name="game_completions")
    op.drop_index("ix_puzzles_daily_date", table_name="puzzles")
