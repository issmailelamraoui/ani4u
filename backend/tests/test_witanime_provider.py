import unittest

import httpx

from providers.base import ProviderUnavailable, SourceUnavailable
from providers.witanime import WitAnimeProvider


class WitAnimeHttpProviderTests(unittest.IsolatedAsyncioTestCase):
    def client(self, handler):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://witanime.site")

    async def test_search_and_episodes_use_public_html_without_a_browser(self):
        async def handler(request):
            if request.url.path == "/search":
                return httpx.Response(200, text='''<a href="/anime/one-piece/"><img alt="One Piece" src="/poster.webp"></a>''')
            if request.url.path == "/anime/one-piece/":
                return httpx.Response(200, text='''
                    <a href="/watch/one-piece/1/">الحلقة 1</a>
                    <a href="/watch/one-piece/1/">الحلقة 1 (مكرر)</a>
                    <a href="/watch/one-piece/2/">Episode 2</a>
                ''')
            return httpx.Response(404)

        client = self.client(handler)
        provider = WitAnimeProvider(client)
        self.assertEqual((await provider.search_anime("One Piece"))[0]["url"], "https://witanime.site/anime/one-piece/")
        episodes = await provider.get_episodes("one-piece")
        self.assertEqual([item["episode"] for item in episodes], [1, 2])
        self.assertTrue(all(item["url"].startswith("https://witanime.site/watch/") for item in episodes))
        await client.aclose()

    async def test_cloudflare_response_is_unavailable_not_bypassed(self):
        client = self.client(lambda request: httpx.Response(403, headers={"server": "cloudflare", "cf-ray": "test"}))
        provider = WitAnimeProvider(client)
        with self.assertRaises(SourceUnavailable) as error:
            await provider.search_anime("One Piece")
        self.assertIsInstance(error.exception, ProviderUnavailable)
        self.assertEqual(error.exception.status, 403)
        self.assertFalse(error.exception.retryable)
        await client.aclose()

    async def test_servers_only_return_unique_public_playback_urls(self):
        async def handler(request):
            return httpx.Response(200, text='''
                <iframe title="Vidmoly" src="https://player.example/e/one#fragment"></iframe>
                <iframe title="Duplicate name is irrelevant" src="https://player.example/e/one"></iframe>
                <a data-server="two" href="https://other.example/embed/two">مشغل السيرفر الثاني</a>
            ''')

        client = self.client(handler)
        provider = WitAnimeProvider(client)
        servers = await provider.get_episode_servers("https://witanime.site/watch/one-piece/1/")
        self.assertEqual([server["embed_url"] for server in servers], [
            "https://player.example/e/one#fragment",
            "https://other.example/embed/two",
        ])
        await client.aclose()


if __name__ == "__main__":
    unittest.main()
