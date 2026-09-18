"""Alembic environment: runs migrations as the schema owner.

The connection URL comes from `Settings.migration_database_url` (`MIGRATION_DATABASE_URL`),
never from `alembic.ini`, so credentials stay out of the repository. Tests pass a URL through
the config attribute `sqlalchemy.url` instead.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import Settings
from app.db import models  # noqa: F401  (imports every table so autogenerate can see it)
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or Settings().migration_database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect as the owner and apply migrations in one transaction."""
    connectable = engine_from_config(
        {"sqlalchemy.url": _url()}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
