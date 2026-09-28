"""Read-only locally validated playback catalog; legacy scraping remains fallback."""

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/api/stream-catalog", tags=["ANI4U Stream Catalog"])
DATA_DIR = Path(__file__).resolve().parent / "data"
LIBRARY_FILE = DATA_DIR / "ani4u_stream_library_PRODUCTION.json"
INDEX_FILE = DATA_DIR / "ani4u_episode_index_PRODUCTION.json"
EXTRA_FILE = DATA_DIR / "ani4u_extra_content_PRODUCTION.json"
OMAR_SPECIALS_FILE = DATA_DIR / "ani4u_omarhidan_specials_PRODUCTION.json"


def _read_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _slugify(title: str) -> str:
    value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if not value:
        raise ValueError(f"Cannot build a safe slug for {title!r}")
    return value


def _valid_server(server: object) -> bool:
    if not isinstance(server, dict) or server.get("tested") is not True or server.get("working") is not True:
        return False
    server_type, host, url = server.get("type"), server.get("host"), server.get("url")
    if not isinstance(url, str) or server_type not in {"direct", "iframe", "hls"}:
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    if server_type == "direct":
        return (
            host == "dl.dropboxusercontent.com"
            and parsed.hostname == host
            and parsed.path.lower().endswith(".mp4")
            and bool(parsed.query)
            and not parsed.fragment
        )

    if server_type == "hls":
        return (
            host == "cdn.msrtsub.com"
            and parsed.hostname == "cdn.msrtsub.com"
            and bool(
                re.fullmatch(
                    r"/media/[^/]+/season-\d+/episode-\d+/master\.m3u8",
                    parsed.path,
                )
            )
            and not parsed.query
            and not parsed.fragment
        )

    if host == "google-drive":
        return (
            parsed.hostname == "drive.google.com"
            and bool(re.fullmatch(r"/file/d/[A-Za-z0-9_-]+/preview", parsed.path))
            and not parsed.fragment
        )
    if host == "mega":
        return (
            parsed.hostname == "mega.nz"
            and bool(re.fullmatch(r"/embed/[A-Za-z0-9_-]+", parsed.path))
            and bool(parsed.fragment)
        )
    # The archived Tsubasa catalog has one separately-tested public player.
    # Accept only its embed endpoint, never a generic OK.ru page or download URL.
    return (
        host == "ok.ru"
        and parsed.hostname == "ok.ru"
        and bool(re.fullmatch(r"/videoembed/\d+", parsed.path))
        and not parsed.fragment
    )


def _validated_servers(servers: object, context: str) -> list[dict]:
    if not isinstance(servers, list) or not servers:
        raise RuntimeError(f"{context} has no servers")
    invalid = [server for server in servers if not _valid_server(server)]
    if invalid:
        raise RuntimeError(f"{context} contains an invalid or untested player: {invalid!r}")
    return [dict(server) for server in servers]


library = _read_json(LIBRARY_FILE)
raw_index = _read_json(INDEX_FILE)
extra = _read_json(EXTRA_FILE)
omar_specials = _read_json(OMAR_SPECIALS_FILE)

series_entries: list[dict] = []
for row in library.get("episodes", []):
    slug, title = row.get("slug"), row.get("anime")
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9-]{1,220}", slug) or not isinstance(title, str):
        raise RuntimeError(f"Invalid series identity: {row!r}")
    series_entries.append({"title": title, "slug": slug, "content_type": "series", "season": int(row["season"]), "episode": int(row["episode"]), "servers": _validated_servers(row.get("servers"), f"{slug}/{row.get('season')}/{row.get('episode')}"), "source_posts": list(row.get("source_posts", []))})

# Reject drift between the two production artifacts instead of silently serving
# a partial episode list.
index_keys = {(slug, int(season), int(item["episode"])) for slug, anime in raw_index.items() for season, items in anime.get("seasons", {}).items() for item in items}
series_keys = {(item["slug"], item["season"], item["episode"]) for item in series_entries}
if index_keys != series_keys:
    raise RuntimeError("Production episode index does not match the production stream library")

standalone_entries: list[dict] = []
# Batches, collections, and movie bundles remain in the imported source file
# but deliberately have no title-to-file mapping. They are reported by stats
# below and are never fabricated as individual movies or numbered episodes.
for row in extra.get("movies", []):
    standalone_entries.append({"title": row["title"], "slug": _slugify(row["title"]), "content_type": "movie", "season": 0, "episode": 0, "servers": _validated_servers(row.get("servers"), row["title"]), "source_posts": list(row.get("source_posts", []))})
for row in [*extra.get("specials", []), *omar_specials.get("specials", [])]:
    standalone_entries.append({"title": row["title"], "slug": _slugify(row["title"]), "content_type": "special", "season": 0, "episode": 0, "servers": _validated_servers(row.get("servers"), row["title"]), "source_posts": list(row.get("source_posts", [row.get("source_post")]))})

all_entries = [*series_entries, *standalone_entries]
if len({item["slug"] for item in standalone_entries}) != len(standalone_entries):
    raise RuntimeError("Standalone content has colliding generated slugs")

catalog: dict[str, dict] = {}
for entry in all_entries:
    item = catalog.setdefault(entry["slug"], {"title": entry["title"], "slug": entry["slug"], "content_type": entry["content_type"], "seasons": {}, "servers": [], "source_posts": []})
    if item["title"] != entry["title"] or item["content_type"] != entry["content_type"]:
        raise RuntimeError(f"Conflicting content identity for {entry['slug']}")
    if entry["content_type"] == "series":
        item["seasons"].setdefault(str(entry["season"]), []).append(entry)
    else:
        item["servers"].extend(entry["servers"])
        item["source_posts"].extend(entry["source_posts"])
for item in catalog.values():
    for rows in item["seasons"].values():
        rows.sort(key=lambda entry: entry["episode"])

watch_lookup = {(entry["slug"], entry["season"], entry["episode"]): entry for entry in all_entries}


def _summary(item: dict) -> dict:
    episode_count = sum(len(rows) for rows in item["seasons"].values())
    server_count = sum(len(row["servers"]) for rows in item["seasons"].values()) if item["content_type"] == "series" else len(item["servers"])
    return {"title": item["title"], "slug": item["slug"], "content_type": item["content_type"], "seasons": sorted(int(season) for season in item["seasons"]), "episode_count": episode_count, "server_count": server_count, "playback": {"season": 0, "episode": 0} if item["content_type"] != "series" else None}


@router.get("/health")
def health():
    kinds = Counter(item["content_type"] for item in catalog.values())
    return {"ok": True, "service": "ani4u-stream-catalog", "series": kinds["series"], "movies": kinds["movie"], "specials": kinds["special"], "episodes": len(series_entries), "servers": sum(len(entry["servers"]) for entry in all_entries)}


@router.get("/stats")
def stats():
    server_types = Counter(server["type"] for entry in all_entries for server in entry["servers"])
    hosts = Counter(server["host"] for entry in all_entries for server in entry["servers"])
    return {**library.get("stats", {}), "series": len(raw_index), "movies": sum(item["content_type"] == "movie" for item in catalog.values()), "specials": sum(item["content_type"] == "special" for item in catalog.values()), "playable_episodes": len(series_entries), "working_video_servers": sum(server_types.values()), "server_types": dict(server_types), "hosts": dict(hosts), "unmapped_grouped_entries": {"batches": len(extra.get("batches", [])), "collections": len(extra.get("collections", [])), "movie_bundles": len(extra.get("movie_bundles", []))}}


@router.get("/anime")
def anime_list():
    result = sorted((_summary(item) for item in catalog.values()), key=lambda item: (item["content_type"] != "series", item["title"].casefold()))
    return {"count": len(result), "series_count": sum(item["content_type"] == "series" for item in result), "movie_count": sum(item["content_type"] == "movie" for item in result), "special_count": sum(item["content_type"] == "special" for item in result), "anime": result}


@router.get("/anime/{slug}")
def anime_details(slug: str):
    item = catalog.get(slug)
    if not item:
        raise HTTPException(404, "Anime not found")
    return _summary(item)


@router.get("/anime/{slug}/episodes")
def anime_episodes(slug: str):
    item = catalog.get(slug)
    if not item:
        raise HTTPException(404, "Anime not found")
    episodes = [{"season": entry["season"], "episode": entry["episode"], "server_count": len(entry["servers"])} for rows in item["seasons"].values() for entry in rows]
    episodes.sort(key=lambda entry: (entry["season"], entry["episode"]))
    return {"title": item["title"], "slug": slug, "content_type": item["content_type"], "count": len(episodes), "episodes": episodes, "playback": {"season": 0, "episode": 0} if item["content_type"] != "series" else None}


@router.get("/watch/{slug}/{season}/{episode}")
def watch(slug: str, season: int, episode: int):
    item = watch_lookup.get((slug, season, episode))
    if not item:
        raise HTTPException(404, "Episode not found")
    server_priority = {"direct": 0, "hls": 1, "iframe": 2}
    servers = sorted(
        item["servers"],
        key=lambda server: server_priority.get(server["type"], 99),
    )
    return {"anime": item["title"], "slug": slug, "content_type": item["content_type"], "season": season, "episode": episode, "server_count": len(servers), "servers": servers, "default_server": servers[0]}
