from app.config import Settings


def test_gigachat_auth_key_prefers_credentials() -> None:
    settings = Settings(
        _env_file=None,
        gigachat_credentials="credentials",
        gigachat_api_key="api-key",
        gigachat_api_pers="api-pers",
    )

    assert settings.gigachat_auth_key == "credentials"


def test_gigachat_auth_key_supports_legacy_api_pers() -> None:
    settings = Settings(_env_file=None, gigachat_api_pers="legacy")

    assert settings.gigachat_auth_key == "legacy"


def test_confluence_page_url_sets_base_url_and_root_page_id() -> None:
    settings = Settings(
        _env_file=None,
        confluence_page_url="https://confluence.delta.sbrf.ru/pages/viewpage.action?pageId=4700310446"
    )

    assert settings.confluence_base_url == "https://confluence.delta.sbrf.ru"
    assert settings.confluence_root_page_id == "4700310446"


def test_confluence_page_url_overrides_root_page_id() -> None:
    settings = Settings(
        _env_file=None,
        confluence_page_url="https://confluence.delta.sbrf.ru/pages/viewpage.action?pageId=4700310446",
        confluence_root_page_id="42",
    )

    assert settings.confluence_root_page_id == "4700310446"
