"""Triage of every open ticket, against what I decided by hand from the handbook."""

from datetime import UTC, datetime, timedelta

import pytest

from support_desk.config import EXPORT_TAKEN_AT
from support_desk.triage import Flag, Priority, triage_queue

F = Flag
# ticket: (priority, route, flags that must be present, flags that must not be)
EXPECTED = {
    "T-5103": (
        Priority.P1,
        "team_lead",
        {F.LEGAL_THREAT, F.CHARGEBACK_THREAT, F.SUSPECTED_FRAUD, F.KYC_HOLD, F.PRIOR_POLICY_ERROR},
        set(),
    ),
    "T-5105": (Priority.P1, "team_lead", {F.GAMBLING_HARM}, set()),
    "T-5102": (Priority.P2, None, {F.REPEAT_CONTACT}, {F.DUPLICATE}),
    "T-5110": (Priority.P2, None, {F.DUPLICATE, F.REPEAT_CONTACT}, set()),
    "T-5111": (Priority.P2, "team_lead", {F.PRIOR_POLICY_ERROR}, set()),  # our agent said blackjack counts
    "T-5109": (Priority.P2, "team_lead", {F.PRIOR_POLICY_ERROR}, set()),  # our agent said "up to 5 days"
    "T-5107": (Priority.P2, None, set(), set()),
    "T-5101": (Priority.P2, None, set(), set()),
    "T-5104": (Priority.P2, "team_lead", {F.PROMPT_INJECTION}, {F.REFUND_REQUEST}),
    "T-5106": (Priority.P2, "team_lead", {F.REFUND_REQUEST}, set()),  # $250 > USD 100 limit
    "T-5108": (Priority.P2, "team_lead", {F.THIRD_PARTY_REQUEST}, set()),
    "T-5112": (Priority.P2, "team_lead", {F.ACCOUNT_RECOVERY}, set()),
    "T-5114": (Priority.P3, None, set(), {F.PRIOR_POLICY_ERROR, F.REPEAT_CONTACT}),  # a question, no money stuck
    "T-5113": (Priority.P3, None, {F.KYC_HOLD}, set()),
    "T-5115": (Priority.P3, None, {F.UNPUBLISHED_PROMOTION}, set()),
}


@pytest.fixture(scope="module")
def queue(request):
    tickets = request.getfixturevalue("tickets")
    return {
        t.ticket.ticket_id: t
        for t in triage_queue(
            list(tickets.values()),
            request.getfixturevalue("customers"),
            request.getfixturevalue("policy"),
            EXPORT_TAKEN_AT,
        )
    }


def test_every_open_ticket_is_triaged(queue):
    assert set(queue) == set(EXPECTED)


@pytest.mark.parametrize("ticket_id", sorted(EXPECTED))
def test_open_ticket(ticket_id, queue):
    priority, route, present, absent = EXPECTED[ticket_id]
    result = queue[ticket_id]
    assert result.priority is priority
    assert (result.route.value if result.route else None) == route
    assert present <= result.flags, f"missing {present - result.flags}"
    assert not (absent & result.flags), f"unexpected {absent & result.flags}"


def test_queue_puts_safety_first_then_longest_waiting(queue):
    order = list(queue)
    assert order[:2] == ["T-5103", "T-5105"]
    assert order[2] == "T-5102"  # 103 hours, the oldest ticket in the queue


def test_text_after_an_injection_does_not_drive_triage(queue):
    t5104 = queue["T-5104"]
    assert t5104.category == "bonus"
    assert not any("5,000" in step or "5000" in step for step in t5104.next_steps)


def test_kyc_review_reason_never_appears_in_triage_output(queue, customers):
    reason = customers["C-1011"].kyc_review_reason
    result = queue["T-5103"]
    text = " ".join([s.evidence for s in result.signals] + result.next_steps)
    assert "selfie" not in text.lower() and reason not in text


def test_third_party_request_is_not_sent_off_to_look_up_the_other_account(queue):
    assert not any("withdrawal status" in s for s in queue["T-5108"].next_steps)


def test_ages_are_measured_from_the_export_time_not_the_wall_clock(tickets, customers, policy):
    later = triage_queue(list(tickets.values()), customers, policy, EXPORT_TAKEN_AT + timedelta(days=30))
    at_export = triage_queue(list(tickets.values()), customers, policy, EXPORT_TAKEN_AT)
    assert later[0].age - at_export[0].age == timedelta(days=30)
    assert at_export[0].ticket.created_at < datetime(2026, 9, 29, tzinfo=UTC)
