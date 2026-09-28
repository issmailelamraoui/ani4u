import asyncio
import base64
import re
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


BASE_URL = "https://witanime.site"


# =========================================================
# HELPERS
# =========================================================

def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def slug_title(url):
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1]
    return slug.replace("-", " ").strip()


def decode_b64(value):
    try:
        value += "=" * (-len(value) % 4)

        result = base64.b64decode(value).decode(
            "utf-8",
            errors="ignore"
        ).strip()

        if result.startswith(("http://", "https://")):
            return result

    except Exception:
        pass

    return None


def get_episode_number(text, url=""):

    source = f"{text} {url}".lower()

    patterns = [
        r"الحلقة\s*(\d+(?:\.\d+)?)",
        r"episode\s*(\d+(?:\.\d+)?)",
        r"\bep\.?\s*(\d+(?:\.\d+)?)",
        r"/watch/[^/]+/(\d+(?:\.\d+)?)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            source,
            re.I
        )

        if match:
            number = float(match.group(1))
            return int(number) if number.is_integer() else number

    return None


# =========================================================
# WITANIME
# =========================================================

class WitAnime:

    def __init__(self):

        self.pw = None
        self.browser = None
        self.context = None
        self.page = None

    # =====================================================
    # START
    # =====================================================

    async def start(self):

        self.pw = await async_playwright().start()

        self.browser = await self.pw.chromium.launch(
            headless=False
        )

        self.context = await self.browser.new_context(
            viewport={
                "width": 1400,
                "height": 900
            },
            locale="ar"
        )

        self.page = await self.context.new_page()

    # =====================================================
    # CLOSE
    # =====================================================

    async def close(self):

        if self.browser:
            await self.browser.close()

        if self.pw:
            await self.pw.stop()

    # =====================================================
    # GET HTML
    # =====================================================

    async def ensure_browser(self):
        # A closed scraper window must not leave an otherwise healthy API
        # returning 502 until its process is manually restarted.
        if self.browser and (
            not self.browser.is_connected()
            or self.page is None
            or self.page.is_closed()
        ):
            print("[!] Scraper browser/page closed; restarting browser.")
            await self.close()
            await self.start()

    async def get_html(self, url):

        print(f"\n[GET] {url}")

        await self.ensure_browser()

        response = await self.page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        if response is not None and response.status >= 400:
            raise RuntimeError(
                f"Anime source returned HTTP {response.status} for {url}"
            )

        try:

            await self.page.wait_for_load_state(
                "networkidle",
                timeout=10000
            )

        except Exception:
            pass

        await self.page.wait_for_timeout(
            1500
        )

        title = await self.page.title()

        if "Just a moment" in title:

            raise RuntimeError(
                "Cloudflare verification page detected."
            )

        return await self.page.content()

    # =====================================================
    # SEARCH
    # =====================================================

    async def search(self, query):

        # IMPORTANT:
        # CURRENT WITANIME SEARCH ROUTE
        #
        # /search?q=black+clover

        url = (
            f"{BASE_URL}/search"
            f"?q={quote_plus(query)}"
        )

        html = await self.get_html(
            url
        )

        soup = BeautifulSoup(
            html,
            "lxml"
        )

        results = []
        seen = set()

        query_words = [
            word.lower()
            for word in re.findall(
                r"[A-Za-z0-9]+",
                query
            )
        ]

        links = soup.select(
            "a[href*='/anime/'], "
            "a[href*='/movie/'], "
            "a[href*='/movies/'], "
            "a[href*='/film/']"
        )

        print(
            f"[+] Anime links found: {len(links)}"
        )

        for a in links:

            href = a.get(
                "href"
            )

            if not href:
                continue

            href = urljoin(
                BASE_URL,
                href
            )

            if href in seen:
                continue

            # =============================================
            # GET TITLE
            # =============================================

            title = None

            img = a.find(
                "img"
            )

            # IMAGE ALT
            if img:

                title = (
                    img.get("alt")
                    or img.get("title")
                )

            # TITLE ATTRIBUTE
            if not title:

                title = a.get(
                    "title"
                )

            # HEADINGS
            if not title:

                heading = a.select_one(
                    "h1,h2,h3,h4,h5,h6,"
                    ".title,.anime-title"
                )

                if heading:

                    title = clean(
                        heading.get_text(
                            " ",
                            strip=True
                        )
                    )

            # Try parent card
            if not title:

                parent = a.parent

                if parent:

                    heading = parent.select_one(
                        "h1,h2,h3,h4,h5,h6,"
                        ".title,.anime-title"
                    )

                    if heading:

                        title = clean(
                            heading.get_text(
                                " ",
                                strip=True
                            )
                        )

            # LINK TEXT
            if not title:

                text = clean(
                    a.get_text(
                        " ",
                        strip=True
                    )
                )

                if text not in [
                    "شاهد الآن",
                    "شاهد",
                    "مشاهدة"
                ]:

                    title = text

            # SLUG FALLBACK
            if (
                not title
                or title in [
                    "شاهد الآن",
                    "شاهد",
                    "مشاهدة"
                ]
            ):

                title = slug_title(
                    href
                )

            title = clean(
                title
            )

            # =============================================
            # FILTER
            # =============================================

            searchable = (
                title.lower()
                + " "
                + slug_title(href).lower()
            )

            matched = [
                word
                for word in query_words
                if word in searchable
            ]

            score = len(
                matched
            )

            # Black Clover => both words must normally exist
            if len(query_words) > 1:

                required = max(
                    1,
                    len(query_words) - 1
                )

                if score < required:
                    continue

            elif query_words:

                if score == 0:
                    continue

            # =============================================
            # IMAGE
            # =============================================

            image = None

            if img:

                image = (
                    img.get("data-src")
                    or img.get("data-lazy-src")
                    or img.get("src")
                )

                if image:

                    image = urljoin(
                        BASE_URL,
                        image
                    )

            seen.add(
                href
            )

            results.append({

                "title": title,

                "url": href,

                "image": image,

                "_score": score
            })

        results.sort(
            key=lambda x: x["_score"],
            reverse=True
        )

        for result in results:

            result.pop(
                "_score",
                None
            )

        print(
            f"[+] Results found: {len(results)}"
        )

        return results

    # =====================================================
    # SEASONS / RELATED
    # =====================================================

    async def seasons(self, anime_name):

        return await self.search(
            anime_name
        )

    # =====================================================
    # EPISODES
    # =====================================================

    async def episodes(self, anime_url):

        html = await self.get_html(
            anime_url
        )

        soup = BeautifulSoup(
            html,
            "lxml"
        )

        episodes = []

        seen = set()

        # =================================================
        # NORMAL WATCH LINKS
        # =================================================

        for a in soup.find_all(
            "a",
            href=True
        ):

            href = a.get(
                "href",
                ""
            )

            text = clean(
                a.get_text(
                    " ",
                    strip=True
                )
            )

            full_url = urljoin(
                BASE_URL,
                href
            )

            # Related catalog cards can contain "Episode 0" in their titles.
            # They are anime/movie entries, not playable episodes of this title.
            if not urlparse(full_url).path.startswith("/watch/"):
                continue

            check = (
                text
                + " "
                + href
            ).lower()

            if not any([

                "الحلقة" in check,

                "episode" in check,

                "/watch/" in check

            ]):

                continue

            if full_url in seen:
                continue

            number = get_episode_number(
                text,
                full_url
            )

            if number is None:
                continue

            seen.add(
                full_url
            )

            if text in [
                "شاهد الآن",
                "شاهد",
                "مشاهدة"
            ]:

                text = f"الحلقة {number}"

            episodes.append({

                "episode": number,

                "title": (
                    text
                    or f"الحلقة {number}"
                ),

                "url": full_url
            })

        # =================================================
        # BASE64 FALLBACK
        # =================================================

        for element in soup.select(
            "[onclick]"
        ):

            onclick = element.get(
                "onclick",
                ""
            )

            if not onclick:
                continue

            text = clean(
                element.get_text(
                    " ",
                    strip=True
                )
            )

            encoded_values = re.findall(
                r"""['"]([A-Za-z0-9+/=_-]{15,})['"]""",
                onclick
            )

            for encoded in encoded_values:

                decoded = decode_b64(
                    encoded
                )

                if not decoded:
                    continue

                if decoded in seen:
                    continue

                if "/watch/" not in decoded:
                    continue

                number = get_episode_number(
                    text,
                    decoded
                )

                if number is None:
                    continue

                seen.add(
                    decoded
                )

                episodes.append({

                    "episode": number,

                    "title":
                        f"الحلقة {number}",

                    "url": decoded
                })

        # =================================================
        # SORT
        # =================================================

        episodes.sort(
            key=lambda x: x["episode"]
        )

        print(
            f"[+] Episodes discovered: {len(episodes)}"
        )

        return episodes

    # =====================================================
    # SERVERS
    # =====================================================

    async def servers(self, episode_url):

        await self.get_html(
            episode_url
        )

        await self.page.wait_for_timeout(
            2500
        )

        servers = []

        seen = set()

        labels = self.page.locator(
            "span",
            has_text="السيرفر"
        )

        label_count = await labels.count()

        print(
            f"[+] Server labels found: {label_count}"
        )

        for i in range(
            label_count
        ):

            label = labels.nth(
                i
            )

            container = label.locator(
                ".."
            )

            items = container.locator(
                "button, a"
            )

            count = await items.count()

            for j in range(
                count
            ):

                element = items.nth(
                    j
                )

                try:

                    name = clean(
                        await element.inner_text()
                    )

                except Exception:

                    continue

                if not name:
                    continue

                if name in [
                    "السيرفر",
                    "السيرفر:"
                ]:

                    continue

                key = name.lower()

                if key in seen:
                    continue

                seen.add(
                    key
                )

                attributes = {}

                server_id = None

                for attr in [

                    "data-server",
                    "data-server-id",
                    "data-id",
                    "data-index",
                    "data-value",
                    "value"

                ]:

                    value = await element.get_attribute(
                        attr
                    )

                    if value:

                        attributes[attr] = value

                        if server_id is None:
                            server_id = value

                servers.append({

                    "name": name,

                    "id": server_id,

                    "attributes": attributes
                })

        print(
            f"[+] Servers discovered: {len(servers)}"
        )

        return servers


    # =====================================================
    # PLAYER
    # =====================================================

    async def player(self, episode_url, server_name=None, server_id=None):

        await self.get_html(
            episode_url
        )

        await self.page.wait_for_timeout(
            1200
        )

        async def iframe_urls():

            found = []
            seen_urls = set()

            # DOM iframe sources.
            for attr in [
                "src",
                "data-src",
            ]:

                frames = self.page.locator(
                    f"iframe[{attr}]"
                )

                for index in range(
                    await frames.count()
                ):

                    value = await frames.nth(index).get_attribute(
                        attr
                    )

                    if not value:
                        continue

                    value = urljoin(
                        episode_url,
                        value
                    )

                    parsed = urlparse(
                        value
                    )

                    if parsed.scheme not in [
                        "http",
                        "https",
                    ]:
                        continue

                    if value in seen_urls:
                        continue

                    seen_urls.add(
                        value
                    )

                    found.append(
                        value
                    )

            # Playwright also exposes attached child-frame URLs even when
            # the iframe source was changed dynamically by JavaScript.
            for frame in self.page.frames:

                if frame == self.page.main_frame:
                    continue

                value = frame.url

                if not value or value == "about:blank":
                    continue

                parsed = urlparse(
                    value
                )

                if parsed.scheme not in [
                    "http",
                    "https",
                ]:
                    continue

                if value in seen_urls:
                    continue

                seen_urls.add(
                    value
                )

                found.append(
                    value
                )

            return found

        initial_iframes = set(
            await iframe_urls()
        )

        labels = self.page.locator(
            "span",
            has_text="السيرفر"
        )

        candidates = []
        seen_candidates = set()

        for i in range(
            await labels.count()
        ):

            container = labels.nth(i).locator(
                ".."
            )

            items = container.locator(
                "button, a"
            )

            for j in range(
                await items.count()
            ):

                element = items.nth(j)

                try:

                    name = clean(
                        await element.inner_text()
                    )

                except Exception:

                    continue

                if not name or name in [
                    "السيرفر",
                    "السيرفر:"
                ]:
                    continue

                attributes = {}
                detected_id = None

                for attr in [
                    "data-server",
                    "data-server-id",
                    "data-id",
                    "data-index",
                    "data-value",
                    "value"
                ]:

                    value = await element.get_attribute(
                        attr
                    )

                    if value:

                        attributes[attr] = value

                        if detected_id is None:
                            detected_id = value

                key = (
                    name.lower(),
                    detected_id or ""
                )

                if key in seen_candidates:
                    continue

                seen_candidates.add(
                    key
                )

                candidates.append({
                    "element": element,
                    "name": name,
                    "id": detected_id,
                    "attributes": attributes,
                })

        if not candidates:
            raise RuntimeError(
                "No episode servers were found"
            )

        selected = None

        if server_id is not None:

            wanted_id = str(
                server_id
            ).strip()

            for candidate in candidates:

                values = set(
                    candidate["attributes"].values()
                )

                if (
                    candidate["id"] == wanted_id
                    or wanted_id in values
                ):

                    selected = candidate
                    break

        if selected is None and server_name:

            wanted_name = clean(
                server_name
            ).lower()

            for candidate in candidates:

                if candidate["name"].lower() == wanted_name:

                    selected = candidate
                    break

            if selected is None:

                for candidate in candidates:

                    if wanted_name in candidate["name"].lower():

                        selected = candidate
                        break

        if selected is None:
            selected = candidates[0]

        print(
            f"[+] Selecting server: {selected['name']}"
        )

        try:

            await selected["element"].click(
                timeout=7000
            )

        except Exception as error:

            raise RuntimeError(
                f"Could not select server {selected['name']}: {error}"
            ) from error

        await self.page.wait_for_timeout(
            1400
        )

        current_iframes = await iframe_urls()

        new_iframes = [
            value
            for value in current_iframes
            if value not in initial_iframes
        ]

        # Some providers are mounted immediately after server selection.
        # Others require the visible Play button to be pressed first.
        if not new_iframes:

            play_selectors = [
                'button:has-text("Play")',
                'button:has-text("تشغيل")',
                'button:has-text("شاهد")',
                '[role="button"][aria-label*="Play" i]',
                '[aria-label*="تشغيل"]',
                '.plyr__control--overlaid',
                '.vjs-big-play-button',
                '.jw-icon-display',
            ]

            clicked_play = False

            for selector in play_selectors:

                elements = self.page.locator(
                    selector
                )

                for index in range(
                    await elements.count()
                ):

                    element = elements.nth(index)

                    try:

                        if not await element.is_visible():
                            continue

                        await element.click(
                            timeout=5000
                        )

                        clicked_play = True
                        break

                    except Exception:
                        continue

                if clicked_play:
                    break

            if clicked_play:

                await self.page.wait_for_timeout(
                    1800
                )

                current_iframes = await iframe_urls()

                new_iframes = [
                    value
                    for value in current_iframes
                    if value not in initial_iframes
                ]

        usable = (
            new_iframes
            or current_iframes
        )

        if not usable:
            raise RuntimeError(
                "The selected server did not expose a playable iframe"
            )

        # Prefer an external provider frame over a frame hosted by WitAnime.
        selected_embed = None

        for value in usable:

            host = urlparse(
                value
            ).hostname

            if host not in [
                "witanime.site",
                "www.witanime.site",
            ]:

                selected_embed = value
                break

        if selected_embed is None:
            selected_embed = usable[0]

        print(
            f"[+] Player iframe resolved: {selected_embed}"
        )

        return {
            "server": selected["name"],
            "server_id": selected["id"],
            "embed_url": selected_embed,
        }


# =========================================================
# TEST
# =========================================================

async def main():

    api = WitAnime()

    await api.start()

    try:

        query = "Black Clover"

        print(
            "\n========== SEARCH ==========\n"
        )

        results = await api.search(
            query
        )

        for index, anime in enumerate(
            results,
            1
        ):

            print(
                f"{index}. {anime['title']}"
            )

            print(
                f"   {anime['url']}"
            )

            print(
                f"   {anime['image']}"
            )

            print()

    finally:

        input(
            "\nPress ENTER to close..."
        )

        await api.close()


if __name__ == "__main__":

    asyncio.run(
        main()
    )
