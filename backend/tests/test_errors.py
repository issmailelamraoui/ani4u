import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import api
from anime4up_scraper import Anime4up, get_episode_number


class Anime4upParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_downloads_read_only_explicit_episode_table_without_following_links(self):
        scraper = Anime4up()
        row = '<tr><td class="td-link"><a href="https://mega.nz/#!file!key">تحميل</a></td><td class="td-server">mega.nz</td><td class="td-quality">FHD 1080p</td><td class="td-lang">مترجم</td></tr>'
        scraper.get_html = AsyncMock(return_value=f'''
          <a href="https://unrelated.test/download">تحميل</a>
          <div id="download"><table>{row}{row}
          <tr><td class="td-link"><a href="javascript:alert(1)">تحميل</a></td></tr>
          <tr><td class="td-link"><a href="https://w1.anime4up.rest/episode/other/">تحميل</a></td></tr>
          <tr><td class="td-link"><a href="https://player.test/embed/1">مشغل الحلقة</a></td></tr>
          </table></div>''')
        url = "https://w1.anime4up.rest/episode/season-two-12.5/"
        rows = await scraper.downloads(url)
        self.assertEqual(rows, [{"url": "https://mega.nz/#!file!key", "server": "mega.nz", "quality": "FHD 1080p", "language": "مترجم"}])
        scraper.get_html.assert_awaited_once_with(url)

    async def test_no_download_table_returns_no_invented_links(self):
        scraper = Anime4up()
        scraper.get_html = AsyncMock(return_value='<a href="https://player.test/e/1">مشغل الحلقة</a>')
        self.assertEqual(await scraper.downloads("https://w1.anime4up.rest/episode/test/"), [])

    def test_episode_number_keeps_fraction(self):
        self.assertEqual(get_episode_number("الحلقة 1092.5"), 1092.5)
        self.assertEqual(get_episode_number("الحلقة 25"), 25)
        self.assertEqual(get_episode_number("الفلم 1"), 1)
        self.assertEqual(get_episode_number("فيلم 2"), 2)

    async def test_episode_links_only_use_episode_paths(self):
        scraper = Anime4up()
        html = '''
        <a href="/anime/one-piece-gfjgfh/">One Piece</a>
        <a href="/episode/one-piece-الحلقة-1/">الحلقة 1</a>
        <a href="/episode/one-piece-الحلقة-2/">الحلقة 2</a>
        '''
        rows = scraper._parse_episode_page(html, "https://w1.anime4up.rest/anime/one-piece-gfjgfh/")
        self.assertEqual([item["episode"] for item in rows], [1, 2])
        self.assertTrue(all("/episode/" in item["url"] for item in rows))

    async def test_server_rows_capture_sibling_player_anchor(self):
        scraper = Anime4up()
        scraper.get_html = AsyncMock(return_value='''
        <div class="watch-server-row">
          <span class="server-name">anime4up1 [HD]</span>
          <a class="watch-now" href="https://4o.example.test/Anime4up-S1/show/1/6/sub/">مشغل الحلقة</a>
        </div>
        <div class="watch-server-row">
          <span class="server-name">videa [HD]</span>
          <a class="watch-now" href="https://videa.example.test/player?v=abc">مشغل الحلقة</a>
        </div>
        ''')
        rows = await scraper.servers("https://w1.anime4up.rest/episode/test-الحلقة-6/")
        by_name = {row["name"].lower(): row for row in rows}
        self.assertNotIn("anime4up1", by_name)
        self.assertEqual(by_name["videa"]["embed_url"], "https://videa.example.test/player?v=abc")

    async def test_player_never_uses_hidden_anime4up_owned_servers(self):
        scraper = Anime4up()
        scraper.get_html = AsyncMock(return_value="""
        <div class="watch-server-row">
          <span>anime4up1 [HD]</span>
          <a href="https://4o.example.test/Anime4up-S1/show/1/6/sub/">مشغل الحلقة</a>
        </div>
        <div class="watch-server-row">
          <span>videa [HD]</span>
          <a href="https://videa.example.test/player?v=abc">مشغل الحلقة</a>
        </div>
        """)
        result = await scraper.player(
            "https://w1.anime4up.rest/episode/test-الحلقة-6/",
            server="anime4up1",
            server_id="0",
        )
        self.assertEqual(result["server"].lower(), "videa")
        self.assertEqual(result["embed_url"], "https://videa.example.test/player?v=abc")

    async def test_server_rows_capture_public_nested_external_embed(self):
        scraper = Anime4up()
        scraper.get_html = AsyncMock(return_value='''
        <ul>
          <li class="server-item">megamax [HD] <a href="https://share4max.com/e/abc">مشغل الحلقة</a></li>
          <li class="server-item">videa [HD] <a href="https://videa.hu/player?v=abc">مشغل الحلقة</a></li>
        </ul>
        ''')
        rows = await scraper.servers("https://w1.anime4up.rest/episode/test-الحلقة-1/")
        self.assertEqual(rows[0]["name"].lower(), "megamax")
        self.assertEqual(rows[0]["embed_url"], "https://share4max.com/e/abc")
        self.assertEqual(rows[1]["embed_url"], "https://videa.hu/player?v=abc")


    async def test_server_parser_ignores_theme_footer_links(self):
        scraper = Anime4up()
        scraper.get_html = AsyncMock(return_value='''
        <div class="watch-area">
          <div class="watch-server-row">
            <span>anime4up1 [HD]</span>
            <a href="https://4o.example.test/Anime4up-S1/show/1/6/sub/">مشغل الحلقة</a>
          </div>
          <footer><a href="https://vnxweb.com/">تصميم وبرمجة: vnxweb</a></footer>
        </div>
        ''')
        rows = await scraper.servers("https://w1.anime4up.rest/episode/test-الحلقة-6/")
        self.assertEqual(rows, [])

    async def test_vnxweb_is_never_accepted_as_player(self):
        scraper = Anime4up()
        scraper.get_html = AsyncMock(return_value="""
        <div class="watch-server-row">
          <span>anime4up1 [HD]</span>
          <a href="https://vnxweb.com/templates/">مشغل الحلقة</a>
        </div>
        """)
        rows = await scraper.servers("https://w1.anime4up.rest/episode/test-الحلقة-6/")
        self.assertEqual(rows, [])

    async def test_legacy_percent_encoded_player_attribute_is_decoded(self):
        scraper = Anime4up()
        scraper.get_html = AsyncMock(return_value="""
        <li class="servers-list-item" data-player="https%3A%2F%2Flegacy.example.test%2Fembed%2Fabc">
          <span>anime4up1 [HD]</span>
          <button type="button">مشغل الحلقة</button>
        </li>
        """)
        rows = await scraper.servers("https://w1.anime4up.rest/episode/test-الحلقة-14/")
        self.assertEqual(rows, [])

    async def test_legacy_server_is_listed_even_without_public_embed(self):
        scraper = Anime4up()
        scraper.get_html = AsyncMock(return_value="""
        <li class="servers-list-item">
          <span>mega [HD]</span>
          <button type="button" data-id="77">مشغل الحلقة</button>
        </li>
        """)
        rows = await scraper.servers("https://w1.anime4up.rest/episode/test-الحلقة-14/")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"].lower(), "mega")
        self.assertIsNone(rows[0]["embed_url"])

    def test_image_parser_supports_lazy_background_images(self):
        from bs4 import BeautifulSoup
        from anime4up_scraper import _candidate_image

        soup = BeautifulSoup(
            '<div class="anime-card" style="background-image:url(https://cdn.example.test/posters/a.webp)"></div>',
            "lxml",
        )
        self.assertEqual(
            _candidate_image(soup.select_one(".anime-card"), "https://w1.anime4up.rest/"),
            "https://cdn.example.test/posters/a.webp",
        )


    def test_detail_poster_prefers_title_image_over_anime4up_brand_og_image(self):
        from bs4 import BeautifulSoup
        from anime4up_scraper import _detail_poster

        soup = BeautifulSoup(
            """
            <html><head>
              <meta property="og:image" content="https://w1.anime4up.rest/wp-content/uploads/site-logo.png">
            </head><body>
              <header><img src="/wp-content/uploads/header-logo.png" alt="Anime4up"></header>
              <main>
                <div class="anime-poster">
                  <img data-src="https://cdn.example.test/posters/gintama.webp" alt="Gintama Movie 3: Yoshiwara Daienjou">
                </div>
              </main>
            </body></html>
            """,
            "lxml",
        )
        self.assertEqual(
            _detail_poster(
                soup,
                "Gintama Movie 3: Yoshiwara Daienjou",
                "https://w1.anime4up.rest/anime/gintama-movie-3-yoshiwara-daienjou/",
            ),
            "https://cdn.example.test/posters/gintama.webp",
        )

    async def test_anime_detail_returns_real_poster_not_site_branding(self):
        scraper = Anime4up()
        scraper.get_html = AsyncMock(return_value="""
        <html><head>
          <meta property="og:image" content="https://w1.anime4up.rest/wp-content/uploads/site-logo.png">
        </head><body>
          <h1>Gintama Movie 3: Yoshiwara Daienjou</h1>
          <div class="anime-poster">
            <img src="https://cdn.example.test/posters/gintama.webp" alt="Gintama Movie 3: Yoshiwara Daienjou">
          </div>
        </body></html>
        """)
        anime = await scraper.anime("gintama-movie-3-yoshiwara-daienjou")
        self.assertIsNotNone(anime)
        self.assertEqual(anime["image"], "https://cdn.example.test/posters/gintama.webp")

    async def test_source_failure_returns_502_and_is_not_cached(self):
        query = "uncached failure test"
        key = ("search", query.lower())
        api.cache.pop(key, None)
        with patch.object(api.scraper, "search", new=AsyncMock(side_effect=RuntimeError("HTTP 503"))):
            with self.assertRaises(HTTPException) as raised:
                await api.search(q=query)
        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn(key, api.cache)

    async def test_whitespace_search_does_not_reach_scraper(self):
        with patch.object(api.scraper, "search", new=AsyncMock()) as search:
            with self.assertRaises(HTTPException) as raised:
                await api.search(q="   ")
        self.assertEqual(raised.exception.status_code, 422)
        search.assert_not_awaited()

    def test_url_validation_rejects_non_anime4up_hosts(self):
        with self.assertRaises(HTTPException):
            api.validate_anime4up_url("https://example.com/anime/x", ("/anime/",))


if __name__ == "__main__":
    unittest.main()
