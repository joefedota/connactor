"""create users puzzles game_completions

Revision ID: a226acbf2368
Revises:
Create Date: 2026-05-24

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a226acbf2368"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "users",
        sa.Column("user_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )

    op.create_table(
        "puzzles",
        sa.Column("puzzle_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("optimal_hops", sa.Integer(), nullable=False),
        sa.Column("is_daily", sa.Boolean(), server_default=sa.text("FALSE"), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("source_id", "target_id", name="uq_puzzles_pair"),
    )

    op.create_table(
        "game_completions",
        sa.Column("completion_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("puzzle_id", sa.UUID(), sa.ForeignKey("puzzles.puzzle_id"), nullable=False),
        sa.Column("hops", sa.Integer(), nullable=False),
        sa.Column("time_ms", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("user_id", "puzzle_id", name="uq_completion_per_user_puzzle"),
    )


def downgrade() -> None:
    op.drop_table("game_completions")
    op.drop_table("puzzles")
    op.drop_table("users")
