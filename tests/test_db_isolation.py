from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quant_dashboard.models import Note


def test_commit_never_leaves_the_test_transaction(db: Session, engine: Engine) -> None:
    db.add(Note(text="x"))
    db.commit()
    assert db.scalar(text("SELECT count(*) FROM notes")) == 1

    # A separate connection can't see it: the work lives in an uncommitted outer transaction
    with engine.connect() as other:
        assert other.scalar(text("SELECT count(*) FROM notes")) == 0


def test_tests_run_against_the_test_database(db: Session) -> None:
    assert str(db.scalar(text("SELECT current_database()"))).endswith("_test")
