import sqlite3
import tempfile
import unittest
from pathlib import Path

from catalog_store import CatalogStore


class CatalogStoreMigrationTests(unittest.TestCase):
    def test_legacy_anime4up_rows_survive_provider_migration_with_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            legacy = sqlite3.connect(path)
            try:
                db = legacy
                db.executescript("""
                    CREATE TABLE anime_identity (
                        id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE,
                        anilist_id INTEGER NOT NULL UNIQUE, mal_id INTEGER, created_at INTEGER NOT NULL
                    );
                    CREATE TABLE source_mapping (
                        anime_id TEXT NOT NULL REFERENCES anime_identity(id),
                        source TEXT NOT NULL CHECK(source = 'anime4up'),
                        source_slug TEXT NOT NULL, verified_at INTEGER NOT NULL, note TEXT NOT NULL,
                        PRIMARY KEY (anime_id, source, source_slug)
                    );
                    INSERT INTO anime_identity VALUES ('nova_21', 'one-piece-21', 21, 21, 1);
                    INSERT INTO source_mapping VALUES ('nova_21', 'anime4up', 'one-piece', 1, 'Legacy mapping');
                """)
                legacy.commit()
            finally:
                legacy.close()

            store = CatalogStore(path)
            store.initialize()
            self.assertEqual(store.mappings(["nova_21"])["nova_21"][0]["source"], "anime4up")
            store.set_mapping(21, "one-piece-wita", "Public HTTP mapping", "witanime")
            self.assertEqual(
                {item["source"] for item in store.mappings(["nova_21"])["nova_21"]},
                {"anime4up", "witanime"},
            )
            backups = list(Path(directory).glob("catalog.sqlite3.pre-provider-migration-*.bak"))
            self.assertEqual(len(backups), 1)
            backup = sqlite3.connect(backups[0])
            try:
                self.assertEqual(backup.execute("SELECT source, source_slug FROM source_mapping").fetchone(), ("anime4up", "one-piece"))
            finally:
                backup.close()


if __name__ == "__main__":
    unittest.main()
