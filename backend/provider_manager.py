"""Strict, bounded provider selection for public episode sources."""

from __future__ import annotations

import asyncio
import time
from typing import Callable
from urllib.parse import urlparse, urlunparse

from providers.base import PublicSourceProvider, SourceNotFound, SourceProviderError, SourceUnavailable


PRIMARY_PROVIDER = "anime4up"
FALLBACK_PROVIDER = "witanime"
PROVIDER_TIMEOUT_SECONDS = 7
RETRY_DELAY_SECONDS = 0.2
FAILURE_CACHE_TTL_SECONDS = 45


def _normalized_public_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
    return urlunparse(("https", host + port, parsed.path or "/", "", parsed.query, ""))


class ProviderManager:
    """Owns provider ordering, time budgets, and successful mappings.

    Calls are intentionally sequential: the fallback is never started unless
    the chosen/mapped provider is unavailable or has no valid episodes.
    """

    def __init__(self, store, providers: list[PublicSourceProvider]):
        self.store = store
        self.providers = {provider.name: provider for provider in providers}
        if PRIMARY_PROVIDER not in self.providers:
            raise ValueError("Anime4Up provider is required")
        self._failure_cache: dict[tuple[str, str], float] = {}

    async def start(self) -> None:
        for provider in self.providers.values():
            await provider.start()

    async def close(self) -> None:
        await asyncio.gather(*(provider.close() for provider in self.providers.values()), return_exceptions=True)

    def provider(self, name: str) -> PublicSourceProvider:
        provider = self.providers.get(name)
        if provider is None:
            raise ValueError("Unsupported source provider")
        return provider

    async def _call(self, provider_name: str, operation: str, *args):
        provider = self.provider(provider_name)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
                    return await getattr(provider, operation)(*args)
            except SourceNotFound:
                raise
            except (SourceUnavailable, SourceProviderError, TimeoutError, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
        raise SourceUnavailable(f"{provider_name} {operation} is temporarily unavailable") from last_error

    @staticmethod
    def _valid_episodes(provider: str, source_slug: str, rows: object) -> list[dict]:
        if not isinstance(rows, list):
            return []
        unique: dict[int | float, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            number = row.get("episode")
            url = row.get("url")
            if isinstance(number, bool) or not isinstance(number, (int, float)) or number < 0 or not isinstance(url, str):
                continue
            normalized = dict(row)
            normalized["title"] = normalized.get("title") if isinstance(normalized.get("title"), str) and normalized["title"].strip() else f"الحلقة {number}"
            unique.setdefault(number, normalized)
        return [unique[number] for number in sorted(unique)]

    def _failure_active(self, provider: str, source_slug: str) -> bool:
        key = (provider, source_slug)
        expires_at = self._failure_cache.get(key, 0)
        if expires_at <= time.monotonic():
            self._failure_cache.pop(key, None)
            return False
        return True

    def _remember_failure(self, provider: str, source_slug: str) -> None:
        self._failure_cache[(provider, source_slug)] = time.monotonic() + FAILURE_CACHE_TTL_SECONDS

    async def episodes_for(self, provider_name: str, source_slug: str) -> list[dict]:
        provider = self.provider(provider_name)
        if self._failure_active(provider_name, source_slug):
            return []
        try:
            rows = await self._call(provider_name, "get_episodes", source_slug)
        except SourceProviderError:
            self._remember_failure(provider_name, source_slug)
            return []
        episodes = self._valid_episodes(provider_name, source_slug, rows)
        if not episodes:
            self._remember_failure(provider_name, source_slug)
        return episodes

    async def fallback_source(
        self,
        anime: dict,
        queries: list[str],
        title_matches: Callable[[str], bool],
    ) -> tuple[dict, list[dict]] | None:
        """Resolve WitAnime only after Anime4Up has already failed/been empty."""
        provider = self.providers.get(FALLBACK_PROVIDER)
        if provider is None:
            return None

        anilist_id = anime.get("providerIds", {}).get("anilist")
        mappings = anime.get("sourceMappings", [])
        for mapping in mappings:
            if mapping.get("source") != FALLBACK_PROVIDER:
                continue
            source_slug = mapping.get("slug")
            if not isinstance(source_slug, str):
                continue
            episodes = await self.episodes_for(FALLBACK_PROVIDER, source_slug)
            if episodes:
                return ({"provider": FALLBACK_PROVIDER, "slug": source_slug, "title": anime["title"], "verified": True}, episodes)

        for query in queries:
            try:
                rows = await self._call(FALLBACK_PROVIDER, "search_anime", query)
            except SourceProviderError:
                # A transient source error is deliberately not persisted as a mapping.
                return None
            for row in rows if isinstance(rows, list) else []:
                source_slug = provider.source_slug_from_url(str(row.get("url", ""))) if isinstance(row, dict) else None
                title = row.get("title") if isinstance(row, dict) else None
                if not source_slug or not isinstance(title, str) or not title_matches(title):
                    continue
                episodes = await self.episodes_for(FALLBACK_PROVIDER, source_slug)
                if not episodes:
                    continue
                if isinstance(anilist_id, int):
                    await asyncio.to_thread(
                        self.store.set_mapping,
                        anilist_id,
                        source_slug,
                        "Matched public WitAnime title and a non-empty public episode list",
                        FALLBACK_PROVIDER,
                    )
                return ({"provider": FALLBACK_PROVIDER, "slug": source_slug, "title": title, "verified": True}, episodes)
        return None

    async def get_episode_servers(self, provider_name: str, episode_url: str) -> list[dict]:
        provider = self.provider(provider_name)
        if not provider.valid_episode_url(episode_url):
            raise ValueError("Unsupported provider episode URL")
        rows = await self._call(provider_name, "get_episode_servers", episode_url)
        servers: list[dict] = []
        seen_urls: set[str] = set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            embed_url = row.get("embed_url")
            if not isinstance(embed_url, str):
                continue
            try:
                key = _normalized_public_url(embed_url)
                parsed = urlparse(key)
            except ValueError:
                continue
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or key in seen_urls:
                continue
            seen_urls.add(key)
            servers.append(dict(row))
        return servers
