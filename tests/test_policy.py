from support_desk import policy as p
from tests.conftest import DATA


def test_limits_match_the_handbook_text():
    # The constants drive refund and escalation decisions. If the handbook changes, this fails
    # instead of the desk quietly applying the old numbers.
    handbook = (DATA / p.HANDBOOK_FILE).read_text(encoding="utf-8")
    assert f"Agents can issue refunds up to USD {p.AGENT_REFUND_LIMIT_USD}." in handbook
    assert f"Refunds above USD {p.AGENT_REFUND_LIMIT_USD} need team lead approval" in handbook
    assert "First reply target: 1 hour from ticket creation." in handbook
    assert "still `pending` after 24 hours, or `processing` after 3 business days" in handbook


def test_clauses_are_parsed_with_stable_refs(policy):
    assert policy.clause("handbook/refunds#2").text == (
        "Refunds above USD 100 need team lead approval before they are issued."
    )
    assert "Table games count 10%" in policy.clause("bonus-terms/welcome-bonus#4").text
    assert policy.clause("handbook/verification-kyc#2").text.startswith("Never share the review reason")


def test_only_current_policy_is_loaded(policy):
    sources = {s.source for s in policy.sections}
    assert sources == {"support-handbook-v2.md", "bonus-terms.md"}
    everything = " ".join(s.text for s in policy.sections)
    assert "USD 200" not in everything  # v1 refund limit / unpublished reload bonus
    assert "48 hours" not in everything


def test_search_maps_customer_words_to_policy_words(policy):
    assert policy.search("can I play blackjack with my bonus")[0].title == "Welcome bonus"
    assert policy.search("refund limit")[0].title == "Refunds"
    assert policy.search("how long does a withdrawal take")[0].title == "Withdrawals"


def test_search_returns_nothing_rather_than_something_irrelevant(policy):
    assert policy.search("lost phone 2FA") == []
    assert policy.search("reload") == []
