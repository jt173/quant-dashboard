from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://quant:quant@localhost:5432/quant"

    # Tests run against their own database, created on demand by test/conftest.py
    test_database_url: str = "postgresql+psycopg://quant:quant@localhost:5432/quant_test"

    @model_validator(mode="after")
    def _test_database_is_disposable(self) -> Self:
        # Guard rail: the test suite must never be pointed at a real database
        name = make_url(self.test_database_url).database or ""
        if not name.endswith("_test"):
            msg = f"TEST_DATABASE_URL must name a database ending in '_test', got {name!r}"
            raise ValueError(msg)
        return self


settings = Settings()
