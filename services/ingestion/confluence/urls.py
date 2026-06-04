from urllib.parse import urljoin, urlparse


def confluence_urljoin(base_url: str, link: str | None) -> str:
    """
    Безопасно объединяет базовый URL Confluence с относительной или абсолютной ссылкой.
    Корректно обрабатывает пути контекста Confluence.
    :param base_url: Базовый URL Confluence.
    :param link: Ссылка для объединения.
    :return: Полный URL.
    """
    if not link:
        return base_url
    if urlparse(link).scheme:
        return link
    base = urlparse(base_url)
    base_path = _context_path(base.path)
    if link.startswith("/") and base_path and not link.startswith(f"{base_path}/"):
        link = f"{base_path}{link}"
        base_url = f"{base.scheme}://{base.netloc}"
    return urljoin(base_url, link)


def _context_path(path: str) -> str:
    """
    Извлекает путь контекста из URL Confluence (например, '/confluence').
    :param path: Путь из URL.
    :return: Путь контекста или пустая строка.
    """
    parts = [part for part in path.split("/") if part]
    if not parts:
        return ""
    if parts[0] in {"pages", "display", "download", "rest", "spaces"}:
        return ""
    return f"/{parts[0]}"
