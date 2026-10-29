"""Actions on the data: escalations, refund requests, drafts, and the human approval step."""

import json

import pytest

from support_desk.desk import DeskError
from support_desk.models import DraftStatus, RefundStatus, Team
from tests.conftest import DATA

WITHDRAWAL_REPLY = (
    "Hi Somchai, I'm sorry this has taken so long and that your email went unanswered. "
    "I've passed your $400 withdrawal to our Payments team to investigate, and we'll update you as soon as they have."
)


def test_export_is_never_modified(desk):
    before = (DATA / "tickets.json").read_bytes()
    desk.escalate("T-5102", Team.PAYMENTS, "Pending since 21 Sep, over 24h")
    desk.save_draft("T-5102", WITHDRAWAL_REPLY, ["handbook/withdrawals#3"], "check dashboard")
    assert (DATA / "tickets.json").read_bytes() == before


def test_escalation_updates_the_ticket_and_is_idempotent(desk):
    first = desk.escalate("T-5102", Team.PAYMENTS, "Pending since 21 Sep")
    again = desk.escalate("T-5102", Team.PAYMENTS, "Pending since 21 Sep")
    assert first.escalation_id == again.escalation_id
    ticket = desk.triage("T-5102").ticket
    assert ticket.escalated_to == ["payments"]
    assert "Pending since 21 Sep" in ticket.internal_notes[0].text


def test_team_lead_tickets_must_be_escalated_before_drafting(desk):
    body = "Hi Ethan, thank you for telling us. We've passed this to a senior colleague who will contact you."
    with pytest.raises(DeskError, match="escalate"):
        desk.save_draft("T-5105", body, [], "")
    desk.escalate("T-5105", Team.TEAM_LEAD, "Gambling harm, asks for permanent closure")
    draft, _ = desk.save_draft("T-5105", body, ["handbook/escalation#3"], "Start self-exclusion before sending")
    assert draft is not None


def test_duplicates_are_answered_on_the_primary_ticket(desk):
    with pytest.raises(DeskError, match="T-5102"):
        desk.save_draft("T-5110", WITHDRAWAL_REPLY, [], "")


def test_blocked_draft_is_not_saved_but_is_audited(desk):
    draft, findings = desk.save_draft("T-5101", "Hi Marcus, withdrawals take 3-5 days.", [], "")
    assert draft is None
    assert any(f.code == "superseded_policy" for f in findings)
    assert desk.workspace.drafts() == []
    audit = (desk.workspace.root / "audit.jsonl").read_text().splitlines()
    assert json.loads(audit[-1])["action"] == "draft_blocked"


def test_unknown_policy_refs_are_refused(desk):
    with pytest.raises(DeskError, match="Unknown policy refs"):
        desk.save_draft("T-5114", "Hi Aisha, thanks for asking.", ["handbook/deposit-methods#1"], "")


def test_newer_draft_supersedes_older_pending_one(desk):
    first, _ = desk.save_draft("T-5114", "Hi Aisha, let me check that for you.", [], "")
    second, _ = desk.save_draft("T-5114", "Hi Aisha, I'm checking which methods are available in Malaysia.", [], "")
    statuses = {d.draft_id: d.status for d in desk.workspace.drafts()}
    assert statuses == {first.draft_id: DraftStatus.REJECTED, second.draft_id: DraftStatus.PENDING_REVIEW}


@pytest.mark.parametrize(
    ("ticket_id", "amount", "status"),
    [
        ("T-5101", 50, RefundStatus.WITHIN_AGENT_LIMIT),
        ("T-5101", 100, RefundStatus.WITHIN_AGENT_LIMIT),
        ("T-5101", 100.01, RefundStatus.AWAITING_APPROVAL),
        ("T-5106", 250, RefundStatus.AWAITING_APPROVAL),
        ("T-5104", 5000, RefundStatus.AWAITING_APPROVAL),
        ("T-5104", 20, RefundStatus.AWAITING_APPROVAL),  # small, but the ticket carries a prompt injection
    ],
)
def test_refund_limits(desk, ticket_id, amount, status):
    assert desk.request_refund(ticket_id, amount, "game round failed").status is status


def test_one_live_refund_request_per_ticket(desk):
    desk.request_refund("T-5106", 250, "Live game froze mid-round")
    with pytest.raises(DeskError, match="already exists"):
        desk.request_refund("T-5106", 250, "again")


def test_reply_may_mention_a_refund_only_once_approved(desk):
    desk.escalate("T-5106", Team.TEAM_LEAD, "$250 refund request, above agent limit")
    refund = desk.request_refund("T-5106", 250, "Live game froze mid-round; verify the round log")
    body = "Hi Hannah, we've refunded the $250 bet to your account."
    draft, _ = desk.save_draft("T-5106", body, ["handbook/refunds#2"], "")
    assert draft is None
    desk.decide_refund(refund.refund_id, "Mai", approve=True)
    draft, _ = desk.save_draft("T-5106", body, ["handbook/refunds#2"], "Issue the refund before sending")
    assert draft is not None


def test_approval_sends_updates_ticket_and_closes_duplicate(desk):
    desk.escalate("T-5102", Team.PAYMENTS, "Pending since 21 Sep")
    draft, _ = desk.save_draft("T-5102", WITHDRAWAL_REPLY, ["handbook/withdrawals#3"], "")
    desk.approve_draft(draft.draft_id, "Arjun")

    tickets = {t.ticket_id: t for t in desk.workspace.tickets()}
    assert tickets["T-5102"].status == "replied"
    assert tickets["T-5102"].agent_reply == WITHDRAWAL_REPLY
    assert tickets["T-5102"].first_response_at is not None
    assert (tickets["T-5110"].status, tickets["T-5110"].resolution) == ("closed", "merged into T-5102")
    sent = [json.loads(line) for line in (desk.workspace.root / "outbox.jsonl").read_text().splitlines()]
    assert [(s["ticket_id"], s["approved_by"]) for s in sent] == [("T-5102", "Arjun")]


def test_a_reviewers_edit_is_checked_too(desk):
    draft, _ = desk.save_draft("T-5101", "Hi Marcus, I'm checking the status of your withdrawal now.", [], "")
    with pytest.raises(DeskError, match="superseded_policy"):
        desk.approve_draft(draft.draft_id, "Linh", body="Hi Marcus, it can take up to 5 days to arrive.")
    assert desk.workspace.drafts()[0].status is DraftStatus.PENDING_REVIEW


def test_nothing_happens_on_a_closed_ticket(desk):
    with pytest.raises(DeskError, match="not open"):
        desk.escalate("T-5001", Team.TEAM_LEAD, "x")
    with pytest.raises(DeskError, match="No ticket"):
        desk.triage("T-9999")
