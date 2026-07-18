"""Alembic environment configuration with dynamic DB path resolution."""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# this is the Alembic Config object
config = context.config

# Set up logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# Resolve DB path same way as key_store.py
def _resolve_db_path() -> str:
    env = os.environ.get("LLM_APIPOOL_DB") or os.environ.get("LLM_APIPOOL_DB_LEGACY")
    if env:
        return env
    return str(Path.home() / ".llm-apipool" / "keys.db")


# Override sqlalchemy.url with resolved path
db_path = _resolve_db_path()
config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

# Import all models for autogenerate support
from llm_apipool.key_store import SCHEMA  # noqa: E402, F401


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=None, literal_binds=True, compare_type=True, compare_server_default=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None, compare_type=True, compare_server_default=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
