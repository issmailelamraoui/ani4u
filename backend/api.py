from ani4u_stream_routes import router as ani4u_stream_router
import asyncio
import os
import re
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from anime4up_scraper import Anime4up, SOURCE_HOST_SUFFIX
from anilist_provider import AniListProvider
from catalog_routes import router as catalog_router
from catalog_service import CatalogService
from catalog_store import CatalogStore, database_path
from catalog_episodes import EpisodeCatalog, router as episode_catalog_router
from provider_manager import ProviderManager
from providers.anime4up import Anime4upProvider
from providers.witanime import WitAnimeProvider


SEARCH_CACHE_TTL = 300
HOME_CACHE_TTL = 180
ANIME_CACHE_TTL = 900
EPISODES_CACHE_TTL = 1800
SERVERS_CACHE_TTL = 300

scraper = Anime4up()
source_lock = asyncio.Lock()
cache: dict[tuple, tuple[float, object]] = {}


def cache_get(key):
    item = cache.get(key)
    if not item:
        return None
    expires_at, data = item
    if time.monotonic() >= expires_at:
        cache.pop(key, None)
        return None
    return data


def cache_set(key, data, ttl):
    cache[key] = (time.monotonic() + ttl, data)


def is_source_host(hostname: str | None) -> bool:
    host = (hostname or "").lower().strip(".")
    return host == SOURCE_HOST_SUFFIX or host.endswith(f".{SOURCE_HOST_SUFFIX}")


def validate_anime4up_url(url: str, allowed_paths: tuple[str, ...]):
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid URL") from exc
    if parsed.scheme != "https" or not is_source_host(parsed.hostname):
        raise HTTPException(status_code=400, detail="Only Anime4up HTTPS URLs are allowed")
    if not any(parsed.path.startswith(prefix) for prefix in allowed_paths):
        raise HTTPException(status_code=400, detail="Unsupported Anime4up URL")
    return url


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[+] Starting Anime4up HTTP client...")
    await scraper.start()
    print("[+] Anime4up client ready.")
    try:
        store = CatalogStore(database_path())
        await asyncio.to_thread(store.initialize)
        async with httpx.AsyncClient(timeout=12, headers={"Accept": "application/json"}) as client:
            app.state.catalog = CatalogService(store, AniListProvider(client))
            providers = ProviderManager(store, [Anime4upProvider(scraper), WitAnimeProvider()])
            await providers.start()
            app.state.provider_manager = providers
            app.state.catalog_episodes = EpisodeCatalog(app.state.catalog, scraper, providers)
            try:
                yield
            finally:
                await app.state.catalog_episodes.close()
                del app.state.catalog_episodes
                await providers.close()
                del app.state.provider_manager
                await app.state.catalog.close()
                del app.state.catalog
    finally:
        print("[+] Closing Anime4up client...")
        await scraper.close()


app = FastAPI(
    title="NOVA Anime API",
    description="Anime4up public source adapter and AniList metadata catalog",
    version="2.0.0",
    lifespan=lifespan,
)
app.include_router(catalog_router)
app.include_router(episode_catalog_router)

frontend_origins = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "name": "NOVA Anime API",
        "source": "Anime4up",
        "routes": ["/api/home", "/api/search", "/api/anime", "/api/episodes", "/api/servers", "/api/player", "/api/downloads"],
        "catalog_routes": ["/api/catalog/home", "/api/catalog/search", "/api/catalog/discover", "/api/catalog/anime", "/api/catalog/anime/{anilist_id}"],
    }


@app.get("/api/health")
async def health():
    manager = getattr(app.state, "provider_manager", None)
    providers = manager.availability() if manager is not None else {
        "anime4up": {"status": "unknown", "last_status": None},
        "witanime": {"status": "unknown", "last_status": None},
    }
    # This is operational telemetry only. It intentionally contains no
    # request headers, cookies, response bodies, tokens, or stack traces.
    return {"status": "ok", "source": "anime4up", "providers": providers}


@app.get("/api/home")
async def home():
    key = ("home",)
    cached = cache_get(key)
    if cached is not None:
        return {**cached, "cached": True}
    try:
        async with source_lock:
            result = await scraper.home()
    except Exception as error:
        print("[HOME ERROR]", repr(error))
        raise HTTPException(status_code=502, detail="Could not load Anime4up home feed") from error
    payload = {**result, "cached": False}
    cache_set(key, payload, HOME_CACHE_TTL)
    return payload


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1, max_length=100)):
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Search query is too short")
    key = ("search", query.lower())
    cached = cache_get(key)
    if cached is not None:
        return {"query": query, "count": len(cached), "cached": True, "results": cached}
    try:
        async with source_lock:
            results = await scraper.search(query)
    except Exception as error:
        print("[SEARCH ERROR]", repr(error))
        raise HTTPException(status_code=502, detail="Could not search Anime4up") from error
    cache_set(key, results, SEARCH_CACHE_TTL)
    return {"query": query, "count": len(results), "cached": False, "results": results}


@app.get("/api/anime")
async def anime(slug: str = Query(..., min_length=1, max_length=220)):
    if not slug.strip() or len(slug) > 220 or "/" in slug or "\\" in slug or ".." in slug:
        raise HTTPException(status_code=400, detail="Invalid anime slug")
    key = ("anime", slug.lower())
    cached = cache_get(key)
    if cached is not None:
        return {"cached": True, "anime": cached}
    try:
        async with source_lock:
            result = await scraper.anime(slug)
    except Exception as error:
        print("[ANIME ERROR]", repr(error))
        raise HTTPException(status_code=502, detail="Could not load anime details") from error
    if result is None:
        raise HTTPException(status_code=404, detail="Anime not found")
    cache_set(key, result, ANIME_CACHE_TTL)
    return {"cached": False, "anime": result}


@app.get("/api/episodes")
async def episodes(url: str = Query(...)):
    url = validate_anime4up_url(url, ("/anime/",))
    key = ("episodes", url)
    cached = cache_get(key)
    if cached is not None:
        return {"url": url, "count": len(cached), "cached": True, "episodes": cached}
    try:
        async with source_lock:
            results = await scraper.episodes(url)
    except Exception as error:
        print("[EPISODES ERROR]", repr(error))
        raise HTTPException(status_code=502, detail="Could not load Anime4up episodes") from error
    cache_set(key, results, EPISODES_CACHE_TTL)
    return {"url": url, "count": len(results), "cached": False, "episodes": results}


@app.get("/api/servers")
async def servers(url: str = Query(...)):
    url = validate_anime4up_url(url, ("/episode/",))
    key = ("servers", url)
    cached = cache_get(key)
    if cached is not None:
        return {"url": url, "count": len(cached), "cached": True, "servers": cached}
    try:
        async with source_lock:
            results = await scraper.servers(url)
    except Exception as error:
        print("[SERVERS ERROR]", repr(error))
        raise HTTPException(status_code=502, detail="Could not load Anime4up watch servers") from error
    cache_set(key, results, SERVERS_CACHE_TTL)
    return {"url": url, "count": len(results), "cached": False, "servers": results}


@app.get("/api/downloads")
async def downloads(url: str = Query(...)):
    url = validate_anime4up_url(url, ("/episode/",))
    key = ("downloads", url)
    cached = cache_get(key)
    if cached is not None:
        return {"url": url, "cached": True, "downloads": cached}
    try:
        async with source_lock:
            results = await scraper.downloads(url)
    except Exception as error:
        print("[DOWNLOADS ERROR]", repr(error))
        raise HTTPException(status_code=502, detail="Could not load episode download links") from error
    cache_set(key, results, SERVERS_CACHE_TTL)
    return {"url": url, "cached": False, "downloads": results}


@app.get("/api/player")
async def player(
    url: str = Query(...),
    server: str | None = Query(default=None, max_length=100),
    server_id: str | None = Query(default=None, max_length=100),
):
    url = validate_anime4up_url(url, ("/episode/",))
    try:
        async with source_lock:
            result = await scraper.player(url, server=server, server_id=server_id)
    except Exception as error:
        print("[PLAYER ERROR]", repr(error))
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"url": url, **result}


app.include_router(ani4u_stream_router)
