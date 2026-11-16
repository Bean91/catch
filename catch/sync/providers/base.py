"""Errors every provider client maps its failures onto, so the sync engine reacts to a *kind* of failure (reconnect / back off /
retry) instead of to one provider's exception class. Messages are fixed text: never a token, a URL with credentials, or a response
body."""

from __future__ import annotations


class ProviderError(RuntimeError):
    pass


class ProviderAuthError(ProviderError):
    """The provider refused the stored credential or authorization. Retrying can't help: the user has to reconnect."""

    detail = "key_rejected"


class ProviderRateLimited(ProviderError):
    def __init__(self, message: str = "The provider is rate-limiting Catch; it will retry on its own.", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """Network failure or a 5xx: transient, retried with backoff."""
