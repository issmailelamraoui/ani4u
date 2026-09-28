# NOVA Anime

A server-rendered Arabic RTL anime catalog. Home and Search consume the normalized
AniList catalog through FastAPI. Existing source detail/watch routes retain the
Anime4up adapter and its playback resolver.

## Run locally

After installing dependencies and creating the backend virtual environment below,
`npm run dev` checks the configured backend health, starts the local backend if
needed, and then starts Next.js. It reuses an already-running backend and only
stops a backend that it started itself. `npm run dev:frontend` starts Next.js alone.
`BACKEND_PYTHON` can override the backend virtual environment's Python path.

The watch page loads public download-server links only after selecting
“عرض روابط التحميل”. These are the episode's explicitly published host links;
the application does not crawl download hosts or resolve temporary media URLs.

Start the backend first (see [backend setup](../backend/README.md)):

```sh
cd ~/anime-platform/backend
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd ~/anime-platform/frontend
npm install
# First setup only; preserve .env.local if you already have one.
test -f .env.local || cp .env.example .env.local
npm run dev
```

Open http://localhost:3000. The backend uses HTTP requests, not browser automation.
Run one backend worker; AniList rate coordination currently lives in that process.

`API_BASE_URL` is a server-only origin, normally `http://127.0.0.1:8000`.
`API_TIMEOUT_MS` defaults to 120000 because uncached scraping can take time.
`SITE_URL` supplies the canonical public origin; set it before deploying.
No `NEXT_PUBLIC_` backend address is needed. Next.js requests use `no-store`;
FastAPI owns the persistent SQLite catalog cache and legacy scraper cache. Catalog
requests use an 18-second timeout, separately from the legacy scraping timeout.

## Structure and routes

There is a single root App Router: `app/`, `components/`, `lib/`, `public/`.
The alias `@/*` resolves to `./*`. Do not reintroduce `src/app`.

- `/`: rotating artwork-colored hero, 10 top-rated titles, 24 initial Discover
  titles and explicit Load More. Hero rotates every 9 seconds; pauses on hover,
  keyboard focus, hidden tabs, explicit pause, and reduced-motion preference.
- `/search?q=Haikyuu&page=1`: paginated metadata results, 24 per page. Counts refer
  to the current page, not a fabricated catalog total.
- `/anime/catalog/[slug]`: normalized metadata and verified links to source details.
- `/api/catalog/discover?page=2`: bounded same-origin Load More endpoint.
- `/anime/[slug]`: existing source details and episodes, unchanged.
- `/watch/[slug]/[episode]`: existing player and server selection, unchanged.

`lib/catalog-model.ts` defines and validates NOVA contracts. `lib/catalog.ts`
requests only `/api/catalog/...`, with no fallback to scraping. `lib/discovery.ts`
provides Home data/error handling. `lib/api.ts` remains the independent legacy
source/playback client. Catalog links disable speculative prefetching.

Canonical catalog slugs and source slugs are different identities. The new detail
page uses explicit verified mappings to link to source episodes; no guesses or
automatic matching are performed. Without a mapping, the title remains available
for discovery and honestly shows that no episode list is linked. Home, Search,
cards, and catalog details never fetch source episodes or servers.

Latest Episodes is deferred until the source-update feed is implemented. Airing
dates are not presented as playable episodes. Ratings display AniList's scores
converted from /100 to /10 with attribution. Descriptions keep their original
language. Artwork uses Next Image with explicit CDN patterns, responsive sizes,
lazy loading, and a local fallback when an image fails. Catalog styles are scoped
in `app/catalog.css`; legacy playback styles are untouched.

Pages and metadata render on the server. Search results are `noindex,follow`;
anime pages use canonical URLs and metadata from real data. No fake ratings,
release dates, or popularity rankings are generated.

## Verify

```sh
npm run lint
npm test
npm run build
```

Run a production build separately from development when memory is limited.
After building, `npm start` serves the production application. Real search and
poster rendering require a reachable backend/CDN; backend downtime produces
an explicit retry state. Next.js must be restarted after changing environment
variables.

For repeatable catalog browser checks against both running services, install
Playwright separately from production dependencies:

```sh
npm install --prefix /tmp/nova-browser playwright
/tmp/nova-browser/node_modules/.bin/playwright install chromium
PLAYWRIGHT_MODULE=/tmp/nova-browser/node_modules/playwright node scripts/catalog-smoke.mjs
```

The smoke check exercises pagination, carousel controls/reduced motion, metadata
details, failed-image and failed-pagination recovery, mobile overflow, and HTML
rendering without JavaScript. `FRONTEND_URL`, `BACKEND_URL`, and `ARTIFACT_DIR`
override the defaults. The older `scripts/smoke.py` targets the pre-catalog UI and
is retained as legacy reference, not the current Home/Search verification.
