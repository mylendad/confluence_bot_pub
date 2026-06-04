class ConfluenceError(RuntimeError):
    """
    Базовый класс для всех ошибок интеграции с Confluence.
    """


class ConfluenceAuthError(ConfluenceError):
    """
    Исключение, возникающее при ошибках аутентификации в Confluence.
    """
