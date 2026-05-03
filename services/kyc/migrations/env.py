"""
Alembic Migration Environment — KYC Service

Supports async SQLAlchemy (asyncpg) and reads DB URL from app settings
so the same config works in dev, CI, and production without editing ini files.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Alembic config object — gives access to values in alembic.ini
# ---------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Import models so Alembic can autogenerate migrations from metadata
# ---------------------------------------------------------------------------
from app.db.models import Base  # noqa: E402

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# DB URL resolution — env var wins over alembic.ini
# ---------------------------------------------------------------------------

def get_url() -> str:
    """
    Resolve the database URL.

    Priority:
      1. DB_URL environment variable (CI / production)
      2. alembic.ini sqlalchemy.url (local dev fallback)
    """
    db_url = os.getenv("DB_URL")
    if db_url:
        # Ensure asyncpg driver is used
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        return db_url
    return config.get_main_option("sqlalchemy.url")


# ---------------------------------------------------------------------------
# Offline mode — emit raw SQL without connecting to DB
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Generates SQL scripts without requiring a live DB connection.
    Useful for reviewing what will be applied before deploying.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode — connect to DB and apply migrations
# ---------------------------------------------------------------------------

def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations inside a sync wrapper."""
    connectable = create_async_engine(get_url(), echo=False)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
