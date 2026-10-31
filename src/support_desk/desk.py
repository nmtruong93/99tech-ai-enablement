"""The operations behind the MCP tools and the CLI.

The model (through MCP) can read, escalate, record refund requests and save drafts. People
(through the CLI) approve or reject drafts and refunds. Nothing the model can call sends a
message or moves money, and that doesn't depend on the model behaving.
"""

import math
from collections.abc import Callable
from datetime import UTC, datetime

from .checks import Finding, ReplyContext, Severity, check_reply
from .config import Settings
from .models import (
    Draft,
    DraftStatus,
    Escalation,
    RefundRequest,
    RefundStatus,
    Team,
    Ticket,
    TicketStatus,
    load_customers,
)
from .policy import AGENT_REFUND_LIMIT_USD, Policy
from .text import detect_language
from .triage import Flag, Triage, triage_queue, triage_ticket
from .workspace import Workspace, next_id

MODEL = "assistant"

# Refunds on these tickets wait for the team lead whatever the amount, as do refunds on any
# ticket routed to the team lead. A refund because we got policy wrong is a judgement call.
_REFUND_NEEDS_APPROVAL = frozenset({Flag.KYC_HOLD, Flag.PRIOR_POLICY_ERROR, Flag.THIRD_PARTY_REQUEST})


class DeskError(Exception):
    """A request the desk won't carry out. The message says what to do instead."""


class SupportDesk:
    def __init__(self, settings: Settings, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.settings = settings
        self.policy = Policy.load(settings.data_dir)
        self.customers = load_customers(settings.data_dir / "customers.csv")
        self.workspace = Workspace(settings.workspace_dir, settings.data_dir / "tickets.json")
        self._clock = clock

    def queue(self) -> list[Triage]:
        return triage_queue(self.workspace.tickets(), self.customers, self.policy, self.settings.as_of)

    def triage(self, ticket_id: str) -> Triage:
        tickets = self.workspace.tickets()
        return triage_ticket(_find(tickets, ticket_id), tickets, self.customers, self.policy, self.settings.as_of)

    def drafts_for(self, ticket_id: str) -> list[Draft]:
        return [d for d in self.workspace.drafts() if d.ticket_id == ticket_id]

    def escalations_for(self, ticket_id: str) -> list[Escalation]:
        return [e for e in self.workspace.escalations() if e.ticket_id == ticket_id]

    def refunds_for(self, ticket_id: str) -> list[RefundRequest]:
        return [r for r in self.workspace.refunds() if r.ticket_id == ticket_id]

    # The model's actions

    def escalate(self, ticket_id: str, team: Team, reason: str) -> Escalation:
        ticket = self._open_ticket(ticket_id)
        _require_text(reason, "reason")
        if existing := next((e for e in self.escalations_for(ticket.ticket_id) if e.team is team), None):
            return existing
        now = self._clock()
        escalation = Escalation(
            escalation_id=next_id("E", [e.escalation_id for e in self.workspace.escalations()]),
            ticket_id=ticket.ticket_id,
            team=team,
            reason=reason.strip(),
            created_at=now,
        )
        self.workspace.save_escalation(escalation)
        self.workspace.log(now, MODEL, "escalate", ticket_id=ticket.ticket_id, team=team, reason=escalation.reason)
        return escalation

    def request_refund(self, ticket_id: str, amount_usd: float, reason: str) -> RefundRequest:
        ticket = self._open_ticket(ticket_id)
        _require_text(reason, "reason")
        amount = round(amount_usd, 2) if math.isfinite(amount_usd) else 0.0
        if amount < 0.01:
            raise DeskError("amount_usd must be a positive amount in USD.")
        triage = self.triage(ticket.ticket_id)
        if triage.duplicate_of:
            raise DeskError(f"{ticket.ticket_id} duplicates {triage.duplicate_of}. Record any refund there.")
        refunds = self.workspace.refunds()
        if active := [r for r in refunds if r.ticket_id == ticket.ticket_id and r.status is not RefundStatus.DECLINED]:
            raise DeskError(f"{active[0].refund_id} already exists for {ticket.ticket_id} ({active[0].status}).")

        # My assumption, not the handbook's: the limit is per customer, so two $90 refunds on two
        # tickets can't add up to $180 without approval.
        customer_total = amount + sum(
            r.amount_usd
            for r in refunds
            if r.customer_id == ticket.customer_id and r.status is not RefundStatus.DECLINED
        )
        why = []
        if customer_total > AGENT_REFUND_LIMIT_USD:
            why.append(f"brings this customer's refunds to ${customer_total:g}, above the USD 100 agent limit")
        if triage.route is Team.TEAM_LEAD:
            why.append("the ticket must go to the team lead")
        if risky := sorted(triage.flags & _REFUND_NEEDS_APPROVAL):
            why.append(f"the ticket is flagged {', '.join(risky)}")
        now = self._clock()
        refund = RefundRequest(
            refund_id=next_id("R", [r.refund_id for r in refunds]),
            ticket_id=ticket.ticket_id,
            customer_id=ticket.customer_id,
            amount_usd=amount,
            reason=reason.strip(),
            status=RefundStatus.AWAITING_APPROVAL if why else RefundStatus.WITHIN_AGENT_LIMIT,
            why="; ".join(why) or "within the USD 100 agent limit (handbook/refunds#1)",
            created_at=now,
        )
        self.workspace.save_refund(refund)
        self.workspace.log(now, MODEL, "request_refund", **refund.model_dump(mode="json", exclude={"created_at"}))
        return refund

    def save_draft(
        self, ticket_id: str, body: str, policy_refs: list[str], note_for_reviewer: str
    ) -> tuple[Draft | None, list[Finding]]:
        """Check a reply and store it for review. Returns (None, findings) when a check blocks it."""
        ticket = self._open_ticket(ticket_id)
        triage = self.triage(ticket.ticket_id)
        if triage.duplicate_of:
            raise DeskError(
                f"{ticket.ticket_id} duplicates {triage.duplicate_of}. Save one draft on {triage.duplicate_of}; "
                f"{ticket.ticket_id} is closed with it when the reply is approved."
            )
        if triage.route is Team.TEAM_LEAD and Team.TEAM_LEAD not in self.escalated_to(ticket.ticket_id):
            raise DeskError(
                f"{ticket.ticket_id} must go to the team lead first ({', '.join(sorted(triage.flags))}). "
                "Call escalate, then save the draft for the team lead to review."
            )
        if unknown := [r for r in policy_refs if self.policy.clause(r) is None]:
            raise DeskError(f"Unknown policy refs {unknown}. Use refs exactly as get_policy returns them.")

        findings = check_reply(body, self._reply_context(triage))
        now = self._clock()
        if blocks := [f for f in findings if f.severity is Severity.BLOCK]:
            self.workspace.log(
                now, MODEL, "draft_blocked", ticket_id=ticket.ticket_id, findings=[str(f) for f in blocks]
            )
            return None, findings

        warnings = [f.message for f in findings]
        if not policy_refs:
            warnings.append("No policy clause was cited; check the facts in this reply.")
        for old in self.drafts_for(ticket.ticket_id):
            if old.status is DraftStatus.PENDING_REVIEW:
                old.status = DraftStatus.SUPERSEDED
                self.workspace.save_draft(old)
        draft = Draft(
            draft_id=next_id("D", [d.draft_id for d in self.workspace.drafts()]),
            ticket_id=ticket.ticket_id,
            body=body.strip(),
            language=detect_language(body),
            policy_refs=policy_refs,
            note_for_reviewer=note_for_reviewer.strip(),
            warnings=warnings,
            created_at=now,
        )
        self.workspace.save_draft(draft)
        self.workspace.log(
            now, MODEL, "save_draft", ticket_id=ticket.ticket_id, draft_id=draft.draft_id, warnings=warnings
        )
        return draft, findings

    # People only: reachable from the CLI, never from MCP.

    def approve_draft(self, draft_id: str, reviewer: str, body: str | None = None) -> Draft:
        _require_text(reviewer, "reviewer")
        draft = self._pending_draft(draft_id)
        triage = self.triage(draft.ticket_id)
        ticket = triage.ticket
        final = (body or draft.body).strip().replace("[AGENT NAME]", reviewer.strip())
        # Re-check even an unedited draft: a refund may have been declined since it was saved.
        context = self._reply_context(triage, sending=True)
        if blocks := [f for f in check_reply(final, context) if f.severity is Severity.BLOCK]:
            raise DeskError("Reply fails checks:\n" + "\n".join(str(f) for f in blocks))

        duplicates = [t.ticket for t in self.queue() if t.duplicate_of == ticket.ticket_id]
        now = self._clock()
        # Outbox first: if a later write fails, the reply is on record as sent rather than lost.
        self.workspace.send(ticket, final, reviewer, now)
        ticket.agent_reply, ticket.status = final, TicketStatus.REPLIED
        ticket.first_response_at = ticket.first_response_at or now
        self.workspace.save_ticket(ticket)
        for dup in duplicates:
            dup.status, dup.merged_into, dup.resolution = (
                TicketStatus.CLOSED,
                ticket.ticket_id,
                "answered on the other ticket",
            )
            self.workspace.save_ticket(dup)
        draft.status, draft.body, draft.reviewed_by, draft.reviewed_at = DraftStatus.APPROVED, final, reviewer, now
        self.workspace.save_draft(draft)
        closed = [d.ticket_id for d in duplicates]
        self.workspace.log(now, reviewer, "approve_draft", draft_id=draft_id, edited=body is not None, closed=closed)
        return draft

    def reject_draft(self, draft_id: str, reviewer: str, comment: str) -> Draft:
        _require_text(reviewer, "reviewer")
        _require_text(comment, "comment")
        draft = self._pending_draft(draft_id)
        now = self._clock()
        draft.status, draft.reviewed_by, draft.reviewed_at = DraftStatus.REJECTED, reviewer, now
        draft.review_comment = comment.strip()
        self.workspace.save_draft(draft)
        self.workspace.log(now, reviewer, "reject_draft", draft_id=draft_id, comment=draft.review_comment)
        return draft

    def decide_refund(self, refund_id: str, approver: str, approve: bool) -> RefundRequest:
        _require_text(approver, "approver")
        refund = next((r for r in self.workspace.refunds() if r.refund_id == refund_id), None)
        if refund is None:
            raise DeskError(f"No refund request {refund_id}.")
        if refund.status in (RefundStatus.APPROVED, RefundStatus.DECLINED):
            raise DeskError(f"{refund_id} was already {refund.status} by {refund.decided_by}.")
        now = self._clock()
        refund.status = RefundStatus.APPROVED if approve else RefundStatus.DECLINED
        refund.decided_by, refund.decided_at = approver, now
        self.workspace.save_refund(refund)
        self.workspace.log(now, approver, "decide_refund", refund_id=refund_id, status=refund.status)
        return refund

    def escalated_to(self, ticket_id: str) -> list[Team]:
        return [e.team for e in self.escalations_for(ticket_id)]

    def _open_ticket(self, ticket_id: str) -> Ticket:
        ticket = _find(self.workspace.tickets(), ticket_id)
        if not ticket.is_open:
            raise DeskError(f"{ticket.ticket_id} is {ticket.status}, not open.")
        return ticket

    def _pending_draft(self, draft_id: str) -> Draft:
        draft = next((d for d in self.workspace.drafts() if d.draft_id == draft_id), None)
        if draft is None:
            raise DeskError(f"No draft {draft_id}.")
        if draft.status is not DraftStatus.PENDING_REVIEW:
            raise DeskError(f"{draft_id} is {draft.status}, not pending review.")
        return draft

    def _reply_context(self, triage: Triage, sending: bool = False) -> ReplyContext:
        issuable = (RefundStatus.WITHIN_AGENT_LIMIT, RefundStatus.APPROVED)
        return ReplyContext(
            ticket=triage.ticket,
            customer=triage.customer,
            other_customers=self.customers.values(),
            policy=self.policy,
            approved_refund_usd=sum(
                r.amount_usd for r in self.refunds_for(triage.ticket.ticket_id) if r.status in issuable
            ),
            harm_sensitive=bool(triage.flags & {Flag.GAMBLING_HARM, Flag.SELF_EXCLUDED}),
            category=triage.category,
            sending=sending,
        )


def _find(tickets: list[Ticket], ticket_id: str) -> Ticket:
    ticket = next((t for t in tickets if t.ticket_id == ticket_id.strip().upper()), None)
    if ticket is None:
        raise DeskError(f"No ticket {ticket_id}. Ticket ids look like T-5101; get_queue lists the open ones.")
    return ticket


def _require_text(value: str, name: str) -> None:
    if not value or not value.strip():
        raise DeskError(f"{name} is required.")
