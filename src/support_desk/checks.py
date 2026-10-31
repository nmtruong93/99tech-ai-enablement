"""Checks a reply when the model saves it, again when a person approves it, and in the backtest
over the replies the team already sent.

BLOCK: the draft isn't saved and the model gets the reason. WARN: it's saved and the reviewer
sees the warning. Talk of giving money back is blocked unless an approval covers it, instead of
trying to list every way of promising a refund. The rest catches the mistakes found in the
export; it proves nothing about mistakes nobody has made yet, which is why a person reviews.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple

from .models import Customer, Ticket
from .policy import UNPUBLISHED_PROMOTIONS, UNPUBLISHED_TERMS, Policy
from .text import REFUND_WORDS, amounts, detect_language, mentions, money, normalise, usd


class Severity(StrEnum):
    BLOCK = "block"
    WARN = "warn"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str
    ref: str = ""  # the clause that applies

    @property
    def summary(self) -> str:
        """What was wrong, without quoting the reply: a reply that leaked a KYC reason must not be repeated."""
        return f"{self.code} ({self.ref})" if self.ref else self.code

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code}: {self.message}"


@dataclass(frozen=True)
class ReplyContext:
    ticket: Ticket
    customer: Customer | None
    other_customers: Iterable[Customer]
    policy: Policy
    approved_refund_usd: float = 0.0
    harm_sensitive: bool = False
    category: str = ""
    sending: bool = False  # a placeholder only warns in a draft; it blocks sending


class OldRule(NamedTuple):
    """Guidance the team still repeats that current policy replaces. It counts in a sentence that
    matches `pattern` and `about`, and not `unless`."""

    said: str
    ref: str
    pattern: re.Pattern[str]
    about: re.Pattern[str]
    unless: re.Pattern[str] | None = None


OLD_RULES = (
    OldRule(
        "agents can refund up to $200 (handbook v1.3)",
        "handbook/refunds#1",
        re.compile(r"\$\s?200\b|\b200\s?(usd|dollars)\b|usd\s?200\b", re.I),
        re.compile(r"refund|goodwill|compensat|limit|discretion", re.I),
    ),
    OldRule(
        "withdrawals take 48 hours, 3-5 days or up to 5 days (handbook v1.3)",
        "handbook/withdrawals#1",
        re.compile(
            r"\b(48\s?(hours|hrs|h|giờ)|(2|two) days)\b|"
            r"\b(3|three)\s?(-|–|to)\s?(5|five)\s?(business\s|working\s)?(days|ngày)|"
            r"\b(up to|within)\s(5|five)\s((business|working)\s)?days\b",
            re.I,
        ),
        re.compile(r"withdr|arrive|process|payout|rút|về tài khoản", re.I),
        # Describing the wait ("more than 48 hours", "2 days ago") or a deposit reversal isn't a promise.
        re.compile(
            r"deposit|revers|nạp|hoàn|trả lại|\bdays? ago\b|\bhours? ago\b|"
            r"\b(more than|over|longer than|past|after|already|since)\s(\w+\s)?(48|2|two|3|three|5|five)\b",
            re.I,
        ),
    ),
    OldRule(
        "all games count towards bonus wagering (Slack 18 Sep)",
        "bonus-terms/welcome-bonus#4",
        re.compile(
            r"\b(any|all|every)\s(casino\s)?games?\b(\W+\w+){0,6}?\W+(count|contribut|qualif)|"
            r"\b(use|play)\b[^.]{0,30}\bon (any|all|every) (casino )?games?\b|"
            r"\b(blackjack|roulette|baccarat|poker|table games?|live (casino|dealer|games?))\b[^.]{0,40}"
            r"\b(count|contribut)\w*\s(fully|in full|100\s?%|the same)",
            re.I,
        ),
        re.compile(r"bonus|wager", re.I),
        re.compile(r"not all|except|only slots?|only slot games|10\s?%|doesn'?t count|don'?t count", re.I),
    ),
)

_RESTRICTED_KYC = {"under_review", "rejected"}
# Anything that describes what a KYC check found. For restricted customers none of it may appear.
_KYC_FINDINGS = re.compile(
    r"your face|likeness|(doesn'?t|does not|didn'?t|did not)( seem to| appear to)? (match|line up)|mismatch|"
    r"discrepanc|altered|forged|fake (id|document|passport|selfie)|third[- ]party|someone else|somebody else|"
    r"another person|not (really )?you\b|impersonat|identity theft|fraud|suspicious|stolen",
    re.I,
)
_REFUND_TALK = re.compile(
    rf"{REFUND_WORDS}|goodwill|"
    # "you'll get your $250 back", not "I'll get back to you" or "get back into your account"
    r"\b(put|give|get|send|pay|paid|return)\w*\b[^.!?]{0,25}?(money|\$|usd|funds?|amount|stake|bet|deposit|\bit\b|\d)"
    r"[^.!?]{0,15}\bback\b|returned to your|"
    r"credit(ed)?\b[^.!?]{0,25}\b(account|balance|card|wallet)|\ba credit of\b",
    re.I,
)
# "A senior colleague will review your refund request" talks about the request, not the outcome.
_ABOUT_THE_REQUEST = re.compile(
    r"request|review|approv|decid|look(ing)? into|investigat|can'?t|cannot|won'?t|unable|not able|"
    r"whether|\bonce\b|\bif\b(?! you (have|need))|yêu cầu|xem xét|\bnếu\b|không thể",
    re.I,
)
_DEPOSIT_REVERSAL = re.compile(r"revers|provider|your bank|nhà cung cấp|ngân hàng", re.I)
_CORRECTING = re.compile(
    r"\b(our|my) (earlier|previous|last) (reply|message|answer|email)|\b(you were|we) (told|said)\b|"
    r"\bincorrect(ly)?\b|\bwasn'?t (accurate|correct|right)\b|\bwrongly\b",
    re.I,
)
_REFUSAL = re.compile(r"can'?t|cannot|unable|not able|won'?t|don'?t share|do not share", re.I)
_ACCOUNT_WORDS = re.compile(r"account|withdr|deposit|balance|transaction|money", re.I)
_ENCOURAGES = r"good luck|best of luck|enjoy (the|your) games?|come back soon|happy (playing|spinning)"
_ENCOURAGES_PLAY = re.compile(_ENCOURAGES, re.I)
# With gambling-harm signals, anything that invites the customer back to play is out too.
_INVITES_PLAY = re.compile(
    rf"{_ENCOURAGES}|free spins?|(your|a|the) bonus (is )?(still )?(waiting|available|ready)|claim (your|a|the) bonus|"
    r"offers? (for|waiting for) you|welcome (you )?back|come back|see you (soon|again|back)|"
    r"whenever you'?re ready|back to (the )?(tables|games|slots)",
    re.I,
)
_PROMISE = re.compile(
    r"\b(guarantee\w*|today|tomorrow|right away|should arrive soon|any minute|hôm nay|ngày mai)\b", re.I
)
_NO_PROMISE = re.compile(r"(can'?t|cannot|won'?t|unable to) (promise|guarantee)", re.I)
_PLACEHOLDER = re.compile(r"\[[A-Z][A-Z _]*\](?!\()|\{\{.*?\}\}|<(?i:name|amount|date)>")


def check_reply(body: str, ctx: ReplyContext) -> list[Finding]:
    text = normalise(body).strip()
    if not text:
        return [Finding("empty", Severity.BLOCK, "The reply is empty.")]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    findings: list[Finding] = []
    add = findings.append

    for sentence in sentences:
        for rule in OLD_RULES:
            # A failed deposit's 3-5 day reversal is current policy, not the old withdrawal timeline.
            if ctx.category == "deposit" and rule.ref.startswith("handbook/withdrawals"):
                continue
            if not (rule.pattern.search(sentence) and rule.about.search(sentence)):
                continue
            if rule.unless and rule.unless.search(sentence):
                continue
            current = ctx.policy.clause(rule.ref)
            # "Our earlier reply said any game counts" is the correction we want, not the error.
            correcting = bool(_CORRECTING.search(sentence))
            what = "quotes old guidance to correct it; make the correction unmistakable" if correcting else "repeats"
            add(
                Finding(
                    "superseded_policy",
                    Severity.WARN if correcting else Severity.BLOCK,
                    f'"{sentence}" {what} old guidance ({rule.said}). '
                    f"Current policy, {rule.ref}: {current.text if current else '(missing)'}",
                    rule.ref,
                )
            )

    if ctx.customer and ctx.customer.kyc_status in _RESTRICTED_KYC and (m := _KYC_FINDINGS.search(text)):
        add(
            Finding(
                "kyc_reason_disclosed",
                Severity.BLOCK,
                f'Mentions "{m.group(0)}". Never share the review reason or what our checks found. Say the '
                "review is in progress and we'll contact them if we need anything.",
                "handbook/verification-kyc#2",
            )
        )

    if problem := next((p for s in sentences if (p := _refund_problem(s, ctx))), None):
        add(Finding("refund_not_approved", Severity.BLOCK, problem, "handbook/refunds#2"))

    for problem in _other_customer_problems(text, sentences, ctx):
        add(Finding("other_customer_data", Severity.BLOCK, problem, "handbook/privacy#1"))

    asked_about_promotion = UNPUBLISHED_PROMOTIONS.search(ctx.ticket.message) or UNPUBLISHED_PROMOTIONS.search(text)
    if asked_about_promotion and (m := UNPUBLISHED_TERMS.search(text)):
        add(
            Finding(
                "unpublished_terms",
                Severity.BLOCK,
                f'"{m.group(0)}" comes from an unpublished marketing draft, or promises eligibility. The terms are '
                "with Legal; say details will be announced and share nothing else.",
            )
        )

    expected, actual = detect_language(ctx.ticket.message), detect_language(text)
    if actual != expected:
        # Detection is confident about diacritics and Thai script, not about their absence:
        # unaccented Vietnamese reads as English. So only a non-English ticket can block.
        add(
            Finding(
                "wrong_language",
                Severity.BLOCK if expected != "en" else Severity.WARN,
                f"Customer wrote in '{expected}', reply is in '{actual}'. Reply in the customer's language.",
                "handbook/response-times#2",
            )
        )

    if m := (_INVITES_PLAY if ctx.harm_sensitive else _ENCOURAGES_PLAY).search(text):
        add(
            Finding(
                "encourages_play",
                Severity.BLOCK if ctx.harm_sensitive else Severity.WARN,
                f'"{m.group(0)}" encourages play.'
                + (" This customer has shown gambling-harm signals or is self-excluded." if ctx.harm_sensitive else ""),
            )
        )

    if m := _PLACEHOLDER.search(text):
        severity = Severity.BLOCK if ctx.sending else Severity.WARN
        add(Finding("placeholder", severity, f'"{m.group(0)}" must be filled in before sending.'))

    if (m := _PROMISE.search(text)) and not _NO_PROMISE.search(text):
        add(
            Finding(
                "unverified_promise",
                Severity.WARN,
                f'"{m.group(0)}" may promise a date or outcome nobody has verified.',
                "handbook/response-times#3",
            )
        )

    known = amounts(f"{ctx.ticket.subject} {ctx.ticket.message} {ctx.policy.text}")
    if ctx.approved_refund_usd:
        known.add((round(ctx.approved_refund_usd, 2), "USD"))
    for value, currency in sorted(amounts(text) - known):
        add(
            Finding(
                "unsourced_amount",
                Severity.WARN,
                f"The amount {money(value, currency)} isn't in the ticket or current policy. Check where it came from.",
            )
        )

    return findings


def _refund_problem(sentence: str, ctx: ReplyContext) -> str | None:
    if not (m := _REFUND_TALK.search(sentence)):
        return None
    if ctx.category == "deposit" and _DEPOSIT_REVERSAL.search(sentence):
        return None  # the provider reversing a failed deposit (handbook/deposits#1), not a refund from us
    if ctx.approved_refund_usd <= 0:
        if _ABOUT_THE_REQUEST.search(sentence):
            return None
        return (
            f'"{sentence}" talks about giving money back ("{m.group(0)}"), but no refund is approved for this '
            "ticket. Say the request is being reviewed and promise nothing; record it with request_refund."
        )
    if over := [a for a in usd(sentence) if a > ctx.approved_refund_usd]:
        return f'"{sentence}" mentions {money(max(over))}, but only {money(ctx.approved_refund_usd)} is approved.'
    return None


def _other_customer_problems(text: str, sentences: list[str], ctx: ReplyContext) -> list[str]:
    problems = []
    for other in ctx.other_customers:
        if other.customer_id == ctx.ticket.customer_id:
            continue
        if mentions(text, other) or other.customer_id.lower() in text.lower():
            problems.append(f"Contains details of another customer ({other.customer_id}).")
            continue
        # The customer named someone else ("my husband Rahul"). Saying anything about that
        # person's account, even by first name, discloses it.
        if mentions(ctx.ticket.message, other):
            name = re.compile(rf"\b{re.escape(other.given_name)}\b|\b(he|his|him|she|her)\b", re.I)
            for sentence in sentences:
                if name.search(sentence) and _ACCOUNT_WORDS.search(sentence) and not _REFUSAL.search(sentence):
                    problems.append(
                        f'"{sentence}" says something about the account of the person the customer asked about. '
                        "Share nothing, not even whether the account exists."
                    )
                    break
    return problems
