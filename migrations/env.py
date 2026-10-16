"""Alembic migration environment.

Reads the database URL from the application config (DATABASE_URL env var) and
targets the SQLAlchemy metadata so `alembic revision --autogenerate` tracks the
ORM models. Works for both SQLite (dev) and PostgreSQL (production).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_config as get_app_config
from app.database import Base
from app import models  # noqa: F401  (register all tables on Base.metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime database URL (never hard-coded in alembic.ini).
config.set_main_option("sqlalchemy.url", get_app_config().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"}, render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            render_as_batch=True,  # batch mode for SQLite ALTER support
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
