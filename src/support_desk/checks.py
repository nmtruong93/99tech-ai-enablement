"""Checks a reply before a person sees it.

These rules encode the mistakes that are actually in the export: v1 timelines,
the old $200 refund limit, "any game counts", a KYC reason told to the customer,
refunds promised with no approval. They run on every draft the model saves, again
when a person approves it, and in the backtest on every reply the team already sent.

BLOCK means the draft is not saved; the model gets the reason and rewrites.
WARN means it is saved, and the reviewer sees the warning next to it.

Where money or restricted data is involved the checks deny by default: any
sentence that talks about giving money back is blocked unless an approval covers
it, rather than trying to list every way of promising a refund. Elsewhere they
are a net for known failure modes, not a proof of correctness. The person
reviewing the draft is still the control.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from .models import Customer, Ticket
from .policy import SUPERSEDED, UNPUBLISHED_PROMOTIONS, UNPUBLISHED_TERMS, Policy
from .text import amounts, detect_language, digits, normalise


class Severity(StrEnum):
    BLOCK = "block"
    WARN = "warn"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str
    brief: str = ""

    @property
    def summary(self) -> str:
        """What was wrong, without quoting the reply. Safe to show outside the review itself:
        quoting a reply that leaked a KYC reason would leak it again."""
        return self.brief or _BRIEFS.get(self.code, self.code)

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code}: {self.message}"


_BRIEFS = {
    "kyc_reason_disclosed": "disclosed what the KYC review found",
    "refund_not_approved": "promised a refund with no approval on record",
    "other_customer_data": "included another customer's details",
    "unpublished_terms": "quoted unpublished promotion terms",
    "wrong_language": "was not in the customer's language",
    "encourages_play": "encouraged play",
    "unverified_promise": "promised something nobody had verified",
    "unsourced_amount": "stated an amount with no source",
}


@dataclass(frozen=True)
class ReplyContext:
    ticket: Ticket
    customer: Customer | None
    other_customers: Iterable[Customer]
    policy: Policy
    approved_refund_usd: float = 0.0
    harm_sensitive: bool = False
    category: str = ""


_RESTRICTED_KYC = {"under_review", "rejected"}
# Anything that describes what a KYC check found. For restricted customers none of it may appear.
_KYC_FINDINGS = re.compile(
    r"selfie|photo|picture|your face|likeness|(doesn'?t|does not|didn'?t|did not) (match|line up)|mismatch|"
    r"discrepanc|altered|forged|fake (id|document|passport|selfie)|third[- ]party|someone else|somebody else|"
    r"another person|not (really )?you\b|impersonat|identity theft|fraud|suspicious|stolen",
    re.I,
)
# Any talk of giving money back. Blocked unless an approval covers it or the sentence is
# about the request rather than the outcome ("a senior colleague will review your refund request").
_REFUND_TALK = re.compile(
    r"refund|reimburs|money back|goodwill|compensat|"
    # "you'll get your $250 back", not "I'll get back to you" or "get back into your account"
    r"\b(put|give|get|send|pay|paid|return)\w*\b[^.!?]{0,25}?(money|\$|usd|funds?|amount|stake|bet|deposit|\bit\b|\d)"
    r"[^.!?]{0,15}\bback\b|returned to your|"
    r"credit(ed)?\b[^.!?]{0,25}\b(account|balance|card|wallet)|\ba credit of\b",
    re.I,
)
_ABOUT_THE_REQUEST = re.compile(
    r"request|review|approv|decid|look(ing)? into|investigat|can'?t|cannot|won'?t|unable|not able|"
    r"whether|\bonce\b|\bif\b(?! you (have|need))",
    re.I,
)
_DEPOSIT_REVERSAL = re.compile(r"revers|provider|your bank", re.I)
_REFUSAL = re.compile(r"can'?t|cannot|unable|not able|won'?t|don'?t share|do not share", re.I)
_ACCOUNT_WORDS = re.compile(r"account|withdr|deposit|balance|transaction|money", re.I)
_ATTRIBUTED_TO_EARLIER_REPLY = re.compile(
    r"\b(our|my) (earlier|previous|last) (reply|message|answer|email)|\b(you were|we) (told|said)\b|"
    r"\bincorrect(ly)?\b|\bwasn'?t (accurate|correct|right)\b|\bwrongly\b",
    re.I,
)
_ENCOURAGES_PLAY = re.compile(
    r"good luck|best of luck|enjoy (the|your) games?|come back soon|happy (playing|spinning)", re.I
)
# With gambling-harm signals, anything that invites the customer back to play is out.
_INVITES_PLAY = re.compile(
    r"bonus|free spins?|promotions?|special offers?|welcome (you )?back|come back|see you (soon|again|back)|"
    r"whenever you'?re ready|back to (the )?(tables|games|slots)",
    re.I,
)
_PROMISE = re.compile(r"\b(guarantee\w*|today|tomorrow|right away|should arrive soon|any minute)\b", re.I)
_NO_PROMISE = re.compile(r"(can'?t|cannot|won'?t|unable to) (promise|guarantee)", re.I)
_PLACEHOLDER = re.compile(r"\[[A-Z][A-Z _]*\](?!\()|\{\{.*?\}\}|<(?i:name|amount|date)>")


def check_reply(body: str, ctx: ReplyContext) -> list[Finding]:
    findings: list[Finding] = []
    add = findings.append
    text = normalise(body).strip()
    if not text:
        return [Finding("empty", Severity.BLOCK, "The reply is empty.")]
    sentences = _sentences(text)

    for sentence in sentences:
        for rule in SUPERSEDED:
            if not rule.matches(sentence, ctx.category):
                continue
            current = ctx.policy.clause(rule.correct_ref)
            correcting = bool(_ATTRIBUTED_TO_EARLIER_REPLY.search(sentence))
            add(
                Finding(
                    "superseded_policy",
                    # "Our earlier reply said any game counts" is the correction we want, not the error.
                    Severity.WARN if correcting else Severity.BLOCK,
                    f'"{sentence}" '
                    + (
                        "quotes outdated guidance to correct it; make sure the correction is unmistakable"
                        if correcting
                        else "repeats outdated guidance"
                    )
                    + f" ({rule.said}; from {rule.origin}). "
                    f"Current policy, {rule.correct_ref}: {current.text if current else '(missing)'}",
                    brief=f'said "{rule.said}"; current policy is {rule.correct_ref}',
                )
            )

    if ctx.customer and ctx.customer.kyc_status in _RESTRICTED_KYC and (m := _KYC_FINDINGS.search(text)):
        add(
            Finding(
                "kyc_reason_disclosed",
                Severity.BLOCK,
                f'Mentions "{m.group(0)}". Never share the review reason or what our checks found '
                "(handbook/verification-kyc#2). Say the review is in progress and we'll contact them "
                "if we need anything.",
            )
        )

    for sentence in sentences:
        if problem := _refund_problem(sentence, ctx):
            add(Finding("refund_not_approved", Severity.BLOCK, problem))
            break

    for problem in _other_customer_problems(text, sentences, ctx):
        add(Finding("other_customer_data", Severity.BLOCK, problem))

    if (UNPUBLISHED_PROMOTIONS.search(ctx.ticket.message) or UNPUBLISHED_PROMOTIONS.search(text)) and (
        m := UNPUBLISHED_TERMS.search(text)
    ):
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
                f"Customer wrote in '{expected}', reply is in '{actual}'. Reply in the customer's language "
                "(handbook/response-times#2).",
            )
        )

    pattern = _INVITES_PLAY if ctx.harm_sensitive else _ENCOURAGES_PLAY
    if (m := pattern.search(text)) or (ctx.harm_sensitive and (m := _ENCOURAGES_PLAY.search(text))):
        add(
            Finding(
                "encourages_play",
                Severity.BLOCK if ctx.harm_sensitive else Severity.WARN,
                f'"{m.group(0)}" encourages play.'
                + (" This customer has shown gambling-harm signals or is self-excluded." if ctx.harm_sensitive else ""),
            )
        )

    if m := _PLACEHOLDER.search(text):
        add(Finding("placeholder", Severity.BLOCK, f'Unfilled placeholder "{m.group(0)}".'))

    if (m := _PROMISE.search(text)) and not _NO_PROMISE.search(text):
        add(
            Finding(
                "unverified_promise",
                Severity.WARN,
                f'"{m.group(0)}" may promise a date or outcome nobody has verified (handbook/response-times#3).',
            )
        )

    known = amounts(ctx.ticket.subject + " " + ctx.ticket.message) | amounts(
        " ".join(s.text for s in ctx.policy.sections)
    )
    if ctx.approved_refund_usd:
        known.add(round(ctx.approved_refund_usd, 2))
    for amount in sorted(amounts(text) - known):
        add(
            Finding(
                "unsourced_amount",
                Severity.WARN,
                f"The amount {amount:g} isn't in the ticket or current policy. Check where it came from.",
            )
        )

    return findings


def _refund_problem(sentence: str, ctx: ReplyContext) -> str | None:
    if not (m := _REFUND_TALK.search(sentence)):
        return None
    if ctx.category == "deposit" and _DEPOSIT_REVERSAL.search(sentence):
        return None  # a failed deposit reversed by the provider (handbook/deposits#1), not a refund from us
    if ctx.approved_refund_usd <= 0:
        if _ABOUT_THE_REQUEST.search(sentence):
            return None
        return (
            f'"{sentence}" talks about giving money back ("{m.group(0)}"), but no refund is approved for this '
            "ticket. Say the request is being reviewed and promise nothing; record it with request_refund "
            "(handbook/refunds#2)."
        )
    if over := [a for a in amounts(sentence) if a > ctx.approved_refund_usd]:
        return (
            f'"{sentence}" mentions ${max(over):g}, but only ${ctx.approved_refund_usd:g} is approved '
            "for this ticket (handbook/refunds#2)."
        )
    return None


def _other_customer_problems(text: str, sentences: list[str], ctx: ReplyContext) -> list[str]:
    lowered = " ".join(text.lower().split())
    reply_digits = digits(text)
    problems = []
    for other in ctx.other_customers:
        if other.customer_id == ctx.ticket.customer_id:
            continue
        exact = [other.full_name.lower(), other.email.lower(), other.customer_id.lower()]
        phone = digits(other.phone)
        if any(v in lowered for v in exact) or (len(phone) >= 8 and phone in reply_digits):
            problems.append(
                f"Contains details of another customer ({other.customer_id}). Never discuss another "
                "customer's account (handbook/privacy#1)."
            )
            continue
        # The customer named someone else ("my husband Rahul"). Saying anything about that
        # person's account, even by first name, discloses it.
        if _mentioned_in(ctx.ticket.message, other):
            name = re.compile(rf"\b{re.escape(other.given_name)}\b|\b(he|his|him|she|her)\b", re.I)
            for sentence in sentences:
                if name.search(sentence) and _ACCOUNT_WORDS.search(sentence) and not _REFUSAL.search(sentence):
                    problems.append(
                        f'"{sentence}" says something about the account of the person the customer asked about. '
                        "Share nothing, not even whether the account exists (handbook/privacy#1)."
                    )
                    break
    return problems


def _mentioned_in(message: str, customer: Customer) -> bool:
    lowered = message.lower()
    return (
        customer.email.lower() in lowered
        or customer.full_name.lower() in lowered
        or (digits(customer.phone) in digits(message) and len(digits(customer.phone)) >= 8)
    )


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
