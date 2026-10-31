"""Current support policy as citable clauses, parsed from support-handbook-v2.md and bonus-terms.md.

Those are the only two documents in the export an agent may quote to a customer. The v1.3
handbook is superseded, the Q4 marketing plan is unpublished and the finance notes are internal.
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

HANDBOOK_FILE = "support-handbook-v2.md"
BONUS_TERMS_FILE = "bonus-terms.md"

# These drive decisions, so they are constants; test_policy pins them to the handbook text.
AGENT_REFUND_LIMIT_USD = 100
FIRST_REPLY_TARGET = timedelta(hours=1)


@dataclass(frozen=True)
class Clause:
    ref: str
    text: str


@dataclass(frozen=True)
class Section:
    source: str
    title: str
    clauses: tuple[Clause, ...]


class Policy:
    def __init__(self, sections: list[Section]):
        self.sections = sections
        self._clauses = {c.ref: c for s in sections for c in s.clauses}

    @classmethod
    def load(cls, data_dir: Path) -> "Policy":
        return cls(_parse(data_dir / HANDBOOK_FILE, "handbook") + _parse(data_dir / BONUS_TERMS_FILE, "bonus-terms"))

    def clause(self, ref: str) -> Clause | None:
        return self._clauses.get(ref)

    @property
    def text(self) -> str:
        return " ".join(c.text for c in self._clauses.values())


def _parse(path: Path, doc: str) -> list[Section]:
    """One section per `## heading`; one clause per bullet or paragraph beneath it."""
    sections: list[Section] = []
    title: str | None = None
    lines: list[str] = []

    def flush() -> None:
        if title and lines:
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            clauses = tuple(Clause(f"{doc}/{slug}#{i}", text) for i, text in enumerate(lines, 1))
            sections.append(Section(path.name, title, clauses))

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            flush()
            title, lines = line[3:].strip(), []
        elif title and line:
            lines.append(line.removeprefix("- ").strip())
    flush()
    return sections


# Copied by hand from the rest of this export. None of it is policy, but the desk needs it.

# Slack, 17 Sep. Shown on refund tickets and at the top of the report.
SLACK_VIP_REFUND_RULE = (
    "Slack 17 Sep told agents to refund Gold+ customers up to $300 without approval. That "
    "contradicts handbook/refunds#2: anything above USD 100 needs team lead approval first."
)

# Marketing draft, 22 Sep: the reload bonus terms are "with Legal, not yet published".
UNPUBLISHED_PROMOTIONS = re.compile(
    r"reload bonus|loyalty tier|silver and gold perks|holiday calendar|daily free spins", re.I
)
UNPUBLISHED_TERMS = re.compile(
    r"\b50\s?(%|percent|per cent)|fifty percent|(once (a|per)|every|each) week|weekly|\$\s?200\b|"
    r"\b200\s?(usd|dollars)\b|usd\s?200\b|two hundred|\b(1(st)?\s)?oct(ober)?\b|eligib",
    re.I,
)

# finance-month-end-sept.md: context for agents, never to be quoted to customers. (category, note)
INTERNAL_NOTICES = (
    (
        "withdrawal",
        "QuickPay settlement incident 20-24 Sep delayed 312 withdrawals; 14 are still pending and the "
        "Payments team owns them. Treat any QuickPay withdrawal from those dates as a Payments escalation. "
        "Don't quote counts or the expected fix date to customers.",
    ),
    (
        "deposit",
        "VietPay: 23 deposits failed on bank timeouts in September and were auto-reversed by the provider. "
        "Check the deposit status before saying which case applies.",
    ),
)
