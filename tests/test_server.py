"""The MCP surface, exercised through a real MCP client session rather than direct calls."""

import json

import pytest
from mcp import Client

from support_desk.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def server(desk):
    return build_server(desk)


async def test_tools_on_offer(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"get_queue", "get_ticket", "search_policy", "escalate", "request_refund", "save_draft"}
    assert not any("send" in name for name in tools)
    for name in ("get_queue", "get_ticket", "search_policy"):
        assert tools[name].annotations.read_only_hint is True
    assert tools["escalate"].input_schema["properties"]["team"]["enum"] == ["team_lead", "payments"]


async def test_get_ticket_withholds_contact_details_and_kyc_reason(server, customers):
    async with Client(server) as client:
        result = await client.call_tool("get_ticket", {"ticket_id": "T-5103"})
    payload = json.dumps(result.structured_content)
    rizal = customers["C-1011"]
    for secret in (rizal.email, rizal.phone, rizal.kyc_review_reason, "selfie"):
        assert secret.lower() not in payload.lower()
    view = result.structured_content
    assert view["route"] == "team_lead"
    assert view["customer"]["kyc_note"].startswith("A review reason is on file")
    assert {c["ref"] for s in view["policy"] for c in s["clauses"]} >= {
        "handbook/verification-kyc#2",
        "handbook/escalation#2",
    }


async def test_vietnamese_survives_the_round_trip(server):
    async with Client(server) as client:
        result = await client.call_tool("get_ticket", {"ticket_id": "T-5107"})
    assert "500.000 đồng" in result.structured_content["customer_message_untrusted"]
    assert result.structured_content["customer"]["given_name"] == "Ha"
    assert "đồng" in result.content[0].text  # not \u-escaped for the model


async def test_misuse_comes_back_as_an_actionable_error(server):
    async with Client(server) as client:
        result = await client.call_tool(
            "save_draft",
            {"ticket_id": "T-5103", "reply": "Hi Rizal", "policy_refs": [], "note_for_reviewer": ""},
        )
    assert result.is_error
    assert "escalate" in result.content[0].text


async def test_full_flow_for_one_ticket(server, desk):
    async with Client(server) as client:
        queue = (await client.call_tool("get_queue", {})).structured_content
        assert queue["open_tickets"] == 15
        assert queue["items"][0]["ticket_id"] == "T-5103"

        escalation = await client.call_tool(
            "escalate", {"ticket_id": "T-5106", "team": "team_lead", "reason": "$250 refund, above limit"}
        )
        refund = await client.call_tool(
            "request_refund", {"ticket_id": "T-5106", "amount_usd": 250, "reason": "Live game froze mid-round"}
        )
        assert refund.structured_content["status"] == "awaiting_team_lead_approval"

        rejected = await client.call_tool(
            "save_draft",
            {
                "ticket_id": "T-5106",
                "reply": "Hi Hannah, as a Gold member I've refunded your $250.",
                "policy_refs": ["handbook/refunds#2"],
                "note_for_reviewer": "",
            },
        )
        assert rejected.structured_content["saved"] is False
        assert any("refund" in p for p in rejected.structured_content["problems"])

        saved = await client.call_tool(
            "save_draft",
            {
                "ticket_id": "T-5106",
                "reply": "Hi Hannah, sorry the game froze. We're checking the round and a senior colleague "
                "will review your refund request. We'll update you as soon as that's done.",
                "policy_refs": ["handbook/refunds#2"],
                "note_for_reviewer": "Check the game round log before deciding R-0001.",
            },
        )
    assert not escalation.is_error
    assert saved.structured_content["saved"] is True
    assert [d.ticket_id for d in desk.workspace.drafts()] == ["T-5106"]


async def test_search_policy_says_so_when_nothing_applies(server):
    async with Client(server) as client:
        result = await client.call_tool("search_policy", {"query": "lost phone 2FA reset"})
    assert result.structured_content["sections"] == []
    assert "escalate" in result.structured_content["note"]


async def test_prompt_is_listed(server):
    async with Client(server) as client:
        prompts = (await client.list_prompts()).prompts
    assert [p.name for p in prompts] == ["work_the_queue"]


async def test_history_shows_where_our_earlier_reply_was_wrong(server):
    async with Client(server) as client:
        result = await client.call_tool("get_ticket", {"ticket_id": "T-5111"})
    history = {h["ticket_id"]: h for h in result.structured_content["history"]}
    assert any("bonus-terms/welcome-bonus#4" in p for p in history["T-5011"]["our_reply_problems"])
