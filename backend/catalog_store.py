"""Durable identities/mappings and bounded, disposable catalog response cache."""

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def database_path() -> Path:
    return Path(os.getenv("NOVA_CATALOG_DB", str(Path(__file__).parent / "data" / "catalog.sqlite3")))


class CatalogStore:
    def __init__(self, path: Path, max_entries: int = 2000):
        self.path = Path(path)
        self.max_entries = max_entries

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS anime_identity (
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    anilist_id INTEGER NOT NULL UNIQUE,
                    mal_id INTEGER,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_mapping (
                    anime_id TEXT NOT NULL REFERENCES anime_identity(id),
                    source TEXT NOT NULL CHECK(source IN ('anime4up', 'witanime')),
                    source_slug TEXT NOT NULL,
                    verified_at INTEGER NOT NULL,
                    note TEXT NOT NULL,
                    PRIMARY KEY (anime_id, source, source_slug)
                );
                CREATE TABLE IF NOT EXISTS catalog_cache (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    stale_until INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS cache_expiry ON catalog_cache(stale_until);
            """)
            mapping_schema = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='source_mapping'"
            ).fetchone()[0]
            if "source = 'anime4up'" in mapping_schema:
                # SQLite cannot alter a CHECK constraint. Keep a physical backup
                # before replacing only this table, then copy every legacy row.
                backup = self.path.with_name(
                    f"{self.path.name}.pre-provider-migration-{int(time.time())}.bak"
                )
                if not backup.exists():
                    destination = sqlite3.connect(backup)
                    try:
                        db.backup(destination)
                    finally:
                        destination.close()
                db.executescript("""
                    CREATE TABLE source_mapping_v2 (
                        anime_id TEXT NOT NULL REFERENCES anime_identity(id),
                        source TEXT NOT NULL CHECK(source IN ('anime4up', 'witanime')),
                        source_slug TEXT NOT NULL,
                        verified_at INTEGER NOT NULL,
                        note TEXT NOT NULL,
                        PRIMARY KEY (anime_id, source, source_slug)
                    );
                    INSERT INTO source_mapping_v2 (anime_id, source, source_slug, verified_at, note)
                        SELECT anime_id, source, source_slug, verified_at, note FROM source_mapping;
                    DROP TABLE source_mapping;
                    ALTER TABLE source_mapping_v2 RENAME TO source_mapping;
                """)

    def identities(self, media: list[dict]) -> dict[int, dict]:
        result = {}
        with self.connect() as db:
            for item in media:
                anilist_id = item["id"]
                if isinstance(anilist_id, bool) or not isinstance(anilist_id, int) or anilist_id <= 0:
                    raise ValueError("Invalid AniList ID")
                nova_id = "nova_" + uuid.uuid4().hex
                title = item.get("title") or {}
                name = title.get("english") or title.get("romaji") or "anime"
                stem = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:120] or "anime"
                # Canonical slug is assigned once. A later title correction cannot break links.
                db.execute("""INSERT INTO anime_identity (id, slug, anilist_id, mal_id, created_at)
                    VALUES (?, ?, ?, ?, ?) ON CONFLICT(anilist_id) DO UPDATE SET
                    mal_id=COALESCE(excluded.mal_id, anime_identity.mal_id)""",
                    (nova_id, f"{stem}-{anilist_id}", anilist_id, item.get("idMal"), int(time.time())))
                row = db.execute("SELECT id, slug FROM anime_identity WHERE anilist_id=?", (anilist_id,)).fetchone()
                result[anilist_id] = dict(row)
        return result

    def anilist_id_for_slug(self, slug: str) -> int | None:
        with self.connect() as db:
            row = db.execute("SELECT anilist_id FROM anime_identity WHERE slug=?", (slug,)).fetchone()
        return row[0] if row else None

    def set_mapping(self, anilist_id: int, source_slug: str, note: str, source: str = "anime4up"):
        # Administrative, explicit verification only. No public write endpoint or fuzzy guessing.
        if not re.fullmatch(r"[\w-]{1,220}", source_slug, flags=re.UNICODE):
            raise ValueError("Use the exact decoded source slug, not a URL or path")
        if source not in {"anime4up", "witanime"}:
            raise ValueError("Unsupported source provider")
        if not note.strip():
            raise ValueError("A verification note is required")
        with self.connect() as db:
            row = db.execute("SELECT id FROM anime_identity WHERE anilist_id=?", (anilist_id,)).fetchone()
            if not row:
                raise ValueError("Load this anime through the catalog before adding a mapping")
            db.execute("""INSERT INTO source_mapping VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(anime_id, source, source_slug) DO UPDATE SET
                verified_at=excluded.verified_at, note=excluded.note""",
                (row[0], source, source_slug, int(time.time()), note.strip()))

    def remove_mapping(self, anilist_id: int, source_slug: str, source: str = "anime4up"):
        with self.connect() as db:
            db.execute("""DELETE FROM source_mapping WHERE anime_id=(
                SELECT id FROM anime_identity WHERE anilist_id=?) AND source=? AND source_slug=?""",
                (anilist_id, source, source_slug))

    def mappings(self, anime_ids: list[str]) -> dict[str, list[dict]]:
        if not anime_ids:
            return {}
        result = {}
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM source_mapping WHERE anime_id IN ({','.join('?' for _ in anime_ids)}) ORDER BY source_slug", anime_ids).fetchall()
        for row in rows:
            result.setdefault(row["anime_id"], []).append({"source": row["source"], "slug": row["source_slug"], "status": "verified", "verifiedAt": row["verified_at"]})
        return result

    def get_cache(self, key: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM catalog_cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        return {"data": json.loads(row["payload"]), "updatedAt": row["updated_at"], "expiresAt": row["expires_at"], "staleUntil": row["stale_until"]}

    def put_cache(self, key: str, data: dict, ttl: int, stale_ttl: int = 72 * 3600) -> dict:
        now = int(time.time())
        record = {"data": data, "updatedAt": now, "expiresAt": now + ttl, "staleUntil": now + ttl + stale_ttl}
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO catalog_cache VALUES (?, ?, ?, ?, ?)",
                       (key, json.dumps(data, ensure_ascii=False), now, record["expiresAt"], record["staleUntil"]))
            db.execute("DELETE FROM catalog_cache WHERE stale_until <= ?", (now,))
            db.execute("""DELETE FROM catalog_cache WHERE key IN (
                SELECT key FROM catalog_cache ORDER BY updated_at DESC, key LIMIT -1 OFFSET ?)""", (self.max_entries,))
        return record

    def delete_cache(self, key: str):
        with self.connect() as db:
            db.execute("DELETE FROM catalog_cache WHERE key=?", (key,))
