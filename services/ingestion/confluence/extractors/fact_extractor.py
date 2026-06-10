import re

from bs4 import BeautifulSoup

from services.ingestion.confluence.extractors.utils import (
    EMAIL_RE,
    OWNER_LABELS,
    clean_text,
    fact_key,
    links_from_node,
)
from services.ingestion.confluence.models import DatamartFact, Stakeholder
from shared.utils.text_utils import fuzzy_contains


class FactExtractor:
    def extract_stakeholders(self, html: str) -> list[Stakeholder]:
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
        soup = BeautifulSoup(html, "html.parser")
        facts: list[DatamartFact] = []
        seen: set[tuple[str, str, str]] = set()

        for table in soup.find_all("table"):
            header_row = table.find("tr")
            if not header_row:
                continue

            headers = [
                clean_text(th.get_text(" ", strip=True))
                for th in header_row.find_all("th", recursive=False)
            ]

            if len(headers) >= 3:
                table_title = ""
                prev_node = table.find_previous(["h1", "h2", "h3", "h4", "p"])
                if prev_node:
                    table_title = clean_text(prev_node.get_text(" ", strip=True))

                for row in table.find_all("tr")[1:]:
                    cells = row.find_all(["td", "th"], recursive=False)
                    if len(cells) == len(headers):
                        row_parts = []
                        for i, cell in enumerate(cells):
                            cell_val = clean_text(cell.get_text(" ", strip=True))
                            if cell_val and headers[i]:
                                row_parts.append(f"{headers[i]}: {cell_val}")

                        if row_parts:
                            full_val = " | ".join(row_parts)
                            key = fact_key(table_title) if table_title else "table_row"
                            label = table_title or "Данные таблицы"
                            facts.append(
                                DatamartFact(
                                    key=key,
                                    label=label,
                                    value=full_val,
                                    links=links_from_node(row),
                                )
                            )
                continue

            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                if len(cells) < 2:
                    continue

                label_node = cells[0]
                value_node = cells[1]

                label = clean_text(label_node.get_text(" ", strip=True))
                if not label:
                    continue

                key = fact_key(label)
                if key == "unknown":
                    continue

                if value_node.find("table"):
                    sub_table = value_node.find("table")
                    sub_rows_texts = []
                    sub_header_tr = sub_table.find("tr")
                    if sub_header_tr:
                        sub_headers = [
                            clean_text(th.get_text(" ", strip=True))
                            for th in sub_header_tr.find_all(["th", "td"])
                        ]
                        for sub_tr in sub_table.find_all("tr")[1:]:
                            sub_tds = sub_tr.find_all(["td", "th"])
                            if len(sub_tds) == len(sub_headers):
                                row_str = "; ".join(
                                    f"{sub_headers[i]}: {clean_text(td.get_text())}"
                                    for i, td in enumerate(sub_tds)
                                )
                                sub_rows_texts.append(row_str)

                    if sub_rows_texts:
                        value = " [ " + " | ".join(sub_rows_texts) + " ] "
                    else:
                        value = clean_text(value_node.get_text(" ", strip=True))
                else:
                    value = clean_text(value_node.get_text(" ", strip=True))

                if not value:
                    continue

                marker = (key, label.casefold(), value)
                if marker in seen:
                    continue
                seen.add(marker)
                facts.append(
                    DatamartFact(
                        key=key, label=label, value=value, links=links_from_node(value_node)
                    )
                )

        return facts

    def _stakeholders_from_text(self, text: str, row) -> list[Stakeholder]:
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
