import re
from datetime import date, datetime

DATE_PATTERNS = [
    (re.compile(r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})"), "%Y-%m-%d"),
    (re.compile(r"(?P<d>\d{2})\.(?P<m>\d{2})\.(?P<y>\d{4})"), "%d.%m.%Y"),
    (re.compile(r"(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})"), "%Y%m%d"),
    (re.compile(r"(?P<d>\d{2})-(?P<m>\d{2})-(?P<y>\d{4})"), "%d-%m-%Y"),
    (re.compile(r"(?P<y>\d{4})_(?P<m>\d{2})_(?P<d>\d{2})"), "%Y_%m_%d"),
]


def parse_date_from_text(text: str) -> date | None:
    for pattern, fmt in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return datetime.strptime(match.group(0), fmt).date()
            except ValueError:
                continue
    return None


def utc_now() -> datetime:
    return datetime.utcnow()
