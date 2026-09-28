# NOVA Anime4up fix v5

Changes:

- Anime4up-owned player entries such as `anime4up1` / `anime4up2` are filtered out of the public server list because their VnxPlayer instances reject third-party embedding.
- If an old watch URL still asks for an Anime4up-owned server, the backend falls back to another playable external server.
- Poster extraction now supports more lazy-load attributes, `srcset`, and CSS `background-image` URLs.
- Added a same-origin NOVA image proxy at `/api/media/image` so Anime4up/CDN posters are fetched server-side with an Anime4up referer instead of being hotlinked directly by the browser.
- Anime cards, hero belt, latest episodes, and anime detail posters now use the NOVA image proxy.

Validation in the build workspace:

- Backend unit tests: 13/13 passed.
- Frontend unit tests: 6/6 passed.
- TypeScript `tsc --noEmit`: passed.
- A full Next production build could not be used as a clean dependency check in the build workspace because the copied historical `node_modules` archive contains broken package/symlink state. `node_modules` and `.next` are therefore excluded from this ZIP; run `npm install` locally before starting Next.
