# NOVA Anime4up v6

Fixes anime detail poster selection.

- Detail pages no longer trust `og:image` first because some Anime4up pages expose a site-wide Anime4up branding image there.
- The scraper now scores page images and strongly prefers the image whose `alt`/`title` matches the anime title.
- Poster/cover wrappers are preferred over generic page images.
- Obvious logo/favicon/placeholder/theme assets are rejected.
- Existing image proxy (`/api/media/image`) remains enabled for hotlink-safe delivery.
- Backend parser tests: 15/15 passing.
