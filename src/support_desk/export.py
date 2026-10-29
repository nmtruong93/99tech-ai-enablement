"""Read the Customer Support export as it was handed over.

Only tickets.json and customers.csv are data the desk acts on. Policy text is
read by policy.py; the rest of the export (Slack, metrics, finance, marketing)
informed the design and the README but is never served to the model.
"""

import csv
import json
from pathlib import Path

from .models import Customer, Ticket


def load_tickets(path: Path) -> list[Ticket]:
    return [Ticket.model_validate(t) for t in json.loads(path.read_text(encoding="utf-8"))]


def load_customers(path: Path) -> dict[str, Customer]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = [{k: (v if v != "" else None) for k, v in row.items()} for row in csv.DictReader(f)]
    return {row["customer_id"]: Customer.model_validate(row) for row in rows}
