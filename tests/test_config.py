from app.config import Settings


def test_gigachat_auth_key_prefers_credentials() -> None:
    settings = Settings(
        gigachat_credentials="credentials",
        gigachat_api_key="api-key",
        gigachat_api_pers="api-pers",
    )

    assert settings.gigachat_auth_key == "credentials"


def test_gigachat_auth_key_supports_legacy_api_pers() -> None:
    settings = Settings(gigachat_api_pers="legacy")

    assert settings.gigachat_auth_key == "legacy"
