"""add gave_up to game_completions

Revision ID: c4e2f3d6a7b8
Revises: b3f1c2d4e5a6
Create Date: 2026-05-25

"""
from __future__ import annotations
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e2f3d6a7b8"
down_revision: Union[str, Sequence[str], None] = "b3f1c2d4e5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "game_completions",
        sa.Column("gave_up", sa.Boolean(), nullable=False, server_default="FALSE"),
    )


def downgrade() -> None:
    op.drop_column("game_completions", "gave_up")
