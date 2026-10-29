"""Current support policy, as citable clauses.

The export contains two handbooks, a bonus terms page, a marketing draft and
finance notes. Only two of those are policy an agent may quote to a customer:

* support-handbook-v2.md (effective 15 Aug 2026, supersedes v1.3)
* bonus-terms.md (effective 1 Jun 2026)

Everything else is either superseded (v1), unpublished (the Q4 marketing plan)
or internal (finance notes). Superseded guidance is kept here on purpose, as
patterns, because the team is still repeating it and the reply checker needs to
recognise it.

Clauses are parsed from the markdown rather than retyped, so an updated
handbook flows through without code changes. The numeric limits below are the
exception: they drive decisions, so they are constants, and a test pins them to
the handbook text so the two can't drift apart silently.
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

HANDBOOK_FILE = "support-handbook-v2.md"
BONUS_TERMS_FILE = "bonus-terms.md"

AGENT_REFUND_LIMIT_USD = 100
FIRST_REPLY_TARGET = timedelta(hours=1)
WITHDRAWAL_PENDING_LIMIT = timedelta(hours=24)
WITHDRAWAL_PROCESSING_LIMIT_BUSINESS_DAYS = 3


@dataclass(frozen=True)
class Clause:
    ref: str
    text: str


@dataclass(frozen=True)
class Section:
    source: str
    title: str
    clauses: tuple[Clause, ...]

    @property
    def text(self) -> str:
        return " ".join(c.text for c in self.clauses)


@dataclass(frozen=True)
class SupersededRule:
    """Guidance the team still follows that current policy contradicts.

    `pattern` must appear in a sentence that also matches `context`, and not
    `unless`, so "your $200 withdrawal" isn't mistaken for the old refund limit.
    Rules are skipped on tickets in `not_for` categories: "3-5 business days"
    is wrong for a withdrawal and right for a failed-deposit reversal.
    """

    pattern: re.Pattern[str]
    context: re.Pattern[str]
    said: str
    origin: str
    correct_ref: str
    unless: re.Pattern[str] | None = None
    not_for: frozenset[str] = frozenset()

    def matches(self, sentence: str, category: str = "") -> bool:
        return bool(
            category not in self.not_for
            and self.pattern.search(sentence)
            and self.context.search(sentence)
            and not (self.unless and self.unless.search(sentence))
        )


@dataclass(frozen=True)
class InternalNotice:
    """Context an agent should know but must not quote to a customer."""

    categories: frozenset[str]
    text: str
    source: str


_REFUND_WORDS = re.compile(r"refund|goodwill|compensat|limit|discretion", re.I)
_WITHDRAWAL_WORDS = re.compile(r"withdr|arrive|process|payout|rút|về tài khoản", re.I)
# "It's been more than 48 hours" describes the wait; it doesn't promise a timeline.
_NOT_A_TIMELINE = re.compile(
    r"deposit|revers|nạp|hoàn|trả lại|"
    r"\b(more than|over|longer than|past|after|already|since)\s(\w+\s)?(48|2|two|3|three|5|five)\b|"
    r"\bdays? ago\b|\bhours? ago\b",
    re.I,
)
_BONUS_WORDS = re.compile(r"bonus|wager", re.I)

SUPERSEDED: tuple[SupersededRule, ...] = (
    SupersededRule(
        re.compile(r"\$\s?200\b|\b200\s?(usd|dollars)\b|usd\s?200\b", re.I),
        _REFUND_WORDS,
        "agents can refund up to $200",
        "handbook v1.3",
        "handbook/refunds#1",
    ),
    SupersededRule(
        re.compile(r"\b(48\s?(hours|hrs|h|giờ)|(2|two) days)\b", re.I),
        _WITHDRAWAL_WORDS,
        "withdrawals are processed within 48 hours",
        "handbook v1.3",
        "handbook/withdrawals#1",
        unless=_NOT_A_TIMELINE,
        not_for=frozenset({"deposit"}),
    ),
    SupersededRule(
        re.compile(r"\b(3|three)\s?(-|–|to)\s?(5|five)\s?(business\s|working\s)?(days|ngày)", re.I),
        _WITHDRAWAL_WORDS,
        "withdrawals arrive within 3-5 days",
        "handbook v1.3",
        "handbook/withdrawals#1",
        unless=_NOT_A_TIMELINE,
        not_for=frozenset({"deposit"}),
    ),
    SupersededRule(
        re.compile(r"\b(up to|within)\s(5|five)\s((business|working)\s)?days\b", re.I),
        _WITHDRAWAL_WORDS,
        "withdrawals can take up to 5 days",
        "handbook v1.3",
        "handbook/withdrawals#1",
        unless=_NOT_A_TIMELINE,
        not_for=frozenset({"deposit"}),
    ),
    SupersededRule(
        re.compile(
            r"\b(any|all|every)\s(casino\s)?games?\b(\W+\w+){0,6}?\W+(count|contribut|qualif)"
            r"|\b(use|play)\b[^.]{0,30}\bon (any|all|every) (casino )?games?\b",
            re.I,
        ),
        _BONUS_WORDS,
        "all games count towards bonus wagering",
        "Slack 18 Sep, and the reply on T-5011",
        "bonus-terms/welcome-bonus#4",
        unless=re.compile(r"not all|except|only slots?|only slot games|10\s?%|doesn'?t count|don'?t count", re.I),
    ),
    SupersededRule(
        re.compile(
            r"\b(blackjack|roulette|baccarat|poker|table games?|live (casino|dealer|games?))\b[^.]{0,40}"
            r"\b(count|contribut)\w*\s(fully|in full|100\s?%|the same)",
            re.I,
        ),
        _BONUS_WORDS,
        "table and live games count fully towards bonus wagering",
        "Slack 18 Sep, and the reply on T-5011",
        "bonus-terms/welcome-bonus#4",
    ),
)

# Slack, 17 Sep: "for Gold and above just refund up to $300 if they complain, don't
# wait for me". It contradicts handbook/refunds#2 and is the likeliest source of the
# USD 6,200 of unapproved refunds Finance found. The desk never lets a draft promise
# a refund without a recorded request, which covers it; this note is shown on refund tickets.
SLACK_VIP_REFUND_RULE = (
    "Slack 17 Sep told agents to refund Gold+ customers up to $300 without approval. That "
    "contradicts handbook/refunds#2: anything above USD 100 needs team lead approval first."
)

# The reload bonus terms are "with Legal, not yet published" (marketing draft,
# 22 Sep). Customers asking about these get "not available yet", nothing more.
UNPUBLISHED_PROMOTIONS = re.compile(
    r"reload bonus|loyalty tier|silver and gold perks|holiday calendar|daily free spins", re.I
)
UNPUBLISHED_TERMS = re.compile(
    r"\b50\s?(%|percent|per cent)|fifty percent|(once (a|per)|every|each) week|weekly|\$\s?200\b|"
    r"\b200\s?(usd|dollars)\b|usd\s?200\b|two hundred|\b(1(st)?\s)?oct(ober)?\b|eligib",
    re.I,
)

INTERNAL_NOTICES: tuple[InternalNotice, ...] = (
    InternalNotice(
        frozenset({"withdrawal"}),
        "QuickPay settlement incident 20-24 Sep delayed 312 withdrawals; 14 are still pending "
        "and the Payments team owns them. Treat any QuickPay withdrawal from those dates as a "
        "Payments escalation. Don't quote counts or the expected fix date to customers.",
        "finance-month-end-sept.md",
    ),
    InternalNotice(
        frozenset({"deposit"}),
        "VietPay: 23 deposits failed on bank timeouts in September and were auto-reversed by "
        "the provider. Check the deposit status before saying which case applies.",
        "finance-month-end-sept.md",
    ),
)


class Policy:
    def __init__(self, sections: list[Section]):
        self.sections = sections
        self._clauses = {c.ref: c for s in sections for c in s.clauses}

    @classmethod
    def load(cls, data_dir: Path) -> "Policy":
        return cls(_parse(data_dir / HANDBOOK_FILE, "handbook") + _parse(data_dir / BONUS_TERMS_FILE, "bonus-terms"))

    def clause(self, ref: str) -> Clause | None:
        return self._clauses.get(ref)

    def section_of(self, ref: str) -> Section | None:
        prefix = ref.split("#")[0] + "#"
        return next((s for s in self.sections if s.clauses[0].ref.startswith(prefix)), None)

    def search(self, query: str, limit: int = 3) -> list[Section]:
        """Rank sections by how many query terms they mention. Empty when nothing matches."""
        terms = _terms(query)
        scored = []
        for section in self.sections:
            title = _terms(section.title)
            body = _terms(section.text)
            score = sum(3 * _hits(t, title) + _hits(t, body) for t in terms)
            if score:
                scored.append((score, section))
        scored.sort(key=lambda pair: -pair[0])
        return [section for _, section in scored[:limit]]


# Customers and agents rarely use the handbook's words. Map the common ones.
_SYNONYMS = {
    "blackjack": "table",
    "roulette": "table",
    "baccarat": "table",
    "poker": "table",
    "dealer": "live casino",
    "cashout": "withdrawal",
    "payout": "withdrawal",
    "withdraw": "withdrawal",
    "verify": "verification kyc",
    "passport": "verification kyc",
    "identity": "verification kyc",
    "compensation": "refund",
    "goodwill": "refund",
    "wager": "wagering",
    "addiction": "gambling harm",
    "self-exclusion": "gambling harm self-exclusion",
    "lawyer": "legal",
    "family": "another customer",
    "husband": "another customer",
    "wife": "another customer",
}
_STOPWORDS = frozenset(
    "the a an and or of to in on for is are be can do does how what when why my i you your "
    "with from it this that not if any there their our we us they".split()
)


def _terms(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9-]+", text.lower())
    expanded: list[str] = []
    for word in words:
        expanded.extend(_SYNONYMS.get(word, word).split())
    return [w.rstrip("s") for w in expanded if w not in _STOPWORDS and len(w) > 2]


def _hits(term: str, words: list[str]) -> int:
    # Prefix match in either direction so "withdrawal" finds "withdrawals" and "wager" finds "wagering".
    return sum(1 for w in words if w.startswith(term) or (len(w) >= 5 and term.startswith(w)))


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _parse(path: Path, doc: str) -> list[Section]:
    """One section per `## heading`; one clause per bullet or paragraph beneath it."""
    sections: list[Section] = []
    title: str | None = None
    lines: list[str] = []

    def flush() -> None:
        if title and lines:
            slug = _slug(title)
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
