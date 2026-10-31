"""The MCP surface, exercised through a real MCP client session rather than direct calls."""

import json

import pytest
from mcp import Client

from support_desk.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def server(desk):
    return build_server(desk)


async def call(server, tool, **arguments):
    async with Client(server) as client:
        return await client.call_tool(tool, arguments)


async def test_tools_and_prompt_on_offer(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        prompts = [p.name for p in (await client.list_prompts()).prompts]
    # No tool sends a reply or moves money.
    assert set(tools) == {"get_policy", "get_queue", "get_ticket", "escalate", "request_refund", "save_draft"}
    assert all(tools[name].annotations.read_only_hint for name in ("get_policy", "get_queue", "get_ticket"))
    assert tools["escalate"].input_schema["properties"]["team"]["enum"] == ["team_lead", "payments"]
    assert prompts == ["work_the_queue"]


async def test_get_policy_returns_citable_clauses(server):
    result = await call(server, "get_policy")
    refs = {c["ref"] for s in result.structured_content["sections"] for c in s["clauses"]}
    assert {"handbook/refunds#2", "bonus-terms/welcome-bonus#4"} <= refs


async def test_get_ticket_withholds_contact_details_and_the_kyc_reason(server, customers):
    result = await call(server, "get_ticket", ticket_id="T-5103")
    payload = json.dumps(result.structured_content).lower()
    rizal = customers["C-1011"]
    for secret in (rizal.email, rizal.phone, rizal.kyc_review_reason, "selfie"):
        assert secret.lower() not in payload
    assert result.structured_content["customer"]["kyc_note"].startswith("A review reason is on file")
    history = {h["ticket_id"]: h for h in result.structured_content["history"]}
    assert history["T-5004"]["our_reply"].startswith("[withheld")


async def test_history_shows_where_our_earlier_reply_was_wrong(server):
    result = await call(server, "get_ticket", ticket_id="T-5111")
    history = {h["ticket_id"]: h for h in result.structured_content["history"]}
    assert history["T-5011"]["our_reply_problems"] == ["superseded_policy (bonus-terms/welcome-bonus#4)"]


async def test_vietnamese_survives_the_round_trip(server):
    result = await call(server, "get_ticket", ticket_id="T-5107")
    assert "500.000 đồng" in result.structured_content["customer_message_untrusted"]
    assert result.structured_content["customer"]["given_name"] == "Ha"
    assert "đồng" in result.content[0].text  # not \u-escaped for the model


async def test_misuse_comes_back_as_an_actionable_error(server):
    draft = await call(server, "save_draft", ticket_id="T-5103", reply="Hi Rizal", policy_refs=[], note_for_reviewer="")
    assert draft.is_error and "escalate" in draft.content[0].text
    unknown = await call(server, "get_ticket", ticket_id="T-9999")
    assert unknown.is_error and "get_queue lists the open ones" in unknown.content[0].text


async def test_full_flow_for_one_ticket(server, desk):
    async with Client(server) as client:
        queue = (await client.call_tool("get_queue", {})).structured_content
        assert len(queue["items"]) == 15 and queue["items"][0]["ticket_id"] == "T-5103"

        escalation = await client.call_tool(
            "escalate", {"ticket_id": "T-5106", "team": "team_lead", "reason": "$250 refund, above limit"}
        )
        assert escalation.structured_content["escalation_id"] == "E-0001"

        refund = await client.call_tool(
            "request_refund", {"ticket_id": "T-5106", "amount_usd": 250, "reason": "Live game froze mid-round"}
        )
        assert refund.structured_content["refund_id"] == "R-0001"
        assert refund.structured_content["status"] == "awaiting_team_lead_approval"

        draft = {"ticket_id": "T-5106", "policy_refs": ["handbook/refunds#2"], "note_for_reviewer": ""}
        rejected = await client.call_tool("save_draft", {**draft, "reply": "Hi Hannah, I've refunded your $250."})
        assert rejected.structured_content["saved"] is False
        assert any("refund" in p for p in rejected.structured_content["problems"])

        reply = "Hi Hannah, sorry the game froze. Our team lead will review your refund request and reply."
        saved = await client.call_tool("save_draft", {**draft, "reply": reply})
        assert saved.structured_content["saved"] is True
    assert [d.ticket_id for d in desk.workspace.drafts()] == ["T-5106"]
