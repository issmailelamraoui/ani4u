"""Shared, deliberately small interface for public anime source providers."""

from __future__ import annotations

from typing import Protocol


class SourceProviderError(RuntimeError):
    """A provider response could not be used safely."""


class SourceUnavailable(SourceProviderError):
    """The public source is unavailable, rate-limited, or challenged."""


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
