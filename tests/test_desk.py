"""Actions on the data: escalations, refund requests, drafts, and the human approval step."""

import hashlib
import json

import pytest

from support_desk.desk import DeskError
from support_desk.models import DraftStatus, RefundStatus, Team, TicketStatus

WITHDRAWAL_REPLY = (
    "Hi Somchai, I'm sorry your email went unanswered. I've passed your $400 withdrawal to our Payments team, "
    "and they will update you."
)
CHECKING = "Hi Marcus, your withdrawal is [WITHDRAWAL STATUS]. [AGENT NAME], 99Tech Support"


@pytest.mark.parametrize(
    ("ticket_id", "amount", "status"),
    [
        ("T-5101", 100, RefundStatus.WITHIN_AGENT_LIMIT),
        ("T-5101", 100.01, RefundStatus.AWAITING_APPROVAL),
        ("T-5104", 20, RefundStatus.AWAITING_APPROVAL),  # small, but the ticket carries a prompt injection
        ("T-5113", 20, RefundStatus.AWAITING_APPROVAL),  # small, but the customer's KYC isn't complete
        ("T-5111", 20, RefundStatus.AWAITING_APPROVAL),  # small, but it's about our own earlier mistake
    ],
)
def test_refund_limits(desk, ticket_id, amount, status):
    assert desk.request_refund(ticket_id, amount, "game round failed").status is status


def test_the_agent_limit_is_per_customer(desk):
    # Two refunds of $60 for one customer, on two unrelated tickets, add up to more than USD 100.
    tickets = desk.workspace.tickets()
    second = tickets[0].model_copy(
        update={
            "ticket_id": "T-9001",
            "customer_id": "C-1003",
            "subject": "Fee",
            "message": "I was charged a fee twice.",
            "status": TicketStatus.OPEN,
            "agent_reply": None,
        }
    )
    desk.workspace.root.mkdir(parents=True)
    payload = [t.model_dump(mode="json") for t in [*tickets, second]]
    (desk.workspace.root / "tickets.json").write_text(json.dumps(payload), encoding="utf-8")
    assert desk.request_refund("T-5101", 60, "fee").status is RefundStatus.WITHIN_AGENT_LIMIT
    refund = desk.request_refund("T-9001", 60, "fee")
    assert refund.status is RefundStatus.AWAITING_APPROVAL
    assert "$120" in refund.why


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), 0.001, -5])
def test_nonsense_amounts_are_refused(desk, amount):
    with pytest.raises(DeskError, match="positive"):
        desk.request_refund("T-5101", amount, "x")


def test_one_live_refund_per_ticket_whatever_the_id_spelling(desk):
    desk.request_refund("t-5101", 50, "fee")
    with pytest.raises(DeskError, match="already exists"):
        desk.request_refund(" T-5101 ", 50, "fee")


def test_a_refund_on_a_duplicate_is_refused(desk):
    with pytest.raises(DeskError, match="duplicates T-5102"):
        desk.request_refund("T-5110", 90, "fee")


def test_escalation_is_idempotent(desk):
    first = desk.escalate("T-5102", Team.PAYMENTS, "Pending since 21 Sep")
    assert desk.escalate("T-5102", Team.PAYMENTS, "Pending since 21 Sep") == first
    assert desk.escalated_to("T-5102") == [Team.PAYMENTS]


def test_team_lead_tickets_must_be_escalated_before_drafting(desk):
    body = "Hi Ethan, thank you for telling us. Our team lead is closing your account now."
    with pytest.raises(DeskError, match="escalate"):
        desk.save_draft("T-5105", body, [], "")
    desk.escalate("T-5105", Team.TEAM_LEAD, "Gambling harm, asks for permanent closure")
    draft, _ = desk.save_draft("T-5105", body, ["handbook/escalation#3"], "Start self-exclusion before sending")
    assert draft is not None


def test_a_duplicate_is_answered_on_the_first_ticket(desk):
    with pytest.raises(DeskError, match="T-5102"):
        desk.save_draft("T-5110", WITHDRAWAL_REPLY, [], "")


def test_a_blocked_draft_is_not_saved_but_is_audited(desk):
    draft, findings = desk.save_draft("T-5101", "Hi Marcus, withdrawals take 3-5 days.", [], "")
    assert (draft, [f.code for f in findings]) == (None, ["superseded_policy"])
    assert desk.workspace.drafts() == []
    audit = (desk.workspace.root / "audit.jsonl").read_text().splitlines()
    assert json.loads(audit[-1])["action"] == "draft_blocked"


def test_unknown_policy_refs_are_refused(desk):
    with pytest.raises(DeskError, match="Unknown policy refs"):
        desk.save_draft("T-5114", "Hi Aisha, thanks for asking.", ["handbook/deposit-methods#1"], "")


def test_a_newer_draft_supersedes_the_pending_one(desk):
    first, _ = desk.save_draft("T-5114", "Hi Aisha, card deposits are open in Malaysia.", [], "")
    second, _ = desk.save_draft("T-5114", "Hi Aisha, card and bank transfer are open in Malaysia.", [], "")
    statuses = {d.draft_id: d.status for d in desk.workspace.drafts()}
    assert statuses == {first.draft_id: DraftStatus.SUPERSEDED, second.draft_id: DraftStatus.PENDING_REVIEW}


def test_a_reply_may_mention_a_refund_only_once_approved(desk):
    desk.escalate("T-5106", Team.TEAM_LEAD, "$250 refund request, above agent limit")
    refund = desk.request_refund("T-5106", 250, "Live game froze mid-round; verify the round log")
    body = "Hi Hannah, we've refunded the $250 bet to your account."
    assert desk.save_draft("T-5106", body, ["handbook/refunds#2"], "")[0] is None
    desk.decide_refund(refund.refund_id, "Mai", approve=True)
    assert desk.save_draft("T-5106", body, ["handbook/refunds#2"], "Issue the refund first")[0] is not None


def test_a_declined_refund_stops_a_saved_draft_from_going_out(desk):
    refund = desk.request_refund("T-5101", 20, "fee charged twice")
    draft, _ = desk.save_draft("T-5101", "Hi Marcus, I've refunded the $20 fee to your account.", [], "")
    desk.decide_refund(refund.refund_id, "Mai", approve=False)
    with pytest.raises(DeskError, match="refund_not_approved"):
        desk.approve_draft(draft.draft_id, "Mai")


def test_a_refund_is_decided_once(desk):
    refund = desk.request_refund("T-5106", 250, "Live game froze mid-round")
    desk.decide_refund(refund.refund_id, "Mai", approve=False)
    with pytest.raises(DeskError, match="already"):
        desk.decide_refund(refund.refund_id, "Mai", approve=True)


def test_approval_sends_updates_the_ticket_and_closes_the_duplicate(desk, data_dir):
    export = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in data_dir.iterdir()}
    desk.escalate("T-5102", Team.PAYMENTS, "Pending since 21 Sep")
    draft, _ = desk.save_draft("T-5102", WITHDRAWAL_REPLY, ["handbook/withdrawals#3"], "")
    desk.approve_draft(draft.draft_id, "Arjun")

    tickets = {t.ticket_id: t for t in desk.workspace.tickets()}
    assert (tickets["T-5102"].status, tickets["T-5102"].agent_reply) == (TicketStatus.REPLIED, WITHDRAWAL_REPLY)
    assert tickets["T-5102"].first_response_at is not None
    assert (tickets["T-5110"].status, tickets["T-5110"].merged_into) == (TicketStatus.CLOSED, "T-5102")
    sent = [json.loads(line) for line in (desk.workspace.root / "outbox.jsonl").read_text().splitlines()]
    assert [(s["ticket_id"], s["approved_by"]) for s in sent] == [("T-5102", "Arjun")]
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in data_dir.iterdir()} == export


def test_a_placeholder_must_be_filled_before_sending(desk):
    draft, _ = desk.save_draft("T-5101", CHECKING, [], "Fill in the status from the payments dashboard")
    assert any("[WITHDRAWAL STATUS]" in w for w in draft.warnings)
    with pytest.raises(DeskError, match="placeholder"):
        desk.approve_draft(draft.draft_id, "Linh")
    approved = desk.approve_draft(draft.draft_id, "Linh", body=CHECKING.replace("[WITHDRAWAL STATUS]", "on its way"))
    assert approved.body.endswith("Linh, 99Tech Support")


def test_a_reviewers_edit_is_checked_too(desk):
    draft, _ = desk.save_draft("T-5101", CHECKING, [], "")
    with pytest.raises(DeskError, match="superseded_policy"):
        desk.approve_draft(draft.draft_id, "Linh", body="Hi Marcus, it can take up to 5 days to arrive.")
    assert desk.workspace.drafts()[0].status is DraftStatus.PENDING_REVIEW


def test_a_draft_is_approved_once(desk):
    draft, _ = desk.save_draft("T-5101", "Hi Marcus, your withdrawal is on its way.", [], "")
    desk.approve_draft(draft.draft_id, "Linh")
    with pytest.raises(DeskError, match="not pending review"):
        desk.approve_draft(draft.draft_id, "Linh")
    assert len((desk.workspace.root / "outbox.jsonl").read_text().splitlines()) == 1


def test_a_rejected_draft_is_never_sent(desk):
    draft, _ = desk.save_draft("T-5101", "Hi Marcus, your withdrawal is on its way.", [], "")
    desk.reject_draft(draft.draft_id, "Mai", "Check the status first")
    with pytest.raises(DeskError, match="not pending review"):
        desk.approve_draft(draft.draft_id, "Mai")
    assert not (desk.workspace.root / "outbox.jsonl").exists()


def test_closed_tickets_are_read_only(desk):
    with pytest.raises(DeskError, match="not open"):
        desk.escalate("T-5001", Team.TEAM_LEAD, "x")
