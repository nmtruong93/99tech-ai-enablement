"""Text helpers shared by triage and the reply checks."""

import re

from .models import Customer

_VIETNAMESE = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)
_THAI = re.compile(r"[฀-๿]")

# Words for giving money back, in the languages the team answers in. Triage reads them as a
# refund request; the reply checks treat them as a refund promise unless an approval covers it.
REFUND_WORDS = r"refund|reimburs|money back|compensat|hoàn tiền|hoàn lại|trả lại|คืนเงิน"

_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("account_access", re.compile(r"\b2fa\b|two[- ]factor|log ?in|password|locked out|change (my |the )?email", re.I)),
    ("kyc", re.compile(r"verification|verify|passport|\bkyc\b|identity|documents?\b", re.I)),
    ("bonus", re.compile(r"bonus|wager", re.I)),
    ("withdrawal", re.compile(r"withdr|cash ?out|payout|rút tiền|where is my money", re.I)),
    ("deposit", re.compile(r"deposit|nạp tiền|top ?up", re.I)),
    ("complaint", re.compile(rf"{REFUND_WORDS}|froze|crash|disappoint|complain|chargeback|lawyer", re.I)),
)

_MONEY = re.compile(r"(?:\$|usd\s?)\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,.]*)\s?(usd|dollars|đồng|vnd)\b", re.I)


def normalise(text: str) -> str:
    """Curly apostrophes defeat every "can't"/"we've" pattern, and phones type them by default."""
    return text.replace("’", "'").replace("‘", "'")


def detect_language(text: str) -> str:
    """Good enough for routing: the export's non-English tickets are Vietnamese and (per Slack) Thai."""
    if _THAI.search(text):
        return "th"
    if len(_VIETNAMESE.findall(text)) >= 2:
        return "vi"
    return "en"


def categorise(subject: str, message: str) -> str:
    """Map a ticket onto the categories used in support-metrics-sept.csv."""
    text = f"{subject} {message}"
    return next((name for name, rx in _CATEGORY_RULES if rx.search(text)), "other")


def amounts(text: str) -> set[tuple[float, str]]:
    """Money mentioned in text, as (value, currency). Only USD and VND appear in the export."""
    found = set()
    for m in _MONEY.finditer(text):
        raw = (m.group(1) or m.group(2)).rstrip(".,")
        # 1.500.000 đồng uses dots as thousands separators; $1,200.50 uses a decimal point.
        if raw.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
            raw = raw.replace(".", "")
        currency = "VND" if (m.group(3) or "").lower() in ("đồng", "vnd") else "USD"
        found.add((round(float(raw.replace(",", "")), 2), currency))
    return found


def usd(text: str) -> set[float]:
    return {value for value, currency in amounts(text) if currency == "USD"}


def money(value: float, currency: str = "USD") -> str:
    if currency == "USD":
        return f"${value:,.2f}".removesuffix(".00")
    return f"{value:,.0f} {currency}"


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def mentions(text: str, customer: Customer) -> bool:
    """Whether text names a customer by full name, email or phone number (in any format)."""
    lowered = text.lower()
    phone = digits(customer.phone)
    return (
        customer.full_name.lower() in lowered
        or customer.email.lower() in lowered
        or (len(phone) >= 8 and phone in digits(text))
    )
