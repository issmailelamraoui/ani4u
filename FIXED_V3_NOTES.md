# NOVA Anime v3 player fix

## Fixed

The previous player resolver accepted the first external iframe on the WitAnime watch page. That could be the advertising iframe (`acceptable.a-ads.com`) instead of the actual video player.

The resolver now follows the source page's own player flow:

1. Select the requested server.
2. Trigger the source's `[data-testid="player-start"]` control.
3. Wait specifically for `iframe.player-frame`.
4. Return only that iframe's `src`.
5. Reject known advertising iframe hosts as an extra guard.

No direct media playlist extraction or access-control bypass is used.

## Verification

- `python -m py_compile backend/witanime_scraper.py` — OK
- `PYTHONPATH=. python -m unittest discover -s tests -v` — 7/7 tests OK

## Run

Backend:

```bash
cd ~/anime-platform/backend
source ~/witanime-project/.venv/bin/activate
uvicorn api:app --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd ~/anime-platform/frontend
npm install
npm run dev -- --hostname 0.0.0.0 --port 3000
```
