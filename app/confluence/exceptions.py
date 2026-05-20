class ConfluenceError(RuntimeError):
    """Base Confluence integration error."""


class ConfluenceAuthError(ConfluenceError):
    """Raised when Confluence authentication fails."""
