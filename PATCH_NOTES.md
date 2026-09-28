# NOVA watch patch — primary media first

This patch keeps the existing WitAnime server/embed fallback and adds an optional authorized primary media provider.

## Flow

1. `/api/primary-media?slug=...&episode=...` asks the configured primary provider for a fresh signed URL.
2. If available, the watch page renders it with native HTML5 `<video>`.
3. If it returns 404 or is unavailable, NOVA automatically falls back to the existing WitAnime server list/player flow.
4. Signed media URLs are never cached by this patch.

## Backend environment

```env
PRIMARY_MEDIA_API_URL=https://media.example.com/api/episode
PRIMARY_MEDIA_TOKEN=optional-bearer-token
PRIMARY_MEDIA_ALLOWED_HOSTS=cdn.example.com,media.example.com
PRIMARY_MEDIA_TIMEOUT=10
```

Provider contract:

```json
{
  "url": "https://cdn.example.com/video/episode-41.mp4?signature=...",
  "mime_type": "video/mp4",
  "label": "NOVA Primary"
}
```

The provider receives `slug` and `episode` as query parameters. Return HTTP 404 (or `{ "available": false }`) when that episode is not available so the fallback servers can be used.

Only connect this to media/storage you are authorized to use.
