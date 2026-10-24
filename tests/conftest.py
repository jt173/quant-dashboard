from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

import quant_dashboard.models  # noqa: F401 (registers tables on Base.metadata)
from quant_dashboard.config import settings
from quant_dashboard.db import Base, get_db
from quant_dashboard.main import app

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _ensure_database(url: URL) -> None:
    """Create the test database if it doesn't exist yet (CREATE DATABASE can't run in a txn)."""
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            )
            if not exists:
                quoted = admin.dialect.identifier_preparer.quote(str(url.database))
                conn.execute(text(f"CREATE DATABASE {quoted}"))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Engine for the dedicated test database, migrated to head once per session."""
    url = make_url(settings.test_database_url)
    _ensure_database(url)

    test_engine = create_engine(url, pool_pre_ping=True)
    alembic_cfg = Config(str(ALEMBIC_INI))
    with test_engine.begin() as connection:  # commits on exit
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")

    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after each test.

    The session joins an outer transaction through a SAVEPOINT, so code under test can call
    ``commit()`` freely while nothing is ever really committed.
    """
    connection = engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
