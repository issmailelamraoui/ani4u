# NOVA Anime4up fix v4

This patch keeps the NOVA frontend design intact and hardens the Anime4up backend parser for old/legacy episode pages.

Changes:
- detect legacy server rows even when the watch control is a button instead of a normal external anchor
- decode public player destinations stored in percent-encoded / escaped / base64 data attributes
- support older Anime4up server labels such as 4shared, solidfiles, vidbom, uptostream, uptobox, redload, vadbam and larhu
- keep listed servers visible even when an old page no longer exposes a public external embed URL
- if a selected server has no public embed URL but another listed server does, the backend falls back to the first playable public embed
- keep theme/footer links such as VNxWeb excluded from player URLs
- improved backend logging: `Public embed URLs discovered: X/Y`

Backend tests: 12/12 passing.
