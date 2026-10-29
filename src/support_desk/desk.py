"""The operations behind the MCP tools and the CLI.

Two kinds of caller use this class. The assistant (through MCP) can read,
escalate, record refund requests and save drafts. People (through the CLI)
approve or reject drafts and refunds. Nothing the assistant can call sends a
message or moves money; that boundary is the main safety property of the
design, and it doesn't depend on the model behaving.
"""

import math
from collections.abc import Callable
from datetime import UTC, datetime

from .checks import Finding, ReplyContext, Severity, check_reply
from .config import Settings
from .export import load_customers
from .models import (
    Customer,
    Draft,
    DraftStatus,
    Escalation,
    Note,
    RefundRequest,
    RefundStatus,
    Team,
    Ticket,
)
from .policy import AGENT_REFUND_LIMIT_USD, Policy, Section
from .text import detect_language
from .triage import TEAM_LEAD_FLAGS, Flag, Triage, triage_queue, triage_ticket
from .workspace import Workspace, next_id

ASSISTANT = "assistant"

# Refunds on tickets with these flags always go to the team lead, whatever the amount.
_REFUND_RISK_FLAGS = TEAM_LEAD_FLAGS | {Flag.KYC_HOLD}

# Which policy sections matter for which kind of ticket.
_SECTIONS_BY_CATEGORY = {
    "withdrawal": ["handbook/withdrawals"],
    "deposit": ["handbook/deposits"],
    "bonus": [
        "handbook/bonuses",
        "bonus-terms/welcome-bonus",
        "bonus-terms/withdrawing-with-an-active-bonus",
        "bonus-terms/exceptions",
    ],
    "kyc": ["handbook/verification-kyc"],
    "complaint": ["handbook/refunds"],
}
_SECTIONS_BY_FLAG = {
    Flag.KYC_HOLD: ["handbook/verification-kyc"],
    Flag.REFUND_REQUEST: ["handbook/refunds"],
    Flag.THIRD_PARTY_REQUEST: ["handbook/privacy"],
}


class DeskError(Exception):
    """A request the desk won't carry out. The message says what to do instead."""


class SupportDesk:
    def __init__(self, settings: Settings, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.settings = settings
        self.policy = Policy.load(settings.data_dir)
        self.customers = load_customers(settings.data_dir / "customers.csv")
        self.workspace = Workspace(settings.workspace_dir, settings.data_dir / "tickets.json")
        self._clock = clock

    # Reading

    def queue(self) -> list[Triage]:
        return triage_queue(self.workspace.tickets(), self.customers, self.policy, self.settings.as_of)

    def triage(self, ticket_id: str) -> Triage:
        tickets = self.workspace.tickets()
        ticket = _find(tickets, ticket_id)
        return triage_ticket(
            ticket, self.customers.get(ticket.customer_id), tickets, self.customers, self.policy, self.settings.as_of
        )

    def customer_of(self, ticket: Ticket) -> Customer | None:
        return self.customers.get(ticket.customer_id)

    def history(self, ticket: Ticket) -> list[Ticket]:
        return sorted(
            (
                t
                for t in self.workspace.tickets()
                if t.customer_id == ticket.customer_id and t.ticket_id != ticket.ticket_id
            ),
            key=lambda t: t.created_at,
        )

    def past_replies(self, ticket: Ticket) -> list[tuple[Ticket, str | None, list[str]]]:
        """Earlier tickets from the same customer, each with our reply and what was wrong with it.

        A reply that disclosed a KYC finding is withheld: showing it to the model would
        put the reason right back in front of it.
        """
        result = []
        for past in self.history(ticket):
            reply, problems = past.agent_reply, []
            if reply:
                findings = check_reply(
                    reply, ReplyContext(past, self.customer_of(past), self.customers.values(), self.policy)
                )
                problems = [f.summary for f in findings if f.severity is Severity.BLOCK]
                if any(f.code == "kyc_reason_disclosed" for f in findings):
                    reply = "[withheld: this reply disclosed the KYC review reason and must not be repeated]"
            result.append((past, reply, problems))
        return result

    def relevant_policy(self, triage: Triage) -> list[Section]:
        prefixes = ["handbook/response-times"] + _SECTIONS_BY_CATEGORY.get(triage.category, [])
        for flag in triage.flags:
            prefixes += _SECTIONS_BY_FLAG.get(flag, [])
        if triage.route is Team.TEAM_LEAD:
            prefixes.append("handbook/escalation")
        sections = []
        for prefix in dict.fromkeys(prefixes):
            if (section := self.policy.section_of(prefix)) and section not in sections:
                sections.append(section)
        return sections

    def search_policy(self, query: str) -> list[Section]:
        return self.policy.search(query)

    def drafts_for(self, ticket_id: str) -> list[Draft]:
        return [d for d in self.workspace.drafts() if d.ticket_id == ticket_id]

    def escalations_for(self, ticket_id: str) -> list[Escalation]:
        return [e for e in self.workspace.escalations() if e.ticket_id == ticket_id]

    def refunds_for(self, ticket_id: str) -> list[RefundRequest]:
        return [r for r in self.workspace.refunds() if r.ticket_id == ticket_id]

    # Assistant actions

    def escalate(self, ticket_id: str, team: Team, reason: str) -> Escalation:
        ticket = self._open_ticket(ticket_id)
        ticket_id = ticket.ticket_id
        _require_text(reason, "reason")
        if existing := next((e for e in self.escalations_for(ticket_id) if e.team is team), None):
            return existing

        now = self._clock()
        escalation = Escalation(
            escalation_id=next_id("E", [e.escalation_id for e in self.workspace.escalations()]),
            ticket_id=ticket_id,
            team=team,
            reason=reason.strip(),
            created_at=now,
        )
        self.workspace.save_escalation(escalation)
        ticket.escalated_to.append(team.value)
        ticket.internal_notes.append(Note(at=now, by=ASSISTANT, text=f"Escalated to {team.value}: {reason.strip()}"))
        self.workspace.save_ticket(ticket)
        self.workspace.log(now, ASSISTANT, "escalate", ticket_id=ticket_id, team=team.value, reason=reason.strip())
        return escalation

    def request_refund(self, ticket_id: str, amount_usd: float, reason: str) -> RefundRequest:
        ticket = self._open_ticket(ticket_id)
        ticket_id = ticket.ticket_id
        _require_text(reason, "reason")
        amount = round(amount_usd, 2) if math.isfinite(amount_usd) else 0.0
        if amount < 0.01:
            raise DeskError("amount_usd must be a positive amount in USD.")
        triage = self.triage(ticket_id)
        if triage.duplicate_of:
            raise DeskError(f"{ticket_id} duplicates {triage.duplicate_of}. Record any refund there.")
        if active := [r for r in self.refunds_for(ticket_id) if r.status is not RefundStatus.DECLINED]:
            raise DeskError(f"{active[0].refund_id} already exists for {ticket_id} ({active[0].status}).")

        # The agent limit is per customer, so two $90 refunds on two tickets can't add up to $180 unapproved.
        customer_total = amount + sum(
            r.amount_usd
            for r in self.workspace.refunds()
            if r.customer_id == ticket.customer_id and r.status is not RefundStatus.DECLINED
        )
        risk = sorted(f.value for f in triage.flags & _REFUND_RISK_FLAGS)
        within_limit = customer_total <= AGENT_REFUND_LIMIT_USD and not risk and triage.route is None
        now = self._clock()
        refund = RefundRequest(
            refund_id=next_id("R", [r.refund_id for r in self.workspace.refunds()]),
            ticket_id=ticket_id,
            customer_id=ticket.customer_id,
            amount_usd=amount,
            reason=reason.strip(),
            status=RefundStatus.WITHIN_AGENT_LIMIT if within_limit else RefundStatus.AWAITING_APPROVAL,
            risk_flags=risk,
            created_at=now,
        )
        self.workspace.save_refund(refund)
        self.workspace.log(
            now,
            ASSISTANT,
            "request_refund",
            ticket_id=ticket_id,
            refund_id=refund.refund_id,
            amount_usd=refund.amount_usd,
            status=refund.status.value,
            risk_flags=risk,
        )
        return refund

    def save_draft(
        self, ticket_id: str, body: str, policy_refs: list[str], note_for_reviewer: str
    ) -> tuple[Draft | None, list[Finding]]:
        """Check a reply and store it for review. Returns (None, findings) when a check blocks it."""
        ticket = self._open_ticket(ticket_id)
        ticket_id = ticket.ticket_id
        triage = self.triage(ticket_id)
        if triage.duplicate_of:
            raise DeskError(
                f"{ticket_id} duplicates {triage.duplicate_of}. Save one draft on {triage.duplicate_of}; "
                f"{ticket_id} is closed with it when the reply is approved."
            )
        if triage.route is Team.TEAM_LEAD and not any(
            e.team is Team.TEAM_LEAD for e in self.escalations_for(ticket_id)
        ):
            raise DeskError(
                f"{ticket_id} must go to the team lead first ({', '.join(sorted(triage.flags))}). "
                "Call escalate, then save the draft for the team lead to review."
            )
        if unknown := [r for r in policy_refs if self.policy.clause(r) is None]:
            raise DeskError(
                f"Unknown policy refs {unknown}. Use refs exactly as get_ticket or search_policy return them, "
                "e.g. handbook/refunds#2."
            )

        findings = check_reply(body, self._reply_context(ticket, triage))
        now = self._clock()
        blocks = [f for f in findings if f.severity is Severity.BLOCK]
        if blocks:
            self.workspace.log(now, ASSISTANT, "draft_blocked", ticket_id=ticket_id, findings=[str(f) for f in blocks])
            return None, findings

        warnings = [str(f) for f in findings]
        if not policy_refs:
            warnings.append("[warn] no_policy_cited: no policy clause was cited; check the facts in this reply.")

        for old in self.drafts_for(ticket_id):
            if old.status is DraftStatus.PENDING_REVIEW:
                old.status, old.review_comment = DraftStatus.REJECTED, "superseded by a newer draft"
                self.workspace.save_draft(old)

        draft = Draft(
            draft_id=next_id("D", [d.draft_id for d in self.workspace.drafts()]),
            ticket_id=ticket_id,
            body=body.strip(),
            language=detect_language(body),
            policy_refs=policy_refs,
            note_for_reviewer=note_for_reviewer.strip(),
            warnings=warnings,
            created_at=now,
        )
        self.workspace.save_draft(draft)
        self.workspace.log(
            now, ASSISTANT, "save_draft", ticket_id=ticket_id, draft_id=draft.draft_id, warnings=warnings
        )
        return draft, findings

    # People only: these are reachable from the CLI, never from MCP.

    def approve_draft(self, draft_id: str, reviewer: str, body: str | None = None) -> Draft:
        _require_text(reviewer, "reviewer")
        draft = self._pending_draft(draft_id)
        ticket = self._open_ticket(draft.ticket_id)
        final = (body or draft.body).strip()

        # Re-check even an unedited draft: a refund may have been declined since it was saved.
        context = self._reply_context(ticket, self.triage(ticket.ticket_id))
        if blocks := [f for f in check_reply(final, context) if f.severity is Severity.BLOCK]:
            raise DeskError("Reply fails checks:\n" + "\n".join(str(f) for f in blocks))

        duplicates = [t for t in self.queue() if t.duplicate_of == ticket.ticket_id]
        now = self._clock()
        # Outbox first: if a later write fails, the reply is on record as sent rather than lost.
        self.workspace.send(ticket, final, reviewer, now)

        ticket.agent_reply = final
        ticket.first_response_at = ticket.first_response_at or now
        ticket.status = "replied"
        ticket.internal_notes.append(Note(at=now, by=reviewer, text=f"Approved and sent {draft_id}"))
        self.workspace.save_ticket(ticket)

        for dup in duplicates:
            dup.ticket.status, dup.ticket.resolution = "closed", f"merged into {ticket.ticket_id}"
            dup.ticket.internal_notes.append(Note(at=now, by=reviewer, text=f"Answered on {ticket.ticket_id}"))
            self.workspace.save_ticket(dup.ticket)

        draft.status, draft.body, draft.reviewed_by, draft.reviewed_at = DraftStatus.APPROVED, final, reviewer, now
        self.workspace.save_draft(draft)
        self.workspace.log(
            now,
            reviewer,
            "approve_draft",
            draft_id=draft_id,
            ticket_id=ticket.ticket_id,
            edited=body is not None,
            closed_duplicates=[d.ticket.ticket_id for d in duplicates],
        )
        return draft

    def reject_draft(self, draft_id: str, reviewer: str, comment: str) -> Draft:
        _require_text(reviewer, "reviewer")
        _require_text(comment, "comment")
        draft = self._pending_draft(draft_id)
        now = self._clock()
        draft.status, draft.reviewed_by, draft.reviewed_at, draft.review_comment = (
            DraftStatus.REJECTED,
            reviewer,
            now,
            comment.strip(),
        )
        self.workspace.save_draft(draft)
        self.workspace.log(now, reviewer, "reject_draft", draft_id=draft_id, comment=comment.strip())
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
        self.workspace.log(now, approver, "decide_refund", refund_id=refund_id, status=refund.status.value)
        return refund

    # Helpers

    def _open_ticket(self, ticket_id: str) -> Ticket:
        ticket = _find(self.workspace.tickets(), ticket_id)
        if not ticket.is_open:
            raise DeskError(f"{ticket_id} is {ticket.status}, not open.")
        return ticket

    def _pending_draft(self, draft_id: str) -> Draft:
        draft = next((d for d in self.workspace.drafts() if d.draft_id == draft_id), None)
        if draft is None:
            raise DeskError(f"No draft {draft_id}.")
        if draft.status is not DraftStatus.PENDING_REVIEW:
            raise DeskError(f"{draft_id} is {draft.status}, not pending review.")
        return draft

    def _reply_context(self, ticket: Ticket, triage: Triage) -> ReplyContext:
        return ReplyContext(
            ticket=ticket,
            customer=self.customer_of(ticket),
            other_customers=self.customers.values(),
            policy=self.policy,
            approved_refund_usd=self._issuable_refund(ticket.ticket_id),
            harm_sensitive=bool(triage.flags & {Flag.GAMBLING_HARM, Flag.SELF_EXCLUDED}),
            category=triage.category,
        )

    def _issuable_refund(self, ticket_id: str) -> float:
        ok = (RefundStatus.WITHIN_AGENT_LIMIT, RefundStatus.APPROVED)
        return sum(r.amount_usd for r in self.refunds_for(ticket_id) if r.status in ok)


def _find(tickets: list[Ticket], ticket_id: str) -> Ticket:
    ticket = next((t for t in tickets if t.ticket_id == ticket_id.strip().upper()), None)
    if ticket is None:
        raise DeskError(f"No ticket {ticket_id}. Ticket ids look like T-5101; get_queue lists the open ones.")
    return ticket


def _require_text(value: str, name: str) -> None:
    if not value or not value.strip():
        raise DeskError(f"{name} is required.")
