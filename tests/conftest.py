from datetime import UTC, datetime

import pytest

from support_desk.checks import ReplyContext, Severity, check_reply
from support_desk.config import EXPORT_TAKEN_AT, PROJECT_ROOT, Settings
from support_desk.desk import SupportDesk
from support_desk.models import load_customers, load_tickets
from support_desk.policy import Policy
from support_desk.triage import triage_queue


@pytest.fixture(autouse=True)
def _never_write_to_the_repo(monkeypatch, tmp_path):
    # cli.main builds its settings from the environment; the default workspace is inside the repo.
    monkeypatch.setenv("SUPPORT_DESK_WORKSPACE", str(tmp_path / "env-workspace"))
    monkeypatch.delenv("SUPPORT_DESK_AS_OF", raising=False)


@pytest.fixture(scope="session")
def data_dir():
    return PROJECT_ROOT / "data"


@pytest.fixture
def settings(tmp_path, data_dir) -> Settings:
    return Settings(data_dir=data_dir, workspace_dir=tmp_path / "workspace", as_of=EXPORT_TAKEN_AT)


@pytest.fixture
def desk(settings) -> SupportDesk:
    return SupportDesk(settings, clock=lambda: datetime(2026, 9, 29, 9, 30, tzinfo=UTC))


@pytest.fixture(scope="session")
def policy(data_dir) -> Policy:
    return Policy.load(data_dir)


@pytest.fixture(scope="session")
def customers(data_dir):
    return load_customers(data_dir / "customers.csv")


@pytest.fixture(scope="session")
def tickets(data_dir):
    return {t.ticket_id: t for t in load_tickets(data_dir / "tickets.json")}


@pytest.fixture(scope="session")
def queue(tickets, customers, policy):
    return {t.ticket.ticket_id: t for t in triage_queue(list(tickets.values()), customers, policy, EXPORT_TAKEN_AT)}


@pytest.fixture(scope="session")
def codes(tickets, customers, policy):
    """The finding codes check_reply gives a reply on a ticket, at one severity (None for all)."""

    def run(body, ticket, severity=Severity.BLOCK, **context):
        ticket = tickets[ticket] if isinstance(ticket, str) else ticket
        ctx = ReplyContext(ticket, customers.get(ticket.customer_id), customers.values(), policy, **context)
        return {f.code for f in check_reply(body, ctx) if severity is None or f.severity is severity}

    return run


@pytest.fixture
def anyio_backend():
    return "asyncio"
