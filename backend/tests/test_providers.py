import unittest
from unittest.mock import AsyncMock

from anime4up_scraper import Anime4up, BASE_URL
from providers.anime4up import Anime4upProvider


class Anime4upProviderAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.scraper = Anime4up()
        self.provider = Anime4upProvider(self.scraper)

    async def test_adapter_delegates_without_replacing_the_existing_scraper(self):
        self.scraper.search = AsyncMock(return_value=[{"title": "One Piece"}])
        self.scraper.anime = AsyncMock(return_value={"title": "One Piece"})
        self.scraper.episodes = AsyncMock(return_value=[{"episode": 1}])
        self.scraper.servers = AsyncMock(return_value=[{"name": "Videa"}])

        self.assertEqual(await self.provider.search_anime("One Piece"), [{"title": "One Piece"}])
        self.assertEqual(await self.provider.get_anime("one-piece"), {"title": "One Piece"})
        self.assertEqual(await self.provider.get_episodes("one-piece"), [{"episode": 1}])
        self.assertEqual(await self.provider.get_episode_servers(f"{BASE_URL}/episode/one-piece-1/"), [{"name": "Videa"}])
        self.scraper.episodes.assert_awaited_once_with(f"{BASE_URL}/anime/one-piece/")

    async def test_adapter_keeps_source_url_validation_at_the_boundary(self):
        self.assertEqual(self.provider.source_slug_from_url(f"{BASE_URL}/anime/one-piece/"), "one-piece")
        self.assertIsNone(self.provider.source_slug_from_url("https://untrusted.example/anime/one-piece/"))
        self.assertTrue(self.provider.valid_episode_url(f"{BASE_URL}/episode/one-piece-1/"))
        self.assertFalse(self.provider.valid_episode_url("https://untrusted.example/episode/one-piece-1/"))
        with self.assertRaises(ValueError):
            await self.provider.get_episode_servers("https://untrusted.example/episode/one-piece-1/")


if __name__ == "__main__":
    unittest.main()
