"""WitAnime public-HTML provider.

This adapter deliberately uses ordinary HTTP only. A Cloudflare challenge,
authentication page, or a non-public player is an unavailable source, not
something to automate or bypass.
"""

from __future__ import annotations

import re
from urllib.parse import quote, quote_plus, unquote, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup, Tag

from .base import SourceNotFound, SourceProviderError, SourceUnavailable


BASE_URL = "https://witanime.site"
SOURCE_HOST_SUFFIX = "witanime.site"
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
}


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _source_host(hostname: str | None) -> bool:
    host = (hostname or "").lower().strip(".")
    return host == SOURCE_HOST_SUFFIX or host.endswith("." + SOURCE_HOST_SUFFIX)


def _public_url(value: str | None, base: str) -> str | None:
    if not value:
        return None
    try:
        url = urljoin(base, value)
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return url


def _normalized_playback_url(value: str) -> str:
    """Use a stable URL key without treating a server display name as identity."""
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
    return urlunparse(("https", host + port, parsed.path or "/", "", parsed.query, ""))


def get_episode_number(text: str, url: str = "") -> int | float | None:
    value = f"{text} {url}".lower().replace("٫", ".")
    patterns = (
        r"الحلقة\s*(\d+(?:\.\d+)?)",
        r"episode\s*(\d+(?:\.\d+)?)",
        r"\bep\.?\s*(\d+(?:\.\d+)?)",
        r"(?:-|/)(\d+(?:\.\d+)?)(?:[-/?#]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, re.I)
        if match:
            number = float(match.group(1))
            return int(number) if number.is_integer() else number
    return None


class WitAnimeProvider:
    name = "witanime"

    def __init__(self, client: httpx.AsyncClient | None = None, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                follow_redirects=True,
                headers=DEFAULT_HEADERS,
                timeout=httpx.Timeout(8.0, connect=4.0),
            )

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _html(self, url: str) -> str:
        await self.start()
        assert self._client is not None
        try:
            response = await self._client.get(url)
        except httpx.TimeoutException as exc:
            raise SourceUnavailable("WitAnime public HTTP request timed out") from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailable("WitAnime public HTTP request failed") from exc

        challenge = (
            response.status_code in {403, 429, 503}
            and ("cloudflare" in response.headers.get("server", "").lower()
                 or "cf-ray" in response.headers)
        )
        if challenge:
            raise SourceUnavailable("WitAnime requires a Cloudflare challenge; no bypass is attempted")
        if response.status_code == 404:
            raise SourceNotFound("WitAnime page was not found")
        if response.status_code >= 500:
            raise SourceUnavailable(f"WitAnime returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise SourceProviderError(f"WitAnime returned HTTP {response.status_code}")

        body = response.text
        lowered = body.lower()
        if "just a moment" in lowered or "challenges.cloudflare.com" in lowered:
            raise SourceUnavailable("WitAnime returned a Cloudflare challenge; no bypass is attempted")
        return body

    def anime_url(self, source_slug: str) -> str:
        if not re.fullmatch(r"[\w-]{1,220}", source_slug, flags=re.UNICODE):
            raise ValueError("Invalid WitAnime source slug")
        return f"{self.base_url}/anime/{quote(source_slug, safe='-_')}/"

    def source_slug_from_url(self, url: str) -> str | None:
        try:
            parsed = urlparse(url)
        except ValueError:
            return None
        if parsed.scheme != "https" or not _source_host(parsed.hostname):
            return None
        match = re.fullmatch(r"/(?:anime|movie|movies|film)/([^/]+)/?", parsed.path)
        slug = unquote(match[1]) if match else ""
        return slug if re.fullmatch(r"[\w-]{1,220}", slug, flags=re.UNICODE) else None

    def valid_episode_url(self, episode_url: str) -> bool:
        try:
            parsed = urlparse(episode_url)
        except ValueError:
            return False
        return parsed.scheme == "https" and _source_host(parsed.hostname) and parsed.path.startswith("/watch/")

    @staticmethod
    def _title(anchor: Tag, source_slug: str) -> str:
        image = anchor.find("img")
        choices = [
            image.get("alt") if isinstance(image, Tag) else None,
            anchor.get("title"),
        ]
        heading = anchor.select_one("h1,h2,h3,h4,h5,h6,.title,.anime-title")
        choices.append(heading.get_text(" ", strip=True) if heading else None)
        choices.append(anchor.get_text(" ", strip=True))
        for choice in choices:
            value = clean(choice)
            if value and value not in {"شاهد الآن", "شاهد", "مشاهدة"}:
                return value
        return source_slug.replace("-", " ")

    async def search_anime(self, query: str) -> list[dict]:
        query = clean(query)
        if len(query) < 2:
            return []
        html = await self._html(f"{self.base_url}/search?q={quote_plus(query)}")
        soup = BeautifulSoup(html, "lxml")
        results: list[dict] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
            href = _public_url(anchor.get("href"), self.base_url)
            slug = self.source_slug_from_url(href or "")
            if not href or not slug or href in seen:
                continue
            seen.add(href)
            image = anchor.find("img")
            image_url = _public_url(
                image.get("data-src") or image.get("data-lazy-src") or image.get("src") if isinstance(image, Tag) else None,
                self.base_url,
            )
            results.append({"title": self._title(anchor, slug), "url": href, "image": image_url, "kind": "anime"})
        return results

    async def get_anime(self, source_slug: str) -> dict | None:
        html = await self._html(self.anime_url(source_slug))
        soup = BeautifulSoup(html, "lxml")
        heading = soup.select_one("h1")
        title = clean(heading.get_text(" ", strip=True) if heading else "") or source_slug.replace("-", " ")
        return {"title": title, "url": self.anime_url(source_slug), "kind": "anime"}

    async def get_episodes(self, source_slug: str) -> list[dict]:
        anime_url = self.anime_url(source_slug)
        html = await self._html(anime_url)
        soup = BeautifulSoup(html, "lxml")
        unique: dict[int | float, dict] = {}
        for anchor in soup.select("a[href]"):
            episode_url = _public_url(anchor.get("href"), anime_url)
            if not episode_url or not self.valid_episode_url(episode_url):
                continue
            title = clean(anchor.get_text(" ", strip=True))
            number = get_episode_number(title, episode_url)
            if number is None:
                continue
            unique.setdefault(number, {
                "episode": number,
                "title": title or f"الحلقة {number}",
                "url": episode_url,
            })
        return [unique[number] for number in sorted(unique)]

    async def get_episode_servers(self, episode_url: str) -> list[dict]:
        if not self.valid_episode_url(episode_url):
            raise ValueError("Unsupported WitAnime episode URL")
        html = await self._html(episode_url)
        soup = BeautifulSoup(html, "lxml")
        servers: list[dict] = []
        seen_urls: set[str] = set()

        def add(name: str | None, raw_url: str | None, server_id: str | None = None, attributes: dict | None = None):
            embed_url = _public_url(raw_url, episode_url)
            if not embed_url:
                return
            key = _normalized_playback_url(embed_url)
            if key in seen_urls:
                return
            seen_urls.add(key)
            servers.append({
                "name": clean(name) or f"WitAnime {len(servers) + 1}",
                "id": server_id or str(len(servers) + 1),
                "attributes": attributes or {},
                "embed_url": embed_url,
            })

        for index, frame in enumerate(soup.select("iframe[src], iframe[data-src]"), start=1):
            raw_url = frame.get("src") or frame.get("data-src")
            add(frame.get("title") or frame.get("aria-label") or f"WitAnime {index}", raw_url, frame.get("data-server") or frame.get("id"))

        for anchor in soup.select("a[href]"):
            text = clean(anchor.get_text(" ", strip=True))
            marker = f"{text} {anchor.get('class', '')}".lower()
            if not any(token in marker for token in ("سيرفر", "server", "مشغل", "player")):
                continue
            add(text, anchor.get("href"), anchor.get("data-server") or anchor.get("data-id"))
        return servers
