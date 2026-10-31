"""Records read from the export and written by the desk.

Tickets keep the export's field names so the working copy of tickets.json stays diffable
against the original.
"""

import csv
import json
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel


class Customer(BaseModel):
    customer_id: str
    full_name: str
    email: str
    phone: str
    country: str
    currency: str
    vip_tier: str
    kyc_status: str
    kyc_review_reason: str | None = None
    self_excluded: bool
    balance: float
    registered_at: date

    @property
    def given_name(self) -> str:
        """The name to greet them by. Vietnamese names put the given name last ("Le Minh Khoa" is Khoa)."""
        parts = self.full_name.split()
        return parts[-1] if self.country == "VN" else parts[0]


class TicketStatus(StrEnum):
    OPEN = "open"
    REPLIED = "replied"
    CLOSED = "closed"


class Ticket(BaseModel):
    ticket_id: str
    customer_id: str
    channel: str
    created_at: datetime
    subject: str
    message: str
    status: TicketStatus
    assigned_to: str | None = None
    first_response_at: datetime | None = None
    agent_reply: str | None = None
    resolution: str | None = None
    merged_into: str | None = None  # set by the desk when a duplicate is answered on another ticket

    @property
    def is_open(self) -> bool:
        return self.status is TicketStatus.OPEN


class Team(StrEnum):
    TEAM_LEAD = "team_lead"
    PAYMENTS = "payments"


class DraftStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class RefundStatus(StrEnum):
    WITHIN_AGENT_LIMIT = "within_agent_limit"
    AWAITING_APPROVAL = "awaiting_team_lead_approval"
    APPROVED = "approved"
    DECLINED = "declined"


class Draft(BaseModel):
    draft_id: str
    ticket_id: str
    body: str
    language: str
    policy_refs: list[str]
    note_for_reviewer: str
    warnings: list[str]
    status: DraftStatus = DraftStatus.PENDING_REVIEW
    created_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None


class Escalation(BaseModel):
    escalation_id: str
    ticket_id: str
    team: Team
    reason: str
    created_at: datetime


class RefundRequest(BaseModel):
    refund_id: str
    ticket_id: str
    customer_id: str
    amount_usd: float
    reason: str
    status: RefundStatus
    why: str  # why it has this status
    created_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None


def load_tickets(path: Path) -> list[Ticket]:
    return [Ticket.model_validate(t) for t in json.loads(path.read_text(encoding="utf-8"))]


def load_customers(path: Path) -> dict[str, Customer]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = [{k: (v if v != "" else None) for k, v in row.items()} for row in csv.DictReader(f)]
    return {row["customer_id"]: Customer.model_validate(row) for row in rows}
