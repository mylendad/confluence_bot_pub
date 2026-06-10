import re
from urllib.parse import parse_qs, unquote, urlparse

from shared.utils.text_utils import normalize_text

OWNER_LABELS = [
    "заинтересованные лица",
    "заинтересовпнные лица",
    "владельцы",
    "ответственные",
    "контакты",
]
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SUPPORTED_S2T_SUFFIXES = (".xlsx", ".xls", ".csv")
LATEST_MARKERS = {"новый", "new", "latest", "актуальный"}
FACT_ALIASES = {
    "business_stakeholders": [
        "заинтересованные со стороны бизнеса",
        "заинтересованное лица",
        "заинтересованные лица",
        "заинтересованные фио",
    ],
    "meta_links": ["мета", "ка фо", "карта данных", "смд"],
    "ke": ["кэ"],
    "db_name": ["имя витрины в бд", "витрина в бд", "название витрины в бд"],
    "periodicity": ["периодичность", "частота"],
    "depth": ["глубина"],
    "bank_process": [
        "процесс из реестра",
        "процесс",
        "реестр зарегистрированных процессов",
        "реестр зарегестрированных процессов",
    ],
    "release_changes": ["изменения в релизах"],
    "data_location": [
        "расположение данных",
        "место публикации",
        "источники данных",
        "источник данных",
        "распространение данных",
        "сервис хранения",
    ],
    "data_category": ["категория данных продукта", "категория данных"],
}
JIRA_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
PLACEHOLDER_TEXTS = {
    "получение подробных данных проблемы",
    "статус",
}

def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()

def fact_key(label: str) -> str:
    normalized = normalize_text(label)
    for key, aliases in FACT_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return key
    return "unknown"

def links_from_node(node) -> list[dict[str, str]]:
    links = []
    for link in node.find_all("a"):
        href = link.get("href")
        if not href:
            continue
        links.append({"title": link.get_text(" ", strip=True) or href, "url": href})
    return links

def page_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    page_id = query.get("pageId", [None])[0]
    if page_id:
        return page_id
    path_parts = [part for part in parsed.path.split("/") if part]
    for part in path_parts:
        if part.isdigit():
            return part
    return None

def file_name_from_url(url: str | None) -> str | None:
    if not url:
        return None
    path = urlparse(url).path
    if not path or path.endswith("/"):
        return None
    return unquote(path.rsplit("/", 1)[-1])

def attachment_lookup_key(value: str | None) -> str | None:
    if not value:
        return None
    return unquote(value).strip().casefold()
