"""Small dialect helpers shared by the serialized Alembic revision chain."""

from __future__ import annotations

from alembic import context, op


def dialect_name() -> str:
    """Return the configured dialect in both online and ``--sql`` modes."""
    return op.get_bind().dialect.name


def is_sqlite() -> bool:
    return dialect_name() == "sqlite"


def is_postgresql() -> bool:
    return dialect_name() == "postgresql"


def is_offline() -> bool:
    return context.is_offline_mode()
