"""AniList HTTP/GraphQL adapter. Never imports or calls a streaming source."""

import asyncio
import re
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from catalog_models import NovaAnime


FIELDS = """
id idMal title { romaji english native } synonyms description(asHtml: true)
coverImage { extraLarge large color } bannerImage averageScore genres
seasonYear startDate { year } season status format episodes duration countryOfOrigin
studios(isMain: true) { nodes { name } } trailer { id site } popularity
"""
PAGE_INFO = "pageInfo { currentPage perPage hasNextPage }"
HOME_QUERY = """
query {
  featured: Page(page: 1, perPage: 5) {
    media(type: ANIME, isAdult: false, sort: [TRENDING_DESC, ID_DESC]) { ...AnimeFields }
  }
  topRated: Page(page: 1, perPage: 10) {
    media(type: ANIME, isAdult: false, sort: [SCORE_DESC, ID_DESC]) { ...AnimeFields }
  }
  discover: Page(page: 1, perPage: 24) {
    pageInfo { currentPage perPage hasNextPage }
    media(type: ANIME, isAdult: false, sort: [POPULARITY_DESC, ID_DESC]) { ...AnimeFields }
  }
}
fragment AnimeFields on Media { %s }
""" % FIELDS
PAGE_QUERY = """
query ($page: Int!, $perPage: Int!, $search: String, $sort: [MediaSort]) {
  Page(page: $page, perPage: $perPage) {
    %s
    media(type: ANIME, isAdult: false, search: $search, sort: $sort) { %s }
  }
}
""" % (PAGE_INFO, FIELDS)
DETAIL_QUERY = "query ($id: Int!) { Media(id: $id, type: ANIME, isAdult: false) { %s } }" % FIELDS


class ProviderError(Exception):
    pass


class AnimeNotFound(Exception):
    pass


def safe_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.hostname and not parsed.username else None


def normalize(media: dict, identity: dict, now: int) -> NovaAnime:
    titles = media.get("title") or {}
    title = titles.get("english") or titles.get("romaji") or titles.get("native") or f"Anime {media['id']}"
    alternatives = list(dict.fromkeys(t for t in [*titles.values(), *(media.get("synonyms") or [])] if t and t != title))
    description = None
    if media.get("description"):
        soup = BeautifulSoup(media["description"], "html.parser")
        for node in soup(["script", "style"]):
            node.decompose()
        description = soup.get_text(" ", strip=True) or None
    cover = media.get("coverImage") or {}
    color = cover.get("color")
    trailer = media.get("trailer") or {}
    trailer_url = None
    if trailer.get("site") == "youtube" and re.fullmatch(r"[A-Za-z0-9_-]{11}", trailer.get("id") or ""):
        trailer_url = f"https://www.youtube.com/watch?v={trailer['id']}"
    provider_ids = {"anilist": media["id"]}
    if media.get("idMal"):
        provider_ids["mal"] = media["idMal"]
    status = {"FINISHED": "finished", "RELEASING": "releasing", "NOT_YET_RELEASED": "announced", "CANCELLED": "cancelled", "HIATUS": "hiatus"}
    return NovaAnime(
        **identity, providerIds=provider_ids, title=title, alternativeTitles=alternatives,
        description=description, descriptionLanguage="en" if description else None,
        image=safe_url(cover.get("extraLarge") or cover.get("large")),
        banner=safe_url(media.get("bannerImage")),
        accentColor=color if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color) else None,
        score={"value": media["averageScore"]} if media.get("averageScore") is not None else None,
        genres=media.get("genres") or [], year=media.get("seasonYear") or (media.get("startDate") or {}).get("year"),
        season=(media.get("season") or "").lower() or None,
        status=status.get(media.get("status"), "unknown"), type=(media.get("format") or "").lower() or None,
        episodeCount=media.get("episodes"), runtime=media.get("duration"), country=media.get("countryOfOrigin"),
        studios=[s["name"] for s in (media.get("studios") or {}).get("nodes", []) if s.get("name")],
        trailer=trailer_url, popularity=media.get("popularity"), metadataUpdatedAt=now,
    )


class AniListProvider:
    def __init__(self, client: httpx.AsyncClient, min_interval: float = 2.1):
        self.client = client
        self.min_interval = min_interval
        self.lock = asyncio.Lock()
        self.next_request = 0.0
        self.blocked_until = 0.0

    async def query(self, query: str, variables: dict | None = None) -> dict:
        # One paced upstream request at a time, separate from the legacy source lock.
        async with self.lock:
            if time.monotonic() < self.blocked_until:
                raise ProviderError("AniList is temporarily unavailable")
            await asyncio.sleep(max(0, self.next_request - time.monotonic()))
            self.next_request = time.monotonic() + self.min_interval
            try:
                response = await self.client.post("https://graphql.anilist.co", json={"query": query, "variables": variables or {}})
                if response.status_code == 429:
                    try:
                        delay = float(response.headers.get("Retry-After", "60"))
                    except ValueError:
                        delay = 60
                    self.blocked_until = time.monotonic() + max(1, min(delay, 3600))
                    raise ProviderError("AniList rate limit reached")
                if response.headers.get("X-RateLimit-Remaining") == "0":
                    try:
                        reset_delay = float(response.headers.get("X-RateLimit-Reset", "0")) - time.time()
                    except ValueError:
                        reset_delay = 60
                    self.blocked_until = time.monotonic() + (reset_delay if reset_delay > 0 else 60)
                if response.status_code == 404:
                    raise AnimeNotFound()
                response.raise_for_status()
                payload = response.json()
                if payload.get("errors"):
                    if all(error.get("status") == 404 for error in payload["errors"]):
                        raise AnimeNotFound()
                    self.blocked_until = time.monotonic() + 15
                    raise ProviderError("AniList GraphQL error")
                if not isinstance(payload.get("data"), dict):
                    self.blocked_until = time.monotonic() + 15
                    raise ProviderError("Invalid AniList response")
                return payload["data"]
            except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
                self.blocked_until = max(self.blocked_until, time.monotonic() + 15)
                raise ProviderError("AniList request failed") from error

    async def home(self):
        return await self.query(HOME_QUERY)

    async def page(self, page: int, per_page: int, search: str | None = None):
        data = await self.query(PAGE_QUERY, {"page": page, "perPage": per_page, "search": search, "sort": ["SEARCH_MATCH", "ID_DESC"] if search else ["POPULARITY_DESC", "ID_DESC"]})
        return data["Page"]

    async def detail(self, anilist_id: int):
        media = (await self.query(DETAIL_QUERY, {"id": anilist_id})).get("Media")
        if media is None:
            raise AnimeNotFound()
        if media.get("id") != anilist_id:
            raise ProviderError("AniList returned an unexpected identity")
        return media
