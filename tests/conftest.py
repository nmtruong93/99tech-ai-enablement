from datetime import UTC, datetime
from pathlib import Path

import pytest

from support_desk.config import EXPORT_TAKEN_AT, PROJECT_ROOT, Settings
from support_desk.desk import SupportDesk
from support_desk.export import load_customers, load_tickets
from support_desk.policy import Policy

DATA = PROJECT_ROOT / "data"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=DATA, workspace_dir=tmp_path / "workspace", as_of=EXPORT_TAKEN_AT)


@pytest.fixture
def desk(settings: Settings) -> SupportDesk:
    return SupportDesk(settings, clock=lambda: datetime(2026, 9, 29, 9, 30, tzinfo=UTC))


@pytest.fixture(scope="session")
def policy() -> Policy:
    return Policy.load(DATA)


@pytest.fixture(scope="session")
def customers():
    return load_customers(DATA / "customers.csv")


@pytest.fixture(scope="session")
def tickets():
    return {t.ticket_id: t for t in load_tickets(DATA / "tickets.json")}


@pytest.fixture
def anyio_backend():
    return "asyncio"
