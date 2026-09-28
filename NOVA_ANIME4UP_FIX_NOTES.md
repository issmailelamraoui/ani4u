# NOVA Anime4up parser fix

This revision fixes watch-server resolution for Anime4up layouts where the server
label (for example `anime4up1 [HD]`) and the public `مشغل الحلقة` anchor are siblings
inside the same server row.

The backend now:
- discovers public watch-player anchors first,
- associates each anchor with the nearest server label,
- returns the public external player URL as `embed_url`,
- keeps a compatibility path for older layouts,
- does not inspect or extract provider media playlists.

Backend parser tests: 8/8 passing.
