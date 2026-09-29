# NOVA Anime backend — catalog and Anime4up adapter

The legacy routes read Anime4up's public HTML pages for catalog metadata, anime pages,
episode lists, and public server/embed links. It does not inspect or extract direct
media playlists and does not bypass provider access controls.

## Run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

## Routes

- `GET /api/health`
- `GET /api/home`
- `GET /api/search?q=One+Piece`
- `GET /api/anime?slug=<anime4up-slug>`
- `GET /api/episodes?url=<Anime4up anime URL>`
- `GET /api/servers?url=<Anime4up episode URL>`
- `GET /api/player?url=<Anime4up episode URL>&server=<name>`

The player route only returns an external HTTP(S) embed URL that is already exposed
in the episode page HTML. If a server does not expose one, the API returns a 502 for
that server instead of trying to bypass it.

## Stage 1: metadata catalog

The additive `/api/catalog` routes use AniList and SQLite only. They never call
Anime4up, fetch episode lists, or resolve servers. All legacy routes and playback
code are preserved. Stage 2 connects frontend Home/Search and the additive
`/anime/catalog/[slug]` metadata page to these routes. Legacy source detail/watch
pages continue to use the original adapter.

| GET route | Response data |
| --- | --- |
| `/api/catalog/home` | `featured` (5), `topRated` (10), `discover` (first 24, with pagination) |
| `/api/catalog/search?q=One+Piece&page=1&per_page=24` | Paginated normalized anime |
| `/api/catalog/discover?page=2&per_page=24` | Popularity-sorted catalog page |
| `/api/catalog/anime/21` | Details by AniList ID |
| `/api/catalog/anime?slug=one-piece-21` | Details by an already assigned NOVA canonical slug |

Search accepts at most 100 characters and requires at least two after whitespace
normalization. Pagination is bounded:
`page` 1–100, `per_page` 1–30 (default 24). Use `hasNextPage`; no guessed totals.
Home uses one GraphQL request with bounded sections. Stage 1 does not provide a
latest-available-episodes section: metadata airing dates cannot establish source
availability. Discover/search can include titles with no streaming-source match.

Every response has this envelope:

```json
{
  "data": {},
  "cache": {
    "status": "miss",
    "updatedAt": 1780000000,
    "expiresAt": 1780000900,
    "staleUntil": 1780260100
  }
}
```

`data` contains a Home object, a page (`items`, `page`, `perPage`, `hasNextPage`),
or one anime. `catalog_models.py` defines the complete response schema, also
available in FastAPI's `/docs` and `/openapi.json`.

NOVA anime has an internal `id`, canonical `slug`, `providerIds`, title and aliases,
plain-text synopsis/language, image/banner/accent, attributed score, genres,
year/season/status/type, episode total, runtime, country, studios, trailer,
popularity, metadata fetch timestamp, and independently recorded source mappings.
Scores retain AniList's 100-point scale. Unknown values remain null. Description
HTML is stripped, unsafe image schemes are rejected, and only recognized YouTube
trailer IDs are exposed. No Arabic translation is fabricated. Adult titles are
excluded from queries.

### Storage and cache

SQLite uses `backend/data/catalog.sqlite3` by default, independent of the working
directory. Override with `NOVA_CATALOG_DB=/persistent/path/catalog.sqlite3`.
The parent directory is created at startup and must be writable. No new package
dependencies are required. Use persistent storage for the DB; identities and
manual mappings must survive deployments. Back it up with SQLite's backup tooling
or while the service is stopped (the live database uses WAL).

#### Vercel and external backend deployment

When `VERCEL` is set, the runtime database path is `/tmp/ani4u/catalog.sqlite3`.
That directory is disposable: at a cold start the versioned
`data/catalog_seed.json` initializes known identities and verified mappings, but
new mappings and response cache entries are not durable there. The seed is only
used for an empty database, so it never overwrites an existing database. For
durable changes, set `NOVA_CATALOG_DB` to external persistent storage on a
non-Vercel backend host.

The Next.js application resolves its server-side backend origin in this order:
`ANI4U_BACKEND_URL`, `API_BASE_URL`, then `http://127.0.0.1:8000`. Set
`ANI4U_BACKEND_URL` on Vercel to the public URL of an external FastAPI host when
that topology is needed; no Vercel-internal address is hard-coded. The loopback
fallback remains local-development only.

`GET /api/health` reports a safe public-provider summary, for example an
unavailable provider with its last HTTP status. It intentionally never includes
cookies, headers, tokens, response bodies, or traces. A 403/429 from Anime4Up
or WitAnime is treated as unavailable and the application uses the next public
fallback or renders the episode panel's unavailable state. This project does not
attempt challenges, proxy rotation, authentication, or other access-control
bypasses.

Tables:

- `anime_identity`: internal NOVA ID, stable canonical slug, unique AniList ID,
  optional MAL ID, creation time. Created on demand, without importing a full catalog.
- `source_mapping`: explicit verified Anime4up title associations and verification
  notes/timestamps. Multiple source listings per anime and shared listings across
  anime are permitted; episode-level disambiguation is deferred to the next stage.
- `catalog_cache`: versioned JSON responses and freshness timestamps, capped at
  2,000 entries. Expired entries are pruned on successful cache writes. This bounds
  response rows, not a strict file-size quota; SQLite reuses freed pages.

| Cached response | Fresh TTL |
| --- | --- |
| Home (all sections together) | 15 minutes |
| Search query + page + page size | 10 minutes |
| Discover page + page size | 30 minutes |
| Completed anime details | 24 hours |
| Other anime details | 1 hour |

Fresh cache hits never call AniList. On expiry, one request refreshes the entry;
concurrent requests for that key share its task. This is **stale-on-error**, not
background stale-while-revalidate: if refresh fails, last-good data may be returned
for up to 72 hours after expiry with `cache.status: "stale"`. A refresh has a
15-second total deadline, including provider queue time. Failed/partial GraphQL
responses never replace good data. A confirmed missing title returns 404 and
invalidates its cached details. With no usable cached data, upstream failures
return 503 plus `Retry-After: 60`.

AniList requests are paced at least 2.1 seconds apart, with rate-header handling,
429 cooldowns, and short failure backoff. There are at most 32 in-flight cache
refresh keys per process. SQLite work runs off the async event loop. Cache
deduplication/rate pacing are process-local: **run one backend worker for now**;
multiple workers/replicas need shared rate coordination. No second provider is
queried in Stage 1. HTTP responses use `Cache-Control: no-store` so SQLite owns
freshness and mapping changes are immediately visible.

### AniList ID ↔ source slug

The AniList ID identifies the metadata record; it is not a source slug. On first
fetch, NOVA assigns an internal UUID and canonical slug such as `one-piece-21`.
Both persist across title changes and cache eviction. The MAL ID is stored as a
cross-reference. Never pass the NOVA canonical slug to a legacy source route.

There is no automatic title matching in Stage 1. `sourceMappings` is empty until
an operator verifies a source listing. A mapping records title identity only:
`availability` stays `unknown` and `availableEpisodeCount` stays null. It does not
guarantee playable episodes, numbering compatibility, or a working server.

Load the title through the catalog first, then use the local command (not an
unauthenticated HTTP write endpoint):

```bash
cd backend
# Replace placeholders with a checked AniList ID, exact decoded source slug,
# and a description of how the title/season match was verified.
python catalog_mapping.py set ANILIST_ID EXACT_SOURCE_SLUG --note "Verification evidence"
python catalog_mapping.py remove ANILIST_ID EXACT_SOURCE_SLUG
```

The command does not fetch any source pages. A `set` updates that exact mapping;
use `remove` to delete an incorrect/old association. Manual associations are
joined into every response, including metadata cache hits. Metadata refreshes
cannot overwrite them. Existing `/anime/<source-slug>` and watch links continue
to use their current source identities. The new `/anime/catalog/<canonical-slug>`
frontend route links to legacy source details only through verified mappings.

### Verification

```bash
cd backend
python -m unittest discover -s tests -v
```

Catalog tests use temporary SQLite databases and mocked AniList HTTP responses.
They cover normalization, request bounds, persistence, verified mappings, cache
expiry/stale windows, concurrent misses, cancellation, upstream errors and rate
limits, startup/shutdown, and zero source calls across all catalog endpoints.
The existing resolver regression tests run in the same suite.

Provider references: [AniList media fields](https://docs.anilist.co/reference/object/media),
[pagination](https://docs.anilist.co/guide/graphql/pagination),
[rate limits](https://docs.anilist.co/guide/rate-limiting),
[terms](https://docs.anilist.co/guide/terms-of-use).
