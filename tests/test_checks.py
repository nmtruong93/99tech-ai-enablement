"""The reply checks: a backtest on the replies the team already sent, then what must be blocked and
what must get through."""

import pytest

from support_desk.checks import Severity

# My own read of each sent reply against handbook v2 and the Bonus Terms, done before writing
# the checks. (blocking codes, warning codes)
SENT_REPLIES = {
    "T-5001": ({"superseded_policy", "refund_not_approved"}, {"encourages_play", "unsourced_amount"}),  # "up to $200"
    "T-5002": ({"superseded_policy"}, set()),  # "3-5 days"
    "T-5003": (set(), set()),
    "T-5004": ({"kyc_reason_disclosed"}, set()),  # told the customer the selfie didn't match
    "T-5005": (set(), set()),  # self-exclusion, handled correctly
    "T-5006": ({"superseded_policy"}, set()),  # "48 hours"
    "T-5007": ({"refund_not_approved"}, {"unsourced_amount"}),  # $300 goodwill, no recorded approval
    "T-5008": (set(), set()),  # Vietnamese, correct timeline
    "T-5009": (set(), {"unverified_promise"}),  # "should arrive soon"
    "T-5010": (set(), {"unsourced_amount"}),  # "$10,000 per day" is in no document
    "T-5011": ({"superseded_policy"}, set()),  # "any game"
    "T-5012": (set(), set()),
    "T-5013": ({"superseded_policy"}, set()),  # "3-5 days"
    "T-5014": (set(), set()),  # can't be verified from the export, but nothing contradicts it
    "T-5015": ({"superseded_policy"}, set()),  # "up to 5 days"
}


def test_the_backtest_covers_every_sent_reply(tickets):
    assert set(SENT_REPLIES) == {t.ticket_id for t in tickets.values() if t.agent_reply}


@pytest.mark.parametrize("ticket_id", sorted(SENT_REPLIES))
def test_backtest_on_replies_already_sent(ticket_id, tickets, codes):
    reply = tickets[ticket_id].agent_reply
    assert (codes(reply, ticket_id), codes(reply, ticket_id, Severity.WARN)) == SENT_REPLIES[ticket_id]


MUST_BLOCK = [
    # Old guidance
    ("T-5101", "Hi Marcus, withdrawals take 3-5 days.", "superseded_policy", {}),
    ("T-5101", "Hi Marcus, it can take up to 5 days to arrive.", "superseded_policy", {}),
    # Talk of money back with no approval, or more than was approved
    ("T-5106", "Hi Hannah, your $250 has been refunded.", "refund_not_approved", {}),
    ("T-5106", "I've processed a $250 refund for you.", "refund_not_approved", {}),
    ("T-5106", "You'll get your $250 back.", "refund_not_approved", {}),
    ("T-5106", "We'll put $250 back in your balance.", "refund_not_approved", {}),
    ("T-5106", "A credit of $250 is on its way.", "refund_not_approved", {}),
    ("T-5106", "I've gone ahead and refunded your bet.", "refund_not_approved", {}),
    ("T-5106", "Your money will be returned to your account.", "refund_not_approved", {}),
    ("T-5106", "Consider it refunded.", "refund_not_approved", {}),
    ("T-5106", "I’ve refunded your $250.", "refund_not_approved", {}),  # curly apostrophe, as phones type it
    ("T-5106", "I've refunded your $250 bet to your balance.", "refund_not_approved", {"approved_refund_usd": 1}),
    (
        "T-5107",
        "Chào quý khách, chúng tôi sẽ hoàn tiền 1.500.000 đồng cho quý khách hôm nay.",
        "refund_not_approved",
        {},
    ),
    # What a KYC review found, for a customer under review
    ("T-5103", "Your selfie doesn't match the photo on your ID.", "kyc_reason_disclosed", {}),
    ("T-5103", "The photo you sent didn't line up with your ID.", "kyc_reason_disclosed", {}),
    ("T-5103", "We think someone else may be using your account.", "kyc_reason_disclosed", {}),
    ("T-5103", "There was a discrepancy in your documents.", "kyc_reason_disclosed", {}),
    # Anything about another customer's account
    ("T-5108", "Rahul has an account with us and withdrew $600 this month.", "other_customer_data", {}),
    ("T-5108", "I checked and his account shows two withdrawals.", "other_customer_data", {}),
    ("T-5108", "We can't share anything about rahul.nair@example.com.", "other_customer_data", {}),
    ("T-5108", "Customer C-1023 is not something I can discuss.", "other_customer_data", {}),
    # Unpublished promotion terms
    ("T-5115", "Hi Wei, the reload bonus is 50% on deposits up to $200, once per week.", "unpublished_terms", {}),
    ("T-5115", "The reload bonus will be fifty percent, every week.", "unpublished_terms", {}),
    ("T-5115", "You'll be eligible for the reload bonus from 1 October.", "unpublished_terms", {}),
    # Inviting a customer with gambling-harm signals back to play
    ("T-5105", "Hi Ethan, we've passed this to our team. Good luck!", "encourages_play", {"harm_sensitive": True}),
    ("T-5105", "There's a free spins offer when you're ready.", "encourages_play", {"harm_sensitive": True}),
    ("T-5105", "We'll welcome you back whenever you're ready.", "encourages_play", {"harm_sensitive": True}),
    ("T-5105", "Your bonus is still waiting for you.", "encourages_play", {"harm_sensitive": True}),
    # Language, placeholders, empty replies
    ("T-5107", "Hi, we're checking your deposit.", "wrong_language", {}),
    ("T-5114", "Hi [NAME], thanks.", "placeholder", {"sending": True}),
    ("T-5114", "   ", "empty", {}),
]


@pytest.mark.parametrize(("ticket_id", "body", "code", "context"), MUST_BLOCK)
def test_must_block(ticket_id, body, code, context, codes):
    assert code in codes(body, ticket_id, **context)


MUST_PASS = [
    # Current policy that looks like old guidance
    ("T-5101", "Your $200 withdrawal was processed and should reach you in 1-3 business days.", {}),
    ("T-5101", "If the deposit failed, your bank will reverse the charge within 3-5 business days.", {}),
    ("T-5104", "Not all games count equally: table games count 10% and live casino doesn't count.", {}),
    ("T-5104", "The bonus applies to all games, but only slots count fully towards wagering.", {}),
    ("T-5102", "Your withdrawal has now been pending for more than 48 hours, so I've escalated it.", {}),
    ("T-5101", "Your withdrawal from 2 days ago is being processed.", {}),
    (
        "T-5114",
        "If the deposit failed, your bank will get the money back within 3-5 business days.",
        {"category": "deposit"},
    ),
    (
        "T-5107",
        "Nếu giao dịch không thành công, nhà cung cấp sẽ trả lại tiền trong 3–5 ngày làm việc.",
        {"category": "deposit"},
    ),
    ("T-5114", "You can read more in our [Help Centre](https://help.example.com).", {}),
    # Talking about a refund request, not promising the outcome
    ("T-5106", "A senior colleague will review your refund request and we'll update you.", {}),
    ("T-5106", "We can't promise a refund, but the round will be checked.", {}),
    ("T-5106", "If the round shows a fault, the team lead will decide on a refund.", {}),
    ("T-5106", "Hi Hannah, we've refunded the $250 to your account.", {"approved_refund_usd": 250}),
    # From the second real run: both were blocked as refund talk.
    ("T-5112", "I'm sorry you've lost your phone, and I understand you want to get back into your account.", {}),
    ("T-5114", "I'm checking which deposit methods are available, and I'll get back to you shortly.", {}),
    # Ordinary wording
    ("T-5103", "To finish the review we may ask you to upload a clear photo of your passport.", {}),
    ("T-5104", "Your selfie doesn't match the photo on your ID.", {}),  # verified customer: nothing restricted
    ("T-5105", "We have stopped all promotions and bonus offers to your account.", {"harm_sensitive": True}),
    ("T-5108", "We can't share any information about another person's account, including whether Rahul has one.", {}),
    ("T-5107", "Chào chị Hà, chúng tôi đang kiểm tra khoản nạp tiền của chị.", {}),
    ("T-5114", "Hi [NAME], thanks.", {}),  # a placeholder in a draft is for the reviewer to fill in
]


@pytest.mark.parametrize(("ticket_id", "body", "context"), MUST_PASS)
def test_must_pass(ticket_id, body, context, codes):
    assert codes(body, ticket_id, **context) == set()


def test_quoting_old_guidance_to_correct_it_is_a_warning(codes):
    # From the real run: Claude's first T-5111 draft was blocked for exactly this sentence.
    correction = "Our earlier reply said you could use your bonus on any game. That was wrong."
    assert "superseded_policy" not in codes(correction, "T-5111")
    assert "superseded_policy" in codes(correction, "T-5111", Severity.WARN)


def test_unaccented_vietnamese_only_warns(tickets, codes):
    ticket = tickets["T-5107"].model_copy(update={"message": "toi nap tien roi nhung so du van bang 0"})
    reply = "Chào bạn, chúng tôi đang kiểm tra khoản nạp tiền của bạn."
    assert codes(reply, ticket, Severity.WARN) == {"wrong_language"}


def test_encouraging_play_only_warns_without_harm_signals(codes):
    assert codes("Hi Ethan, good luck!", "T-5105", Severity.WARN) == {"encourages_play"}


def test_amounts_keep_their_currency(codes):
    # "500.000 đồng" is in the ticket; "1.500.000 đồng" isn't, and is shown as written, not as 1.5e+06.
    assert codes("Chào chị Hà, khoản nạp 500.000 đồng của chị.", "T-5107", None) == set()
    assert "unsourced_amount" in codes("Chào chị Hà, khoản 1.500.000 đồng của chị.", "T-5107", Severity.WARN)
