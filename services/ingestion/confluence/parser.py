import logging
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from shared.config.config import Settings
from services.ingestion.confluence.client import ConfluenceClient
from services.ingestion.confluence.jira_client import JiraClient
from services.ingestion.confluence.models import (
    ConfluencePage,
    Datamart,
    DatamartFact,
    ParseResult,
    ReleaseChange,
    S2TResource,
    Stakeholder,
)
from services.ingestion.confluence.urls import confluence_urljoin
from shared.utils.date_utils import parse_date_from_text
from shared.utils.text_utils import fuzzy_contains, normalize_text

logger = logging.getLogger(__name__)

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


class ConfluenceParser:
    """
    Парсер страниц Confluence для извлечения информации о витринах данных.
    Обеспечивает сбор данных о стейкхолдерах, атрибутах витрины, истории релизов и поиск файлов S2T.
    """

    def __init__(
        self,
        client: ConfluenceClient,
        settings: Settings,
        jira_client: JiraClient | None = None,
    ) -> None:
        """
        Инициализирует парсер Confluence.

        :param client: Клиент Confluence для взаимодействия с API.
        :param settings: Объект настроек приложения.
        :param jira_client: Клиент Jira для обогащения информации о задачах (опционально).
        """
        self.client = client
        self.settings = settings
        self.jira_client = jira_client

    def parse(self, dry_run: bool = False, skip_jira: bool = False) -> ParseResult:
        """
        Выполняет поиск и парсинг всех страниц витрин данных, соответствующих заданному паттерну.

        :param dry_run: Флаг тестового запуска без сохранения результатов.
        :param skip_jira: Флаг пропуска обогащения данных из Jira.
        :return: Объект ParseResult, содержащий список найденных витрин.
        """
        result = ParseResult()
        pattern = normalize_text(self.settings.datamart_page_pattern)
        for page in self.client.iter_top_level_pages():
            if pattern not in normalize_text(page.title):
                continue
            logger.info("Found datamart page %s", page.title)
            datamart = self.parse_datamart_page(page, skip_jira=skip_jira)
            logger.info(
                "Parsed datamart=%s stakeholders=%s release_changes=%s s2t=%s",
                datamart.name,
                len(datamart.stakeholders),
                len(datamart.release_changes),
                datamart.s2t_resource.title if datamart.s2t_resource else "-",
            )
            result.datamarts.append(datamart)
        return result

    def parse_datamart_page(self, page: ConfluencePage, skip_jira: bool = False) -> Datamart:
        """
        Парсит содержимое конкретной страницы витрины данных.

        :param page: Объект страницы Confluence.
        :param skip_jira: Флаг пропуска обогащения данных из Jira.
        :return: Объект Datamart с извлеченной информацией.
        """
        # Track all pages visited for this specific datamart
        visited_versions: dict[str, int] = {}
        if page.version:
            visited_versions[page.id] = page.version

        html = page.body_html or ""
        stakeholders = self.extract_stakeholders(html)
        facts = self.extract_datamart_facts(html)

        # Parse checklist if exists
        checklist_facts = self.extract_checklist_facts(page, visited_versions=visited_versions)
        if checklist_facts:
            # Merge facts, avoiding duplicates by key
            existing_keys = {f.key for f in facts}
            for cf in checklist_facts:
                if cf.key not in existing_keys:
                    facts.append(cf)
                    existing_keys.add(cf.key)

        # FINAL DEDUPLICATION: just in case there are multiple facts with same key
        # from the same page or merged. We keep the FIRST occurrence.
        unique_facts = []
        seen_keys = set()
        for f in facts:
            if f.key not in seen_keys:
                unique_facts.append(f)
                seen_keys.add(f.key)
        facts = unique_facts

        release_changes = self.extract_release_changes(
            page, html, visited_versions=visited_versions
        )
        if self.jira_client and not skip_jira:
            self.enrich_release_changes(release_changes)

        candidates = self.find_s2t_candidates(page, visited_versions=visited_versions)
        selected = self.choose_latest_s2t(candidates)

        return Datamart(
            name=page.title,
            confluence_page_id=page.id,
            confluence_url=page.url,
            page_version=page.version,
            page_version_when=page.version_when,
            page_last_modified=page.last_modified,
            page_history_last_updated=page.history_last_updated,
            stakeholders=stakeholders,
            facts=facts,
            release_changes=release_changes,
            s2t_resource=selected,
            visited_pages=visited_versions,
        )

    def extract_checklist_facts(
        self, page: ConfluencePage, visited_versions: dict[str, int] | None = None
    ) -> list[DatamartFact]:
        """
        Извлекает факты (характеристики) витрины со страницы чек-листа, если она существует.

        :param page: Текущая страница витрины.
        :param visited_versions: Словарь для отслеживания версий посещенных страниц.
        :return: Список объектов DatamartFact.
        """
        checklist_page = self._find_checklist_page_recursive(
            page, depth=0, visited=set(), visited_versions=visited_versions
        )
        if not checklist_page or not checklist_page.body_html:
            return []

        logger.info("Parsing checklist page: %s", checklist_page.title)
        soup = BeautifulSoup(checklist_page.body_html, "html.parser")
        facts: list[DatamartFact] = []
        seen: set[tuple[str, str, str]] = set()

        for row in soup.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False) or row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            label = self._clean_text(cells[0].get_text(" ", strip=True))
            value = self._clean_text(cells[1].get_text(" ", strip=True))
            if not label or not value:
                continue

            key = self._fact_key(label)
            if key == "unknown":
                # For checklists, we include all rows, using normalized label as key if unknown
                key = normalize_text(label).replace(" ", "_")

            links = self._links_from_node(cells[1])
            marker = (key, label.casefold(), value)
            if marker in seen:
                continue
            seen.add(marker)
            facts.append(DatamartFact(key=key, label=label, value=value, links=links))

        return facts

    def _find_checklist_page_recursive(
        self,
        page: ConfluencePage,
        depth: int,
        visited: set[str],
        visited_versions: dict[str, int] | None = None,
    ) -> ConfluencePage | None:
        """
        Рекурсивно ищет страницу чек-листа в дочерних страницах.

        :param page: Страница, с которой начинается поиск.
        :param depth: Текущая глубина рекурсии.
        :param visited: Множество ID уже посещенных страниц.
        :param visited_versions: Словарь для отслеживания версий посещенных страниц.
        :return: Объект ConfluencePage или None.
        """
        if page.id in visited or depth > 3:
            return None
        visited.add(page.id)
        if visited_versions is not None and page.version:
            visited_versions[page.id] = page.version

        kw_checklist = normalize_text("чек-лист")
        kw_checklists = normalize_text("чек-листы")

        # 1. Check if CURRENT page is a checklist (unlikely for recursive entry but good for completeness)
        norm_title = normalize_text(page.title)
        if kw_checklist in norm_title and kw_checklists not in norm_title:
            return page

        # 2. Look among children
        try:
            children = self.client.get_children(page.id)

            # Sort children to prefer latest by date in title or just by title
            children = sorted(children, key=lambda c: c.title, reverse=True)

            # First pass: look for direct checklist
            for child in children:
                c_norm_title = normalize_text(child.title)
                if kw_checklist in c_norm_title and kw_checklists not in c_norm_title:
                    logger.info("Found checklist page: %s", child.title)
                    full_page = self.client.get_page(child.id)
                    if visited_versions is not None and full_page.version:
                        visited_versions[full_page.id] = full_page.version
                    return full_page

            # Second pass: look for "Check-lists" folder and dive into it
            for child in children:
                c_norm_title = normalize_text(child.title)
                if kw_checklists in c_norm_title:
                    logger.info("Found checklists folder: %s", child.title)
                    res = self._find_checklist_page_recursive(
                        child, depth + 1, visited, visited_versions=visited_versions
                    )
                    if res:
                        return res

        except Exception as exc:
            logger.warning("Error searching checklists for %s: %s", page.id, exc)

        return None

    def enrich_release_changes(self, changes: list[ReleaseChange]) -> None:
        """
        Обогащает список изменений релиза данными из Jira (даты создания, завершения, доп. поля).

        :param changes: Список объектов ReleaseChange для обогащения.
        """
        if not self.jira_client:
            logger.warning("JiraClient is None. Skipping Jira enrichment.")
            return
        field_mapping = self.jira_client.get_field_mapping()
        logger.info(f"Enriching {len(changes)} release changes with Jira data...")
        for change in changes:
            if not change.jira_key:
                continue
            logger.info(f"Fetching Jira issue: {change.jira_key}")
            issue = self.jira_client.get_issue(change.jira_key)
            if not issue:
                continue
            fields = issue.get("fields", {})
            created = fields.get("created")
            if created:
                try:
                    change.jira_created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except Exception:
                    logger.warning("Failed to parse Jira created date: %s", created)

            # 1. Пытаемся взять дату решения напрямую из системного поля
            resolution_date = fields.get("resolutiondate")
            if resolution_date:
                try:
                    change.jira_done_at = datetime.fromisoformat(
                        resolution_date.replace("Z", "+00:00")
                    )
                except Exception:
                    logger.warning("Failed to parse Jira resolution date: %s", resolution_date)

            # 2. Если даты решения нет, ищем в истории изменений (changelog)
            if not change.jira_done_at:
                changelog = issue.get("changelog", {})
                histories = changelog.get("histories", [])
                # Сортируем истории: от новых к старым
                histories.sort(key=lambda x: x.get("created", ""), reverse=True)

                # Ищем дату завершения (поле Status или Решение)
                tag = (change.change_type or "").lower()
                done_statuses = {
                    "сделан",
                    "сделано",
                    "done",
                    "resolved",
                    "решено",
                    "закрыт",
                    "closed",
                    "выполнено",
                    "выполнен",
                    "завершено",
                    "завершен",
                    "готово",
                    "готов",
                }

                for history in histories:
                    history_created = history.get("created")
                    found_done_in_this_history = False
                    for item in history.get("items", []):
                        field_name = (item.get("field") or "").lower()
                        status_name = (item.get("toString") or "").lower()

                        # Проверяем системные поля (Status, Resolution/Решение) или поле-тег из Confluence
                        is_done_field = field_name in {"status", "resolution", "решение"}
                        is_tag_field = tag and field_name == tag

                        if (is_done_field or is_tag_field) and status_name in done_statuses:
                            found_done_in_this_history = True
                            break

                    if found_done_in_this_history and history_created:
                        try:
                            # Jira присылает дату типа 2025-10-15T14:04:57.000+0300
                            clean_date = history_created.replace("Z", "+00:00")
                            change.jira_done_at = datetime.fromisoformat(clean_date)
                            break
                        except Exception as exc:
                            logger.warning(
                                "Failed to parse Jira history date %s: %s", history_created, exc
                            )

            # 3. Ищем значение для конкретного типа изменения (если есть)
            tag = (change.change_type or "").lower()
            if tag:
                tag_upper = tag.upper()
                found_value = None
                # Сначала ищем в истории (для динамических статусов)
                # Note: histories might not be defined if resolutiondate was found directly
                changelog = issue.get("changelog", {})
                current_histories = changelog.get("histories", [])

                for history in current_histories:
                    for item in history.get("items", []):
                        if (item.get("field") or "").upper() == tag_upper:
                            found_value = item.get("toString")
                            break
                    if found_value:
                        break

                if not found_value and tag_upper in field_mapping:
                    field_id = field_mapping[tag_upper]
                    found_value = fields.get(field_id)

                change.jira_last_activity_value = found_value

    def extract_stakeholders(self, html: str) -> list[Stakeholder]:
        """
        Извлекает информацию о стейкхолдерах (владельцах, контактах) из HTML-содержимого страницы.

        :param html: HTML-код страницы.
        :return: Список объектов Stakeholder.
        """
        soup = BeautifulSoup(html, "html.parser")
        stakeholders: list[Stakeholder] = []
        for row in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            if len(cells) >= 2 and fuzzy_contains(cells[0], OWNER_LABELS):
                stakeholders.extend(self._stakeholders_from_text(cells[1], row))
        if stakeholders:
            return stakeholders
        text = soup.get_text("\n", strip=True)
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if fuzzy_contains(line, OWNER_LABELS):
                block = " ".join(lines[idx + 1 : idx + 5])
                stakeholders.extend(self._stakeholders_from_text(block, None))
                break
        return stakeholders

    def extract_datamart_facts(self, html: str) -> list[DatamartFact]:
        """
        Извлекает основные атрибуты витрины данных из таблиц на странице.
        Поддерживает как вертикальные (ключ-значение), так и горизонтальные таблицы,
        а также вложенные таблицы внутри ячеек.
        """
        soup = BeautifulSoup(html, "html.parser")
        facts: list[DatamartFact] = []
        seen: set[tuple[str, str, str]] = set()

        for table in soup.find_all("table"):
            # 1. Проверяем, является ли таблица горизонтальной (заголовки в первой строке)
            header_row = table.find("tr")
            if not header_row:
                continue

            headers = [
                self._clean_text(th.get_text(" ", strip=True))
                for th in header_row.find_all("th", recursive=False)
            ]

            # Если это широкая таблица (заголовков много), парсим каждую строку как отдельный факт
            if len(headers) >= 3:
                table_title = ""
                # Пытаемся найти заголовок таблицы в тексте выше
                prev_node = table.find_previous(["h1", "h2", "h3", "h4", "p"])
                if prev_node:
                    table_title = self._clean_text(prev_node.get_text(" ", strip=True))

                for row in table.find_all("tr")[1:]:  # Пропускаем заголовок
                    cells = row.find_all(["td", "th"], recursive=False)
                    if len(cells) == len(headers):
                        row_parts = []
                        for i, cell in enumerate(cells):
                            cell_val = self._clean_text(cell.get_text(" ", strip=True))
                            if cell_val and headers[i]:
                                row_parts.append(f"{headers[i]}: {cell_val}")

                        if row_parts:
                            full_val = " | ".join(row_parts)
                            key = self._fact_key(table_title) if table_title else "table_row"
                            label = table_title or "Данные таблицы"
                            facts.append(
                                DatamartFact(
                                    key=key,
                                    label=label,
                                    value=full_val,
                                    links=self._links_from_node(row),
                                )
                            )
                continue  # Горизонтальную таблицу обработали, идем дальше

            # 2. Обработка вертикальных таблиц (Ключ в левой колонке)
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                if len(cells) < 2:
                    continue

                label_node = cells[0]
                value_node = cells[1]

                label = self._clean_text(label_node.get_text(" ", strip=True))
                if not label:
                    continue

                key = self._fact_key(label)
                # Даже если ключ unknown, для чек-листов мы часто хотим сохранить строку,
                # но здесь полагаемся на фильтрацию по FACT_ALIASES для чистоты RAG
                if key == "unknown":
                    continue

                # Обработка вложенных таблиц внутри ячейки значения (как в вашем примере)
                if value_node.find("table"):
                    sub_table = value_node.find("table")
                    sub_rows_texts = []
                    sub_header_tr = sub_table.find("tr")
                    if sub_header_tr:
                        sub_headers = [
                            self._clean_text(th.get_text(" ", strip=True))
                            for th in sub_header_tr.find_all(["th", "td"])
                        ]
                        for sub_tr in sub_table.find_all("tr")[1:]:
                            sub_tds = sub_tr.find_all(["td", "th"])
                            if len(sub_tds) == len(sub_headers):
                                row_str = "; ".join(
                                    f"{sub_headers[i]}: {self._clean_text(td.get_text())}"
                                    for i, td in enumerate(sub_tds)
                                )
                                sub_rows_texts.append(row_str)

                    if sub_rows_texts:
                        value = " [ " + " | ".join(sub_rows_texts) + " ] "
                    else:
                        value = self._clean_text(value_node.get_text(" ", strip=True))
                else:
                    value = self._clean_text(value_node.get_text(" ", strip=True))

                if not value:
                    continue

                marker = (key, label.casefold(), value)
                if marker in seen:
                    continue
                seen.add(marker)
                facts.append(
                    DatamartFact(
                        key=key, label=label, value=value, links=self._links_from_node(value_node)
                    )
                )

        return facts

    def extract_release_changes(
        self, page: ConfluencePage, html: str, visited_versions: dict[str, int] | None = None
    ) -> list[ReleaseChange]:
        """
        Находит и парсит историю изменений (релизов) для витрины.

        :param page: Страница витрины.
        :param html: HTML-код страницы.
        :param visited_versions: Словарь посещенных версий страниц.
        :return: Список объектов ReleaseChange.
        """
        # Ищем страницу изменений рекурсивно
        release_page = self._find_release_page_recursive(
            page, depth=0, visited=set(), visited_versions=visited_versions
        )
        if not release_page or not release_page.body_html:
            return []
        changes = self.parse_release_changes_page(release_page.body_html, release_page.url)
        # Сортируем изменения для стабильного хэширования
        changes.sort(key=lambda x: (x.version or "", x.jira_key or ""))
        return changes

    def _find_release_page_recursive(
        self,
        page: ConfluencePage,
        depth: int,
        visited: set[str],
        visited_versions: dict[str, int] | None = None,
    ) -> ConfluencePage | None:
        """
        Рекурсивно ищет страницу с журналом изменений.

        :param page: Стартовая страница.
        :param depth: Глубина поиска.
        :param visited: Посещенные ID страниц.
        :param visited_versions: Словарь посещенных версий.
        :return: Объект ConfluencePage или None.
        """
        if page.id in visited or depth > 3:
            return None
        visited.add(page.id)
        if visited_versions is not None and page.version:
            visited_versions[page.id] = page.version

        html = page.body_html
        if html is None:
            try:
                full_page = self.client.get_page(page.id)
                html = full_page.body_html or ""
                if visited_versions is not None and full_page.version:
                    visited_versions[full_page.id] = full_page.version
            except Exception:
                html = ""

        # Пробуем найти ссылку на текущей странице
        found = self._release_page_from_link(page, html, visited_versions=visited_versions)
        if found:
            return found

        # Если не нашли, идем в дочерние страницы
        try:
            children = self.client.get_children(page.id)
            for child in children:
                # Если сама страница называется "Изменения...", берем её
                norm_title = normalize_text(child.title)
                if any(
                    kw in norm_title
                    for kw in ["изменения в релизах", "журнал изменений", "список изменений"]
                ):
                    logger.info(f"Found release changes by child page title: '{child.title}'")
                    full_child = self.client.get_page(child.id)
                    if visited_versions is not None and full_child.version:
                        visited_versions[full_child.id] = full_child.version
                    return full_child

                # Иначе рекурсивно ищем внутри дочерней
                res = self._find_release_page_recursive(
                    child, depth + 1, visited, visited_versions=visited_versions
                )
                if res:
                    return res
        except Exception:
            pass

        return None

    def parse_release_changes_page(
        self, html: str, source_url: str | None = None
    ) -> list[ReleaseChange]:
        """
        Парсит HTML-содержимое страницы изменений релиза.

        :param html: HTML-код страницы.
        :param source_url: URL страницы-источника.
        :return: Список объектов ReleaseChange.
        """
        soup = BeautifulSoup(html, "html.parser")

        # In Confluence, main content might be nested deep inside layouts, columns, or macros
        # So we search globally, not just at the top level
        changes: list[ReleaseChange] = []

        current_version = "Неизвестная версия"
        current_jira_keys = []
        current_jira_titles = {}  # Map key -> title
        current_status = None

        # Перебираем ВСЕ элементы на странице последовательно
        for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "ul", "ol"]):
            text = self._clean_text(node.get_text(" ", strip=True))
            norm_text = normalize_text(text)

            # 1. Если это заголовок версии
            if node.name in ["h1", "h2", "h3", "h4"] or ("версия" in norm_text and len(text) < 50):
                if (
                    "версия" in norm_text
                    or "релиз" in norm_text
                    or re.search(r"202[0-9]", norm_text)
                ):
                    current_version = text
                    current_jira_keys = []  # Сбрасываем контекст задачи для новой версии
                    current_jira_titles = {}
                    current_status = None
                    continue

            # 2. Ищем ключи Jira и статусы в текущем узле (параграфе или заголовке)
            node_keys = self._jira_keys_from_node(node)
            if node_keys:
                current_jira_keys = node_keys
                # Собираем заголовки
                for key in node_keys:
                    issue_node = node.find(attrs={"data-jira-key": key})
                    if issue_node:
                        title = self._jira_title_from_node(issue_node)
                        if title:
                            current_jira_titles[key] = title

                # Собираем статус, если он есть в узле
                node_status = self._jira_status_from_node(node)
                if node_status:
                    current_status = node_status

            # 3. Если это список изменений
            if node.name in ["ul", "ol"]:
                for item in node.find_all("li", recursive=False):
                    # Ключи могут быть внутри li или наследоваться от родительского p
                    item_keys = self._jira_keys_from_node(item) or current_jira_keys

                    if not item_keys:
                        continue

                    # Если ключи в самом li, собираем заголовки и оттуда
                    for key in self._jira_keys_from_node(item):
                        issue_node = item.find(attrs={"data-jira-key": key})
                        if issue_node:
                            title = self._jira_title_from_node(issue_node)
                            if title:
                                current_jira_titles[key] = title

                    change_type = self._release_change_type(item)
                    summary = self._release_summary(item, change_type)

                    # Статус в li имеет приоритет над статусом в p
                    item_status = self._jira_status_from_node(item) or current_status

                    # Фильтр шаблонов
                    if summary and ("[" in summary and "]" in summary):
                        continue

                    for key in item_keys:
                        changes.append(
                            ReleaseChange(
                                version=current_version,
                                jira_key=key,
                                jira_title=current_jira_titles.get(key),
                                change_type=change_type,
                                summary=summary,
                                status=item_status,
                                source_url=source_url,
                            )
                        )

        return changes

    def find_s2t_candidates(
        self, page: ConfluencePage, visited_versions: dict[str, int] | None = None
    ) -> list[S2TResource]:
        """
        Ищет потенциальные ссылки на файлы S2T на странице и в дочерних элементах.

        :param page: Страница для поиска.
        :param visited_versions: Словарь посещенных версий страниц.
        :return: Список объектов S2TResource.
        """
        return self._find_s2t_recursive(
            page, depth=0, visited=set(), visited_versions=visited_versions
        )

    def _find_s2t_recursive(
        self,
        page: ConfluencePage,
        depth: int,
        visited: set[str],
        visited_versions: dict[str, int] | None = None,
    ) -> list[S2TResource]:
        """
        Рекурсивный поиск файлов S2T.

        :param page: Текущая страница.
        :param depth: Глубина поиска.
        :param visited: Посещенные ID.
        :param visited_versions: Словарь посещенных версий.
        :return: Список объектов S2TResource.
        """
        if page.id in visited or depth > 5:
            return []
        visited.add(page.id)
        if visited_versions is not None and page.version:
            visited_versions[page.id] = page.version

        logger.info(
            "Recursively searching for S2T files on page '%s' (depth %d)", page.title, depth
        )

        html = page.body_html
        if html is None:
            try:
                full_page = self.client.get_page(page.id)
                html = full_page.body_html if full_page and full_page.body_html else ""
                if visited_versions is not None and full_page and full_page.version:
                    visited_versions[full_page.id] = full_page.version
            except Exception:
                logger.warning("Failed to fetch page body for %s", page.id)
                html = ""

        candidates: list[S2TResource] = []
        # 1. Add direct attachments from current page
        attachments = self.client.get_attachments(page.id)
        self._append_new_resources(candidates, attachments)
        attachment_index = self._attachment_index(attachments)

        if html:
            soup = BeautifulSoup(html, "html.parser")
            # 2. Add files found in tables on current page
            self._append_new_resources(
                candidates,
                self._enrich_resources(
                    self._extract_s2t_table_resources(page, soup), attachment_index
                ),
            )

            # 3. Explore links on current page
            for link in soup.find_all("a"):
                title = link.get_text(" ", strip=True) or link.get("href", "")
                href = link.get("href")
                if not href:
                    continue

                parent_text = link.parent.get_text(" ", strip=True) if link.parent else ""

                if "/download/attachments/" in href and (
                    self._looks_like_s2t_file(href, title)
                    or self._looks_like_s2t(title)
                    or self._looks_like_s2t(parent_text)
                ):
                    file_name = self._file_name_from_url(href)
                    resource_title = file_name or title
                    self._append_new_resources(
                        candidates,
                        [
                            self._enrich_resource(
                                S2TResource(
                                    title=resource_title,
                                    url=confluence_urljoin(page.url, href),
                                    file_name=file_name or resource_title,
                                    resource_type="link",
                                    file_date=parse_date_from_text(resource_title),
                                    updated_at=page.updated_at,
                                ),
                                attachment_index,
                            )
                        ],
                    )
                elif ("pageId=" in href or "/display/" in href) and self._looks_like_s2t(
                    f"{title} {parent_text}"
                ):
                    child_page_id = self._page_id_from_url(href)
                    if child_page_id and child_page_id not in visited:
                        try:
                            child_page = self.client.get_page(child_page_id)
                            if child_page:
                                recursive_files = self._find_s2t_recursive(
                                    child_page,
                                    depth + 1,
                                    visited,
                                    visited_versions=visited_versions,
                                )
                                self._append_new_resources(candidates, recursive_files)
                        except Exception as exc:
                            logger.warning(
                                "Failed to fetch or process linked page %s: %s", child_page_id, exc
                            )

            # Look for attachment references (ac:link / ri:attachment) anywhere in the body
            for attachment_name in self._attachment_references(soup):
                self._append_new_resources(
                    candidates,
                    [
                        self._enrich_resource(
                            self._resource_from_attachment_reference(
                                page=page,
                                file_name=attachment_name,
                                resource_type="body_reference",
                                row_number=0,
                            ),
                            attachment_index,
                        )
                    ],
                )

        # 4. Explore direct child pages
        for child in self.client.get_children(page.id):
            if self._looks_like_s2t(child.title):
                recursive_files = self._find_s2t_recursive(
                    child, depth + 1, visited, visited_versions=visited_versions
                )
                self._append_new_resources(candidates, recursive_files)

        file_candidates = [
            c
            for c in candidates
            if c.file_name and c.file_name.lower().endswith(SUPPORTED_S2T_SUFFIXES)
        ]

        for candidate in file_candidates:
            candidate.file_date = candidate.file_date or parse_date_from_text(candidate.title)

        return file_candidates

    def _release_page_from_link(
        self, page: ConfluencePage, html: str, visited_versions: dict[str, int] | None = None
    ) -> ConfluencePage | None:
        """
        Ищет ссылку на страницу изменений релиза в HTML-коде текущей страницы.

        :param page: Текущая страница.
        :param html: HTML-код для анализа.
        :param visited_versions: Словарь посещенных версий.
        :return: Объект ConfluencePage или None.
        """
        # Исключаем страницы-шаблоны
        if "шаблон" in normalize_text(page.title):
            return None

        # 1. Сначала ищем среди дочерних страниц по заголовку
        try:
            children = self.client.get_children(page.id)
            for child in children:
                norm_child_title = normalize_text(child.title)
                if any(
                    kw in norm_child_title
                    for kw in ["изменения в релизах", "журнал изменений", "список изменений"]
                ):
                    # Игнорируем если это шаблон
                    if "шаблон" in norm_child_title:
                        continue
                    logger.info(f"Found release changes child page: '{child.title}'")
                    full_child = self.client.get_page(child.id)
                    if visited_versions is not None and full_child.version:
                        visited_versions[full_child.id] = full_child.version
                    return full_child
        except Exception:
            pass

        soup = BeautifulSoup(html, "html.parser")

        # 2. Ищем все возможные ссылки (и <a> и <ac:link>)
        # Confluence Storage Format использует ac:link для внутренних ссылок
        for link_tag in soup.find_all(["a", "ac:link"]):
            # Для ac:link текст может быть в разных местах
            link_text = ""
            page_id = None

            if link_tag.name == "a":
                link_text = link_tag.get_text(" ", strip=True)
                page_id = self._page_id_from_url(link_tag.get("href", ""))
            else:
                # ac:link - ищем ri:page
                ri_page = link_tag.find("ri:page")
                if ri_page:
                    link_text = ri_page.get("ri:content-title") or ""
                    # Если текста нет в ri:page, смотрим ac:link-body
                    if not link_text:
                        link_text = link_tag.get_text(" ", strip=True)

            if not link_text:
                continue

            norm_text = normalize_text(link_text)
            if any(
                kw in norm_text
                for kw in [
                    "изменения в релизах",
                    "журнал изменений",
                    "список изменений",
                    "история изменений",
                ]
            ):
                # Если нашли по тексту, но нет page_id (для ac:link), пробуем достать из ri:page
                if not page_id and link_tag.name == "ac:link":
                    ri_page = link_tag.find("ri:page")
                    if ri_page:
                        # В storage format обычно есть title, по нему можно найти
                        title = ri_page.get("ri:content-title")
                        if title:
                            # Ищем страницу по заголовку в этом же пространстве
                            for child in self.client.get_children(page.id):
                                if child.title == title:
                                    page_id = child.id
                                    break

                if page_id:
                    logger.info(f"Found release changes link '{link_text}' (ID: {page_id})")
                    try:
                        full_page = self.client.get_page(page_id)
                        if visited_versions is not None and full_page.version:
                            visited_versions[full_page.id] = full_page.version
                        return full_page
                    except Exception:
                        pass

        return None

    def _extract_s2t_table_resources(
        self, page: ConfluencePage, soup: BeautifulSoup
    ) -> list[S2TResource]:
        """
        Извлекает ссылки на файлы S2T из таблиц на странице.

        :param page: Текущая страница.
        :param soup: Объект BeautifulSoup для анализа.
        :return: Список объектов S2TResource.
        """
        resources: list[S2TResource] = []
        tables = soup.find_all("table") or [soup]
        for table in tables:
            rows = table.find_all("tr")
            if self._table_has_latest_marker(rows):
                latest = self._latest_non_empty_row_resource(page, rows)
                if latest:
                    resources.append(latest)

            for row_number, row in enumerate(rows, start=1):
                cells = row.find_all(["th", "td"])

                # First check for dated rows
                table_date = None
                date_cell_index = -1
                for i, cell in enumerate(cells):
                    table_date = parse_date_from_text(cell.get_text(" ", strip=True))
                    if table_date:
                        date_cell_index = i
                        break

                if table_date and date_cell_index >= 0:
                    resources.extend(
                        self._resources_from_neighbor_links(
                            page=page,
                            cells=cells,
                            index=date_cell_index,
                            file_date=table_date,
                            resource_type="table_link",
                            row_number=row_number,
                        )
                    )
                else:
                    # LIBERAL PASS: Look for any link that looks like S2T in ANY row
                    for link in row.find_all("a"):
                        href = link.get("href")
                        if not href:
                            continue
                        title = link.get_text(" ", strip=True)
                        # Here we require keyword check because it's a generic row
                        if self._looks_like_s2t_file(href, title) or self._looks_like_s2t(title):
                            resources.append(
                                S2TResource(
                                    title=title,
                                    url=confluence_urljoin(page.url, href),
                                    file_name=self._file_name_from_url(href) or title,
                                    resource_type="table_generic_link",
                                    updated_at=page.updated_at,
                                    version=row_number,
                                    page_id=page.id,
                                )
                            )
        return resources

    def choose_latest_s2t(self, candidates: list[S2TResource]) -> S2TResource | None:
        """
        Выбирает наиболее актуальный (последний) файл S2T из списка кандидатов.

        :param candidates: Список найденных ресурсов S2T.
        :return: Наилучший объект S2TResource или None.
        """
        if not candidates:
            logger.warning("S2T resource was not found")
            return None

        def key(item: S2TResource) -> tuple[int, int, datetime, int]:
            has_download = 1 if item.download_url else 0
            priority = 1 if item.resource_type == "table_latest_row" else 0
            if item.file_date:
                dt = datetime.combine(item.file_date, datetime.min.time(), tzinfo=UTC)
            else:
                dt = self._comparable_datetime(item.updated_at)
            row_number = item.version or 0
            return has_download, priority, dt, row_number

        selected = max(candidates, key=key)
        if not selected.file_date and selected.resource_type != "table_latest_row":
            logger.warning(
                "S2T date is absent in title, fallback to updated_at/version for %s", selected.title
            )
        return selected

    @staticmethod
    def _comparable_datetime(value: datetime | None) -> datetime:
        """
        Приводит объект datetime к сопоставимому формату с временной зоной UTC.

        :param value: Исходный объект datetime или None.
        :return: Объект datetime в UTC.
        """
        if not value:
            return datetime.min.replace(tzinfo=UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _looks_like_s2t(self, value: str) -> bool:
        """
        Проверяет, соответствует ли строка шаблонам имен S2T.

        :param value: Текст для проверки.
        :return: True, если текст похож на S2T.
        """
        return any(
            normalize_text(pattern) in normalize_text(value)
            for pattern in self.settings.s2t_patterns
        )

    def _has_s2t_extension(self, value: str) -> bool:
        """
        Проверяет, имеет ли строка расширение поддерживаемого S2T-файла.

        :param value: Имя файла или URL.
        :return: True, если расширение поддерживается.
        """
        return any(suffix in value.lower() for suffix in SUPPORTED_S2T_SUFFIXES)

    def _looks_like_s2t_file(self, href: str, title: str) -> bool:
        """
        Проверяет, является ли ссылка или заголовок файлом S2T.

        :param href: URL ссылки.
        :param title: Заголовок ссылки.
        :return: True, если это похоже на файл S2T.
        """
        lowered = f"{href} {title}".lower()
        if not self._has_s2t_extension(lowered):
            return False
        return self._looks_like_s2t(lowered)

    def _latest_non_empty_row_resource(self, page: ConfluencePage, rows) -> S2TResource | None:
        """
        Ищет ресурс S2T в последней непустой строке таблицы.

        :param page: Текущая страница.
        :param rows: Список строк таблицы.
        :return: Объект S2TResource или None.
        """
        for row_number, row in reversed(list(enumerate(rows, start=1))):
            if not row.get_text(" ", strip=True):
                continue
            for link in row.find_all("a"):
                href = link.get("href")
                file_name = self._file_name_from_url(href)
                title = file_name or link.get_text(" ", strip=True) or href or ""
                # Here we only check extension because it's in a "latest" row
                if href and self._has_s2t_extension(href or title):
                    return S2TResource(
                        title=title,
                        url=confluence_urljoin(page.url, href),
                        file_name=file_name or title,
                        resource_type="table_latest_row",
                        updated_at=page.updated_at,
                        version=row_number,
                        page_id=page.id,
                    )
            for attachment in self._attachment_references(row):
                return self._resource_from_attachment_reference(
                    page=page,
                    file_name=attachment,
                    resource_type="table_latest_row",
                    row_number=row_number,
                )
        return None

    def _resources_from_neighbor_links(
        self,
        page: ConfluencePage,
        cells,
        index: int,
        file_date,
        resource_type: str,
        row_number: int,
    ) -> list[S2TResource]:
        """
        Извлекает ресурсы S2T из ячеек, соседствующих с ячейкой даты.

        :param page: Текущая страница.
        :param cells: Список ячеек строки.
        :param index: Индекс ячейки с датой.
        :param file_date: Извлеченная дата файла.
        :param resource_type: Тип ресурса.
        :param row_number: Номер строки в таблице.
        :return: Список объектов S2TResource.
        """
        resources: list[S2TResource] = []
        for link_cell in self._neighbor_cells(cells, index):
            for link in link_cell.find_all("a"):
                href = link.get("href")
                file_name = self._file_name_from_url(href)
                title = file_name or link.get_text(" ", strip=True) or href or ""
                # Here we only check extension because it's in a dated row
                if href and self._has_s2t_extension(href or title):
                    resources.append(
                        S2TResource(
                            title=title,
                            url=confluence_urljoin(page.url, href),
                            file_name=file_name or title,
                            resource_type=resource_type,
                            file_date=file_date,
                            updated_at=page.updated_at,
                            version=row_number,
                            page_id=page.id,
                        )
                    )
            for attachment in self._attachment_references(link_cell):
                resources.append(
                    self._resource_from_attachment_reference(
                        page=page,
                        file_name=attachment,
                        resource_type=resource_type,
                        row_number=row_number,
                        file_date=file_date,
                    )
                )
        return resources

    def _resource_from_attachment_reference(
        self,
        page: ConfluencePage,
        file_name: str,
        resource_type: str,
        row_number: int,
        file_date=None,
    ) -> S2TResource:
        """
        Создает объект S2TResource на основе ссылки на вложение Confluence.

        :param page: Текущая страница.
        :param file_name: Имя файла вложения.
        :param resource_type: Тип ресурса.
        :param row_number: Номер строки (для таблиц).
        :param file_date: Опциональная дата файла.
        :return: Объект S2TResource.
        """
        return S2TResource(
            title=file_name,
            url=confluence_urljoin(page.url, f"/download/attachments/{page.id}/{file_name}"),
            file_name=file_name,
            resource_type=resource_type,
            file_date=file_date,
            updated_at=page.updated_at,
            version=row_number,
            page_id=page.id,
        )

    def _attachment_references(self, node) -> list[str]:
        """
        Ищет ссылки на вложения в формате Confluence Storage (ri:filename).

        :param node: HTML/Storage узел для анализа.
        :return: Список имен файлов вложений.
        """
        names: list[str] = []
        for tag in node.find_all():
            attrs = {str(key).lower(): str(value) for key, value in tag.attrs.items()}
            file_name = attrs.get("ri:filename") or attrs.get("filename")
            if file_name and self._looks_like_s2t_file(file_name, file_name):
                names.append(file_name)
        return names

    def _append_new_resources(
        self, target: list[S2TResource], resources: list[S2TResource]
    ) -> None:
        """
        Добавляет новые ресурсы в список, заменяя менее качественные ссылки на полные вложения при совпадении ключей.

        :param target: Результирующий список ресурсов.
        :param resources: Список новых ресурсов для добавления.
        """
        target_by_key = {resource.resource_key: i for i, resource in enumerate(target)}
        for resource in resources:
            if resource.resource_key in target_by_key:
                idx = target_by_key[resource.resource_key]
                if (
                    target[idx].resource_type == "attachment"
                    and resource.resource_type != "attachment"
                ):
                    target[idx] = resource
                continue
            target.append(resource)
            target_by_key[resource.resource_key] = len(target) - 1

    def _enrich_resources(
        self, resources: list[S2TResource], attachment_index: dict[str, S2TResource]
    ) -> list[S2TResource]:
        """
        Массово обогащает ресурсы данными из вложений Confluence.

        :param resources: Список ресурсов S2TResource.
        :param attachment_index: Индекс вложений для быстрого поиска.
        :return: Список обогащенных ресурсов S2TResource.
        """
        return [self._enrich_resource(resource, attachment_index) for resource in resources]

    def _enrich_resource(
        self, resource: S2TResource, attachment_index: dict[str, S2TResource]
    ) -> S2TResource:
        """
        Обогащает одиночный ресурс (например, ссылку) реальными данными о вложении (ID, размер, URL скачивания).

        :param resource: Исходный ресурс.
        :param attachment_index: Индекс вложений.
        :return: Обогащенный ресурс S2TResource.
        """
        attachment = self._find_attachment(resource, attachment_index)
        if not attachment:
            return resource
        return resource.model_copy(
            update={
                "id": attachment.id,
                "title": attachment.title or resource.title,
                "url": attachment.url or resource.url,
                "file_name": attachment.file_name or resource.file_name,
                "updated_at": attachment.updated_at or resource.updated_at,
                "version": attachment.version,
                "version_when": attachment.version_when,
                "file_size": attachment.file_size,
                "download_url": attachment.download_url,
                "media_type": attachment.media_type,
                "page_id": attachment.page_id or resource.page_id,
            }
        )

    def _find_attachment(
        self, resource: S2TResource, attachment_index: dict[str, S2TResource]
    ) -> S2TResource | None:
        """
        Ищет вложение в индексе по различным признакам (имя файла, заголовок, URL).

        :param resource: Ресурс для поиска.
        :param attachment_index: Индекс вложений.
        :return: Совпадающее вложение S2TResource или None.
        """
        for value in (
            resource.file_name,
            resource.title,
            self._file_name_from_url(resource.download_url),
            self._file_name_from_url(resource.url),
            resource.download_url,
            resource.url,
        ):
            key = self._attachment_lookup_key(value)
            if key and key in attachment_index:
                return attachment_index[key]
        return None

    def _attachment_index(self, attachments: list[S2TResource]) -> dict[str, S2TResource]:
        """
        Строит индекс вложений для быстрого сопоставления ссылок с реальными файлами.

        :param attachments: Список вложений.
        :return: Словарь-индекс.
        """
        index: dict[str, S2TResource] = {}
        for attachment in attachments:
            for value in (
                attachment.file_name,
                attachment.title,
                self._file_name_from_url(attachment.download_url),
                self._file_name_from_url(attachment.url),
                attachment.download_url,
                attachment.url,
            ):
                key = self._attachment_lookup_key(value)
                if key:
                    index[key] = attachment
        return index

    @staticmethod
    def _attachment_lookup_key(value: str | None) -> str | None:
        """
        Генерирует нормализованный ключ для поиска вложения.

        :param value: Исходное значение (имя или URL).
        :return: Нормализованный ключ.
        """
        if not value:
            return None
        return unquote(value).strip().casefold()

    @staticmethod
    def _file_name_from_url(url: str | None) -> str | None:
        """
        Извлекает имя файла из URL.

        :param url: URL файла.
        :return: Имя файла или None.
        """
        if not url:
            return None
        path = urlparse(url).path
        if not path or path.endswith("/"):
            return None
        return unquote(path.rsplit("/", 1)[-1])

    @staticmethod
    def _table_has_latest_marker(rows) -> bool:
        """
        Проверяет, содержит ли таблица маркер актуальной версии ("latest", "актуальный" и т.д.).

        :param rows: Строки таблицы.
        :return: True, если маркер найден.
        """
        for row in rows:
            tokens = normalize_text(row.get_text(" ", strip=True)).split()
            if any(marker in tokens for marker in LATEST_MARKERS):
                return True
        return False

    @staticmethod
    def _neighbor_cells(cells, index: int):
        """
        Возвращает список соседних ячеек для заданного индекса в строке.

        :param cells: Список ячеек.
        :param index: Базовый индекс.
        :return: Список соседних ячеек.
        """
        start = max(0, index - 1)
        end = min(len(cells), index + 2)
        return [cells[i] for i in range(start, end) if i != index]

    @staticmethod
    def _clean_text(value: str) -> str:
        """
        Очищает текст от лишних пробельных символов.

        :param value: Исходный текст.
        :return: Очищенный текст.
        """
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _fact_key(label: str) -> str:
        """
        Определяет программный ключ факта на основе его текстового заголовка.

        :param label: Заголовок факта из Confluence.
        :return: Строковый ключ (например, "db_name") или "unknown".
        """
        normalized = normalize_text(label)
        for key, aliases in FACT_ALIASES.items():
            if any(alias in normalized for alias in aliases):
                return key
        return "unknown"

    @staticmethod
    def _links_from_node(node) -> list[dict[str, str]]:
        """
        Извлекает все ссылки из HTML-узла.

        :param node: Узел для поиска ссылок.
        :return: Список словарей с заголовком и URL ссылки.
        """
        links = []
        for link in node.find_all("a"):
            href = link.get("href")
            if not href:
                continue
            links.append({"title": link.get_text(" ", strip=True) or href, "url": href})
        return links

    @staticmethod
    def _page_id_from_url(url: str) -> str | None:
        """
        Извлекает ID страницы Confluence из URL.

        :param url: URL страницы.
        :return: Идентификатор страницы или None.
        """
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

    @staticmethod
    def _jira_keys_from_node(node) -> list[str]:
        """
        Извлекает все ключи задач Jira из HTML-узла.

        :param node: Узел для поиска.
        :return: Список найденных ключей Jira.
        """
        keys = []
        for tag in node.find_all(attrs={"data-jira-key": True}):
            if tag.get("data-jira-key"):
                keys.append(str(tag["data-jira-key"]))

        # Also search in text
        text = node.get_text(" ", strip=True)
        found_in_text = JIRA_KEY_RE.findall(text)
        for k in found_in_text:
            if k not in keys:
                keys.append(k)
        return keys

    @staticmethod
    def _jira_key_from_node(node) -> str | None:
        """
        Извлекает первый встреченный ключ задачи Jira из узла.

        :param node: Узел для поиска.
        :return: Ключ Jira или None.
        """
        keys = ConfluenceParser._jira_keys_from_node(node)
        return keys[0] if keys else None

    @staticmethod
    def _jira_title_from_node(node) -> str | None:
        """
        Извлекает заголовок задачи Jira из макроса Jira в Confluence.

        :param node: Узел макроса.
        :return: Текст заголовка или None.
        """
        summary = node.find(class_="summary")
        if not summary:
            return None
        text = ConfluenceParser._clean_text(summary.get_text(" ", strip=True))
        if normalize_text(text) in PLACEHOLDER_TEXTS:
            return None
        return text or None

    @staticmethod
    def _jira_status_from_node(node) -> str | None:
        """
        Извлекает статус задачи Jira из макроса Jira.

        :param node: Узел макроса.
        :return: Текст статуса или None.
        """
        for tag in node.find_all(class_=lambda value: value and "aui-lozenge" in value):
            if tag.find_parent(class_=lambda value: value and "status-macro" in value):
                continue
            text = ConfluenceParser._clean_text(tag.get_text(" ", strip=True))
            if text and normalize_text(text) not in PLACEHOLDER_TEXTS:
                return text
        return None

    @staticmethod
    def _release_change_type(node) -> str | None:
        """
        Определяет тип изменения в релизе (новое, исправление и т.д.) на основе текста или макросов статуса.

        :param node: Узел строки изменения.
        :return: Тип изменения (в нижнем регистре) или None.
        """
        for tag in node.find_all(class_=lambda value: value and "status-macro" in value):
            text = ConfluenceParser._clean_text(tag.get_text(" ", strip=True))
            if text:
                return text.lower()
        text = normalize_text(node.get_text(" ", strip=True))
        for change_type in ("изменение", "новое", "исправление"):
            if change_type in text:
                return change_type
        return None

    @staticmethod
    def _release_summary(node, change_type: str | None) -> str | None:
        """
        Извлекает текстовое описание изменения, очищая его от типа изменения и лишних символов.

        :param node: Узел строки изменения.
        :param change_type: Ранее определенный тип изменения для удаления из текста.
        :return: Очищенное описание изменения или None.
        """
        text = ConfluenceParser._clean_text(node.get_text(" ", strip=True))
        if change_type:
            text = re.sub(change_type, "", text, count=1, flags=re.IGNORECASE).strip()
        text = re.sub(r"^[\s:–—-]+", "", text)
        return text or None

    def _stakeholders_from_text(self, text: str, row) -> list[Stakeholder]:
        """
        Парсит информацию о стейкхолдерах из текстового блока, извлекая имена, email и ссылки на профили.

        :param text: Текст для парсинга.
        :param row: HTML-строка таблицы (для поиска ссылок).
        :return: Список объектов Stakeholder.
        """
        emails = EMAIL_RE.findall(text)
        names = [
            part.strip(" ,;")
            for part in re.split(r"[,;\n]", EMAIL_RE.sub("", text))
            if part.strip(" ,;")
        ]
        links = []
        if row is not None:
            links = [a.get("href") for a in row.find_all("a") if a.get("href")]
        if not emails and not names:
            return []
        size = max(len(emails), len(names), 1)
        return [
            Stakeholder(
                name=names[i] if i < len(names) else None,
                email=emails[i] if i < len(emails) else None,
                profile_url=links[i] if i < len(links) else None,
            )
            for i in range(size)
        ]
