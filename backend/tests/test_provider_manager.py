import unittest
from unittest.mock import AsyncMock

from provider_manager import ProviderManager
from providers.base import SourceUnavailable


class FakeProvider:
    def __init__(self, name, search=None, episodes=None, servers=None):
        self.name = name
        self.search_anime = AsyncMock(return_value=search or [])
        self.get_episodes = AsyncMock(return_value=episodes or [])
        self.get_episode_servers = AsyncMock(return_value=servers or [])
        self.get_anime = AsyncMock(return_value=None)

    async def start(self):
        pass

    async def close(self):
        pass

    def source_slug_from_url(self, url):
        return url.rstrip("/").split("/")[-1] if "/anime/" in url else None

    def anime_url(self, slug):
        return f"https://{self.name}.test/anime/{slug}/"

    def valid_episode_url(self, url):
        return url.startswith(f"https://{self.name}.test/episode/")


class Store:
    def __init__(self):
        self.mappings = []

    def set_mapping(self, *args):
        self.mappings.append(args)


class ProviderManagerTests(unittest.IsolatedAsyncioTestCase):
    def anime(self, mappings=None):
        return {"title": "One Piece", "providerIds": {"anilist": 21}, "sourceMappings": mappings or []}

    async def test_anime4up_success_does_not_request_witanime(self):
        anime4up = FakeProvider("anime4up")
        witanime = FakeProvider("witanime", search=[{"title": "One Piece", "url": "https://witanime.test/anime/one-piece/"}], episodes=[{"episode": 1, "url": "https://witanime.test/episode/1/"}])
        manager = ProviderManager(Store(), [anime4up, witanime])
        # The catalog calls this method only after Anime4Up has failed. This
        # assertion locks in the strict-primary boundary.
        self.assertEqual(await manager.episodes_for("anime4up", "one-piece"), [])
        witanime.search_anime.assert_not_awaited()
        witanime.get_episodes.assert_not_awaited()

    async def test_witanime_selected_only_after_fallback_without_persisting_mapping(self):
        store = Store()
        anime4up = FakeProvider("anime4up")
        witanime = FakeProvider(
            "witanime",
            search=[{"title": "One Piece", "url": "https://witanime.test/anime/one-piece/"}],
            episodes=[
                {"episode": 1, "url": "https://witanime.test/episode/1/"},
                {"episode": 1, "url": "https://witanime.test/episode/duplicate/"},
            ],
        )
        manager = ProviderManager(store, [anime4up, witanime])
        resolved = await manager.fallback_source(self.anime(), ["One Piece"], lambda title: title == "One Piece")
        self.assertEqual(resolved[0]["provider"], "witanime")
        self.assertEqual([row["episode"] for row in resolved[1]], [1])
        self.assertEqual(store.mappings, [])

    async def test_failure_cache_is_short_lived_and_not_a_mapping(self):
        store = Store()
        anime4up = FakeProvider("anime4up")
        witanime = FakeProvider("witanime", episodes=[])
        manager = ProviderManager(store, [anime4up, witanime])
        self.assertEqual(await manager.episodes_for("witanime", "missing"), [])
        self.assertEqual(await manager.episodes_for("witanime", "missing"), [])
        self.assertEqual(witanime.get_episodes.await_count, 1)
        self.assertEqual(store.mappings, [])

    async def test_403_is_recorded_and_never_retried(self):
        anime4up = FakeProvider("anime4up")
        witanime = FakeProvider("witanime")
        witanime.search_anime = AsyncMock(side_effect=SourceUnavailable("HTTP 403", status=403))
        manager = ProviderManager(Store(), [anime4up, witanime])
        self.assertIsNone(await manager.fallback_source(self.anime(), ["One Piece"], lambda title: True))
        self.assertEqual(witanime.search_anime.await_count, 1)
        self.assertEqual(manager.availability()["witanime"], {"status": "unavailable", "last_status": 403})

    async def test_server_deduplication_uses_normalized_public_url_not_name(self):
        anime4up = FakeProvider("anime4up", servers=[
            {"name": "same name", "embed_url": "https://player.test/e/one#x"},
            {"name": "different name", "embed_url": "https://player.test/e/one"},
            {"name": "same name", "embed_url": "https://player.test/e/two"},
        ])
        manager = ProviderManager(Store(), [anime4up])
        servers = await manager.get_episode_servers("anime4up", "https://anime4up.test/episode/1/")
        self.assertEqual([server["embed_url"] for server in servers], [
            "https://player.test/e/one#x", "https://player.test/e/two",
        ])


if __name__ == "__main__":
    unittest.main()
