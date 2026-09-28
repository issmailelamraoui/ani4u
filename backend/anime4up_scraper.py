import asyncio
import base64
import html as html_lib
import re
from typing import Iterable
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag


BASE_URL = "https://w1.anime4up.rest"
SOURCE_HOST_SUFFIX = "anime4up.rest"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SERVER_HINTS = {
    "megamax", "anime4up", "videa", "voe", "vk", "uqload", "dood",
    "mp4upload", "streamruby", "vidmoly", "ok.ru", "mega", "sendvid",
    "streamwish", "streamtape", "filelions", "dsvplay",
    # Legacy Anime4up providers still present on older episode pages.
    "4shared", "solidfiles", "vidbom", "uptostream", "uptobox",
    "redload", "vadbam", "larhu", "openload",
}
NON_PLAYER_HOSTS = {
    "facebook.com", "www.facebook.com", "t.me", "telegram.me", "x.com",
    "twitter.com", "instagram.com", "youtube.com", "www.youtube.com",
    # Theme/designer/social links are not video players. Keep correctness
    # filters, but do not suppress advertising hosts here; third-party embeds
    # are allowed to behave exactly as their provider serves them.
    "vnxweb.com", "www.vnxweb.com",
}

# Anime4up's own VnxPlayer-backed servers reject embedding from third-party
# domains such as NOVA. Keep them out of the public server list so users only
# see providers that have a chance to work as external embeds.
HIDDEN_SERVER_PREFIXES = ("anime4up",)


def _hidden_server_name(value: str | None) -> bool:
    lowered = clean(value).lower()
    return any(lowered.startswith(prefix) for prefix in HIDDEN_SERVER_PREFIXES)


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def absolute_url(value: str | None, base: str = BASE_URL) -> str | None:
    value = clean(value)
    if not value or value.startswith(("javascript:", "mailto:", "tel:")):
        return None
    try:
        return urljoin(base, value)
    except Exception:
        return None


def source_host(host: str | None) -> bool:
    host = (host or "").lower().strip(".")
    return host == SOURCE_HOST_SUFFIX or host.endswith(f".{SOURCE_HOST_SUFFIX}")


def source_path(url: str, prefix: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and source_host(parsed.hostname) and parsed.path.startswith(prefix)


def slug_from_url(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


def get_episode_number(text: str, url: str = "") -> int | float | None:
    source = f"{text} {url}".lower().replace("٫", ".")
    patterns = [
        r"الحلقة\s*(\d+(?:\.\d+)?)",
        r"(?:فيلم|الفلم|movie|film)\s*(\d+(?:\.\d+)?)",
        r"episode\s*(\d+(?:\.\d+)?)",
        r"\bep\.?\s*(\d+(?:\.\d+)?)",
        r"(?:-|/)(\d+(?:\.\d+)?)(?:-|/|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, source, re.I)
        if not match:
            continue
        number = float(match.group(1))
        return int(number) if number.is_integer() else number
    return None


def _candidate_image(node: Tag | None, base: str) -> str | None:
    if node is None:
        return None

    candidates: list[str] = []

    def push(raw) -> None:
        if not isinstance(raw, str):
            return
        raw = html_lib.unescape(raw).strip()
        if not raw:
            return

        # srcset/data-srcset can contain multiple candidates.
        if "," in raw and any(token in raw for token in (" 1x", " 2x", " 320w", " 640w", " 1280w")):
            for part in raw.split(","):
                value = part.strip().split(" ")[0]
                if value:
                    candidates.append(value)
            return

        # CSS lazy-loaders commonly keep poster URLs in style/background attrs.
        for match in re.findall(r"url\((?:['\"]?)(.*?)(?:['\"]?)\)", raw, re.I):
            if match:
                candidates.append(match.strip())

        candidates.append(raw)

    elements: list[Tag] = []
    if node.name in {"img", "source"}:
        elements.append(node)
    elements.extend(
        element
        for element in node.find_all(["img", "source"], recursive=True)
        if isinstance(element, Tag)
    )

    # Some Anime4up cards lazy-load the poster on a wrapper instead of <img>.
    wrappers = [node]
    wrappers.extend(
        element
        for element in node.find_all(True, recursive=True)
        if isinstance(element, Tag) and element.has_attr("style")
    )

    image_attrs = (
        "data-src", "data-lazy-src", "data-original", "data-url", "data-image",
        "data-img", "data-bg", "data-background", "data-background-image",
        "src", "data-srcset", "srcset",
    )

    for element in elements:
        for attr in image_attrs:
            push(element.get(attr))

    for element in wrappers:
        for attr in (
            "data-src", "data-lazy-src", "data-original", "data-image", "data-img",
            "data-bg", "data-background", "data-background-image", "style",
        ):
            push(element.get(attr))

    for value in candidates:
        value = value.strip().strip('"\'')
        if not value or value.startswith(("data:", "blob:")):
            continue
        resolved = absolute_url(value, base)
        if not resolved:
            continue
        parsed = urlparse(resolved)
        # Ignore common 1x1/placeholder/theme assets.
        path = parsed.path.lower()
        if any(token in path for token in ("placeholder", "transparent", "loading.gif", "spinner")):
            continue
        return resolved

    return None


def _normalized_title(text: str) -> str:
    return re.sub(r"[^\w\u0600-\u06ff]+", " ", clean(text).lower(), flags=re.UNICODE).strip()


def _is_brand_image(url: str) -> bool:
    """Reject obvious site chrome so detail pages do not use the Anime4up logo as poster."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    filename = path.rsplit("/", 1)[-1]
    junk_tokens = (
        "favicon", "apple-touch", "site-icon", "site_logo", "site-logo",
        "header-logo", "footer-logo", "brand-logo", "logo-dark", "logo-light",
        "spinner", "loading", "placeholder", "transparent", "avatar",
    )
    if any(token in path for token in junk_tokens):
        return True
    if filename.startswith(("logo.", "logo-", "logo_")):
        return True
    return False


def _detail_poster(soup: BeautifulSoup, title: str, base: str) -> str | None:
    """Pick the anime poster, preferring images whose alt/title matches the anime title."""
    target = _normalized_title(title)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()

    def add(candidate: str | None, score: int) -> None:
        if not candidate or candidate in seen or _is_brand_image(candidate):
            return
        seen.add(candidate)
        scored.append((score, candidate))

    # Strongest signal on Anime4up detail pages: the poster image is labelled with
    # the anime title. This deliberately beats og:image because some pages use a
    # site-wide Anime4up social image there.
    for img in soup.find_all("img"):
        if not isinstance(img, Tag):
            continue
        candidate = _candidate_image(img, base)
        if not candidate:
            continue
        label = _normalized_title(
            " ".join(
                value for value in (
                    img.get("alt") if isinstance(img.get("alt"), str) else "",
                    img.get("title") if isinstance(img.get("title"), str) else "",
                ) if value
            )
        )
        score = 20
        if target and label:
            if label == target:
                score += 200
            elif target in label or label in target:
                score += 140
            else:
                target_words = set(target.split())
                label_words = set(label.split())
                score += 12 * len(target_words & label_words)

        classes = " ".join(img.get("class", []))
        parent = img.parent if isinstance(img.parent, Tag) else None
        if parent is not None:
            classes += " " + " ".join(parent.get("class", []))
        if re.search(r"poster|cover|anime[-_ ]?(?:image|img)|thumb", classes, re.I):
            score += 70

        width = img.get("width")
        height = img.get("height")
        try:
            w = float(width) if width else 0
            h = float(height) if height else 0
            if w and h and h > w:
                score += 15
        except (TypeError, ValueError):
            pass

        add(candidate, score)

    # Theme-specific wrappers are a useful fallback when the <img> itself has no label.
    for selector in (
        ".anime-poster", ".anime-cover", ".poster", ".cover",
        ".anime-image", ".anime-img", "[class*='poster']", "[class*='cover']",
    ):
        for node in soup.select(selector):
            if isinstance(node, Tag):
                add(_candidate_image(node, base), 90)

    # Social metadata is only a fallback. Never allow it to outrank a labelled poster.
    for attrs in (
        {"property": "og:image"},
        {"name": "twitter:image"},
        {"property": "twitter:image"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if isinstance(meta, Tag) and isinstance(meta.get("content"), str):
            add(absolute_url(meta.get("content"), base), 10)

    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _card_for(anchor: Tag) -> Tag:
    current = anchor
    best = anchor
    for _ in range(5):
        parent = current.parent
        if not isinstance(parent, Tag):
            break
        best = parent
        classes = " ".join(parent.get("class", []))
        if parent.name in {"article", "li"} or re.search(r"card|item|anime|episode|post", classes, re.I):
            return parent
        current = parent
    return best


def _title_from_anchor(anchor: Tag) -> str:
    for heading in anchor.select("h1,h2,h3,h4,h5,h6,.title,.anime-title,.name"):
        title = clean(heading.get_text(" ", strip=True))
        if title:
            return title
    image = anchor.find("img")
    if isinstance(image, Tag):
        for attr in ("alt", "title"):
            title = clean(image.get(attr) if isinstance(image.get(attr), str) else "")
            if title:
                return title
    for attr in ("title", "aria-label"):
        raw = anchor.get(attr)
        if isinstance(raw, str) and clean(raw):
            return clean(raw)
    return clean(anchor.get_text(" ", strip=True))


def _kind_from_node(node: Tag | None) -> str:
    text = clean(node.get_text(" ", strip=True) if isinstance(node, Tag) else "")
    if re.search(r"\bmovie\b|فيلم", text, re.I):
        return "movie"
    return "anime"


def _anime_from_anchor(anchor: Tag, base: str) -> dict | None:
    href = absolute_url(anchor.get("href") if isinstance(anchor.get("href"), str) else None, base)
    if not href or not source_path(href, "/anime/"):
        return None
    title = _title_from_anchor(anchor)
    card = _card_for(anchor)
    if not title:
        heading = card.select_one("h1,h2,h3,h4,h5,h6,.title,.anime-title")
        title = clean(heading.get_text(" ", strip=True) if isinstance(heading, Tag) else "")
    if not title:
        title = slug_from_url(href).replace("-", " ")
    image = _candidate_image(anchor, base) or _candidate_image(card, base)
    return {
        "title": title,
        "url": href,
        "image": image,
        "kind": _kind_from_node(card),
    }


def _dedupe_anime(items: Iterable[dict], limit: int | None = None) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
        if limit is not None and len(out) >= limit:
            break
    return out


def _section_links(soup: BeautifulSoup, phrases: tuple[str, ...], prefix: str, limit: int) -> list[Tag]:
    heading: Tag | None = None
    for candidate in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
        text = clean(candidate.get_text(" ", strip=True))
        if any(phrase in text for phrase in phrases):
            heading = candidate
            break
    if heading is None:
        return []

    links: list[Tag] = []
    seen: set[str] = set()
    section_markers = (
        "الأنميات المثبتة", "الانميات المثبتة",
        "أخر الحلقات المضافة", "آخر الحلقات المضافة",
        "أحدث الأنميات", "احدث الانميات",
    )
    for node in heading.find_all_next():
        if node is not heading and node.name in {"h1", "h2", "h3", "h4"}:
            text = clean(node.get_text(" ", strip=True))
            if any(marker in text for marker in section_markers) and not any(phrase in text for phrase in phrases):
                break
        if node.name != "a":
            continue
        raw = node.get("href")
        if not isinstance(raw, str):
            continue
        href = absolute_url(raw, BASE_URL)
        if not href or not source_path(href, prefix) or href in seen:
            continue
        seen.add(href)
        links.append(node)
        if len(links) >= limit:
            break
    return links


def _literal_urls(value: str) -> list[str]:
    return re.findall(r"(?:https?:)?//[^\s'\"<>]+", value or "", re.I)


def _decoded_urlish_values(value: str | None) -> list[str]:
    """Expand common public HTML encodings without touching media manifests.

    Older Anime4up templates sometimes store the public player destination in a
    data-* attribute, percent-encoded string, escaped JS string, or base64 blob.
    We only keep values that decode to normal HTTP(S) URLs later.
    """
    raw = clean(value)
    if not raw:
        return []

    variants: list[str] = []
    queue = [raw]
    seen: set[str] = set()

    while queue and len(seen) < 20:
        item = queue.pop(0)
        if not item or item in seen:
            continue
        seen.add(item)
        variants.append(item)

        unescaped = html_lib.unescape(item).replace('\\/', '/')
        if unescaped != item:
            queue.append(unescaped)

        decoded = unquote(item)
        if decoded != item:
            queue.append(decoded)

        compact = item.strip()
        if 16 <= len(compact) <= 4096 and re.fullmatch(r"[A-Za-z0-9_+/=-]+", compact):
            for decoder in (base64.b64decode, base64.urlsafe_b64decode):
                try:
                    padded = compact + "=" * (-len(compact) % 4)
                    text = decoder(padded.encode()).decode('utf-8', errors='ignore').strip()
                except Exception:
                    continue
                if text and text != item:
                    queue.append(text)

    out: list[str] = []
    emitted: set[str] = set()
    for item in variants:
        candidates = [item, *_literal_urls(item)]
        for candidate in candidates:
            candidate = candidate.strip().strip('\"\'()[]{};,')
            if candidate.startswith('//'):
                candidate = 'https:' + candidate
            if candidate.startswith(('http://', 'https://')) and candidate not in emitted:
                emitted.add(candidate)
                out.append(candidate)
    return out


def _is_external_player_url(url: str, base: str) -> bool:
    resolved = absolute_url(url, base)
    if not resolved:
        return False
    parsed = urlparse(resolved)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if source_host(host):
        return False
    if any(host == blocked or host.endswith(f'.{blocked}') for blocked in NON_PLAYER_HOSTS):
        return False
    # Static/theme assets are never watch players.
    if re.search(r"\.(?:css|js|mjs|png|jpe?g|gif|webp|svg|ico|woff2?|ttf)(?:$|\?)", parsed.path, re.I):
        return False
    return True


def _external_urls_from_element(element: Tag, base: str) -> list[str]:
    values: list[str] = []

    # Inspect every attribute on the local server row. Legacy templates use
    # several different data-* names, so a fixed allowlist is too brittle.
    for raw in element.attrs.values():
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(str(v) for v in raw)

    # The row is deliberately small/local; descendant scanning here does not
    # leak into the footer/theme links that caused the VNxWeb false-positive.
    for child in element.find_all(['a', 'iframe', 'button', 'source'], recursive=True):
        if not isinstance(child, Tag):
            continue
        child_text = clean(child.get_text(' ', strip=True))
        if child.name == 'a' and any(word in child_text for word in ('تحميل', 'Download')):
            continue
        for raw in child.attrs.values():
            if isinstance(raw, str):
                values.append(raw)
            elif isinstance(raw, list):
                values.extend(str(v) for v in raw)

    # Some old rows carry the destination in a tiny inline script.
    for script in element.find_all('script'):
        values.append(script.get_text(' ', strip=False))

    urls: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for candidate in _decoded_urlish_values(raw):
            resolved = absolute_url(candidate, base)
            if not resolved or resolved in seen or not _is_external_player_url(resolved, base):
                continue
            seen.add(resolved)
            urls.append(resolved)
    return urls


def _clean_server_name(value: str) -> str:
    value = clean(value)
    value = re.sub(r"مشغل\s*الحلقة", " ", value, flags=re.I)
    value = re.sub(
        r"\s*(?:\[?(?:f?hd|sd|1080p|720p|480p|متعدد الجودات)\]?)\s*",
        " ",
        value,
        flags=re.I,
    )
    value = re.sub(r"\s+", " ", value).strip(" -–—|:[]()")
    return value


def _looks_like_server_name(value: str) -> bool:
    lowered = clean(value).lower()
    return bool(lowered) and any(hint in lowered for hint in SERVER_HINTS)


def _server_name_for_player_anchor(anchor: Tag) -> str | None:
    # Anime4up commonly renders a server label and a sibling link whose text is
    # "مشغل الحلقة".  Start from that public player link and recover the label
    # from the nearest row instead of assuming the label wraps the anchor.
    parent = anchor.parent if isinstance(anchor.parent, Tag) else None

    if parent is not None:
        sibling_chunks: list[str] = []
        for sibling in anchor.previous_siblings:
            if isinstance(sibling, Tag):
                text = clean(sibling.get_text(" ", strip=True))
            else:
                text = clean(str(sibling))
            if text:
                sibling_chunks.append(text)
        if sibling_chunks:
            candidate = _clean_server_name(" ".join(reversed(sibling_chunks)))
            if candidate and len(candidate) <= 80 and _looks_like_server_name(candidate):
                return candidate

    current = parent
    for _ in range(4):
        if current is None:
            break
        row_text = clean(current.get_text(" ", strip=True))
        candidate = _clean_server_name(row_text)
        if (
            candidate
            and candidate.lower() not in {"مشغل", "الحلقة"}
            and len(candidate) <= 80
            and _looks_like_server_name(candidate)
        ):
            return candidate
        current = current.parent if isinstance(current.parent, Tag) else None

    # Last-resort display name only when the player host itself looks like a
    # known server.  Do not turn unrelated theme/footer links into servers.
    href = anchor.get("href")
    if isinstance(href, str):
        url = absolute_url(href, BASE_URL)
        if url:
            host = (urlparse(url).hostname or "").lower()
            if _looks_like_server_name(host):
                return host
    return None

def _external_embed_candidate(element: Tag, base: str) -> str | None:
    urls = _external_urls_from_element(element, base)
    return urls[0] if urls else None


def _smallest_server_row(node: Tag) -> Tag | None:
    current: Tag | None = node
    best: Tag | None = None
    for _ in range(6):
        if current is None:
            break
        text = clean(current.get_text(' ', strip=True))
        if 'مشغل الحلقة' in text and len(text) <= 220 and _looks_like_server_name(text):
            best = current
            # Prefer semantic row containers when available.
            if current.name in {'li', 'tr'}:
                return current
            classes = ' '.join(current.get('class', [])).lower()
            if re.search(r'server|watch|player|episode', classes):
                return current
        current = current.parent if isinstance(current.parent, Tag) else None
    return best


class Anime4up:
    def __init__(self):
        self.client: httpx.AsyncClient | None = None

    async def start(self):
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, connect=15.0),
            )

    async def close(self):
        if self.client is not None and not self.client.is_closed:
            await self.client.aclose()
        self.client = None

    async def get_html(self, url: str, params: dict[str, str] | None = None) -> str:
        if self.client is None or self.client.is_closed:
            await self.start()
        assert self.client is not None
        print(f"\n[GET] {url}")
        response = await self.client.get(url, params=params)
        if response.status_code >= 400:
            raise RuntimeError(f"Anime4up returned HTTP {response.status_code} for {response.url}")
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower() and not response.text.lstrip().startswith("<"):
            raise RuntimeError(f"Anime4up returned a non-HTML response for {response.url}")
        return response.text

    async def home(self) -> dict:
        html = await self.get_html(f"{BASE_URL}/home8/")
        soup = BeautifulSoup(html, "lxml")

        pinned_links = _section_links(soup, ("الأنميات المثبتة", "الانميات المثبتة"), "/anime/", 10)
        latest_anime_links = _section_links(soup, ("أحدث الأنميات", "احدث الانميات"), "/anime/", 30)
        latest_episode_links = _section_links(soup, ("أخر الحلقات المضافة", "آخر الحلقات المضافة"), "/episode/", 30)

        if not pinned_links:
            pinned_links = [a for a in soup.find_all("a", href=True) if source_path(absolute_url(a.get("href"), BASE_URL) or "", "/anime/")][:8]
        if not latest_anime_links:
            latest_anime_links = [a for a in soup.find_all("a", href=True) if source_path(absolute_url(a.get("href"), BASE_URL) or "", "/anime/")][8:40]
        if not latest_episode_links:
            latest_episode_links = [a for a in soup.find_all("a", href=True) if source_path(absolute_url(a.get("href"), BASE_URL) or "", "/episode/")][:30]

        pinned = _dedupe_anime(filter(None, (_anime_from_anchor(a, BASE_URL) for a in pinned_links)), 8)
        latest_anime = _dedupe_anime(filter(None, (_anime_from_anchor(a, BASE_URL) for a in latest_anime_links)), 24)

        all_anime = _dedupe_anime(
            filter(None, (_anime_from_anchor(a, BASE_URL) for a in soup.find_all("a", href=True))),
            120,
        )
        by_title = {clean(item["title"]).lower(): item for item in all_anime}

        latest_episodes: list[dict] = []
        seen_episode_urls: set[str] = set()
        for anchor in latest_episode_links:
            episode_url = absolute_url(anchor.get("href") if isinstance(anchor.get("href"), str) else None, BASE_URL)
            if not episode_url or episode_url in seen_episode_urls:
                continue
            number = get_episode_number(clean(anchor.get_text(" ", strip=True)), episode_url)
            if number is None:
                continue
            card = _card_for(anchor)
            anime_link = card.find("a", href=lambda href: isinstance(href, str) and "/anime/" in href)
            anime_item = _anime_from_anchor(anime_link, BASE_URL) if isinstance(anime_link, Tag) else None
            if anime_item is None:
                raw_title = clean(anchor.get_text(" ", strip=True))
                raw_title = re.sub(r"\s*الحلقة\s*\d+(?:\.\d+)?\s*", " ", raw_title).strip()
                anime_item = by_title.get(raw_title.lower())
            if anime_item is None:
                continue
            seen_episode_urls.add(episode_url)
            latest_episodes.append({
                "episode": number,
                "title": clean(anchor.get_text(" ", strip=True)) or f"الحلقة {number}",
                "url": episode_url,
                "anime": anime_item,
            })
            if len(latest_episodes) >= 24:
                break

        featured = _dedupe_anime([*pinned, *latest_anime, *(item["anime"] for item in latest_episodes)], 4)
        return {
            "featured": featured,
            "pinned": pinned,
            "latest_anime": latest_anime,
            "latest_episodes": latest_episodes,
        }

    async def search(self, query: str) -> list[dict]:
        html = await self.get_html(f"{BASE_URL}/", params={"s": query})
        soup = BeautifulSoup(html, "lxml")
        items = _dedupe_anime(
            filter(None, (_anime_from_anchor(a, BASE_URL) for a in soup.find_all("a", href=True))),
            80,
        )

        words = [word.lower() for word in re.findall(r"[\w]+", query, re.UNICODE) if len(word) > 1]
        if words:
            scored: list[tuple[int, dict]] = []
            for item in items:
                haystack = f"{item['title']} {slug_from_url(item['url']).replace('-', ' ')}".lower()
                score = sum(1 for word in words if word in haystack)
                if score:
                    scored.append((score, item))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            items = [item for _, item in scored]

        print(f"[+] Search results found: {len(items)}")
        return items

    async def anime(self, slug: str) -> dict | None:
        url = f"{BASE_URL}/anime/{quote(slug.strip('/'), safe='-_')}/"
        try:
            html = await self.get_html(url)
        except RuntimeError as error:
            if "HTTP 404" in str(error):
                return None
            raise
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("h1") or soup.find("h2")
        title = clean(title_tag.get_text(" ", strip=True) if isinstance(title_tag, Tag) else "")
        if not title:
            title = slug.replace("-", " ")

        # Do not trust og:image first: some Anime4up pages use a site-wide
        # Anime4up branding image there. Prefer the actual poster in the page DOM.
        image = _detail_poster(soup, title, url)
        if not image:
            main = soup.find("main") or soup
            fallback = _candidate_image(main if isinstance(main, Tag) else None, url)
            image = None if (fallback and _is_brand_image(fallback)) else fallback

        page_text = clean(soup.get_text(" ", strip=True))
        kind = "movie" if re.search(r"نوع الأنمي\s*:\s*Movie|\bMovie\b", page_text, re.I) else "anime"
        return {"title": title, "url": url, "image": image, "kind": kind}

    def _parse_episode_page(self, html: str, base: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        episodes: list[dict] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = absolute_url(anchor.get("href") if isinstance(anchor.get("href"), str) else None, base)
            if not href or not source_path(href, "/episode/") or href in seen:
                continue
            text = clean(anchor.get_text(" ", strip=True))
            number = get_episode_number(text, href)
            if number is None:
                continue
            seen.add(href)
            episodes.append({
                "episode": number,
                "title": text or f"الحلقة {number}",
                "url": href,
            })
        return episodes

    async def episodes(self, anime_url: str) -> list[dict]:
        first_html = await self.get_html(anime_url)
        soup = BeautifulSoup(first_html, "lxml")
        pages = {1}
        normalized = anime_url.rstrip("/")
        for anchor in soup.find_all("a", href=True):
            href = absolute_url(anchor.get("href") if isinstance(anchor.get("href"), str) else None, anime_url)
            if not href:
                continue
            match = re.search(r"/page/(\d+)/?", urlparse(href).path)
            if match and href.startswith(normalized):
                pages.add(int(match.group(1)))

        max_page = min(max(pages), 80)
        html_pages: list[tuple[int, str]] = [(1, first_html)]
        if max_page > 1:
            semaphore = asyncio.Semaphore(6)

            async def load(page_number: int):
                async with semaphore:
                    return page_number, await self.get_html(f"{normalized}/page/{page_number}/")

            loaded = await asyncio.gather(*(load(page) for page in range(2, max_page + 1)))
            html_pages.extend(loaded)

        all_episodes: dict[str, dict] = {}
        for _, html in sorted(html_pages):
            for episode in self._parse_episode_page(html, anime_url):
                # Anime4up can expose duplicated cards for the same episode.
                # Public NOVA routes are episode-number based, so keep one.
                all_episodes[str(episode["episode"])] = episode

        episodes = list(all_episodes.values())
        episodes.sort(key=lambda item: float(item["episode"]))
        print(f"[+] Episodes discovered: {len(episodes)}")
        return episodes

    async def downloads(self, episode_url: str) -> list[dict]:
        """Read explicit public download links; never follow hosts or resolve media."""
        soup = BeautifulSoup(await self.get_html(episode_url), "lxml")
        rows = []
        seen = set()
        for row in soup.select("#download tr, #downloads tr, .download-links tr"):
            anchor = row.select_one(".td-link a[href]")
            if not anchor or not re.search(r"تحميل|download", anchor.get_text(" ", strip=True), re.I):
                continue
            url = absolute_url(anchor.get("href"), episode_url)
            if not url:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                continue
            # Only links explicitly advertised in the episode's download table.
            if source_host(parsed.hostname) or url in seen:
                continue
            seen.add(url)
            server = row.select_one(".server-name, .td-server")
            quality = row.select_one(".td-quality")
            language = row.select_one(".td-lang")
            rows.append({"url": url, "server": (clean(server.get_text(" ", strip=True)) if server else "") or parsed.hostname,
                         "quality": (clean(quality.get_text(" ", strip=True)) if quality else "") or None,
                         "language": (clean(language.get_text(" ", strip=True)) if language else "") or None})
        return rows

    async def servers(self, episode_url: str) -> list[dict]:
        html = await self.get_html(episode_url)
        soup = BeautifulSoup(html, "lxml")

        servers: list[dict] = []
        seen: set[str] = set()

        # Primary path: Anime4up exposes the actual external player destinations
        # through public anchors labelled "مشغل الحلقة".  The server name can be
        # a sibling (for example <span>anime4up1</span><a>مشغل الحلقة</a>), so
        # resolve from the anchor first and recover the nearest row label.
        for index, anchor in enumerate(soup.find_all("a", href=True)):
            if not isinstance(anchor, Tag):
                continue
            anchor_text = clean(anchor.get_text(" ", strip=True))
            if "مشغل الحلقة" not in anchor_text:
                continue

            embed_url = _external_embed_candidate(anchor, episode_url)
            if not embed_url:
                continue

            name = _server_name_for_player_anchor(anchor)
            if not name:
                # A generic external link labelled "مشغل الحلقة" is not enough
                # evidence that it belongs to the watch-server list.
                continue
            name = _clean_server_name(name) or name
            key = name.lower()
            if key in seen:
                # Keep distinct rows that share a display label by suffixing the
                # later one.  This matters for variants such as mega HD/FHD.
                base_name = name
                suffix = 2
                while f"{base_name} {suffix}".lower() in seen:
                    suffix += 1
                name = f"{base_name} {suffix}"
                key = name.lower()

            seen.add(key)
            attrs: dict[str, str] = {}
            for attr, raw in anchor.attrs.items():
                if isinstance(raw, str):
                    attrs[attr] = raw
                elif isinstance(raw, list):
                    attrs[attr] = " ".join(str(v) for v in raw)

            servers.append({
                "name": name,
                "id": attrs.get("data-id") or attrs.get("data-server") or str(index),
                "attributes": attrs,
                "embed_url": embed_url,
            })

        # Secondary compatibility path for older Anime4up layouts where the
        # player URL is stored directly on the server element.
        candidates: list[Tag] = []
        for element in soup.find_all(["a", "button", "li", "div"]):
            if not isinstance(element, Tag):
                continue
            name = clean(element.get_text(" ", strip=True))
            if not name or len(name) > 100:
                continue
            lowered = name.lower()
            classes = " ".join(element.get("class", [])).lower()
            attrs_text = " ".join(str(v) for v in element.attrs.values()).lower()
            if (
                any(hint in lowered for hint in SERVER_HINTS)
                or "server" in classes
                or "server" in attrs_text
                or "watch" in classes
            ):
                candidates.append(element)

        for index, element in enumerate(candidates):
            # If this container already includes an explicit public "مشغل الحلقة"
            # anchor, the primary pass has handled it. Skipping it here avoids
            # turning broad wrappers (which can also contain footer/theme links)
            # into duplicate fake servers.
            explicit_player_anchor = element.find(
                "a",
                href=True,
                string=lambda text: isinstance(text, str) and "مشغل الحلقة" in clean(text),
            )
            if explicit_player_anchor is not None:
                continue

            raw_name = clean(element.get_text(" ", strip=True))
            name = _clean_server_name(raw_name)
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            embed_url = _external_embed_candidate(element, episode_url)
            if not embed_url:
                continue

            attrs: dict[str, str] = {}
            for attr, raw in element.attrs.items():
                if isinstance(raw, str):
                    attrs[attr] = raw
                elif isinstance(raw, list):
                    attrs[attr] = " ".join(str(v) for v in raw)
            seen.add(key)
            servers.append({
                "name": name,
                "id": attrs.get("data-id") or attrs.get("data-server") or f"legacy-{index}",
                "attributes": attrs,
                "embed_url": embed_url,
            })

        # Tertiary legacy path: very old Anime4up episode pages can render
        # server rows whose public player URL lives in encoded data attributes
        # instead of the anchor href. Search the smallest local row containing
        # both a server-looking label and "مشغل الحلقة". Even when no public
        # URL is exposed, keep the server in the list so the frontend can show
        # that the source offers it instead of pretending there are zero servers.
        for text_node in soup.find_all(string=re.compile(r"مشغل\s*الحلقة", re.I)):
            parent = text_node.parent if isinstance(text_node.parent, Tag) else None
            if parent is None:
                continue
            row = _smallest_server_row(parent)
            if row is None:
                continue
            name = _clean_server_name(clean(row.get_text(' ', strip=True)))
            if not name or not _looks_like_server_name(name):
                continue

            # Keep the label concise when a legacy row contains extra UI text.
            name = re.split(r"(?:الحلقة السابقة|الحلقة التالية|روابط تحميل|المفضلة)", name, maxsplit=1)[0].strip()
            if len(name) > 80:
                words = name.split()
                short = []
                for word in words:
                    short.append(word)
                    if _looks_like_server_name(' '.join(short)):
                        break
                name = ' '.join(short).strip()
            if not name:
                continue

            key = name.lower()
            if key in seen:
                continue
            embed_url = _external_embed_candidate(row, episode_url)
            attrs: dict[str, str] = {}
            for attr, raw in row.attrs.items():
                if isinstance(raw, str):
                    attrs[attr] = raw
                elif isinstance(raw, list):
                    attrs[attr] = ' '.join(str(v) for v in raw)

            seen.add(key)
            servers.append({
                'name': name,
                'id': attrs.get('data-id') or attrs.get('data-server') or f'legacy-text-{len(servers)}',
                'attributes': attrs,
                'embed_url': embed_url,
            })

        before_filter = len(servers)
        servers = [item for item in servers if not _hidden_server_name(item.get("name"))]
        hidden_count = before_filter - len(servers)
        if hidden_count:
            print(f"[+] Hidden Anime4up-owned servers: {hidden_count}")

        print(f"[+] Servers discovered: {len(servers)}")
        if servers:
            playable = sum(1 for item in servers if item.get('embed_url'))
            print(f"[+] Public embed URLs discovered: {playable}/{len(servers)}")
        return servers

    async def player(self, episode_url: str, server: str | None = None, server_id: str | None = None) -> dict:
        servers = await self.servers(episode_url)
        if not servers:
            raise RuntimeError("No watch servers found")

        selected = None
        if server:
            selected = next((item for item in servers if item["name"].lower() == server.lower()), None)
        if selected is None and server_id:
            selected = next((item for item in servers if str(item.get("id")) == str(server_id)), None)
        if selected is None:
            selected = next((item for item in servers if item.get("embed_url")), servers[0])

        embed_url = selected.get("embed_url")
        if not embed_url:
            fallback = next((item for item in servers if item.get("embed_url")), None)
            if fallback is not None:
                print(f"[!] Server {selected['name']} is listed but has no public embed URL; falling back to {fallback['name']}")
                selected = fallback
                embed_url = selected.get("embed_url")
        if not embed_url:
            raise RuntimeError(
                f"Anime4up lists {len(servers)} watch server(s), but this legacy episode page does not expose a public external embed URL in its static HTML"
            )

        print(f"[+] Player iframe resolved: {embed_url}")
        return {
            "server": selected["name"],
            "server_id": selected.get("id"),
            "embed_url": embed_url,
            "sandbox": None,
            "referrer_policy": "origin",
            "allow": "autoplay *; encrypted-media *; picture-in-picture *; fullscreen *",
        }
