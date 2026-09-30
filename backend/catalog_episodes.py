"""Catalog source matching, bounded episode lists, and provider-aware watch lookup."""

import asyncio
import json
import re
import time
import unicodedata
from urllib.parse import quote, unquote, urlparse

from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Query, Request, Response

from anilist_provider import AnimeNotFound, ProviderError
from anime4up_scraper import BASE_URL, SOURCE_HOST_SUFFIX
from provider_manager import ProviderManager
from providers.anime4up import Anime4upProvider
from providers.base import ProviderUnavailable, SourceProviderError


def title_key(value):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", value).casefold())


def _neutral_title_key(value):
    """Compare titles without harmless source-site labels such as ``(TV)``."""
    value = re.sub(r"[\(\[]\s*(?:tv|anime)\s*[\)\]]", " ", value, flags=re.I)
    return title_key(value)


def _season_title_root(value):
    """Return the title before an explicit season number, if it has one."""
    match = re.search(r"\bseason\s*(?:\d+|[ivxlcdm]+)\b", value, flags=re.I)
    if not match:
        return None
    root = title_key(value[:match.start()])
    return root or None


def _source_search_queries(anime, query):
    """Build a small, conservative set of source search spellings.

    AniList's season labels and source-site labels sometimes use different
    numbering (for example, ``Gintama Season 3`` versus ``Season 4``).  The
    broad title is only used to find candidates; an external AniList/MAL ID is
    still required before a source can be automatically selected.
    """
    if query:
        return [query]
    primary = []
    fallback = []
    seen = set()

    def add(values, value):
        key = " ".join(value.split()).casefold()
        if key and key not in seen:
            seen.add(key)
            values.append(value)

    for value in [anime["title"], *anime["alternativeTitles"]]:
        if not isinstance(value, str) or not re.search(r"[a-zA-Z]{2}", value):
            continue
        value = value.strip()[:100]
        if value:
            add(primary, value)
        # Source search can be strict about an alternate subtitle (for example,
        # "Death Note: Relight" versus "Death Note: Rewrite"). The base title
        # broadens discovery only; the identity check below remains mandatory.
        base_title = re.split(r"\s*[:\-–—]\s*", value, maxsplit=1)[0].strip()
        if len(base_title) >= 2:
            add(fallback, base_title)
        simplified = re.sub(r"[\(\[].*?[\)\]]", " ", value)
        simplified = re.sub(r"\b(?:season|part|cour)\s*(?:\d+|[ivxlcdm]+)\b.*", " ", simplified, flags=re.I)
        simplified = " ".join(re.findall(r"[A-Za-z][A-Za-z0-9']*", simplified))[:100]
        if len(simplified) >= 2:
            add(fallback, simplified)
    # Preserve the original two-title lookup budget, then make one bounded
    # structural fallback available for season labels that differ by site.
    return [*primary[:2], *fallback[:1]]


def _identity_candidate(source_title, catalog_titles):
    """Whether it is safe to spend a bounded identity lookup on a candidate.

    Text never establishes a mapping. It only admits a likely equivalent title
    to the external-ID verification below, while excluding obvious sequels,
    movies, and unrelated recommendations.
    """
    candidate = _neutral_title_key(source_title)
    candidate_season_root = _season_title_root(source_title)
    for title in catalog_titles:
        if candidate == _neutral_title_key(title):
            return True
        title_season_root = _season_title_root(title)
        if title_season_root and candidate_season_root and title_season_root == candidate_season_root:
            return True
    return False


def source_slug(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not (parsed.hostname == SOURCE_HOST_SUFFIX or (parsed.hostname or "").endswith("." + SOURCE_HOST_SUFFIX)):
        return None
    match = re.fullmatch(r"/anime/([^/]+)/?", parsed.path)
    slug = unquote(match[1]) if match else ""
    return slug if re.fullmatch(r"[\w-]{1,220}", slug) else None


def _episode_series_key(url):
    """Group episode links that belong to the same title without trusting page layout."""
    try:
        slug = unquote(urlparse(url).path.rstrip("/").split("/")[-1])
    except Exception:
        return ""
    original = slug
    slug = re.sub(
        r"(?:[-_\s]*)(?:الحلقة|episode|ep)[-_\s]*\d+(?:\.\d+)?(?:[-_\s].*)?$",
        "",
        slug,
        flags=re.I,
    )
    if slug == original:
        slug = re.sub(r"[-_\s]+\d+(?:\.\d+)?$", "", slug)
    return title_key(slug)


def _playback_type(url):
    path = urlparse(url).path.lower()
    if path.endswith(".m3u8"):
        return "hls"
    if path.endswith((".mp4", ".m4v", ".webm", ".ogv", ".ogg")):
        return "direct"
    return "iframe"


def _upstream_status(error):
    if isinstance(error, ProviderUnavailable):
        return error.status
    match = re.search(r"\bHTTP\s+(\d{3})\b", str(error), flags=re.I)
    return int(match.group(1)) if match else None


def _fallback_episode_grid(soup, scraper, base):
    """Recover the real episode grid when Anime4up changes its CSS classes.

    The source currently exposes episode links reliably, but the wrapper class is
    not stable. We ignore obvious sidebar/footer/download regions and choose the
    largest same-series cluster instead of treating a single 'watch now' CTA as
    the complete episode list.
    """
    rows = []
    excluded_hints = (
        "sidebar", "related", "recommend", "download", "footer",
        "anime-external-links", "social", "telegram",
    )
    for anchor in soup.find_all("a", href=True):
        excluded = False
        for parent in anchor.parents:
            if getattr(parent, "name", None) in {"aside", "footer", "header"}:
                excluded = True
                break
            classes = " ".join(parent.get("class", [])) if hasattr(parent, "get") else ""
            identifier = parent.get("id", "") if hasattr(parent, "get") else ""
            marker = f"{classes} {identifier}".lower()
            if any(hint in marker for hint in excluded_hints):
                excluded = True
                break
        if excluded:
            continue
        rows.extend(scraper._parse_episode_page(str(anchor), base))

    if not rows:
        return []

    groups = {}
    for row in rows:
        key = _episode_series_key(row.get("url", "")) or "__unknown__"
        groups.setdefault(key, {})[row["episode"]] = row

    # Main episode grids overwhelmingly form the largest repeated URL family.
    # Number-span is a tie breaker for layouts with duplicated cards.
    def score(group):
        values = list(group.values())
        numbers = [float(item["episode"]) for item in values]
        span = max(numbers) - min(numbers) if len(numbers) > 1 else 0
        return (len(values), span)

    best = max(groups.values(), key=score)
    return list(best.values())


class EpisodeCatalog:
    def __init__(self, catalog, scraper, provider_manager=None):
        self.catalog = catalog
        self.store = catalog.store
        self.scraper = scraper
        # Keep the old scraper path as the default. api.py injects the
        # additional provider manager; isolated legacy callers remain valid.
        self.provider_manager = provider_manager or ProviderManager(
            self.store, [Anime4upProvider(scraper)]
        )
        self.inflight = {}
        self.cache_lock = asyncio.Lock()
        self.limit = asyncio.Semaphore(2)

    async def close(self):
        tasks = list(self.inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _availability(self):
        return self.provider_manager.availability()

    def _both_external_providers_unavailable(self):
        availability = self._availability()
        return all(
            availability.get(name, {}).get("status") == "unavailable"
            for name in ("anime4up", "witanime")
        )

    @staticmethod
    def _stored_candidate(anime, selected, provider):
        """Resolve a verified mapping by its full provider/slug identity.

        Source slugs are provider-local identifiers.  When a fallback happens
        to use the same text as Anime4Up, it must not shadow the primary
        mapping or make an explicit ``provider=anime4up`` request fail.
        """
        if not selected or not provider:
            return None
        matches = [
            mapping for mapping in anime.get("sourceMappings", [])
            if mapping.get("slug") == selected
            and mapping.get("source") == provider
        ]
        if not matches:
            return None
        mapping = matches[0]
        return {
            "provider": mapping["source"],
            "slug": mapping["slug"],
            "title": anime["title"],
            "verified": True,
        }

    def _sources_response(self, sources, selected_source, selected_provider=None):
        if selected_source is None:
            selected_provider = None
        else:
            matches = [
                item for item in sources
                if item["slug"] == selected_source
                and item["verified"]
                and (selected_provider is None or item["provider"] == selected_provider)
            ]
            if len(matches) != 1:
                raise ProviderError("Selected episode source identity is ambiguous")
            selected_provider = matches[0]["provider"]
        return {
            "sources": sources,
            "selectedSource": selected_source,
            "selectedProvider": selected_provider,
            "availability": self._availability(),
        }

    def _unavailable_response(self, candidate, page, offset):
        """Keep an upstream denial out of the page-level error path."""
        availability = self._availability()
        if candidate:
            return {
                **self._response(candidate, {"items": [], "pages": 1, "next": None}, page, offset),
                "externalUnavailable": self._both_external_providers_unavailable(),
            }
        return {
            "items": [],
            "sources": [],
            "selectedSource": None,
            "page": page,
            "offset": offset,
            "totalPages": 1,
            "next": None,
            "availability": availability,
            "externalUnavailable": self._both_external_providers_unavailable(),
        }

    async def _cached(self, key, loader, ttl=600):
        # The v3 parser recognizes the source's Arabic movie labels. Bumping
        # the persistent key prevents an old cached empty movie grid from
        # masking that fix until its TTL expires.
        key = "episodes-v3:" + key
        # Check and task creation must be one critical section. Otherwise a
        # caller that observed an empty SQLite cache just before another
        # caller's refresh completes can miss both the persisted cache and the
        # now-cleaned in-flight task, causing a duplicate provider GET.
        async with self.cache_lock:
            entry = await asyncio.to_thread(self.store.get_cache, key)
            if entry and entry["expiresAt"] > time.time():
                return entry["data"]
            task = self.inflight.get(key)
            if task is None:
                if len(self.inflight) >= 24:
                    raise ProviderError("Episode lookup queue is full")

                async def refresh():
                    async with asyncio.timeout(20):
                        async with self.limit:
                            data = await loader()
                    await asyncio.to_thread(self.store.put_cache, key, data, ttl, 0)
                    return data

                task = asyncio.create_task(refresh())
                self.inflight[key] = task

                def cleanup(done):
                    self.inflight.pop(key, None)
                    if not done.cancelled():
                        done.exception()

                task.add_done_callback(cleanup)
        return await asyncio.shield(task)

    async def _source_page(self, slug, page=1):
        base = f"{BASE_URL}/anime/{quote(slug, safe='-_')}/"
        url = base if page == 1 else f"{base}page/{page}/"

        async def load():
            last_error = None

            for attempt in range(1, 3):
                try:
                    print(
                        f"[catalog episodes] requesting source page "
                        f"provider=anime4up source={slug} page={page}",
                        flush=True,
                    )
                    async with asyncio.timeout(8):
                        html = await self.scraper.get_html(url)
                    self.provider_manager.mark_available("anime4up")
                    break
                except Exception as exc:
                    error = Anime4upProvider.public_error(exc)
                    if isinstance(error, ProviderUnavailable):
                        self.provider_manager.mark_unavailable("anime4up", error)
                    last_error = error

                    print(
                        f"[catalog episodes] source attempt {attempt}/2 failed "
                        f"for {url}: {type(error).__name__}: {error}",
                        flush=True,
                    )

                    # A public 403/429 must allow the fallback immediately;
                    # only short transient failures receive one retry.
                    if not isinstance(error, ProviderUnavailable) or not error.retryable or attempt >= 2:
                        raise error from exc

                    await asyncio.sleep(0.25 * attempt)
            else:
                raise last_error or ProviderError(
                    "Could not load source episode page"
                )

            soup = BeautifulSoup(html, "lxml")
            pages = {page}
            for anchor in soup.find_all("a", href=True):
                parsed = urlparse(anchor["href"])
                # Only pagination belonging to this exact anime, never a related title.
                match = re.fullmatch(re.escape(urlparse(base).path) + r"page/(\d+)/?", parsed.path)
                if match and 1 <= int(match[1]) <= 1000:
                    pages.add(int(match[1]))
            # Prefer a known episode-grid wrapper, but Anime4up changes these
            # classes from time to time. If the wrapper is absent, recover the
            # largest real episode-link cluster from the page instead of using
            # the single "watch now" CTA as if it were the whole season.
            listing = soup.select_one("#episodesList, .episodes-list, .anime-episodes")
            episodes = self.scraper._parse_episode_page(str(listing), base) if listing else []
            if not episodes:
                episodes = _fallback_episode_grid(soup, self.scraper, base)
            if not episodes:
                # Movies may legitimately expose only one watch link.
                movie_links = soup.select_one(".anime-external-links")
                episodes = self.scraper._parse_episode_page(str(movie_links), base) if movie_links else []
            unique = {item["episode"]: item for item in episodes}
            numbers = list(unique)
            descending = sum(a > b for a, b in zip(numbers, numbers[1:])) > sum(a < b for a, b in zip(numbers, numbers[1:]))
            ids = {"mal": set(), "anilist": set()}
            identity_links = soup.select_one(".anime-external-links")
            if identity_links:
                for anchor in identity_links.find_all("a", href=True):
                    parsed = urlparse(anchor["href"])
                    match = re.match(r"/anime/(\d+)(?:/|$)", parsed.path)
                    if match:
                        if parsed.hostname in ("myanimelist.net", "www.myanimelist.net"):
                            ids["mal"].add(int(match[1]))
                        elif parsed.hostname in ("anilist.co", "www.anilist.co"):
                            ids["anilist"].add(int(match[1]))
            return {"items": sorted(unique.values(), key=lambda item: item["episode"]), "pages": max(pages), "descending": descending, "providerIds": {name: sorted(values) for name, values in ids.items()}}

        return await self._cached(f"page:{slug}:{page}", load)

    async def _anime4up_sources(self, anime, query=None):
        mappings = [m for m in anime["sourceMappings"] if m["source"] == "anime4up"]
        verified = [{"provider": "anime4up", "slug": m["slug"], "title": anime["title"], "verified": True} for m in mappings]
        if verified and query is None:
            return {"sources": verified, "selectedSource": verified[0]["slug"] if len(verified) == 1 else None}

        titles = list(dict.fromkeys([anime["title"], *anime["alternativeTitles"]]))
        queries = _source_search_queries(anime, query)
        candidates = {}
        inspected = set()
        choices = []
        for term in queries:
            async def search(term=term):
                provider = Anime4upProvider(self.scraper)
                try:
                    rows = await provider.search_anime(term)
                    self.provider_manager.mark_available("anime4up")
                    return rows
                except ProviderUnavailable as error:
                    self.provider_manager.mark_unavailable("anime4up", error)
                    raise
            try:
                rows = await self._cached("search:" + term.casefold(), search, 600)
            except ProviderUnavailable:
                if verified:
                    # A query endpoint outage cannot erase a durable Anime4Up
                    # identity. Keep it selected and let the exact episode-page
                    # request establish whether that mapping is usable.
                    verified = list({item["slug"]: item for item in verified}.values())
                    return {
                        "sources": verified,
                        "selectedSource": verified[0]["slug"] if len(verified) == 1 else None,
                    }
                raise
            for row in rows:
                candidate = source_slug(row.get("url", ""))
                if candidate:
                    candidates[candidate] = {"provider": "anime4up", "slug": candidate, "title": row["title"], "verified": False}
            choices = sorted(candidates.values(), key=lambda item: not _identity_candidate(item["title"], titles))[:20]

            async def inspect(item):
                try:
                    return item, await self._source_page(item["slug"])
                except (RuntimeError, TimeoutError, ProviderError):
                    return item, None  # A candidate's failure must not hide other source choices.

            # Inspect only title-family matches and cap the parallel work. An
            # exact provider ID is still mandatory, so a source title alone
            # cannot map a different season or movie.
            inspectable = [item for item in choices if item["slug"] not in inspected and _identity_candidate(item["title"], titles)][:8]
            inspected.update(item["slug"] for item in inspectable)
            for item, detail in await asyncio.gather(*(inspect(item) for item in inspectable)):
                if detail is None:
                    continue
                checks = [values == [anime["providerIds"][name]] for name, values in detail["providerIds"].items() if values and name in anime["providerIds"]]
                if checks and all(checks):
                    if item["slug"] not in {m["slug"] for m in mappings}:
                        await asyncio.to_thread(self.store.set_mapping, anime["providerIds"]["anilist"], item["slug"], "Verified against the source title's explicit AniList/MAL external link")
                    item["verified"] = True
                    verified.append(item)
            if verified and query is None:
                verified = list({item["slug"]: item for item in verified}.values())
                return {"sources": verified, "selectedSource": verified[0]["slug"] if len(verified) == 1 else None}
        by_slug = {item["slug"]: item for item in [*choices, *verified]}
        verified = list({item["slug"]: item for item in verified}.values())
        return {"sources": verified if verified and query is None else list(by_slug.values()), "selectedSource": verified[0]["slug"] if len(verified) == 1 else None}

    async def sources(self, slug, query=None):
        anime = (await self.catalog.detail_by_slug(slug))["data"]
        # Always resolve the Anime4Up primary first.  A stored WitAnime result
        # is fallback evidence, not permission to replace a verified primary
        # mapping merely because this request omitted ``q``.
        try:
            primary = await self._anime4up_sources(anime, query)
        except ProviderUnavailable:
            # A search/identity failure is itself a strict-fallback condition.
            resolved = await self._witanime_fallback(anime, query)
            if resolved:
                candidate, _ = resolved
                return self._sources_response([candidate], candidate["slug"], candidate["provider"])
            return self._sources_response([], None)
        except Exception:
            # Parsing or catalog programming errors remain visible rather than
            # being mislabeled as a provider access denial.
            raise
        if primary["sources"]:
            return self._sources_response(
                primary["sources"], primary["selectedSource"],
                "anime4up" if primary["selectedSource"] else None,
            )
        resolved = await self._witanime_fallback(anime, query)
        if resolved:
            candidate, _ = resolved
            return self._sources_response([candidate], candidate["slug"], candidate["provider"])
        return self._sources_response(primary["sources"], primary["selectedSource"])

    @staticmethod
    def _witanime_page(items, page, offset):
        if page != 1:
            raise HTTPException(404, "Episode page does not exist")
        if offset and offset >= len(items):
            raise HTTPException(404, "Episode range does not exist")
        return {
            "items": items[offset:offset + 30], "pages": 1, "descending": False,
            "next": {"page": 1, "offset": offset + 30} if offset + 30 < len(items) else None,
        }

    async def _witanime_fallback(self, anime, query):
        titles = list(dict.fromkeys([anime["title"], *anime["alternativeTitles"]]))
        return await self.provider_manager.fallback_source(
            anime,
            _source_search_queries(anime, query),
            lambda source_title: _identity_candidate(source_title, titles),
        )

    async def _witanime_data(self, candidate, page, offset):
        rows = await self.provider_manager.episodes_for("witanime", candidate["slug"])
        return self._witanime_page(rows, page, offset) if rows else None

    def _response(self, candidate, data, page, offset, requested_candidate=None):
        chunk = data["items"]
        response = {
            "sourceSlug": candidate["slug"], "sourceTitle": candidate["title"],
            "sourceProvider": candidate["provider"], "verified": candidate["verified"],
            # Episode identity always carries its provider. The watch route
            # must never infer it from a source slug alone.
            "items": [{"episode": e["episode"], "title": e["title"], "sources": [
                {"provider": candidate["provider"], "sourceSlug": candidate["slug"], "episodeUrl": e["url"]}
            ]} for e in chunk],
            "page": page, "offset": offset, "totalPages": data["pages"], "next": data.get("next"),
            "availability": self._availability(),
            "externalUnavailable": self._both_external_providers_unavailable(),
        }
        if requested_candidate and (
            requested_candidate["provider"] != candidate["provider"]
            or requested_candidate["slug"] != candidate["slug"]
        ):
            # Let the frontend verify that a provider/source mismatch is an
            # intentional backend fallback, not an unrelated response.
            response["requestedSource"] = {
                "provider": requested_candidate["provider"],
                "sourceSlug": requested_candidate["slug"],
            }
        print(
            f"[catalog episodes] parsed {len(chunk)} episodes "
            f"provider={candidate['provider']} source={candidate['slug']}",
            flush=True,
        )
        return response

    async def episodes(self, slug, selected, page=1, offset=0, query=None, provider=None):
        anime = (await self.catalog.detail_by_slug(slug))["data"]
        # An explicit provider/source pair is authoritative when that verified
        # mapping exists.  Do not re-resolve it through a provider-agnostic
        # slug list where a same-slug fallback mapping could shadow it.
        candidate = self._stored_candidate(anime, selected, provider)
        if candidate is None:
            resolved = await self.sources(slug, query)
            selected = selected or resolved["selectedSource"]
            selected_provider = provider or resolved.get("selectedProvider")
            candidate = next((
                item for item in resolved["sources"]
                if item["slug"] == selected
                and (selected_provider is None or item["provider"] == selected_provider)
            ), None)
        if not candidate:
            # ``sources()`` already exhausted primary then fallback discovery.
            # Do not run fallback twice: a second search can overwrite the
            # availability state that explains why no candidate was usable.
            if self._both_external_providers_unavailable():
                mappings = sorted(
                    anime.get("sourceMappings", []),
                    key=lambda item: (item.get("source") != "anime4up", item.get("source", "")),
                )
                unavailable_candidate = None
                if mappings:
                    mapping = mappings[0]
                    unavailable_candidate = self._stored_candidate(
                        anime, mapping.get("slug"), mapping.get("source")
                    )
                return self._unavailable_response(unavailable_candidate, page, offset)
            raise HTTPException(409, "Choose a source title from this anime's candidates")
        requested_candidate = candidate
        print(
            f"[catalog episodes] selected source={candidate['slug']}",
            flush=True,
        )
        print(
            f"[catalog episodes] provider={candidate['provider']}",
            flush=True,
        )
        if candidate["provider"] == "witanime":
            data = await self._witanime_data(candidate, page, offset)
            if data:
                return self._response(candidate, data, page, offset)
            # The mapped provider may be transiently unavailable; then return
            # to strict Anime4Up primary rather than retrying WitAnime search.
            try:
                primary = await self._anime4up_sources(anime, query)
            except ProviderUnavailable:
                return self._unavailable_response(candidate, page, offset)
            primary_selected = primary["selectedSource"]
            candidate = next((item for item in primary["sources"] if item["slug"] == primary_selected), None)
            if not candidate:
                raise ProviderError("Could not load mapped source episodes")

        primary_error = None
        try:
            first = await self._source_page(candidate["slug"])
            total_pages = first["pages"]
            if page > total_pages:
                raise HTTPException(404, "Episode page does not exist")
            physical = total_pages - page + 1 if first["descending"] else page
            data = first if physical == 1 else await self._source_page(candidate["slug"], physical)
            if data["items"]:
                if offset and offset >= len(data["items"]):
                    raise HTTPException(404, "Episode range does not exist")
                item_count = len(data["items"])
                chunk = data["items"][offset:offset + 30]
                data = {**data, "items": chunk, "next": {"page": page, "offset": offset + 30} if offset + 30 < item_count else ({"page": page + 1, "offset": 0} if page < total_pages else None)}
                return self._response(candidate, data, page, offset, requested_candidate)
        except HTTPException:
            raise
        except Exception as exc:
            primary_error = exc

        fallback = await self._witanime_fallback(anime, query)
        if fallback:
            fallback_candidate, rows = fallback
            return self._response(
                fallback_candidate,
                self._witanime_page(rows, page, offset),
                page,
                offset,
                requested_candidate,
            )
        if isinstance(primary_error, ProviderUnavailable):
            return self._unavailable_response(candidate, page, offset)
        if primary_error:
            raise primary_error
        return self._response(candidate, {"items": [], "pages": 1, "next": None}, page, offset)

    @staticmethod
    def _anime4up_watch_source(
        anime, selected_provider=None, selected_source=None, requested_source=None
    ):
        """Choose only a verified Anime4Up mapping for playback lookup."""
        mappings = [
            item for item in anime.get("sourceMappings", [])
            if item.get("source") == "anime4up"
            and isinstance(item.get("slug"), str)
        ]
        preferred = []
        if requested_source:
            preferred.append(requested_source)
        if selected_provider == "anime4up" and selected_source:
            preferred.append(selected_source)
        for source_slug in preferred:
            if any(item["slug"] == source_slug for item in mappings):
                return source_slug
        return mappings[0]["slug"] if len(mappings) == 1 else None

    async def _anime4up_watch_episode_url(self, source_slug, episode):
        """Find one exact public episode URL without crawling a long series."""
        target = float(episode)

        def match(data):
            for item in data.get("items", []):
                number = item.get("episode")
                episode_url = item.get("url")
                if (
                    isinstance(number, (int, float))
                    and not isinstance(number, bool)
                    and float(number) == target
                    and isinstance(episode_url, str)
                ):
                    return episode_url
            return None

        print(
            f"[catalog watch] requesting Anime4Up source page "
            f"source={source_slug} episode={episode}",
            flush=True,
        )
        first = await self._source_page(source_slug, 1)
        episode_url = match(first)
        if episode_url:
            return episode_url

        total_pages = int(first.get("pages") or 1)
        if total_pages <= 1:
            return None

        # Physical Anime4Up pages are monotonic. Estimate by the first page's
        # range, then retain a binary-search fallback. This keeps One Piece
        # bounded instead of downloading every historical page merely to open
        # one episode.
        descending = bool(first.get("descending"))
        first_numbers = [
            float(item["episode"]) for item in first.get("items", [])
            if isinstance(item.get("episode"), (int, float))
            and not isinstance(item.get("episode"), bool)
        ]
        if first_numbers:
            page_size = max(1, len(first_numbers))
            boundary = max(first_numbers) if descending else min(first_numbers)
            distance = boundary - target if descending else target - boundary
            estimated_page = max(2, min(total_pages, int(distance // page_size) + 1))
            estimated = await self._source_page(source_slug, estimated_page)
            episode_url = match(estimated)
            if episode_url:
                return episode_url

        low, high = 2, total_pages
        while low <= high:
            page = (low + high) // 2
            data = await self._source_page(source_slug, page)
            episode_url = match(data)
            if episode_url:
                return episode_url
            numbers = [
                float(item["episode"]) for item in data.get("items", [])
                if isinstance(item.get("episode"), (int, float))
                and not isinstance(item.get("episode"), bool)
            ]
            if not numbers:
                break
            minimum, maximum = min(numbers), max(numbers)
            if minimum <= target <= maximum:
                return None
            if descending:
                if target < minimum:
                    low = page + 1
                else:
                    high = page - 1
            elif target > maximum:
                low = page + 1
            else:
                high = page - 1
        return None

    @staticmethod
    def _watch_attempt(
        provider, source_slug, episode_url, status, upstream_status=None,
        raw_count=0, servers=None,
    ):
        normalized = []
        for row in servers or []:
            embed_url = row.get("embed_url")
            if not isinstance(embed_url, str):
                continue
            playback_type = row.get("type")
            normalized.append({
                **row,
                "type": playback_type
                if playback_type in {"iframe", "direct", "hls"}
                else _playback_type(embed_url),
            })
        return {
            "provider": provider,
            "sourceSlug": source_slug,
            "episodeUrl": episode_url,
            "status": status,
            "upstreamStatus": upstream_status,
            "rawCandidateCount": raw_count,
            "count": len(normalized),
            "servers": normalized,
        }

    @staticmethod
    def _log_watch_attempt(attempt):
        provider = attempt["provider"]
        print(
            f"[catalog watch] provider={provider} upstream HTTP status="
            f"{attempt['upstreamStatus']}",
            flush=True,
        )
        print(
            f"[catalog watch] provider={provider} raw server candidates="
            f"{attempt['rawCandidateCount']}",
            flush=True,
        )
        print(
            f"[catalog watch] provider={provider} accepted servers="
            f"{attempt['count']}",
            flush=True,
        )
        print(
            f"[catalog watch] provider={provider} server names="
            f"{json.dumps([item.get('name') for item in attempt['servers']], ensure_ascii=False)}",
            flush=True,
        )
        print(
            f"[catalog watch] provider={provider} server types="
            f"{json.dumps([item.get('type') for item in attempt['servers']])}",
            flush=True,
        )
        print(
            f"[catalog watch] provider={provider} final playable URLs="
            f"{json.dumps([item.get('embed_url') for item in attempt['servers']])}",
            flush=True,
        )

    async def _provider_watch_attempt(self, provider, source_slug, episode_url):
        try:
            raw, accepted = await self.provider_manager.episode_server_candidates(
                provider, episode_url
            )
            attempt = self._watch_attempt(
                provider,
                source_slug,
                episode_url,
                "available" if accepted else "empty",
                200,
                len(raw),
                accepted,
            )
        except ProviderUnavailable as error:
            attempt = self._watch_attempt(
                provider, source_slug, episode_url, "unavailable", error.status
            )
            print(
                f"[catalog watch] provider={provider} request failed: "
                f"{type(error).__name__}: {error}",
                flush=True,
            )
        except (SourceProviderError, ValueError) as error:
            attempt = self._watch_attempt(
                provider, source_slug, episode_url, "error", _upstream_status(error)
            )
            print(
                f"[catalog watch] provider={provider} request failed: "
                f"{type(error).__name__}: {error}",
                flush=True,
            )
        except Exception as error:
            attempt = self._watch_attempt(
                provider, source_slug, episode_url, "error", _upstream_status(error)
            )
            print(
                f"[catalog watch] provider={provider} request failed: "
                f"{type(error).__name__}: {error}",
                flush=True,
            )
        self._log_watch_attempt(attempt)
        return attempt

    async def watch_servers(
        self, slug, episode, selected_provider=None, selected_url=None,
        selected_source=None, requested_source=None, allow_fallback=True,
    ):
        if bool(selected_provider) != bool(selected_url):
            raise HTTPException(422, "Selected provider and episode URL must be supplied together")
        if selected_provider:
            provider = self.provider_manager.provider(selected_provider)
            if not provider.valid_episode_url(selected_url):
                raise HTTPException(422, "Selected episode URL does not match its provider")

        anime = (await self.catalog.detail_by_slug(slug))["data"]
        anime4up_source = self._anime4up_watch_source(
            anime, selected_provider, selected_source, requested_source
        )
        print(f"[catalog watch] requested anime slug={slug}", flush=True)
        print(f"[catalog watch] episode number={episode}", flush=True)
        print(f"[catalog watch] selected provider={selected_provider}", flush=True)
        print(f"[catalog watch] Anime4Up source slug={anime4up_source}", flush=True)

        attempts = []
        anime4up_url = selected_url if selected_provider == "anime4up" else None
        anime4up_resolution_error = None
        if anime4up_url is None and anime4up_source:
            try:
                anime4up_url = await self._anime4up_watch_episode_url(
                    anime4up_source, episode
                )
            except Exception as error:
                anime4up_resolution_error = error

        print(f"[catalog watch] Anime4Up episode URL={anime4up_url}", flush=True)
        if anime4up_url:
            anime4up_attempt = await self._provider_watch_attempt(
                "anime4up", anime4up_source or selected_source, anime4up_url
            )
        elif anime4up_resolution_error is not None:
            status = _upstream_status(anime4up_resolution_error)
            anime4up_attempt = self._watch_attempt(
                "anime4up",
                anime4up_source,
                None,
                "unavailable" if isinstance(anime4up_resolution_error, ProviderUnavailable) else "error",
                status,
            )
            print(
                f"[catalog watch] provider=anime4up episode resolution failed: "
                f"{type(anime4up_resolution_error).__name__}: {anime4up_resolution_error}",
                flush=True,
            )
            self._log_watch_attempt(anime4up_attempt)
        else:
            anime4up_attempt = self._watch_attempt(
                "anime4up",
                anime4up_source,
                None,
                "not_found" if anime4up_source else "not_mapped",
                200 if anime4up_source else None,
            )
            self._log_watch_attempt(anime4up_attempt)
        attempts.append(anime4up_attempt)

        # The episode reference is a fallback input, not the playback priority.
        # Do not contact WitAnime when Anime4Up already supplied playable URLs.
        if (
            anime4up_attempt["count"] == 0
            and allow_fallback
            and selected_provider
            and selected_provider != "anime4up"
        ):
            attempts.append(await self._provider_watch_attempt(
                selected_provider, selected_source, selected_url
            ))

        return {
            "animeSlug": slug,
            "episode": episode,
            "selectedProvider": selected_provider,
            "attempts": attempts,
            "availability": self._availability(),
        }

    async def episode_servers(self, provider, episode_url):
        servers = await self.provider_manager.get_episode_servers(provider, episode_url)
        return {"provider": provider, "url": episode_url, "count": len(servers), "servers": servers}


router = APIRouter(prefix="/api/catalog", tags=["catalog episodes"])


async def run(request, response, method, *args):
    response.headers["Cache-Control"] = "no-store"
    service = getattr(request.app.state, "catalog_episodes", None)
    if service is None:
        raise HTTPException(503, "Episode catalog is unavailable")
    try:
        async with asyncio.timeout(22):
            return await getattr(service, method)(*args)
    except AnimeNotFound:
        raise HTTPException(404, "Catalog anime not found") from None
    except HTTPException:
        raise
    except Exception as exc:
        print(
            f"[catalog episodes] {method} failed: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        raise HTTPException(
            502,
            "Could not load source episodes. Try again shortly."
        ) from None


@router.get("/sources")
async def sources(request: Request, response: Response, slug: str = Query(min_length=1, max_length=220, pattern=r"^[a-z0-9-]+$"), q: str | None = Query(None, min_length=2, max_length=100)):
    if q is not None and len(q.strip()) < 2:
        raise HTTPException(422, "Source query is too short")
    return await run(request, response, "sources", slug, q.strip() if q else None)


@router.get("/episode-list")
async def episode_list(request: Request, response: Response, slug: str = Query(min_length=1, max_length=220, pattern=r"^[a-z0-9-]+$"), source: str | None = Query(None, min_length=1, max_length=220, pattern=r"^[\w-]+$"), provider: str | None = Query(None, pattern=r"^(anime4up|witanime)$"), page: int = Query(1, ge=1, le=1000), offset: int = Query(0, ge=0, le=30000, multiple_of=30), q: str | None = Query(None, min_length=2, max_length=100)):
    if q is not None and len(q.strip()) < 2:
        raise HTTPException(422, "Source query is too short")
    return await run(request, response, "episodes", slug, source, page, offset, q.strip() if q else None, provider)


@router.get("/episode-servers")
async def episode_servers(request: Request, response: Response, provider: str = Query(pattern=r"^(anime4up|witanime)$"), url: str = Query(min_length=12, max_length=2048)):
    return await run(request, response, "episode_servers", provider, url)


@router.get("/watch-servers")
async def watch_servers(
    request: Request,
    response: Response,
    slug: str = Query(min_length=1, max_length=220, pattern=r"^[a-z0-9-]+$"),
    episode: float = Query(ge=0, le=100000),
    provider: str | None = Query(None, pattern=r"^(anime4up|witanime)$"),
    url: str | None = Query(None, min_length=12, max_length=2048),
    source: str | None = Query(None, min_length=1, max_length=220, pattern=r"^[\w-]+$"),
    requested_source: str | None = Query(None, min_length=1, max_length=220, pattern=r"^[\w-]+$"),
    fallback: bool = Query(True),
):
    return await run(
        request,
        response,
        "watch_servers",
        slug,
        episode,
        provider,
        url,
        source,
        requested_source,
        fallback,
    )
