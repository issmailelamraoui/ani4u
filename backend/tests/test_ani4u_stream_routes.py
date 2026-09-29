import unittest

import httpx

import ani4u_stream_routes
import api


class StreamCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.http.aclose()

    async def test_catalog_keeps_all_validated_series_and_standalone_content(self):
        response = await self.http.get("/api/stream-catalog/anime")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["series_count"], data["movie_count"], data["special_count"]), (23, 31, 2))
        self.assertEqual(data["count"], 56)

        health = (await self.http.get("/api/stream-catalog/health")).json()
        self.assertEqual(health["episodes"], 168)
        self.assertEqual(health["servers"], 210)

    async def test_high_episode_direct_iframe_and_multiple_servers(self):
        naruto = await self.http.get("/api/stream-catalog/anime/naruto-shippuuden/episodes")
        self.assertEqual([item["episode"] for item in naruto.json()["episodes"]], [414, 415, 451, 452, 453])

        iframe = await self.http.get("/api/stream-catalog/watch/naruto-shippuuden/1/414")
        self.assertEqual(iframe.json()["default_server"]["type"], "iframe")
        direct = await self.http.get("/api/stream-catalog/watch/jujutsu-kaisen/3/1")
        self.assertEqual(direct.json()["default_server"]["type"], "direct")
        hls = await self.http.get("/api/stream-catalog/watch/yu-gi-oh-duel-monsters/1/1")
        self.assertEqual(hls.json()["default_server"]["type"], "hls")
        self.assertTrue(hls.json()["default_server"]["url"].endswith("/master.m3u8"))
        multiple = await self.http.get("/api/stream-catalog/watch/pokemon-xy/1/17")
        self.assertEqual(multiple.json()["server_count"], 2)

    async def test_movie_and_special_use_standalone_playback_not_episode_numbers(self):
        movie = await self.http.get("/api/stream-catalog/watch/andersen-douwa-ningyohime/0/0")
        special = await self.http.get("/api/stream-catalog/watch/gakkou-no-yuurei/0/0")
        self.assertEqual(movie.json()["content_type"], "movie")
        self.assertEqual(special.json()["content_type"], "special")
        self.assertEqual((await self.http.get("/api/stream-catalog/anime/andersen-douwa-ningyohime/episodes")).json()["count"], 0)

    def test_every_exposed_server_has_a_safe_player_format(self):
        self.assertEqual(sum(len(entry["servers"]) for entry in ani4u_stream_routes.all_entries), 210)
        self.assertTrue(all(ani4u_stream_routes._valid_server(server) for entry in ani4u_stream_routes.all_entries for server in entry["servers"]))


if __name__ == "__main__":
    unittest.main()
