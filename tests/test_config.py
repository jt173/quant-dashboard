import pytest
from pydantic import ValidationError

from quant_dashboard.config import Settings


def test_test_database_url_must_end_in_test() -> None:
    with pytest.raises(ValidationError, match="_test"):
        Settings(test_database_url="postgresql+psycopg://quant:quant@localhost:5432/quant")


def test_default_test_databse_url_is_valid() -> None:
    assert Settings().test_database_url.endswith("_test")
