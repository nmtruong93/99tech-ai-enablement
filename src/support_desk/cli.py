"""Command line for the people side of the desk.

support-desk serve                       run the MCP server on stdio (what Claude launches)
support-desk queue                       triage the open queue, no model involved
support-desk backtest                    run the reply checks over replies already sent
support-desk review                      list drafts waiting for a person
support-desk approve D-0001 --by Mai     approve (optionally --body-file edited.txt) and send
support-desk reject D-0001 --by Mai --comment "..."
support-desk refund R-0001 --by Mai --approve | --decline
support-desk report [--out FILE]         markdown report of the open tickets and what was done
"""

import argparse
import sys
from pathlib import Path

from .checks import ReplyContext, Severity, check_reply
from .config import Settings
from .desk import DeskError, SupportDesk
from .export import load_tickets
from .models import DraftStatus, RefundStatus
from .server import build_server
from .triage import Triage


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
            body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else None
            draft = desk.approve_draft(args.draft_id, args.by, body)
            print(f"{draft.draft_id} approved by {draft.reviewed_by}; reply to {draft.ticket_id} is in the outbox.")
            merged = [t.ticket_id for t in desk.workspace.tickets() if t.resolution == f"merged into {draft.ticket_id}"]
            if merged:
                print(f"Also closed {', '.join(merged)} as answered by this reply.")
        elif args.command == "reject":
            draft = desk.reject_draft(args.draft_id, args.by, args.comment)
            print(f"{draft.draft_id} rejected.")
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
    sub.add_parser("serve")
    sub.add_parser("queue")
    sub.add_parser("backtest")
    sub.add_parser("review")
    approve = sub.add_parser("approve")
    approve.add_argument("draft_id")
    approve.add_argument("--by", required=True)
    approve.add_argument("--body-file")
    reject = sub.add_parser("reject")
    reject.add_argument("draft_id")
    reject.add_argument("--by", required=True)
    reject.add_argument("--comment", required=True)
    refund = sub.add_parser("refund")
    refund.add_argument("refund_id")
    refund.add_argument("--by", required=True)
    decision = refund.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--decline", action="store_true")
    report = sub.add_parser("report")
    report.add_argument("--out")
    return p


def render_queue(queue: list[Triage]) -> str:
    rows = ["| Ticket | Pri | Route | Category | Lang | Waiting | Flags |", "|---|---|---|---|---|---|---|"]
    for t in queue:
        rows.append(
            f"| {t.ticket.ticket_id} | {t.priority.name} | {t.route or '-'} | {t.category} | {t.language} "
            f"| {t.age.total_seconds() / 3600:.0f}h | {', '.join(sorted(t.flags)) or '-'} |"
        )
    return "\n".join(rows)


def render_backtest(desk: SupportDesk) -> str:
    rows = ["| Ticket | Agent | Result | Findings |", "|---|---|---|---|"]
    for ticket in desk.workspace.tickets():
        if not ticket.agent_reply or ticket.ticket_id not in _export_ids(desk, open_only=False):
            continue
        findings = check_reply(
            ticket.agent_reply,
            ReplyContext(ticket, desk.customer_of(ticket), desk.customers.values(), desk.policy),
        )
        worst = "BLOCK" if any(f.severity is Severity.BLOCK for f in findings) else ("warn" if findings else "ok")
        detail = "<br>".join(f"{f.code}: {_cell(f.message)}" for f in findings) or "-"
        rows.append(f"| {ticket.ticket_id} | {ticket.assigned_to} | {worst} | {detail} |")
    return "\n".join(rows)


def render_review(desk: SupportDesk) -> str:
    pending = [d for d in desk.workspace.drafts() if d.status is DraftStatus.PENDING_REVIEW]
    if not pending:
        return "No drafts waiting for review."
    blocks = []
    for d in pending:
        blocks.append(
            f"{d.draft_id} for {d.ticket_id} ({d.language})\n"
            f"  Check before sending: {d.note_for_reviewer or '-'}\n"
            + "".join(f"  {w}\n" for w in d.warnings)
            + "\n".join("  > " + line for line in d.body.splitlines())
        )
    return "\n\n".join(blocks)


def render_report(desk: SupportDesk) -> str:
    """The open tickets from the export, what triage decided, and what was done about each."""
    open_ids = _export_ids(desk, open_only=True)
    triaged = sorted((desk.triage(i) for i in open_ids), key=lambda t: (t.priority, -t.age))
    out = [
        "# Open tickets: triage and drafts",
        "",
        f"Export as of {desk.settings.as_of:%d %b %Y %H:%M} UTC. {len(triaged)} tickets were open, "
        "every one already past the 1-hour first-reply target.",
        "",
        "Triage (priority, route, flags) is deterministic and reproducible with `support-desk queue`. "
        "Escalations, refund requests and drafts were made by Claude through the MCP tools and are waiting "
        "for a person: nothing here has been sent.",
        "",
        "| Ticket | Pri | Route | Flags | Escalated to | Refund | Draft |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in triaged:
        draft = _latest_draft(desk, t.ticket.ticket_id)
        refunds = desk.refunds_for(t.ticket.ticket_id)
        out.append(
            f"| {t.ticket.ticket_id} | {t.priority.name} | {t.route or '-'} | {', '.join(sorted(t.flags)) or '-'} "
            f"| {', '.join(t.ticket.escalated_to) or '-'} "
            f"| {', '.join(f'${r.amount_usd:g} {_refund_label(r.status)}' for r in refunds) or '-'} "
            f"| {draft.draft_id if draft else ('see ' + t.duplicate_of if t.duplicate_of else '-')} |"
        )

    for t in triaged:
        ticket = t.ticket
        out += [
            "",
            f"## {ticket.ticket_id}: {ticket.subject}",
            "",
            f"{ticket.channel}, {t.language}, waiting {t.age.total_seconds() / 3600:.0f}h. "
            f"Priority {t.priority.name}, route {t.route or 'agent'}.",
            "",
            "**Customer wrote:**",
            "",
            *_quote(ticket.message),
            "",
        ]
        if t.signals:
            out += ["**Signals**", "", *[f"- `{s.flag}` {s.evidence}" for s in t.signals], ""]
        for e in desk.escalations_for(ticket.ticket_id):
            out += [f"**Escalated to {e.team}:** {e.reason}", ""]
        for r in desk.refunds_for(ticket.ticket_id):
            out += [f"**Refund request {r.refund_id}:** ${r.amount_usd:g}, {r.status}. {r.reason}", ""]
        if t.duplicate_of:
            out += [f"Answered on {t.duplicate_of}.", ""]
        if draft := _latest_draft(desk, ticket.ticket_id):
            out += [
                f"**Draft {draft.draft_id}** ({draft.status}), cites {', '.join(draft.policy_refs) or 'nothing'}:",
                "",
                *_quote(draft.body),
                "",
                f"**Reviewer note:** {draft.note_for_reviewer}",
            ]
            out += [f"- {w}" for w in draft.warnings]
        elif not t.duplicate_of:
            out.append("_No draft._")
    return "\n".join(out) + "\n"


def _quote(text: str) -> list[str]:
    """A markdown blockquote that wraps on GitHub, unlike a code block. The trailing
    double space keeps the reply's own line breaks, e.g. in the sign-off."""
    return [f"> {line}  " if line.strip() else ">" for line in text.splitlines()]


def _export_ids(desk: SupportDesk, open_only: bool) -> list[str]:
    tickets = load_tickets(desk.settings.data_dir / "tickets.json")
    return [t.ticket_id for t in tickets if t.is_open or not open_only]


def _latest_draft(desk: SupportDesk, ticket_id: str):
    live = [d for d in desk.drafts_for(ticket_id) if d.review_comment != "superseded by a newer draft"]
    return live[-1] if live else None


def _refund_label(status: RefundStatus) -> str:
    return {RefundStatus.AWAITING_APPROVAL: "awaiting approval"}.get(status, status.value.replace("_", " "))


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


if __name__ == "__main__":
    raise SystemExit(main())
