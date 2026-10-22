from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def test_models_match_migrations(engine: Engine) -> None:
    """
    Fails if columns, indexes, FKs or unique contraints changed without a migration.

    (Alembic does not compare CHECK constraints, so those changes need a manual eye)
    """
    alembic_cfg = Config(str(ALEMBIC_INI))
    with engine.connect() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.check(alembic_cfg)
