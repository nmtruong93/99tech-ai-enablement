"""Small text helpers shared by triage and the reply checks."""

import re

_VIETNAMESE = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)
_THAI = re.compile(r"[฀-๿]")

_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("account_access", re.compile(r"\b2fa\b|two[- ]factor|log ?in|password|locked out|change (my |the )?email", re.I)),
    ("kyc", re.compile(r"verification|verify|passport|\bkyc\b|identity|documents?\b", re.I)),
    ("bonus", re.compile(r"bonus|wager", re.I)),
    ("withdrawal", re.compile(r"withdr|cash ?out|payout|rút tiền|where is my money", re.I)),
    ("deposit", re.compile(r"deposit|nạp tiền|top ?up", re.I)),
    ("complaint", re.compile(r"refund|froze|crash|disappoint|complain|chargeback|lawyer", re.I)),
)

_MONEY = re.compile(r"(?:\$|usd\s?)\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,.]*)\s?(?:usd|dollars|đồng|vnd)\b", re.I)


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


def amounts(text: str) -> set[float]:
    """Money amounts mentioned in text, in whatever currency."""
    found = set()
    for m in _MONEY.finditer(text):
        raw = (m.group(1) or m.group(2)).rstrip(".,")
        # 1.500.000 đồng uses dots as thousands separators; $1,200.50 uses a decimal point.
        if raw.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
            raw = raw.replace(".", "")
        try:
            found.add(round(float(raw.replace(",", "")), 2))
        except ValueError:
            continue
    return found


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)
