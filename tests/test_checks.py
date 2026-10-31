"""The reply checks, starting with a backtest on the replies the team already sent."""

import pytest

from support_desk.checks import ReplyContext, Severity, check_reply


def _check(body, ticket, customers, policy, **kw):
    return check_reply(body, ReplyContext(ticket, customers.get(ticket.customer_id), customers.values(), policy, **kw))


def _codes(findings, severity=None):
    return {f.code for f in findings if severity is None or f.severity is severity}


# My own read of each sent reply against handbook v2 and the Bonus Terms, done before
# writing the checks. (expected blocking codes, expected warning codes)
SENT_REPLIES = {
    "T-5001": (
        {"superseded_policy", "refund_not_approved"},
        {"encourages_play", "unsourced_amount"},
    ),  # $180, "up to $200"
    "T-5002": ({"superseded_policy"}, set()),  # "3-5 days"
    "T-5003": (set(), set()),  # correct
    "T-5004": ({"kyc_reason_disclosed"}, set()),  # told the customer the selfie didn't match
    "T-5005": (set(), set()),  # correct self-exclusion answer
    "T-5006": ({"superseded_policy"}, set()),  # "48 hours"
    "T-5007": ({"refund_not_approved"}, {"unsourced_amount"}),  # $300 goodwill, no recorded approval
    "T-5008": (set(), set()),  # Vietnamese, correct timeline
    "T-5009": (set(), {"unverified_promise"}),  # "should arrive soon"
    "T-5010": (set(), {"unsourced_amount"}),  # "$10,000 per day" exists in no document
    "T-5011": ({"superseded_policy"}, set()),  # "any game"
    "T-5012": (set(), set()),
    "T-5013": ({"superseded_policy"}, set()),  # "3-5 days"
    "T-5014": (set(), set()),  # unverifiable from the export, but nothing contradicts it
    "T-5015": ({"superseded_policy"}, set()),  # "up to 5 days"
}


@pytest.mark.parametrize("ticket_id", sorted(SENT_REPLIES))
def test_backtest_on_replies_already_sent(ticket_id, tickets, customers, policy):
    ticket = tickets[ticket_id]
    findings = _check(ticket.agent_reply, ticket, customers, policy)
    blocks, warns = SENT_REPLIES[ticket_id]
    assert _codes(findings, Severity.BLOCK) == blocks
    assert _codes(findings, Severity.WARN) == warns


def test_backtest_totals(tickets, customers, policy):
    blocked = [
        t
        for t in tickets.values()
        if t.agent_reply and _codes(_check(t.agent_reply, t, customers, policy), Severity.BLOCK)
    ]
    assert len(blocked) == 8  # of 15 sent replies


@pytest.mark.parametrize(
    "body",
    [
        "If the deposit failed, your bank will reverse the charge within 3-5 business days.",
        "Your $200 withdrawal was processed and should reach you in 1-3 business days.",
        "Only slot games count fully; table games count 10% and live casino doesn't count.",
    ],
)
def test_correct_statements_are_not_mistaken_for_old_policy(body, tickets, customers, policy):
    ticket = tickets["T-5101"]
    assert "superseded_policy" not in _codes(_check(body, ticket, customers, policy))


def test_kyc_wording_is_only_restricted_for_customers_under_review(tickets, customers, policy):
    body = "Your selfie doesn't match the photo on your ID."
    rizal = tickets["T-5103"]  # under_review
    assert "kyc_reason_disclosed" in _codes(_check(body, rizal, customers, policy), Severity.BLOCK)
    tomasz = tickets["T-5104"]  # verified
    assert "kyc_reason_disclosed" not in _codes(_check(body, tomasz, customers, policy))


def test_refund_language_needs_a_refund_on_record(tickets, customers, policy):
    ticket = tickets["T-5106"]
    body = "Hi Hannah, we've refunded the $250 to your account."
    assert "refund_not_approved" in _codes(_check(body, ticket, customers, policy), Severity.BLOCK)
    assert "refund_not_approved" not in _codes(_check(body, ticket, customers, policy, approved_refund_usd=250))


def test_another_customers_details_are_blocked(tickets, customers, policy):
    body = "Hi Priya, I can't share anything about rahul.nair@example.com."
    findings = _check(body, tickets["T-5108"], customers, policy)
    assert "other_customer_data" in _codes(findings, Severity.BLOCK)


def test_reply_must_be_in_the_customers_language(tickets, customers, policy):
    ticket = tickets["T-5107"]  # Vietnamese
    english = "Hi, we're checking your deposit."
    vietnamese = "Chào chị Hà, chúng tôi đang kiểm tra khoản nạp tiền của chị."
    assert "wrong_language" in _codes(_check(english, ticket, customers, policy), Severity.BLOCK)
    assert "wrong_language" not in _codes(_check(vietnamese, ticket, customers, policy))


def test_encouraging_play_is_blocked_when_harm_is_flagged(tickets, customers, policy):
    ticket = tickets["T-5105"]
    body = "Hi Ethan, we've passed this to our team. Good luck!"
    assert "encourages_play" in _codes(_check(body, ticket, customers, policy, harm_sensitive=True), Severity.BLOCK)
    assert "encourages_play" in _codes(_check(body, ticket, customers, policy), Severity.WARN)


def test_unpublished_promotion_terms_are_blocked(tickets, customers, policy):
    body = "Hi Wei, the reload bonus is 50% on deposits up to $200, once per week."
    findings = _check(body, tickets["T-5115"], customers, policy)
    assert "unpublished_terms" in _codes(findings, Severity.BLOCK)


def test_vietnamese_thousands_separators_are_read_as_one_amount(tickets, customers, policy):
    ticket = tickets["T-5107"]  # "Tôi đã nạp 500.000 đồng"
    body = "Chào chị Hà, chúng tôi đã nhận được yêu cầu về khoản nạp 500.000 đồng của chị."
    assert "unsourced_amount" not in _codes(_check(body, ticket, customers, policy))


def test_placeholders_and_empty_replies_are_blocked(tickets, customers, policy):
    ticket = tickets["T-5114"]
    assert _codes(_check("Hi [NAME], thanks.", ticket, customers, policy), Severity.BLOCK) == {"placeholder"}
    assert _codes(_check("   ", ticket, customers, policy), Severity.BLOCK) == {"empty"}


def test_quoting_old_guidance_to_correct_it_is_a_warning_not_a_block(tickets, customers, policy):
    # From the real run: Claude's first T-5111 draft was blocked for exactly this sentence.
    ticket = tickets["T-5111"]
    correction = "Our earlier reply said you could use your bonus on any game. That was wrong."
    findings = _check(correction, ticket, customers, policy)
    assert "superseded_policy" in _codes(findings, Severity.WARN)
    assert "superseded_policy" not in _codes(findings, Severity.BLOCK)


def test_a_refund_promise_in_vietnamese_is_blocked(tickets, customers, policy):
    ticket = tickets["T-5107"]
    body = "Chào quý khách, chúng tôi sẽ hoàn tiền 1.500.000 đồng cho quý khách ngay hôm nay."
    findings = _check(body, ticket, customers, policy)
    assert "refund_not_approved" in _codes(findings, Severity.BLOCK)
    assert not any("e+06" in f.message for f in findings)


@pytest.mark.parametrize(
    ("ticket_id", "body", "harm"),
    [
        ("T-5103", "To finish the review we may ask you to upload a clear photo of your passport.", False),
        ("T-5105", "We have stopped all promotions and bonus offers to your account.", True),
    ],
)
def test_ordinary_wording_is_not_blocked(ticket_id, body, harm, tickets, customers, policy):
    assert not _codes(_check(body, tickets[ticket_id], customers, policy, harm_sensitive=harm), Severity.BLOCK)
