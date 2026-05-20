from datetime import datetime

from app.config import Settings
from app.confluence.models import ConfluencePage, S2TResource
from app.confluence.parser import ConfluenceParser


class FakeClient:
    def __init__(self, children=None, attachments_by_page=None):
        self.children = children or []
        self.attachments_by_page = attachments_by_page or {}

    def iter_top_level_pages(self):
        return []

    def get_attachments(self, page_id: str):
        return self.attachments_by_page.get(page_id, [])

    def get_children(self, page_id: str):
        return self.children


def test_extract_stakeholders_from_table() -> None:
    parser = ConfluenceParser(FakeClient(), Settings())
    html = """
    <table><tr><td>Заинтересованные лица</td>
    <td><a href="/u/ivanov">Иванов Иван</a> ivanov@example.ru;
    Петров Петр petrov@example.ru</td></tr></table>
    """

    stakeholders = parser.extract_stakeholders(html)

    assert len(stakeholders) == 2
    assert stakeholders[0].email == "ivanov@example.ru"


def test_choose_latest_s2t_prefers_title_date_then_version() -> None:
    parser = ConfluenceParser(FakeClient(), Settings())
    candidates = [
        S2TResource(title="s2t_2024_01_01.xlsx", updated_at=datetime(2026, 1, 1), version=10),
        S2TResource(title="s2t_2025_01_01.xlsx", updated_at=datetime(2025, 1, 1), version=1),
        S2TResource(title="s2t.xlsx", updated_at=datetime(2026, 5, 1), version=1),
    ]
    for item in candidates:
        item.file_date = parser.choose_latest_s2t([item]).file_date

    selected = parser.choose_latest_s2t(candidates)

    assert selected is not None
    assert selected.title == "s2t.xlsx"


def test_find_s2t_candidate_from_table_date_and_neighbor_download_link() -> None:
    parser = ConfluenceParser(FakeClient(), Settings())
    page = ConfluencePage(
        id="42",
        title="Витрина клиентских операций",
        url="https://confluence.example.ru/pages/42",
        updated_at=datetime(2026, 1, 1),
    )
    html = """
    <table>
      <tr>
        <th>Дата</th>
        <th>Файл</th>
      </tr>
      <tr>
        <td>2026-05-10</td>
        <td><a href="/download/attachments/42/random_name.xlsx">скачать</a></td>
      </tr>
      <tr>
        <td>2026-04-01</td>
        <td><a href="/download/attachments/42/another.xlsx">download</a></td>
      </tr>
    </table>
    """

    candidates = parser.find_s2t_candidates(page, html)
    selected = parser.choose_latest_s2t(candidates)

    assert selected is not None
    assert selected.file_date.isoformat() == "2026-05-10"
    assert selected.resource_type == "table_link"
    assert selected.url == "https://confluence.example.ru/download/attachments/42/random_name.xlsx"


def test_table_candidate_is_enriched_from_confluence_attachment_api() -> None:
    attachment = S2TResource(
        id="100500",
        title="random_name.xlsx",
        file_name="random_name.xlsx",
        resource_type="attachment",
        url="https://confluence.example.ru/download/attachments/42/random_name.xlsx",
        download_url="https://confluence.example.ru/download/attachments/42/random_name.xlsx?version=2",
        updated_at=datetime(2026, 5, 11),
        version=2,
        file_size=12345,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        page_id="42",
    )
    parser = ConfluenceParser(FakeClient(attachments_by_page={"42": [attachment]}), Settings())
    page = ConfluencePage(
        id="42",
        title="Витрина клиентских операций",
        url="https://confluence.example.ru/pages/42",
        updated_at=datetime(2026, 1, 1),
    )
    html = """
    <table>
      <tr><th>Дата</th><th>Файл</th></tr>
      <tr>
        <td>2026-05-10</td>
        <td><a href="/download/attachments/42/random_name.xlsx">download</a></td>
      </tr>
    </table>
    """

    candidates = parser.find_s2t_candidates(page, html)
    selected = parser.choose_latest_s2t(candidates)

    assert selected is not None
    assert selected.resource_type == "table_link"
    assert selected.id == "100500"
    assert selected.title == "random_name.xlsx"
    assert selected.version == 2
    assert selected.file_size == 12345
    assert selected.download_url == attachment.download_url
    assert selected.media_type == attachment.media_type


def test_find_s2t_candidate_from_latest_non_empty_row_when_date_is_new() -> None:
    parser = ConfluenceParser(FakeClient(), Settings())
    page = ConfluencePage(
        id="42",
        title="Витрина клиентских операций",
        url="https://confluence.example.ru/pages/42",
        updated_at=datetime(2026, 1, 1),
    )
    html = """
    <table>
      <tr>
        <th>Дата</th>
        <th>Файл</th>
      </tr>
      <tr>
        <td>2026-04-01</td>
        <td><a href="/download/attachments/42/old.xlsx">download</a></td>
      </tr>
      <tr>
        <td>новый</td>
        <td><a href="/download/attachments/42/arbitrary_name.xlsx">download</a></td>
      </tr>
      <tr><td></td><td></td></tr>
    </table>
    """

    candidates = parser.find_s2t_candidates(page, html)
    selected = parser.choose_latest_s2t(candidates)

    assert selected is not None
    assert selected.resource_type == "table_latest_row"
    assert selected.url == "https://confluence.example.ru/download/attachments/42/arbitrary_name.xlsx"


def test_latest_row_without_date_is_not_warning(caplog) -> None:
    parser = ConfluenceParser(FakeClient(), Settings())
    candidate = S2TResource(
        title="arbitrary_name.xlsx",
        resource_type="table_latest_row",
        updated_at=datetime(2026, 5, 16),
        version=4,
    )

    selected = parser.choose_latest_s2t([candidate])

    assert selected is candidate
    assert "S2T date is absent" not in caplog.text


def test_find_s2t_candidate_from_child_s2t_page_table() -> None:
    child = ConfluencePage(
        id="491521",
        title="S2T",
        url="https://confluence.example.ru/spaces/TH/pages/491521/S2T",
        updated_at=datetime(2026, 5, 16),
        body_html="""
        <table>
          <tr><th>Дата</th><th>Файл</th></tr>
          <tr>
            <td>2026-05-16</td>
            <td><a href="/download/attachments/491521/current.xlsx">download</a></td>
          </tr>
        </table>
        """,
    )
    parser = ConfluenceParser(FakeClient(children=[child]), Settings())
    page = ConfluencePage(
        id="458753",
        title="Прокси-витрина такая-то",
        url="https://confluence.example.ru/spaces/TH/pages/458753/datamart",
    )

    candidates = parser.find_s2t_candidates(page, "")
    selected = parser.choose_latest_s2t(candidates)

    assert selected is not None
    assert selected.resource_type == "table_link"
    assert selected.file_date.isoformat() == "2026-05-16"


def test_find_s2t_candidate_from_confluence_attachment_macro() -> None:
    parser = ConfluenceParser(FakeClient(), Settings())
    page = ConfluencePage(
        id="491521",
        title="S2T",
        url="https://confluence.example.ru/spaces/TH/pages/491521/S2T",
        updated_at=datetime(2026, 5, 16),
    )
    html = """
    <table>
      <tr><th>Дата</th><th>Файл</th></tr>
      <tr>
        <td>2026-05-16</td>
        <td>
          <ac:link>
            <ri:attachment ri:filename="current_s2t.xlsx" />
          </ac:link>
        </td>
      </tr>
    </table>
    """

    candidates = parser.find_s2t_candidates(page, html)
    selected = parser.choose_latest_s2t(candidates)

    assert selected is not None
    assert selected.title == "current_s2t.xlsx"
    assert selected.file_date.isoformat() == "2026-05-16"
