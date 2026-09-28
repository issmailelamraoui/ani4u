# Fixed project notes

The uploaded project was repaired in place.

## Main fix

`frontend/app/watch/[slug]/[episode]/page.tsx` imported `getEpisodePlayer` and `PlayerResponse`, but `frontend/lib/api.ts` did not export them. The missing API client contract was added and wired to the existing FastAPI `/api/player` endpoint.

## Validation

- Next.js production build: passed
- TypeScript: passed
- ESLint: passed
- Frontend API tests: 17/17 passed
- Backend Python tests: 7/7 passed
- Python compile checks: passed

## Install / run

Frontend:

```bash
cd frontend
npm install
npm run dev -- --hostname 0.0.0.0 --port 3000
```

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
uvicorn api:app --host 0.0.0.0 --port 8000
```

`frontend/.env.local` already points `API_BASE_URL` to `http://127.0.0.1:8000`.
