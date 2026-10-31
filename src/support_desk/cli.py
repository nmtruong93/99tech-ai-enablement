"""Command line for the people side of the desk.

serve                              run the MCP server on stdio (what Claude launches)
queue                              triage the open queue, no model involved
backtest                           run the reply checks over the replies the team already sent
review                             list drafts waiting for a person
approve D-0001 --by Mai            approve a draft, which writes it to outbox.jsonl
reject D-0001 --by Mai --comment "..."
refund R-0001 --by Mai --approve | --decline
report [--out FILE]                the open tickets and what was done about each, for the team lead
"""

import argparse
import sys
from pathlib import Path

from .checks import ReplyContext, Severity, check_reply
from .config import Settings
from .desk import DeskError, SupportDesk
from .models import Draft, DraftStatus, RefundStatus, Team, load_tickets
from .policy import FIRST_REPLY_TARGET, SLACK_VIP_REFUND_RULE
from .server import build_server
from .triage import Flag, Priority, Triage


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    desk = SupportDesk(Settings.from_env())
    try:
        if args.command == "serve":
            build_server(desk).run()
        elif args.command == "queue":
            print(render_queue(desk.queue()))
        elif args.command == "backtest":
            print(render_backtest(desk))
        elif args.command == "review":
            print(render_review(desk))
        elif args.command == "approve":
            body = _read_body(args.body_file)
            draft = desk.approve_draft(args.draft_id, args.by, body)
            print(f"{draft.draft_id} approved by {draft.reviewed_by}; the reply to {draft.ticket_id} is in the outbox.")
            if merged := [t.ticket_id for t in desk.workspace.tickets() if t.merged_into == draft.ticket_id]:
                print(f"Also closed {', '.join(merged)}, answered by this reply.")
        elif args.command == "reject":
            print(f"{desk.reject_draft(args.draft_id, args.by, args.comment).draft_id} rejected.")
        elif args.command == "refund":
            refund = desk.decide_refund(args.refund_id, args.by, approve=args.approve)
            print(f"{refund.refund_id} {refund.status}. Issue it in the back office before the reply goes out.")
        elif args.command == "report":
            report = render_report(desk)
            if args.out:
                Path(args.out).write_text(report, encoding="utf-8")
                print(f"Wrote {args.out}")
            else:
                print(report)
    except DeskError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="support-desk", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the MCP server on stdio")
    sub.add_parser("queue", help="triage the open queue")
    sub.add_parser("backtest", help="check the replies already sent")
    sub.add_parser("review", help="list drafts waiting for a person")
    approve = sub.add_parser("approve", help="approve a draft and write it to the outbox")
    approve.add_argument("draft_id")
    approve.add_argument("--by", required=True, help="your name; it signs the reply")
    approve.add_argument("--body-file", help="a file with your edited reply; it is checked again")
    reject = sub.add_parser("reject", help="reject a draft")
    reject.add_argument("draft_id")
    reject.add_argument("--by", required=True)
    reject.add_argument("--comment", required=True)
    refund = sub.add_parser("refund", help="approve or decline a refund request")
    refund.add_argument("refund_id")
    refund.add_argument("--by", required=True)
    decision = refund.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--decline", action="store_true")
    report = sub.add_parser("report", help="markdown report of the open tickets")
    report.add_argument("--out")
    return p


def _read_body(path: str | None) -> str | None:
    if path is None:
        return None
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise DeskError(f"Can't read {path}: {e.strerror}.") from e


def render_queue(queue: list[Triage]) -> str:
    rows = ["| Ticket | Pri | Route | Category | Lang | Waiting | Flags |", "|---|---|---|---|---|---|---|"]
    for t in queue:
        rows.append(
            f"| {t.ticket.ticket_id} | {t.priority.name} | {t.route or '-'} | {t.category} | {t.language} "
            f"| {_hours(t)}h | {', '.join(sorted(t.flags)) or '-'} |"
        )
    return "\n".join(rows)


def render_backtest(desk: SupportDesk) -> str:
    rows = ["| Ticket | Agent | Result | Findings |", "|---|---|---|---|"]
    for ticket in load_tickets(desk.settings.data_dir / "tickets.json"):
        if not ticket.agent_reply:
            continue
        context = ReplyContext(ticket, desk.customers.get(ticket.customer_id), desk.customers.values(), desk.policy)
        findings = check_reply(ticket.agent_reply, context)
        worst = "BLOCK" if any(f.severity is Severity.BLOCK for f in findings) else ("warn" if findings else "ok")
        detail = "<br>".join(f"{f.code}: {f.message.replace('|', '\\|')}" for f in findings) or "-"
        rows.append(f"| {ticket.ticket_id} | {ticket.assigned_to} | {worst} | {detail} |")
    return "\n".join(rows)


def render_review(desk: SupportDesk) -> str:
    pending = [d for d in desk.workspace.drafts() if d.status is DraftStatus.PENDING_REVIEW]
    if not pending:
        return "No drafts waiting for review."
    return "\n\n".join(
        f"{d.draft_id} for {d.ticket_id} ({d.language})\n"
        f"  Check before sending: {d.note_for_reviewer or '-'}\n"
        + "".join(f"  Warning: {w}\n" for w in d.warnings)
        + "\n".join("  > " + line for line in d.body.splitlines())
        for d in pending
    )


def render_report(desk: SupportDesk) -> str:
    """The export's open tickets, what triage decided and what Claude did about each, for the team lead."""
    export = load_tickets(desk.settings.data_dir / "tickets.json")
    triaged = sorted((desk.triage(t.ticket_id) for t in export if t.is_open), key=lambda t: (t.priority, -t.age))
    late = sum(t.age > FIRST_REPLY_TARGET for t in triaged)
    out = [
        f"# Open tickets at {desk.settings.as_of:%d %b %Y %H:%M} UTC",
        "",
        f"The export's 30-ticket sample has {len(triaged)} open tickets, {late} of them past the 1-hour "
        "first-reply target. Claude escalated and drafted through the MCP tools. Nothing has been sent: "
        "a person approves each draft with `support-desk approve`.",
        "",
    ]
    if notes := _notes(triaged):
        out += ["## Before you start", "", *[f"- {n}" for n in notes], ""]

    def needs_decision(t: Triage) -> bool:
        refunds = desk.refunds_for(t.ticket.ticket_id)
        return Team.TEAM_LEAD in desk.escalated_to(t.ticket.ticket_id) or any(
            r.status is RefundStatus.AWAITING_APPROVAL for r in refunds
        )

    answerable = [t for t in triaged if not t.duplicate_of]
    groups = (
        ("Do now", [t for t in answerable if t.priority is Priority.P1]),
        ("You decide", [t for t in answerable if t.priority is not Priority.P1 and needs_decision(t)]),
        ("Ready once checked", [t for t in answerable if t.priority is not Priority.P1 and not needs_decision(t)]),
    )
    for title, tickets in groups:
        if tickets:
            out += [f"## {title}", "", *[_summary(desk, t) for t in tickets], ""]

    out.append("## Ticket by ticket")
    for t in triaged:
        out += _detail(desk, t)
    return "\n".join(out) + "\n"


def _notes(triaged: list[Triage]) -> list[str]:
    notes = [SLACK_VIP_REFUND_RULE] if any(Flag.REFUND_REQUEST in t.flags for t in triaged) else []
    for t in triaged:
        if wrong := [p.ticket.ticket_id for p in t.history if p.problems and Flag.PRIOR_POLICY_ERROR in t.flags]:
            notes.append(f"{t.ticket.ticket_id} follows our earlier reply on {', '.join(wrong)}, which broke policy.")
        if t.duplicate_of:
            first = next(x for x in triaged if x.ticket.ticket_id == t.duplicate_of)
            notes.append(
                f"{t.ticket.ticket_id} chases {t.duplicate_of}, unanswered for {_hours(first)}h; one reply covers both."
            )
    return notes


def _summary(desk: SupportDesk, t: Triage) -> str:
    ticket_id = t.ticket.ticket_id
    reasons = [e.reason for e in desk.escalations_for(ticket_id) if e.team is Team.TEAM_LEAD]
    draft = _latest_draft(desk, ticket_id)
    why = reasons[0] if reasons else (draft.note_for_reviewer if draft else "")
    subject = t.ticket.subject if t.ticket.subject[-1:] in ".?!" else f"{t.ticket.subject}."
    return f"- **{ticket_id}** {subject} {_first_sentence(why)} " + (
        f"Draft {draft.draft_id}." if draft else "No draft."
    )


def _detail(desk: SupportDesk, t: Triage) -> list[str]:
    ticket = t.ticket
    out = [
        "",
        f"### {ticket.ticket_id}: {ticket.subject}",
        "",
        f"{t.priority.name}, {ticket.channel}, {t.language}, waiting {_hours(t)}h.",
        "",
        "**Customer wrote**",
        "",
        *_quote(ticket.message),
        "",
    ]
    if t.signals:
        out += ["**Flagged:** " + "; ".join(f"{s.flag.replace('_', ' ')} ({s.evidence})" for s in t.signals), ""]
    for e in desk.escalations_for(ticket.ticket_id):
        out += [f"**Escalated to {e.team.replace('_', ' ')}:** {e.reason}", ""]
    for r in desk.refunds_for(ticket.ticket_id):
        out += [f"**Refund {r.refund_id}:** ${r.amount_usd:g}, {r.status.replace('_', ' ')} ({r.why}). {r.reason}", ""]
    if t.duplicate_of:
        out.append(f"Answered on {t.duplicate_of}.")
    elif draft := _latest_draft(desk, ticket.ticket_id):
        out += [
            f"**Draft {draft.draft_id}**",
            "",
            *_quote(draft.body),
            "",
            f"**Check before sending:** {draft.note_for_reviewer}",
        ]
        if draft.warnings:
            out += ["", "**Warnings:** " + " ".join(draft.warnings)]
    else:
        out.append("No draft.")
    return out


def _latest_draft(desk: SupportDesk, ticket_id: str) -> Draft | None:
    live = [d for d in desk.drafts_for(ticket_id) if d.status is not DraftStatus.SUPERSEDED]
    return live[-1] if live else None


def _quote(text: str) -> list[str]:
    """A markdown blockquote, which wraps on GitHub. The trailing double space keeps the reply's line breaks."""
    return [f"> {line}  " if line.strip() else ">" for line in text.splitlines()]


def _first_sentence(text: str) -> str:
    return text.split(". ")[0].rstrip(".") + "." if text else ""


def _hours(t: Triage) -> int:
    return round(t.age.total_seconds() / 3600)


if __name__ == "__main__":
    raise SystemExit(main())
