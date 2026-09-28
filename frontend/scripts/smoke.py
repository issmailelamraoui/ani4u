"""Live API-to-browser smoke checks; run with a Python environment with Playwright.

FRONTEND_URL=http://localhost:3000 BACKEND_URL=http://127.0.0.1:8000 \
    python smoke.py --phase catalog
Use --phase details after /anime/[slug] is implemented, or --phase all.
"""

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


FRONTEND = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
BACKEND = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
OUT = Path(os.getenv("ARTIFACT_DIR", "/tmp/anime-verification"))
QUERIES = ["Haikyuu", "Black Clover", "One Piece", "Bleach"]


def api(path):
    with urlopen(BACKEND + path, timeout=180) as response:
        assert response.status == 200
        assert "application/json" in response.headers.get("content-type", "")
        return json.load(response)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def navigate(page, path):
    # Check rendered content/images explicitly; speculative Next.js requests
    # need not become idle before the document is usable.
    response = page.goto(FRONTEND + path, wait_until="domcontentloaded", timeout=180000)
    check(response is not None and response.status == 200,
          f"{path}: document HTTP {response.status if response else 'missing'}")


def overflow(page):
    sizes = page.evaluate("""() => ({width: innerWidth,
      scroll: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)})""")
    check(sizes["scroll"] <= sizes["width"] + 1, f"Horizontal overflow: {sizes}")
    return sizes


def cards(page):
    return page.locator(".anime-card")


def card_data(page):
    return cards(page).evaluate_all("""nodes => nodes.map(node => ({
      href: node.getAttribute('href'),
      title: node.querySelector('h3')?.textContent.trim(),
      image: node.querySelector('img')?.getAttribute('src')
    }))""")


def verify_posters(page, selector=".anime-card img"):
    images = page.locator(selector)
    images.evaluate_all("nodes => nodes.forEach(node => node.loading = 'eager')")
    page.wait_for_function("""selector => [...document.querySelectorAll(selector)]
      .every(image => image.complete)""", arg=selector, timeout=90000)
    states = images.evaluate_all("""nodes => nodes.map(node => ({
      alt: node.alt, src: node.currentSrc, width: node.naturalWidth,
      complete: node.complete
    }))""")
    broken = [state for state in states if state["width"] == 0]
    check(not broken, f"Broken posters: {broken}")
    return len(states)


def verify_search(page, query, backend_data):
    navigate(page, "/search?" + urlencode({"q": query}))
    actual = card_data(page)
    expected = backend_data["results"]
    check(len(actual) == backend_data["count"] == len(expected),
          f"{query}: UI={len(actual)}, API count={backend_data['count']}, results={len(expected)}")
    check(sorted(item["title"] for item in actual) == sorted(item["title"] for item in expected),
          f"{query}: UI titles do not match API titles")
    by_title = {item["title"]: item for item in expected}
    for item in actual:
        href = urlparse(item["href"])
        slug = urlparse(by_title[item["title"]]["url"]).path.strip("/").split("/")[-1]
        check(not href.netloc and href.path == "/anime/" + slug,
              f"{query}: unexpected card href {item['href']}")
    count_element = page.locator("[data-result-count], .result-count, .search-count")
    if count_element.count():
        count_text = count_element.first.inner_text()
        check(str(len(expected)) in count_text, f"{query}: count text mismatch: {count_text}")
    else:
        text = page.locator("main").inner_text()
        check(re.search(rf"\b{len(expected)}\b", text), f"{query}: result count missing from UI")
    loaded = verify_posters(page)
    check(loaded == len([item for item in expected if item.get("image")]),
          f"{query}: incorrect number of poster elements")
    sizes = overflow(page)
    page.screenshot(path=str(OUT / (query.lower().replace(" ", "-") + ".png")), full_page=True)
    return {"query": query, "count": len(actual), "posters_loaded": loaded, "viewport": sizes,
            "titles": [item["title"] for item in actual], "hrefs": [item["href"] for item in actual]}


def verify_home(page, known):
    navigate(page, "/")
    check(page.locator("html").get_attribute("dir") == "rtl", "Arabic page must use RTL direction")
    actual = card_data(page)
    check(actual, "Home has no anime cards")
    hrefs = [item["href"].split("?")[0] for item in actual]
    check(len(hrefs) == len(set(hrefs)), "Home contains duplicated anime cards")
    known_titles = {item["title"] for data in known.values() for item in data["results"]}
    unknown = [item["title"] for item in actual if item["title"] not in known_titles]
    check(not unknown, f"Home cards do not match discovery API results: {unknown}")
    check(all(item["href"].startswith("/anime/") for item in actual), "External home card URL")
    loaded = verify_posters(page)
    sizes = overflow(page)
    page.screenshot(path=str(OUT / "home-desktop.png"), full_page=True)
    return {"count": len(actual), "posters_loaded": loaded, "viewport": sizes}


def verify_search_form(page, expected_count):
    navigate(page, "/")
    form = page.locator('form[role="search"]').first
    form.locator('input[name="q"]').fill("Black Clover")
    with page.expect_navigation(wait_until="domcontentloaded", timeout=180000):
        form.locator('button[type="submit"]').click()
    check(urlparse(page.url).path == "/search", "Search form did not navigate to /search")
    check(cards(page).count() == expected_count, "Submitted search results do not match the API")
    return {"url": page.url, "cards": cards(page).count()}


def verify_details(page):
    data = api("/api/anime/haikyuu/episodes")
    navigate(page, "/anime/haikyuu")
    title = page.locator("h1").inner_text()
    check("Haikyuu" in title, f"Unexpected detail title: {title}")
    episodes = page.locator(".episode-card, [data-episode]")
    if not episodes.count():
        episodes = page.locator('a[href^="/watch/haikyuu/"]')
    expected = data.get("episodes", data.get("results", []))
    check(len(expected) == 25, f"API now returns {len(expected)} Haikyuu episodes, expected 25")
    check(episodes.count() == len(expected),
          f"Detail episodes: UI={episodes.count()}, API={len(expected)}")
    sizes = overflow(page)
    loaded = verify_posters(page, "main img")
    page.screenshot(path=str(OUT / "haikyuu-details-desktop.png"), full_page=True)
    return {"title": title, "episodes": episodes.count(), "posters_loaded": loaded, "viewport": sizes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["catalog", "details", "all"], default="all")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results, errors, console_errors, page_errors = {}, [], [], []

    def run(name, fn):
        try:
            results[name] = fn()
            print(f"PASS {name}: {json.dumps(results[name], ensure_ascii=False)}", flush=True)
        except Exception as error:
            errors.append({"check": name, "error": str(error)})
            print(f"FAIL {name}: {error}", flush=True)

    known = {}
    if args.phase in ("catalog", "all"):
        for query in QUERIES + ["Mushoku Tensei"]:
            known[query] = api("/api/search?" + urlencode({"q": query}))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page = context.new_page()
        page.on("console", lambda message: console_errors.append({"url": page.url, "text": message.text})
                if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append({"url": page.url, "text": str(error)}))

        if args.phase in ("catalog", "all"):
            for query in QUERIES:
                run("search_" + query, lambda query=query: verify_search(page, query, known[query]))
            run("home", lambda: verify_home(page, known))
            run("search_form", lambda: verify_search_form(page, known["Black Clover"]["count"]))
        if args.phase in ("details", "all"):
            run("details", lambda: verify_details(page))

        for width in (390, 320):
            page.set_viewport_size({"width": width, "height": 844})
            paths = (["/", "/search?q=Haikyuu"] if args.phase in ("catalog", "all") else [])
            if args.phase in ("details", "all"):
                paths.append("/anime/haikyuu")
            for path in paths:
                def mobile(path=path, width=width):
                    navigate(page, path)
                    sizes = overflow(page)
                    filename = "home" if path == "/" else "search" if path.startswith("/search") else "details"
                    page.screenshot(path=str(OUT / f"{filename}-mobile-{width}.png"), full_page=True)
                    return sizes
                run(f"mobile_{width}_{path}", mobile)

        context.close()
        nojs = browser.new_context(java_script_enabled=False, viewport={"width": 1440, "height": 1000})
        ssr_page = nojs.new_page()
        if args.phase in ("catalog", "all"):
            def ssr_search():
                navigate(ssr_page, "/search?q=Haikyuu")
                count = cards(ssr_page).count()
                check(count == known["Haikyuu"]["count"], "Search content missing with JavaScript disabled")
                return {"cards_without_javascript": count}
            run("ssr_search", ssr_search)
            def ssr_home():
                navigate(ssr_page, "/")
                count = cards(ssr_page).count()
                check(count > 0, "Home content missing with JavaScript disabled")
                return {"cards_without_javascript": count}
            run("ssr_home", ssr_home)
        if args.phase in ("details", "all"):
            def ssr_details():
                navigate(ssr_page, "/anime/haikyuu")
                check("Haikyuu" in ssr_page.locator("h1").inner_text(), "SSR detail title missing")
                episodes = ssr_page.locator(".episode-card, [data-episode]")
                if not episodes.count():
                    episodes = ssr_page.locator('a[href^="/watch/haikyuu/"]')
                check(episodes.count() == 25, "SSR detail episodes missing")
                return {"episodes_without_javascript": episodes.count()}
            run("ssr_details", ssr_details)
        browser.close()

    if console_errors:
        errors.append({"check": "browser_console", "errors": console_errors})
    if page_errors:
        errors.append({"check": "browser_exceptions", "errors": page_errors})
    report = {"frontend": FRONTEND, "backend": BACKEND, "phase": args.phase,
              "results": results, "errors": errors, "console_errors": console_errors,
              "page_errors": page_errors}
    (OUT / ("report-" + args.phase + ".json")).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({"checks": len(results), "errors": errors}, ensure_ascii=False), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
