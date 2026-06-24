# alembic/env.py
"""
Alembic migration environment.

Key config:
  - Uses SYNC database URL (psycopg2) because Alembic is synchronous
  - Imports all models via app.models so autogenerate detects all tables
  - target_metadata tells Alembic what the schema SHOULD look like
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Load app config ────────────────────────────────────────────────────────
from app.core.config import settings

# ── Import models so Alembic sees them ────────────────────────────────────
from app.models import Sensor, Signal, Anomaly          # noqa: F401
from app.db.session import Base

# ── Alembic Config object ──────────────────────────────────────────────────
config = context.config

# Override sqlalchemy.url with our settings value
config.set_main_option("sqlalchemy.url", settings.DATABASE_SYNC_URL)

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is what Alembic diffs against to generate migrations
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL scripts)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,          # Detects column type changes
            compare_server_default=True, # Detects default value changes
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()