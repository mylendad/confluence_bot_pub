import httpx
import pytest

from app.config import Settings
from app.confluence.client import ConfluenceClient
from app.confluence.exceptions import ConfluenceAuthError


def test_attachment_download_url_keeps_cloud_context_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/wiki/rest/api/content/42/child/attachment"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "att1",
                        "title": "s2t.xlsx",
                        "_links": {
                            "download": "/download/attachments/42/s2t.xlsx?version=1",
                        },
                    }
                ]
            },
        )

    client = ConfluenceClient(
        Settings(confluence_base_url="https://example.atlassian.net/wiki"),
        httpx.Client(
            base_url="https://example.atlassian.net/wiki",
            transport=httpx.MockTransport(handler),
        ),
    )

    attachments = client.get_attachments("42")

    assert (
        attachments[0].download_url
        == "https://example.atlassian.net/wiki/download/attachments/42/s2t.xlsx?version=1"
    )


def test_api_token_without_username_uses_bearer_auth() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "42",
                "title": "Page",
                "_links": {"webui": "/pages/viewpage.action?pageId=42"},
            },
        )

    client = ConfluenceClient(
        Settings(
            _env_file=None,
            confluence_base_url="https://confluence.example.ru",
            confluence_api_token="secret-token",
        )
    )
    client._client = httpx.Client(
        base_url="https://confluence.example.ru",
        headers=client._client.headers,
        transport=httpx.MockTransport(handler),
    )

    client.get_page("42")

    assert requests[0].headers["Authorization"] == "Bearer secret-token"


def test_basic_auth_is_used_when_username_is_configured() -> None:
    auth, headers = ConfluenceClient._auth_config(
        Settings(
            _env_file=None,
            confluence_username="user",
            confluence_api_token="secret-token",
        )
    )

    assert auth == ("user", "secret-token")
    assert headers is None


def test_attachment_download_401_is_auth_error() -> None:
    client = ConfluenceClient(
        Settings(confluence_base_url="https://example.atlassian.net/wiki"),
        httpx.Client(
            base_url="https://example.atlassian.net/wiki",
            transport=httpx.MockTransport(lambda request: httpx.Response(401)),
        ),
    )

    with pytest.raises(ConfluenceAuthError):
        client.download("https://example.atlassian.net/wiki/download/attachments/42/s2t.xlsx")


def test_attachment_download_resource_falls_back_to_rest_endpoint() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/wiki/download/attachments/42/s2t.xlsx":
            return httpx.Response(401)
        if request.url.path == "/wiki/rest/api/content/42/child/attachment/att1/download":
            return httpx.Response(200, content=b"file-content")
        return httpx.Response(404)

    client = ConfluenceClient(
        Settings(confluence_base_url="https://example.atlassian.net/wiki"),
        httpx.Client(
            base_url="https://example.atlassian.net/wiki",
            transport=httpx.MockTransport(handler),
        ),
    )

    content = client.download_resource(
        attachments_resource(
            page_id="42",
            attachment_id="att1",
            url="https://example.atlassian.net/wiki/download/attachments/42/s2t.xlsx",
        )
    )

    assert content == b"file-content"
    assert calls == [
        "/wiki/download/attachments/42/s2t.xlsx",
        "/wiki/rest/api/content/42/child/attachment/att1/download",
    ]


def attachments_resource(page_id: str, attachment_id: str, url: str):
    from app.confluence.models import S2TResource

    return S2TResource(
        id=attachment_id,
        title="s2t.xlsx",
        file_name="s2t.xlsx",
        page_id=page_id,
        url=url,
        download_url=url,
        resource_type="attachment",
    )
