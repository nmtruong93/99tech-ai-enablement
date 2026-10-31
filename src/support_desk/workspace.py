"""Everything the desk writes, as plain JSON a person can open and diff: tickets.json (a working
copy of the export's tickets), drafts.json, escalations.json, refunds.json, outbox.jsonl (replies a
person approved) and audit.jsonl (every action, including drafts the checks blocked).

The export in data/ is never modified. Delete the workspace to start over.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from .models import Draft, Escalation, RefundRequest, Ticket


class Workspace:
    def __init__(self, root: Path, export_tickets: Path):
        self.root = root
        self._export_tickets = export_tickets

    def tickets(self) -> list[Ticket]:
        # Until the first change, the working copy is the export itself.
        path = self.root / "tickets.json"
        return _read(path if path.exists() else self._export_tickets, Ticket)

    def save_ticket(self, ticket: Ticket) -> None:
        _write(self.root / "tickets.json", [ticket if t.ticket_id == ticket.ticket_id else t for t in self.tickets()])

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
        record = {"ticket_id": ticket.ticket_id, "channel": ticket.channel, "approved_by": approved_by, "body": body}
        self._append("outbox.jsonl", {"at": at.isoformat(), "customer_id": ticket.customer_id, **record})

    def log(self, at: datetime, actor: str, action: str, **details: Any) -> None:
        self._append("audit.jsonl", {"at": at.isoformat(), "actor": actor, "action": action, **details})

    def _append(self, name: str, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
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
    path.parent.mkdir(parents=True, exist_ok=True)
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
