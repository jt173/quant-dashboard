from sqlalchemy import text
from sqlalchemy.orm import Session


def test_tests_run_against_the_test_database(db: Session) -> None:
    assert str(db.scalar(text("SELECT current_database()"))).endswith("_test")
