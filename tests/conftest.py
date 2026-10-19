from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from quant_dashboard.db import engine
from quant_dashboard.main import app


@pytest.fixture(scope="session", autouse=True)
def _migrate() -> None:
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE notes RESTART IDENTITY"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
