"""add path_ids to game_completions

Revision ID: b3f1c2d4e5a6
Revises: 29e9654d36aa
Create Date: 2026-05-25

"""
from __future__ import annotations
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3f1c2d4e5a6"
down_revision: Union[str, Sequence[str], None] = "29e9654d36aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Stores the ordered list of actor/movie node IDs for the player's path.
    # Used to compute path uniqueness percentile on the daily results screen.
    # Nullable so existing rows are unaffected.
    op.add_column(
        "game_completions",
        sa.Column("path_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("game_completions", "path_ids")
