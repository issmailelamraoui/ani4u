import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from anime4up_scraper import Anime4up, BASE_URL
from catalog_episodes import EpisodeCatalog, router
from catalog_store import CatalogStore
from provider_manager import ProviderManager
from providers.anime4up import Anime4upProvider
from providers.base import ProviderUnavailable, SourceUnavailable


SLUG = "one-piece-21"
SOURCE = "one-piece"
MUSHOKU_SLUG = "mushoku-tensei-jobless-reincarnation-season-3-178789"
MUSHOKU_SOURCE = "mushoku-tensei-iii-isekai-ittara-honki-dasu"


def anime4up_page(numbers):
    links = "".join(f'<a href="{BASE_URL}/episode/one-piece-{number}/">الحلقة {number}</a>' for number in numbers)
    return f'<div id="episodesList">{links}</div>'


class FakeWitAnime:
    name = "witanime"

    def __init__(self, episodes, search=None, servers=None):
        self.search_anime = AsyncMock(return_value=search or [{"title": "One Piece", "url": "https://witanime.site/anime/one-piece/"}])
        self.get_episodes = AsyncMock(return_value=episodes)
        self.get_episode_servers = AsyncMock(return_value=servers or [])
        self.get_anime = AsyncMock(return_value=None)

    async def start(self):
        pass

    async def close(self):
        pass

    def source_slug_from_url(self, url):
        return "one-piece" if url == "https://witanime.site/anime/one-piece/" else None

    def anime_url(self, slug):
        return f"https://witanime.site/anime/{slug}/"

    def valid_episode_url(self, url):
        return url.startswith("https://witanime.site/watch/")


class CatalogProviderFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CatalogStore(Path(self.tmp.name) / "catalog.sqlite3")
        self.store.initialize()
        identity = self.store.identities([{"id": 21, "idMal": 21, "title": {"english": "One Piece"}}])[21]
        self.anime = {
            **identity, "title": "One Piece", "alternativeTitles": ["ONE PIECE"],
            "providerIds": {"anilist": 21, "mal": 21}, "sourceMappings": [],
        }
        self.catalog = AsyncMock()
        self.catalog.store = self.store

        async def detail(_slug):
            mappings = self.store.mappings([identity["id"]]).get(identity["id"], [])
            return {"data": {**self.anime, "sourceMappings": mappings}}
        self.catalog.detail_by_slug.side_effect = detail
        self.scraper = Anime4up()
        self.scraper.search = AsyncMock(return_value=[])
        self.scraper.get_html = AsyncMock(return_value=anime4up_page([1]))
        self.store.set_mapping(21, SOURCE, "Existing Anime4Up mapping")

    async def asyncTearDown(self):
        await self.service.close()
        self.tmp.cleanup()

    async def make_service(self, wit):
        self.wit = wit
        self.manager = ProviderManager(self.store, [Anime4upProvider(self.scraper), wit])
        self.service = EpisodeCatalog(self.catalog, self.scraper, self.manager)

    async def test_anime4up_episodes_stop_before_witanime_is_requested(self):
        await self.make_service(FakeWitAnime([{"episode": 1, "url": "https://witanime.site/watch/one-piece/1/"}]))
        response = await self.service.episodes(SLUG, None)
        self.assertEqual(response["sourceProvider"], "anime4up")
        self.assertEqual([item["episode"] for item in response["items"]], [1])
        self.wit.search_anime.assert_not_awaited()
        self.wit.get_episodes.assert_not_awaited()

    async def test_empty_anime4up_falls_back_to_witanime_and_uses_its_servers(self):
        self.scraper.get_html.return_value = anime4up_page([])
        wit = FakeWitAnime(
            [{"episode": 7, "title": "الحلقة 7", "url": "https://witanime.site/watch/one-piece/7/"}],
            servers=[{"name": "Wit player", "id": "1", "attributes": {}, "embed_url": "https://player.example/e/7"}],
        )
        await self.make_service(wit)
        response = await self.service.episodes(SLUG, None)
        self.assertEqual(response["sourceProvider"], "witanime")
        ref = response["items"][0]["sources"][0]
        self.assertEqual(response["requestedSource"], {
            "provider": "anime4up", "sourceSlug": SOURCE,
        })
        self.assertEqual(ref, {"provider": "witanime", "sourceSlug": "one-piece", "episodeUrl": "https://witanime.site/watch/one-piece/7/"})
        servers = await self.service.episode_servers(ref["provider"], ref["episodeUrl"])
        self.assertEqual(servers["servers"][0]["embed_url"], "https://player.example/e/7")
        mappings = self.store.mappings([self.anime["id"]])[self.anime["id"]]
        self.assertEqual([(item["source"], item["slug"]) for item in mappings], [
            ("anime4up", SOURCE),
        ])
        # A transient fallback must not change the next default source.
        choices = await self.service.sources(SLUG)
        self.assertEqual(choices["selectedProvider"], "anime4up")

    async def test_mushoku_same_slug_mappings_always_resolve_verified_anime4up(self):
        self.store.remove_mapping(21, SOURCE)
        self.store.set_mapping(21, MUSHOKU_SOURCE, "Verified Mushoku Anime4Up mapping")
        # Reproduce the stale row created by the old automatic fallback logic.
        self.store.set_mapping(21, MUSHOKU_SOURCE, "Old WitAnime fallback row", "witanime")
        self.anime = {
            **self.anime,
            "title": "Mushoku Tensei: Jobless Reincarnation Season 3",
            "alternativeTitles": ["Mushoku Tensei III: Isekai Ittara Honki Dasu"],
        }
        self.scraper.get_html.return_value = (
            f'<div id="episodesList"><a href="{BASE_URL}/episode/{MUSHOKU_SOURCE}-1/">'
            "الحلقة 1</a></div>"
        )
        self.scraper.search = AsyncMock(side_effect=RuntimeError("HTTP 403"))
        await self.make_service(FakeWitAnime([
            {"episode": 1, "url": f"https://witanime.site/watch/{MUSHOKU_SOURCE}/1/"},
        ]))

        app = FastAPI()
        app.state.catalog_episodes = self.service
        app.include_router(router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            without_response = await client.get(
                "/api/catalog/sources", params={"slug": MUSHOKU_SLUG}
            )
            with_response = await client.get(
                "/api/catalog/sources",
                params={"slug": MUSHOKU_SLUG, "q": "Mushoku Tensei"},
            )
            episode_response = await client.get(
                "/api/catalog/episode-list",
                params={
                    "slug": MUSHOKU_SLUG,
                    "source": MUSHOKU_SOURCE,
                    "provider": "anime4up",
                    "page": 1,
                    "offset": 0,
                },
            )

        self.assertEqual(without_response.status_code, 200)
        self.assertEqual(with_response.status_code, 200)
        without_query = without_response.json()
        with_query = with_response.json()
        for choices in (without_query, with_query):
            self.assertEqual(choices["selectedSource"], MUSHOKU_SOURCE)
            self.assertEqual(choices["selectedProvider"], "anime4up")
            self.assertEqual(
                [(item["provider"], item["slug"]) for item in choices["sources"]],
                [("anime4up", MUSHOKU_SOURCE)],
            )

        self.assertEqual(episode_response.status_code, 200)
        response = episode_response.json()
        self.assertEqual(response["sourceProvider"], "anime4up")
        self.assertEqual([item["episode"] for item in response["items"]], [1])
        self.assertEqual(self.scraper.search.await_count, 1)
        self.wit.search_anime.assert_not_awaited()
        self.wit.get_episodes.assert_not_awaited()

    async def test_anime4up_timeout_or_502_falls_back_without_a_concurrent_witanime_request(self):
        self.scraper.get_html = AsyncMock(side_effect=RuntimeError("HTTP 502"))
        wit = FakeWitAnime([{"episode": 3, "url": "https://witanime.site/watch/one-piece/3/"}])
        await self.make_service(wit)
        response = await self.service.episodes(SLUG, None)
        self.assertEqual(response["sourceProvider"], "witanime")
        self.assertEqual(self.scraper.get_html.await_count, 2)
        self.assertEqual(wit.search_anime.await_count, 1)

    async def test_anime4up_403_does_not_retry_and_uses_witanime_once(self):
        self.scraper.get_html = AsyncMock(side_effect=RuntimeError("Anime4up returned HTTP 403"))
        wit = FakeWitAnime([{"episode": 6, "url": "https://witanime.site/watch/one-piece/6/"}])
        await self.make_service(wit)
        response = await self.service.episodes(SLUG, None)
        self.assertEqual(response["sourceProvider"], "witanime")
        self.assertEqual(self.scraper.get_html.await_count, 1)
        self.assertEqual(wit.search_anime.await_count, 1)

    async def test_anime4up_timeout_falls_back_to_witanime(self):
        self.scraper.get_html = AsyncMock(side_effect=asyncio.TimeoutError())
        wit = FakeWitAnime([{"episode": 4, "url": "https://witanime.site/watch/one-piece/4/"}])
        await self.make_service(wit)
        response = await self.service.episodes(SLUG, None)
        self.assertEqual(response["sourceProvider"], "witanime")
        self.assertEqual(self.scraper.get_html.await_count, 2)

    async def test_no_anime4up_match_uses_witanime_during_episode_discovery(self):
        self.store.remove_mapping(21, SOURCE)
        self.scraper.search = AsyncMock(return_value=[])
        wit = FakeWitAnime([{"episode": 5, "url": "https://witanime.site/watch/one-piece/5/"}])
        await self.make_service(wit)
        choices = await self.service.sources(SLUG)
        self.assertEqual(choices["sources"][0]["provider"], "witanime")
        self.assertEqual(wit.search_anime.await_count, 1)

    async def test_both_empty_returns_the_normal_empty_episode_state(self):
        self.scraper.get_html.return_value = anime4up_page([])
        await self.make_service(FakeWitAnime([]))
        response = await self.service.episodes(SLUG, None)
        self.assertEqual(response["sourceProvider"], "anime4up")
        self.assertEqual(response["items"], [])

    async def test_both_403_providers_return_a_safe_unavailable_response(self):
        self.scraper.get_html = AsyncMock(side_effect=RuntimeError("HTTP 403"))
        wit = FakeWitAnime([])
        wit.search_anime = AsyncMock(side_effect=ProviderUnavailable("HTTP 403", status=403))
        await self.make_service(wit)
        response = await self.service.episodes(SLUG, None)
        self.assertEqual(response["items"], [])
        self.assertTrue(response["externalUnavailable"])
        self.assertEqual(response["availability"]["anime4up"], {"status": "unavailable", "last_status": 403})
        self.assertEqual(response["availability"]["witanime"], {"status": "unavailable", "last_status": 403})
        self.assertEqual(self.scraper.get_html.await_count, 1)
        self.assertEqual(wit.search_anime.await_count, 1)

    async def test_mapped_witanime_403_can_fall_through_to_safe_unavailable_state(self):
        self.store.remove_mapping(21, SOURCE)
        self.store.set_mapping(21, "one-piece", "Existing WitAnime mapping", "witanime")
        self.scraper.search = AsyncMock(side_effect=RuntimeError("HTTP 403"))
        wit = FakeWitAnime([])
        wit.get_episodes = AsyncMock(side_effect=ProviderUnavailable("HTTP 403", status=403))
        await self.make_service(wit)
        response = await self.service.episodes(SLUG, None)
        self.assertTrue(response["externalUnavailable"])
        self.assertEqual(response["sourceProvider"], "witanime")
        self.assertEqual(self.scraper.search.await_count, 1)
        self.scraper.get_html.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
