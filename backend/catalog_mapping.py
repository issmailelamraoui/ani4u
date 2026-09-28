"""Local administrative mapping command. Makes no network requests."""

import argparse

from catalog_store import CatalogStore, database_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["set", "remove"])
    parser.add_argument("anilist_id", type=int)
    parser.add_argument("source_slug", help="Exact decoded Anime4up slug, without /anime/")
    parser.add_argument("--note", default="", help="Required for set: evidence used to verify this title mapping")
    args = parser.parse_args()
    store = CatalogStore(database_path())
    store.initialize()
    try:
        if args.action == "set":
            store.set_mapping(args.anilist_id, args.source_slug, args.note)
        else:
            store.remove_mapping(args.anilist_id, args.source_slug)
    except ValueError as error:
        parser.error(str(error))
    print("Mapping updated. Playback routes are unchanged.")


if __name__ == "__main__":
    main()
