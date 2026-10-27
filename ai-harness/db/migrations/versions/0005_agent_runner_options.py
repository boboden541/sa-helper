"""Опции раннера у агента: модель, инструменты, MCP, папка скиллов («мост», решение владельца 27.10.2026).

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_profile", sa.Column("model", sa.String(128), nullable=True))
    op.add_column("agent_profile", sa.Column("allowed_tools", JSONB, nullable=True))
    op.add_column("agent_profile", sa.Column("mcp_servers", JSONB, nullable=True))
    op.add_column("agent_profile", sa.Column("agent_dir", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_profile", "agent_dir")
    op.drop_column("agent_profile", "mcp_servers")
    op.drop_column("agent_profile", "allowed_tools")
    op.drop_column("agent_profile", "model")
