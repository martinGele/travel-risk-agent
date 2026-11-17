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
