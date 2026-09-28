# Anime platform repair report

## Root causes

- Next.js used `frontend/app`, while the search page lived in the unreachable `frontend/src/src/app/search` tree. Duplicate layouts also mixed root and `src` structures.
- The active home page was static marketing content: it did not request or render anime.
- The misplaced search page swallowed errors and replaced them with an empty array, making failures look like no matching anime.
- The existing API origin and `/api/search` path were already correct. They were verified against `backend/api.py`, the running OpenAPI schema, and actual curl responses; this was not a CORS problem.
- The episode parser also mistook related titles containing “Episode 0” for actual episodes on One Piece pages. It now keeps actual `/watch/` links and preserves fractional episode numbers such as `1022.5`.
- During verification, the running backend also returned 502 despite a successful process-health response. Restarting its browser restored real results. The scraper now recreates a closed browser/page on the next uncached request. Upstream HTTP errors are logged and returned as 502 instead of parsed as empty catalogs.

## Changed files

Frontend:

- `app/layout.tsx`, `app/page.tsx`, `app/globals.css`: one root App Router, real discovery sections, responsive Arabic RTL design, metadata.
- `app/search/page.tsx`: real SSR search, exact counts, input validation, useful errors.
- `app/anime/[slug]/page.tsx`: actual anime/movie details, episodes, related search entries, canonical/Open Graph metadata.
- `app/error.tsx`, `app/not-found.tsx`: retry and missing-page states.
- `components/AnimeCard.tsx`, `Navbar.tsx`, `SearchForm.tsx`, `Icons.tsx`, `ApiErrorState.tsx`: reusable accessible interface and local card links.
- `lib/api.ts`: server-only, validated FastAPI adapter; actual source URLs for movies/episodes; logged HTTP/network/schema failures; framework rendering exceptions preserved.
- `lib/discovery.ts`: replaceable search-based discovery with deduplication and visible partial failures.
- `next.config.ts`: explicit Turbopack root and permitted poster host.
- `.env.example`, `.gitignore`, `README.md`: environment and run documentation.
- `package.json`, `tests/api.test.mjs`, `scripts/smoke.py`: contract and live-browser checks.
- Removed the conflicting `src/` files/directories. `tsconfig.json` already had the required `"@/*": ["./*"]` alias and retains it.

Backend:

- `api.py`: rejects whitespace-only search queries.
- `witanime_scraper.py`: upstream HTTP error detection, closed-browser recovery, and filtering related catalog cards out of episode lists; existing extraction strategy preserved.
- `requirements.txt`, `README.md`, `tests/test_errors.py`: reproducible dependencies, run instructions, regression checks.

## Active routes

FastAPI GET routes:

- `/`, `/api/health`
- `/api/search?q=...`
- `/api/episodes?url=...`
- `/api/servers?url=...`
- `/api/anime/{slug}/episodes`
- `/api/anime/{slug}/episode/{episode_number}/servers`
- Documentation: `/docs`, `/redoc`, `/openapi.json`

Frontend:

- `/`
- `/search`, `/search?q=Haikyuu`
- `/anime/[slug]`, including anime and movie entries

There is intentionally no playback route yet: `/watch/[slug]/[episode]` remains future work.

## Verified data and behavior

| Query/page | Actual result |
| --- | --- |
| Haikyuu search | 5 results |
| Black Clover search | 3 results |
| One Piece search | 24 results |
| Bleach search | 10 results |
| Home | 26 deduplicated real anime cards |
| `/anime/haikyuu` | 25 episodes |
| `/anime/black-clover` | 170 episodes |
| `/anime/one-piece` | 1,200 actual watch entries, including fractional specials |
| `/anime/black-clover-2nd-season` | Correct title/poster; source returns 0 episodes |
| `/anime/black-clover-mahou-tei-no-ken` | Correct movie title/poster and source URL; source returns 0 episodes |

Examples returned by the backend include `Haikyuu!!`, `Haikyuu!! Second Season`, `Black Clover`, `Black Clover: Mahou Tei no Ken`, and `One Piece`. Haikyuu episode server names include `soraplay`, `hgcloud`, and `mail`.

Checks performed:

- Real curl requests to FastAPI and HTTP requests to frontend routes.
- ESLint, TypeScript, and production build.
- 16 frontend API contract tests and 7 backend regression tests.
- Browser counts and titles matched the API for all four required searches; posters loaded and card links stayed local.
- Desktop plus 390px/320px mobile layouts; no horizontal overflow.
- Home, search, and Haikyuu episodes rendered with JavaScript disabled.
- All 16 production browser checks passed, with zero browser console errors or runtime exceptions. Fractional-episode handling is additionally covered by a contract regression test and a final live One Piece page check.
- Invalid slug returned HTTP 404; short search displayed validation feedback.
- With FastAPI stopped, the production search page showed a retryable alert without claiming zero results; the terminal logged `ECONNREFUSED` and the actual endpoint.

Browser reports and screenshots are under `.verification/`.

## Remaining work

- Implement playback URL extraction/player and the future watch route. Current server results contain names/IDs/attributes, not playable URLs.
- Replace editorial searches with a proper discovery/detail endpoint when available. Related entries are search matches, not an invented season ordering.
- Set `SITE_URL` to the real public domain before deployment.
- The source currently returns no episodes for the tested Black Clover movie and second-season entry; those pages display an honest empty state.

## Exact run commands

The following uses the already-installed environment verified on this machine. Use separate terminals; do not start a duplicate service on an occupied port.

```sh
cd ~/anime-platform/backend
/home/issmail/witanime-project/.venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

```sh
cd ~/anime-platform/frontend
npm run dev
```

For a fresh independent backend environment, follow `backend/README.md` (`python3 -m venv .venv`, install `requirements.txt`, and install Playwright Chromium). The scraper preserves its visible-browser behavior, so it needs a desktop display or Xvfb.

To repeat checks:

```sh
cd ~/anime-platform/frontend
npm run lint
npm test
npm run build
/home/issmail/witanime-project/.venv/bin/python scripts/smoke.py --phase all
```

```sh
cd ~/anime-platform/backend
/home/issmail/witanime-project/.venv/bin/python -m unittest discover -s tests -v
```

Build separately from browser checks/development on this machine to limit memory use.
