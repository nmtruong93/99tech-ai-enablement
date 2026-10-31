import re

from support_desk import policy as p
from support_desk.config import PROJECT_ROOT


def test_limits_match_the_handbook_text(data_dir):
    # The constants drive refund and escalation decisions. If the handbook changes, this fails
    # instead of the desk quietly applying the old numbers.
    handbook = (data_dir / p.HANDBOOK_FILE).read_text(encoding="utf-8")
    limit = p.AGENT_REFUND_LIMIT_USD
    assert f"Agents can issue refunds up to USD {limit}." in handbook
    assert f"Refunds above USD {limit} need team lead approval" in handbook
    hours = p.FIRST_REPLY_TARGET.total_seconds() / 3600
    assert f"First reply target: {hours:g} hour{'s' if hours != 1 else ''} from ticket creation." in handbook


def test_clauses_are_parsed_with_stable_refs(policy):
    assert (
        policy.clause("handbook/refunds#2").text
        == "Refunds above USD 100 need team lead approval before they are issued."
    )
    assert "Table games count 10%" in policy.clause("bonus-terms/welcome-bonus#4").text
    assert policy.clause("handbook/verification-kyc#2").text.startswith("Never share the review reason")


def test_only_current_policy_is_loaded(policy):
    assert {s.source for s in policy.sections} == {"support-handbook-v2.md", "bonus-terms.md"}
    assert "USD 200" not in policy.text  # the v1.3 refund limit, and the unpublished reload bonus
    assert "48 hours" not in policy.text


def test_every_policy_ref_in_the_code_exists(policy):
    # Refs in tool output get copied into save_draft's policy_refs, which rejects unknown ones.
    code = "\n".join(f.read_text(encoding="utf-8") for f in (PROJECT_ROOT / "src" / "support_desk").glob("*.py"))
    for ref in set(re.findall(r"(?:handbook|bonus-terms)/[a-z-]+#\d+(?:-\d+|, #\d+)?", code)):
        assert policy.clause(ref), ref
