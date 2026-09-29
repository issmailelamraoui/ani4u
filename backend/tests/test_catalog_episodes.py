import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI, HTTPException

from anime4up_scraper import Anime4up, BASE_URL
from catalog_episodes import EpisodeCatalog, router
from catalog_store import CatalogStore


SOURCE = "one-piece-gfjgfh"
SLUG = "one-piece-21"


def source_html(numbers, pages=1, mal=21):
    identity = f'<div class="anime-external-links"><a href="https://myanimelist.net/anime/{mal}/One_Piece">MAL</a><a href="{BASE_URL}/episode/one-piece-9999/">الحلقة 9999</a></div>' if mal else ""
    episodes = ''.join(f'<a href="{BASE_URL}/episode/one-piece-{number}/">الحلقة {number}</a>' for number in numbers)
    return f'{identity}<div id="episodesList">{episodes}</div><a href="{BASE_URL}/anime/{SOURCE}/page/{pages}/">Last</a>'


class EpisodeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CatalogStore(Path(self.tmp.name) / "catalog.sqlite3")
        self.store.initialize()
        identity = self.store.identities([{"id": 21, "idMal": 21, "title": {"english": "One Piece"}}])[21]
        self.anime = {**identity, "title": "One Piece", "alternativeTitles": ["ONE PIECE"], "providerIds": {"anilist": 21, "mal": 21}}
        self.catalog = AsyncMock()
        self.catalog.store = self.store

        async def detail(slug):
            return {"data": {**self.anime, "sourceMappings": self.store.mappings([identity["id"]]).get(identity["id"], [])}}
        self.catalog.detail_by_slug.side_effect = detail
        self.scraper = Anime4up()
        self.scraper.search = AsyncMock(return_value=[{"title": "ONE PIECE", "url": f"{BASE_URL}/anime/{SOURCE}/", "kind": "anime"}])
        self.scraper.get_html = AsyncMock(return_value=source_html(range(60, 0, -1)))
        self.scraper.servers = AsyncMock(side_effect=AssertionError("Server resolution is forbidden"))
        self.scraper.player = AsyncMock(side_effect=AssertionError("Player resolution is forbidden"))
        self.scraper.episodes = AsyncMock(side_effect=AssertionError("Full-catalog episode crawl is forbidden"))
        self.service = EpisodeCatalog(self.catalog, self.scraper)
        app = FastAPI()
        app.state.catalog_episodes = self.service
        app.include_router(router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        self.scraper.servers.assert_not_awaited()
        self.scraper.player.assert_not_awaited()
        self.scraper.episodes.assert_not_awaited()
        await self.client.aclose()
        await self.service.close()
        self.tmp.cleanup()

    async def test_explicit_mal_link_verifies_and_persists_mapping(self):
        choices = await self.service.sources(SLUG)
        self.assertEqual(choices["selectedSource"], SOURCE)
        self.assertTrue(choices["sources"][0]["verified"])
        restarted = EpisodeCatalog(self.catalog, self.scraper)
        await restarted.sources(SLUG)
        self.assertEqual(self.scraper.search.await_count, 1)
        self.assertEqual(self.scraper.get_html.await_count, 1)
        self.assertEqual(self.store.mappings([self.anime["id"]])[self.anime["id"]][0]["slug"], SOURCE)

    async def test_exact_title_without_identity_link_requires_selection(self):
        self.scraper.get_html.return_value = source_html(range(1, 5), mal=None)
        choices = await self.service.sources(SLUG)
        self.assertIsNone(choices["selectedSource"])
        with self.assertRaises(HTTPException) as error:
            await self.service.episodes(SLUG, None)
        self.assertEqual(error.exception.status_code, 409)
        data = await self.service.episodes(SLUG, SOURCE)
        self.assertEqual(len(data["items"]), 4)
        self.assertFalse(data["verified"])
        self.assertEqual(self.store.mappings([self.anime["id"]]), {})

    async def test_neutral_source_qualifier_verifies_against_external_id(self):
        self.scraper.search.return_value = [{"title": "One Piece (TV)", "url": f"{BASE_URL}/anime/{SOURCE}/"}]
        choices = await self.service.sources(SLUG)
        self.assertEqual(choices["selectedSource"], SOURCE)
        self.assertTrue(choices["sources"][0]["verified"])

    async def test_season_alias_uses_broad_query_but_requires_matching_identity(self):
        self.anime = {**self.anime, "title": "Gintama Season 3", "alternativeTitles": ["Gintama°"]}
        season_source = "gintama-season-4"

        async def search(term):
            if term == "Gintama":
                return [{"title": "Gintama Season 4", "url": f"{BASE_URL}/anime/{season_source}/"}]
            return []

        self.scraper.search.side_effect = search
        choices = await self.service.sources(SLUG)
        self.assertEqual(choices["selectedSource"], season_source)
        self.assertTrue(choices["sources"][0]["verified"])
        self.assertIn("Gintama", [call.args[0] for call in self.scraper.search.await_args_list])

    async def test_subtitle_alias_uses_base_title_but_requires_matching_identity(self):
        self.anime = {**self.anime, "title": "Death Note: Relight", "alternativeTitles": ["DEATH NOTE Rewrite"]}
        source = "death-note-rewrite"

        async def search(term):
            if term == "Death Note":
                return [{"title": "Death Note: Rewrite", "url": f"{BASE_URL}/anime/{source}/"}]
            return []

        self.scraper.search.side_effect = search
        choices = await self.service.sources(SLUG)
        self.assertEqual(choices["selectedSource"], source)
        self.assertTrue(choices["sources"][0]["verified"])
        self.assertIn("Death Note", [call.args[0] for call in self.scraper.search.await_args_list])

    async def test_conflicting_external_id_never_auto_matches(self):
        self.scraper.get_html.return_value = source_html([1, 2], mal=22)
        self.assertIsNone((await self.service.sources(SLUG))["selectedSource"])
        self.assertFalse(self.store.mappings([self.anime["id"]]))

    async def test_sidebar_ids_do_not_verify_a_title(self):
        self.scraper.get_html.return_value = source_html([1, 2], mal=None) + '<aside><a href="https://myanimelist.net/anime/21/">Related anime</a></aside>'
        self.assertIsNone((await self.service.sources(SLUG))["selectedSource"])

    async def test_verified_match_does_not_offer_ineligible_sequel_choices(self):
        self.scraper.search.return_value.append({"title": "One Piece Movie", "url": f"{BASE_URL}/anime/one-piece-movie/"})
        choices = await self.service.sources(SLUG)
        self.assertEqual([item["slug"] for item in choices["sources"]], [SOURCE])

    async def test_movie_own_watch_link_is_supported_without_episode_grid(self):
        self.scraper.get_html.return_value = f'<div class="anime-external-links"><a href="https://myanimelist.net/anime/21/">MAL</a><a href="{BASE_URL}/episode/film-one-piece/">الفلم 1</a></div>'
        data = await self.service.episodes(SLUG, None)
        self.assertEqual([item["episode"] for item in data["items"]], [1])

    async def test_episode_grid_survives_source_wrapper_class_changes(self):
        self.store.set_mapping(21, SOURCE, "Verified manually")
        links = "".join(
            f'<article><a href="{BASE_URL}/episode/one-piece-الحلقة-{number}/">الحلقة {number}</a></article>'
            for number in range(28, 0, -1)
        )
        self.scraper.get_html.return_value = f"""
          <div class="anime-external-links">
            <a href="https://myanimelist.net/anime/21/">MAL</a>
            <a href="{BASE_URL}/episode/one-piece-الحلقة-1/">مشاهدة وتحميل الآن</a>
          </div>
          <section class="brand-new-source-layout">{links}</section>
          <aside><a href="{BASE_URL}/episode/unrelated-show-الحلقة-99/">الحلقة 99</a></aside>
        """
        data = await self.service.episodes(SLUG, None)
        self.assertEqual(len(data["items"]), 28)
        self.assertEqual([item["episode"] for item in data["items"]], list(range(1, 29)))

    async def test_manual_mapping_is_used_without_search_and_not_overwritten(self):
        self.store.set_mapping(21, SOURCE, "Verified manually")
        response = await self.service.episodes(SLUG, None)
        self.assertEqual(response["sourceSlug"], SOURCE)
        self.scraper.search.assert_not_awaited()
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT note FROM source_mapping').fetchone()[0], "Verified manually")

    async def test_episode_references_reuse_existing_source_links(self):
        self.store.set_mapping(21, SOURCE, "Verified manually")
        self.scraper.get_html.return_value = source_html([1, 12.5])
        data = await self.service.episodes(SLUG, None)
        for episode in data["items"]:
            self.assertEqual(episode["sources"], [{
                "provider": "anime4up", "sourceSlug": SOURCE,
                "episodeUrl": f'{BASE_URL}/episode/one-piece-{episode["episode"]}/',
            }])

    async def test_only_30_episodes_and_fractional_numbers_are_preserved(self):
        self.scraper.get_html.return_value = source_html([*range(1, 61), 12.5])
        first = await self.service.episodes(SLUG, None)
        self.assertEqual(len(first["items"]), 30)
        self.assertIn(12.5, [item["episode"] for item in first["items"]])
        second = await self.service.episodes(SLUG, None, **first["next"])
        self.assertEqual(len(second["items"]), 30)
        self.assertFalse(set(item["episode"] for item in first["items"]) & set(item["episode"] for item in second["items"]))
        last = await self.service.episodes(SLUG, None, **second["next"])
        self.assertEqual(len(last["items"]), 1)
        self.assertIsNone(last["next"])
        self.assertEqual(self.scraper.get_html.await_count, 1)

    async def test_long_series_fetches_only_index_and_requested_source_page(self):
        self.store.set_mapping(21, SOURCE, "Verified manually")
        async def html(url):
            if url.endswith('/page/26/'):
                return source_html(range(9, 0, -1), pages=26)
            if url.endswith('/page/25/'):
                return source_html(range(54, 9, -1), pages=26)
            return source_html(range(1179, 1134, -1), pages=26)
        self.scraper.get_html.side_effect = html
        first = await self.service.episodes(SLUG, None)
        self.assertEqual([item["episode"] for item in first["items"]], list(range(1, 10)))
        self.assertEqual(first["totalPages"], 26)
        self.assertEqual(self.scraper.get_html.await_count, 2)
        second = await self.service.episodes(SLUG, None, **first["next"])
        self.assertEqual([item["episode"] for item in second["items"]], list(range(10, 40)))
        self.assertEqual(self.scraper.get_html.await_count, 3)
        self.assertNotIn(9999, [item["episode"] for item in second["items"]])

    async def test_concurrent_episode_misses_share_source_requests(self):
        self.store.set_mapping(21, SOURCE, "Verified manually")
        results = await asyncio.gather(*(self.service.episodes(SLUG, None) for _ in range(8)))
        self.assertEqual(self.scraper.get_html.await_count, 1)
        self.assertTrue(all(len(result["items"]) == 30 for result in results))

    async def test_arbitrary_source_slug_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            await self.service.episodes(SLUG, "unrelated-source")
        self.assertEqual(error.exception.status_code, 409)

    async def test_route_validation_and_failure_retry(self):
        for suffix in ('offset=1', 'page=0', 'page=1001', 'source=../other'):
            response = await self.client.get(f'/api/catalog/episode-list?slug={SLUG}&{suffix}')
            self.assertEqual(response.status_code, 422)
        self.scraper.search.side_effect = RuntimeError("Source unavailable")
        response = await self.client.get(f'/api/catalog/sources?slug={SLUG}')
        self.assertEqual(response.status_code, 502)
        self.scraper.search.side_effect = None
        response = await self.client.get(f'/api/catalog/episode-list?slug={SLUG}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 30)

    async def test_empty_source_results_are_not_an_error(self):
        self.scraper.search.return_value = []
        response = await self.client.get(f'/api/catalog/sources?slug={SLUG}')
        self.assertEqual(response.json(), {
            "sources": [], "selectedSource": None,
            "availability": {
                "anime4up": {"status": "available", "last_status": 200},
            },
        })

    async def test_manual_query_can_find_alternative_source_title(self):
        self.scraper.search.return_value = [{"title": "Source spelling", "url": f"{BASE_URL}/anime/{SOURCE}/"}]
        choices = await self.service.sources(SLUG, "Alternate title")
        self.assertEqual(len(choices["sources"]), 1)
        self.assertIsNone(choices["selectedSource"])
        data = await self.service.episodes(SLUG, SOURCE, query="Alternate title")
        self.assertEqual(len(data["items"]), 30)


if __name__ == "__main__":
    unittest.main()
