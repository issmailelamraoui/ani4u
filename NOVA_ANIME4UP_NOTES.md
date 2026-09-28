# NOVA × Anime4up

- Frontend design kept in the existing NOVA visual system.
- Old WitAnime backend removed.
- Backend now uses `httpx + BeautifulSoup` against Anime4up public pages.
- New `/api/home` powers the home feed.
- Home hero changed to a four-title horizontal latest belt.
- Home includes latest episode shortcuts and latest/pinned anime sections.
- Public routes remain `/anime/<slug>` and `/watch/<slug>/<episode>`.
- Episode pages keep server selection.
- Player resolution only uses public external embed URLs already present in source HTML.

Run backend on port 8000 and frontend on port 3000. `frontend/.env.local` should contain:

```env
API_BASE_URL=http://127.0.0.1:8000
```
