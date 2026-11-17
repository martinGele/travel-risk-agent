import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def us_feed_xml() -> bytes:
    return (FIXTURES / "us_state_feed.xml").read_bytes()


@pytest.fixture
def uk_index() -> dict:
    return json.loads((FIXTURES / "uk_index.json").read_text())


def load_uk(name: str) -> dict:
    return json.loads((FIXTURES / f"uk_{name}.json").read_text())


# ---- database fixtures (tests using them must be marked `db`) ----

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from travel_risk.config import get_settings  # noqa: E402
from travel_risk.models import Base  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    url = get_settings().database_url.rsplit("/", 1)[0] + "/travelrisk_test"
    admin = create_engine(get_settings().database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            c.execute(text("DROP DATABASE IF EXISTS travelrisk_test"))
            c.execute(text("CREATE DATABASE travelrisk_test"))
    except OperationalError:
        pytest.skip("PostgreSQL not reachable: docker compose up -d db")
    finally:
        admin.dispose()
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """Each test runs in a transaction that is rolled back; commits become savepoints."""
    with engine.connect() as conn:
        tx = conn.begin()
        with Session(bind=conn, join_transaction_mode="create_savepoint") as s:
            yield s
        tx.rollback()
