"""Shared, deliberately small interface for public anime source providers."""

from __future__ import annotations

from typing import Protocol


class SourceProviderError(RuntimeError):
    """A provider response could not be used safely."""


class ProviderUnavailable(SourceProviderError):
    """A public provider cannot be reached from this runtime.

    This deliberately represents an upstream availability problem, rather
    than a missing anime or an empty episode grid.  ``retryable`` is reserved
    for short-lived failures such as a timeout or 5xx response; access denials
    (403/429) must be handed to the fallback immediately.
    """

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


# Kept as an alias for existing callers while the explicit name documents the
# contract used by the provider manager and health endpoint.
SourceUnavailable = ProviderUnavailable


class SourceNotFound(SourceProviderError):
    """The public source does not contain the requested item."""


class PublicSourceProvider(Protocol):
    """Stable contract used by ``ProviderManager``.

    Providers return only data that is present in their normal public HTML or
    public player URLs. They must never solve challenges, authenticate, or
    derive private media URLs.
    """

    name: str

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def search_anime(self, query: str) -> list[dict]: ...

    async def get_anime(self, source_slug: str) -> dict | None: ...

    async def get_episodes(self, source_slug: str) -> list[dict]: ...

    async def get_episode_servers(self, episode_url: str) -> list[dict]: ...

    def source_slug_from_url(self, url: str) -> str | None: ...

    def anime_url(self, source_slug: str) -> str: ...

    def valid_episode_url(self, episode_url: str) -> bool: ...
