"""Everything the desk writes, as plain JSON files a person can open and diff.

    workspace/
      tickets.json     working copy of the export's tickets, updated as work happens
      drafts.json      reply drafts and their review state
      escalations.json
      refunds.json     refund requests and approvals (no money moves here)
      outbox.jsonl     replies a person approved for sending
      audit.jsonl      every action, including drafts the checks rejected

The export in data/ is never modified. Delete the workspace to start over.
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from .models import Draft, Escalation, RefundRequest, Ticket


class Workspace:
    def __init__(self, root: Path, export_tickets: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self._tickets = root / "tickets.json"
        if not self._tickets.exists():
            shutil.copyfile(export_tickets, self._tickets)

    def tickets(self) -> list[Ticket]:
        return _read(self._tickets, Ticket)

    def save_ticket(self, ticket: Ticket) -> None:
        tickets = [ticket if t.ticket_id == ticket.ticket_id else t for t in self.tickets()]
        _write(self._tickets, tickets)

    def drafts(self) -> list[Draft]:
        return _read(self.root / "drafts.json", Draft)

    def save_draft(self, draft: Draft) -> None:
        _upsert(self.root / "drafts.json", Draft, draft, "draft_id")

    def escalations(self) -> list[Escalation]:
        return _read(self.root / "escalations.json", Escalation)

    def save_escalation(self, escalation: Escalation) -> None:
        _upsert(self.root / "escalations.json", Escalation, escalation, "escalation_id")

    def refunds(self) -> list[RefundRequest]:
        return _read(self.root / "refunds.json", RefundRequest)

    def save_refund(self, refund: RefundRequest) -> None:
        _upsert(self.root / "refunds.json", RefundRequest, refund, "refund_id")

    def send(self, ticket: Ticket, body: str, approved_by: str, at: datetime) -> None:
        self._append(
            "outbox.jsonl",
            {
                "at": at.isoformat(),
                "ticket_id": ticket.ticket_id,
                "customer_id": ticket.customer_id,
                "channel": ticket.channel,
                "approved_by": approved_by,
                "body": body,
            },
        )

    def log(self, at: datetime, actor: str, action: str, **details: Any) -> None:
        self._append("audit.jsonl", {"at": at.isoformat(), "actor": actor, "action": action, **details})

    def _append(self, name: str, record: dict[str, Any]) -> None:
        with (self.root / name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def next_id(prefix: str, existing: list[str]) -> str:
    numbers = [int(i.split("-")[1]) for i in existing if i.startswith(f"{prefix}-")]
    return f"{prefix}-{max(numbers, default=0) + 1:04d}"


def _read[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    if not path.exists():
        return []
    return TypeAdapter(list[model]).validate_json(path.read_bytes())


def _write(path: Path, records: list[BaseModel]) -> None:
    payload = json.dumps([r.model_dump(mode="json") for r in records], ensure_ascii=False, indent=2)
    # Write then rename, so a crash mid-write never leaves half a file behind.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _upsert[T: BaseModel](path: Path, model: type[T], record: T, key: str) -> None:
    records = _read(path, model)
    index = next((i for i, r in enumerate(records) if getattr(r, key) == getattr(record, key)), None)
    if index is None:
        records.append(record)
    else:
        records[index] = record
    _write(path, records)
