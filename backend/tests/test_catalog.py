import asyncio
import copy
import json
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

import api
from anilist_provider import AniListProvider, AnimeNotFound, ProviderError, normalize
from catalog_service import CatalogService
from catalog_store import CatalogStore


MEDIA = {
    "id": 21, "idMal": 21,
    "title": {"romaji": "ONE PIECE", "english": "One Piece", "native": "ワンピース"},
    "synonyms": ["One Piece", "OP"],
    "description": "<b>A story</b><script>bad()</script><br>of pirates &amp; friends.",
    "coverImage": {"large": "https://example.test/poster.jpg", "color": "#aabbcc"},
    "bannerImage": "https://example.test/banner.jpg", "averageScore": 88,
    "genres": ["Adventure"], "seasonYear": 1999, "season": "FALL",
    "status": "RELEASING", "format": "TV", "episodes": None, "duration": 24,
    "countryOfOrigin": "JP", "studios": {"nodes": [{"name": "Toei Animation"}]},
    "trailer": {"site": "youtube", "id": "abcdefghijk"}, "popularity": 1000,
}


def page_payload(variables=None):
    variables = variables or {}
    return {"media": [copy.deepcopy(MEDIA)], "pageInfo": {"currentPage": variables.get("page", 1), "perPage": variables.get("perPage", 24), "hasNextPage": True}}


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = CatalogStore(Path(self.directory.name) / "catalog.sqlite3")
        self.store.initialize()
        self.calls = []
        self.failure = None

        async def upstream(request):
            payload = json.loads(request.content)
            self.calls.append(payload)
            if self.failure:
                status, body = self.failure
                return httpx.Response(status, json=body)
            # Allow overlapping callers to exercise request coalescing.
            await asyncio.sleep(0.01)
            query = payload["query"]
            if "featured:" in query:
                data = {"featured": page_payload(), "topRated": page_payload(), "discover": page_payload()}
            elif "Media(id:" in query:
                data = {"Media": copy.deepcopy(MEDIA)}
            else:
                data = {"Page": page_payload(payload["variables"])}
            return httpx.Response(200, json={"data": data})

        self.client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        self.provider = AniListProvider(self.client, min_interval=0)
        self.catalog = CatalogService(self.store, self.provider)
        self.previous_catalog = getattr(api.app.state, "catalog", None)
        api.app.state.catalog = self.catalog
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.catalog.close()
        await self.http.aclose()
        await self.client.aclose()
        if self.previous_catalog is not None:
            api.app.state.catalog = self.previous_catalog
        else:
            del api.app.state.catalog
        self.directory.cleanup()

    def expire(self, stale=False):
        with self.store.connect() as db:
            db.execute("UPDATE catalog_cache SET expires_at=?", (int(time.time()) - 1,))
            if stale:
                db.execute("UPDATE catalog_cache SET stale_until=?", (int(time.time()) - 1,))

    async def test_normalized_contract_preserves_unknowns_and_score_provenance(self):
        response = await self.http.get("/api/catalog/anime/21")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["id"].startswith("nova_"))
        self.assertEqual(data["slug"], "one-piece-21")
        self.assertEqual(data["providerIds"], {"anilist": 21, "mal": 21})
        self.assertEqual(data["score"], {"value": 88, "scale": 100, "provider": "anilist"})
        self.assertIsNone(data["episodeCount"])
        self.assertEqual(data["availability"], "unknown")
        self.assertEqual(data["sourceMappings"], [])
        self.assertEqual(data["description"], "A story of pirates & friends.")
        self.assertEqual(data["status"], "releasing")
        self.assertEqual(data["type"], "tv")
        self.assertNotIn("coverImage", data)

    def test_optional_metadata_and_untrusted_links(self):
        minimal = {"id": 7, "title": {}, "averageScore": None, "coverImage": {"large": "javascript:alert(1)", "color": "red; background: url(x)"}, "trailer": {"site": "unknown", "id": "x"}}
        result = normalize(minimal, {"id": "nova_test", "slug": "anime-7"}, 123)
        self.assertIsNone(result.image)
        self.assertIsNone(result.accentColor)
        self.assertIsNone(result.trailer)
        self.assertIsNone(result.score)
        self.assertIsNone(result.descriptionLanguage)
        self.assertIsNone(result.episodeCount)

    async def test_all_catalog_routes_never_call_source_or_resolver(self):
        with ExitStack() as stack:
            methods = [stack.enter_context(patch.object(api.scraper, name, new=AsyncMock(side_effect=AssertionError("Source must not be called")))) for name in ("home", "search", "anime", "episodes", "servers", "player", "get_html")]
            for url in ("/api/catalog/home", "/api/catalog/search?q=One+Piece", "/api/catalog/discover?page=2", "/api/catalog/anime/21", "/api/catalog/anime?slug=one-piece-21"):
                with self.subTest(url=url):
                    response = await self.http.get(url)
                    self.assertEqual(response.status_code, 200, response.text)
            for method in methods:
                method.assert_not_awaited()
        self.assertEqual(len(self.calls), 4)  # Slug and ID share the same detail cache.

    async def test_home_is_one_bounded_graphql_request(self):
        response = (await self.http.get("/api/catalog/home")).json()
        self.assertEqual(len(self.calls), 1)
        self.assertIn("perPage: 5", self.calls[0]["query"])
        self.assertIn("perPage: 10", self.calls[0]["query"])
        self.assertIn("perPage: 24", self.calls[0]["query"])
        self.assertEqual(response["data"]["discover"]["perPage"], 24)
        self.assertNotIn("latestEpisodes", response["data"])
        self.assertEqual(response["cache"]["expiresAt"] - response["cache"]["updatedAt"], 900)

    async def test_cache_survives_service_and_store_restart(self):
        original = await self.catalog.detail(21)
        restarted = CatalogService(CatalogStore(self.store.path), self.provider)
        result = await restarted.detail(21)
        self.assertEqual(result["cache"]["status"], "fresh")
        self.assertEqual(result["data"], original["data"])
        self.assertEqual(len(self.calls), 1)

    async def test_concurrent_misses_share_one_request(self):
        results = await asyncio.gather(*(self.catalog.detail(21) for _ in range(12)))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len({r["data"]["id"] for r in results}), 1)
        self.assertFalse(self.catalog.inflight)

    async def test_disconnecting_caller_does_not_cancel_shared_request(self):
        task = asyncio.create_task(self.catalog.detail(21))
        for _ in range(100):
            if self.catalog.inflight:
                break
            await asyncio.sleep(0.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        response = await self.catalog.detail(21)
        self.assertEqual(response["data"]["providerIds"]["anilist"], 21)
        self.assertEqual(len(self.calls), 1)

    async def test_stale_on_failure_keeps_last_good_data(self):
        original = await self.catalog.detail(21)
        self.expire()
        self.failure = (503, {"error": "Unavailable"})
        result = await self.catalog.detail(21)
        self.assertEqual(result["cache"]["status"], "stale")
        self.assertEqual(result["data"], original["data"])
        self.assertEqual(result["cache"]["updatedAt"], original["cache"]["updatedAt"])

    async def test_beyond_stale_window_returns_503(self):
        await self.catalog.detail(21)
        self.expire(stale=True)
        self.failure = (503, {})
        response = await self.http.get("/api/catalog/anime/21")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["retry-after"], "60")

    async def test_graphql_partial_errors_are_not_cached(self):
        self.failure = (200, {"data": {"Media": MEDIA}, "errors": [{"message": "partial failure"}]})
        response = await self.http.get("/api/catalog/anime/21")
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(self.store.get_cache("v1:anime:21"))

    async def test_malformed_provider_data_returns_503_without_cache(self):
        self.failure = (200, {"data": {"Media": {"id": 99}}})
        response = await self.http.get("/api/catalog/anime/21")
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(self.store.get_cache("v1:anime:21"))

    async def test_not_found_removes_old_cache_instead_of_serving_stale(self):
        await self.catalog.detail(21)
        self.expire()
        self.failure = (200, {"data": {"Media": None}})
        response = await self.http.get("/api/catalog/anime/21")
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(self.store.get_cache("v1:anime:21"))

    async def test_identity_and_mappings_survive_metadata_updates_and_cache_eviction(self):
        original = (await self.catalog.detail(21))["data"]
        self.store.set_mapping(21, "one-piece-gfjgfh", "Manually checked the title and season")
        self.store.set_mapping(21, "one-piece-alternative", "Separate verified source listing")
        updated = (await self.catalog.detail(21))["data"]
        self.assertEqual({m["slug"] for m in updated["sourceMappings"]}, {"one-piece-gfjgfh", "one-piece-alternative"})
        self.assertEqual(updated["availability"], "unknown")
        self.assertIsNone(updated["availableEpisodeCount"])
        self.assertEqual(len(self.calls), 1)
        changed = copy.deepcopy(MEDIA)
        changed["title"]["english"] = "Corrected title"
        self.store.identities([changed])
        self.store.delete_cache("v1:anime:21")
        restarted = CatalogStore(self.store.path)
        identity = restarted.identities([changed])[21]
        self.assertEqual(identity, {"id": original["id"], "slug": original["slug"]})
        self.assertEqual(len(restarted.mappings([original["id"]])[original["id"]]), 2)
        self.store.remove_mapping(21, "one-piece-alternative")
        self.assertEqual(len((await self.catalog.detail(21))["data"]["sourceMappings"]), 1)

    async def test_mapping_rejects_unverified_unknown_and_path_values(self):
        with self.assertRaises(ValueError):
            self.store.set_mapping(999, "title", "verified")
        await self.catalog.detail(21)
        for slug, note in (("../x", "verified"), ("https://example.test/anime/x", "verified"), ("title", "")):
            with self.subTest(slug=slug), self.assertRaises(ValueError):
                self.store.set_mapping(21, slug, note)

    async def test_search_pagination_and_cache_keys(self):
        first = await self.http.get("/api/catalog/search", params={"q": " One   Piece ", "page": 2, "per_page": 20})
        self.assertEqual(first.json()["data"]["page"], 2)
        self.assertTrue(first.json()["data"]["hasNextPage"])
        await self.http.get("/api/catalog/search", params={"q": "One Piece", "page": 2, "per_page": 20})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["variables"]["search"], "One Piece")
        await self.http.get("/api/catalog/search", params={"q": "One Piece", "page": 3, "per_page": 20})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(first.headers["cache-control"], "no-store")

    async def test_invalid_requests_do_not_reach_provider(self):
        for url in ("/api/catalog/search?q=%20%20", "/api/catalog/search?q=x", "/api/catalog/discover?per_page=1000", "/api/catalog/discover?page=0", "/api/catalog/discover?page=101", "/api/catalog/anime/0", "/api/catalog/anime?slug=../x"):
            with self.subTest(url=url):
                self.assertEqual((await self.http.get(url)).status_code, 422)
        self.assertEqual((await self.http.get("/api/catalog/anime?slug=unknown")).status_code, 404)
        self.assertFalse(self.calls)

    def test_cache_bound_does_not_delete_identity_or_mappings(self):
        self.store.max_entries = 2
        identity = self.store.identities([MEDIA])[21]
        self.store.set_mapping(21, "source-slug", "verified")
        for index in range(5):
            self.store.put_cache(str(index), {"item": index}, 60)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM catalog_cache").fetchone()[0], 2)
        self.assertEqual(len(self.store.mappings([identity["id"]])[identity["id"]]), 1)

    async def test_completed_details_have_longer_ttl(self):
        completed = copy.deepcopy(MEDIA)
        completed["status"] = "FINISHED"
        with patch.object(self.provider, "detail", new=AsyncMock(return_value=completed)):
            result = await self.catalog.detail(21)
        self.assertEqual(result["cache"]["expiresAt"] - result["cache"]["updatedAt"], 86400)

    def test_legacy_routes_remain_registered(self):
        paths = set(api.app.openapi()["paths"])
        self.assertTrue({"/api/home", "/api/search", "/api/anime", "/api/episodes", "/api/servers", "/api/player"}.issubset(paths))


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_exhausted_rate_header_defers_next_request(self):
        requests = []

        def upstream(request):
            requests.append(request)
            return httpx.Response(200, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()) + 60)}, json={"data": {"Media": MEDIA}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            provider = AniListProvider(client, min_interval=0)
            await provider.detail(21)
            with self.assertRaises(ProviderError):
                await provider.detail(21)
        self.assertEqual(len(requests), 1)

    async def test_429_cooldown_avoids_repeated_requests(self):
        requests = []

        def upstream(request):
            requests.append(request)
            return httpx.Response(429, headers={"Retry-After": "60"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            provider = AniListProvider(client, min_interval=0)
            for _ in range(2):
                with self.assertRaises(ProviderError):
                    await provider.home()
        self.assertEqual(len(requests), 1)

    async def test_graphql_404_is_distinguished_from_outage(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"errors": [{"status": 404}]}))) as client:
            with self.assertRaises(AnimeNotFound):
                await AniListProvider(client, min_interval=0).detail(999)

    async def test_application_lifecycle_opens_and_closes_catalog_without_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"NOVA_CATALOG_DB": str(Path(directory) / "startup.sqlite3")}), patch.object(api.scraper, "start", new=AsyncMock()), patch.object(api.scraper, "close", new=AsyncMock()):
            async with api.lifespan(api.app):
                self.assertTrue(api.app.state.catalog.store.path.exists())
                client = api.app.state.catalog.provider.client
                self.assertFalse(client.is_closed)
                health = await api.health()
                self.assertEqual(set(health["providers"]), {"anime4up", "witanime"})
                self.assertTrue(all(set(state) == {"status", "last_status"} for state in health["providers"].values()))
            self.assertTrue(client.is_closed)
            self.assertFalse(hasattr(api.app.state, "catalog"))


if __name__ == "__main__":
    unittest.main()
