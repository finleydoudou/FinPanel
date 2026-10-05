"""Public, structured errors. Parsing issues live in the returned parse result."""


class FinPanelError(Exception):
    """Base for expected ingestion failures."""


class ValidationError(FinPanelError, ValueError):
    """Invalid input or invalid JSON response envelope."""


class CacheError(FinPanelError):
    """Unreadable, inconsistent, or unwritable local cache."""


class SECRequestError(FinPanelError):
    def __init__(self, message: str, *, url: str, attempts: int, status: int | None = None):
        super().__init__(message)
        self.url = url
        self.attempts = attempts
        self.status = status


class SECTimeoutError(SECRequestError):
    """Per-operation HTTP timeout exhausted the configured retry budget."""
