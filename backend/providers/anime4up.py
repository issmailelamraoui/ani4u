"""Adapter around the established Anime4Up scraper.

The parser itself intentionally stays in :mod:`anime4up_scraper`; this module
only gives it the shared provider contract used by new fallback code.
"""

from __future__ import annotations

from urllib.parse import quote, unquote, urlparse
import re

import httpx

from anime4up_scraper import BASE_URL, SOURCE_HOST_SUFFIX, Anime4up, source_path
from .base import ProviderUnavailable, SourceProviderError


class Anime4upProvider:
    name = "anime4up"

    def __init__(self, scraper: Anime4up):
        self.scraper = scraper

    async def start(self) -> None:
        # api.py continues to own the existing scraper lifecycle.
        return None

    async def close(self) -> None:
        return None

    async def search_anime(self, query: str) -> list[dict]:
        return await self._call(self.scraper.search, query)

    async def get_anime(self, source_slug: str) -> dict | None:
        return await self._call(self.scraper.anime, source_slug)

    async def get_episodes(self, source_slug: str) -> list[dict]:
        return await self._call(self.scraper.episodes, self.anime_url(source_slug))

    async def get_episode_servers(self, episode_url: str) -> list[dict]:
        if not self.valid_episode_url(episode_url):
            raise ValueError("Unsupported Anime4Up episode URL")
        return await self._call(self.scraper.servers, episode_url)

    @staticmethod
    def public_error(error: Exception) -> Exception:
        """Translate raw scraper transport errors into provider semantics.

        The established scraper intentionally has a small interface and raises
        ``RuntimeError`` for HTTP errors.  Keep that parser unchanged while
        making its public-provider boundary precise for catalog fallback.
        """
        if isinstance(error, (ProviderUnavailable, SourceProviderError)):
            return error
        if isinstance(error, (TimeoutError, httpx.TimeoutException)):
            return ProviderUnavailable(
                "Anime4Up public HTTP request timed out", retryable=True
            )
        if isinstance(error, httpx.HTTPError):
            return ProviderUnavailable(
                "Anime4Up public HTTP request failed", retryable=True
            )
        match = re.search(r"\bHTTP\s+(\d{3})\b", str(error), flags=re.I)
        status = int(match.group(1)) if match else None
        if status in {403, 429}:
            return ProviderUnavailable(
                f"Anime4Up returned HTTP {status}", status=status, retryable=False
            )
        if status is not None and status >= 500:
            return ProviderUnavailable(
                f"Anime4Up returned HTTP {status}", status=status, retryable=True
            )
        return error

    async def _call(self, method, *args):
        try:
            return await method(*args)
        except Exception as error:
            translated = self.public_error(error)
            if translated is error:
                raise
            raise translated from error

    def anime_url(self, source_slug: str) -> str:
        if not re.fullmatch(r"[\w-]{1,220}", source_slug, flags=re.UNICODE):
            raise ValueError("Invalid Anime4Up source slug")
        return f"{BASE_URL}/anime/{quote(source_slug, safe='-_')}/"

    def source_slug_from_url(self, url: str) -> str | None:
        try:
            parsed = urlparse(url)
        except ValueError:
            return None
        host = (parsed.hostname or "").lower().strip(".")
        if parsed.scheme != "https" or not (host == SOURCE_HOST_SUFFIX or host.endswith("." + SOURCE_HOST_SUFFIX)):
            return None
        match = re.fullmatch(r"/anime/([^/]+)/?", parsed.path)
        slug = unquote(match[1]) if match else ""
        return slug if re.fullmatch(r"[\w-]{1,220}", slug, flags=re.UNICODE) else None

    def valid_episode_url(self, episode_url: str) -> bool:
        return source_path(episode_url, "/episode/")
