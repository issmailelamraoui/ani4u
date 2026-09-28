import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from anime4up_scraper import Anime4up, BASE_URL
from catalog_episodes import EpisodeCatalog
from catalog_store import CatalogStore
from provider_manager import ProviderManager
from providers.anime4up import Anime4upProvider
from providers.base import SourceUnavailable


SLUG = "one-piece-21"
SOURCE = "one-piece"


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
        self.assertEqual(ref, {"provider": "witanime", "sourceSlug": "one-piece", "episodeUrl": "https://witanime.site/watch/one-piece/7/"})
        servers = await self.service.episode_servers(ref["provider"], ref["episodeUrl"])
        self.assertEqual(servers["servers"][0]["embed_url"], "https://player.example/e/7")
        self.assertEqual(self.store.mappings([self.anime["id"]])[self.anime["id"]][-1]["source"], "witanime")

    async def test_anime4up_timeout_or_502_falls_back_without_a_concurrent_witanime_request(self):
        self.scraper.get_html = AsyncMock(side_effect=RuntimeError("HTTP 502"))
        wit = FakeWitAnime([{"episode": 3, "url": "https://witanime.site/watch/one-piece/3/"}])
        await self.make_service(wit)
        response = await self.service.episodes(SLUG, None)
        self.assertEqual(response["sourceProvider"], "witanime")
        self.assertEqual(self.scraper.get_html.await_count, 2)
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

    async def test_both_provider_failures_return_an_error_state(self):
        self.scraper.get_html = AsyncMock(side_effect=RuntimeError("HTTP 502"))
        wit = FakeWitAnime([])
        wit.search_anime = AsyncMock(side_effect=SourceUnavailable("HTTP 503"))
        await self.make_service(wit)
        with self.assertRaises(RuntimeError):
            await self.service.episodes(SLUG, None)


if __name__ == "__main__":
    unittest.main()
