# Episode loading + embed behavior fix

- Removed the explicit advertising-host rejection from the Anime4up player path and frontend player adapter. External providers can now render their own embed behavior unchanged.
- Kept non-player correctness filters (social/theme links) and the existing rejection of Anime4up-owned internal frames that are not usable as third-party embeds.
- Fixed catalog episode loading when Anime4up changes the CSS class around its episode grid.
- The fallback now finds the largest same-series episode-link group instead of mistaking the single “watch now” link for the full season.
- Bumped the episode cache namespace from `episodes-v1` to `episodes-v2` so old incomplete cached lists are not reused.
- Added a regression test for a 28-episode page with a changed wrapper class and unrelated sidebar links.

Verification:
- Backend: 53 tests + 15 subtests passed.
- Frontend: 17 tests passed.
- Frontend production build passed.
