"""Catalog orchestration: metadata only, with persistent cache and request coalescing."""

import asyncio
import copy
import json
import time

from anilist_provider import AnimeNotFound, ProviderError, normalize
from catalog_models import AnimePage, CatalogHome


class CatalogService:
    def __init__(self, store, provider):
        self.store = store
        self.provider = provider
        self.inflight = {}

    async def close(self):
        tasks = list(self.inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _normalize(self, media):
        identities = await asyncio.to_thread(self.store.identities, media)
        now = int(time.time())
        return [normalize(item, identities[item["id"]], now) for item in media]

    async def _page(self, raw):
        info = raw["pageInfo"]
        return AnimePage(items=await self._normalize(raw["media"]), page=info["currentPage"], perPage=info["perPage"], hasNextPage=info["hasNextPage"])

    async def _refresh(self, key, loader):
        # Recheck after coalescing; another caller may just have filled the cache.
        record = await asyncio.to_thread(self.store.get_cache, key)
        if record and record["expiresAt"] > time.time():
            return record, "fresh"
        try:
            # Covers time waiting for provider pacing, as well as upstream I/O.
            async with asyncio.timeout(15):
                data, ttl = await loader()
            record = await asyncio.to_thread(self.store.put_cache, key, data, ttl)
            return record, "miss"
        except AnimeNotFound:
            # A definitive removal must not resurrect old detail data.
            await asyncio.to_thread(self.store.delete_cache, key)
            raise
        except (ProviderError, TimeoutError, KeyError, TypeError, ValueError) as error:
            if record and record["staleUntil"] > time.time():
                return record, "stale"
            raise ProviderError("Catalog metadata is temporarily unavailable") from error

    async def _cached(self, key, loader):
        key = "v1:" + key
        record = await asyncio.to_thread(self.store.get_cache, key)
        status = "fresh"
        if not record or record["expiresAt"] <= time.time():
            task = self.inflight.get(key)
            if task is None:
                # Bound the queue rather than accumulating work during a provider outage.
                if len(self.inflight) >= 32:
                    if record and record["staleUntil"] > time.time():
                        return await self._response(record, "stale")
                    raise ProviderError("Catalog request queue is full")
                task = asyncio.create_task(self._refresh(key, loader))
                self.inflight[key] = task

                def cleanup(done):
                    self.inflight.pop(key, None)
                    if not done.cancelled():
                        done.exception()  # Consume errors even if every requester disconnected.

                task.add_done_callback(cleanup)
            record, status = await asyncio.shield(task)
        return await self._response(record, status)

    async def _response(self, record, status):
        data = copy.deepcopy(record["data"])
        anime = []

        def collect(value):
            if isinstance(value, dict):
                if "providerIds" in value:
                    anime.append(value)
                else:
                    for child in value.values():
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(data)
        mappings = await asyncio.to_thread(self.store.mappings, list({a["id"] for a in anime}))
        for item in anime:
            item["sourceMappings"] = mappings.get(item["id"], [])
        return {"data": data, "cache": {"status": status, **{k: record[k] for k in ("updatedAt", "expiresAt", "staleUntil")}}}

    async def home(self):
        async def load():
            raw = await self.provider.home()
            home = CatalogHome(featured=await self._normalize(raw["featured"]["media"]), topRated=await self._normalize(raw["topRated"]["media"]), discover=await self._page(raw["discover"]))
            return home.model_dump(), 900
        return await self._cached("home", load)

    async def page(self, page=1, per_page=24, search=None):
        search = " ".join(search.split()) if search else None
        key = json.dumps(["page", page, per_page, search], ensure_ascii=False)

        async def load():
            result = await self._page(await self.provider.page(page, per_page, search))
            return result.model_dump(), 600 if search else 1800
        return await self._cached(key, load)

    async def detail(self, anilist_id):
        async def load():
            anime = (await self._normalize([await self.provider.detail(anilist_id)]))[0]
            return anime.model_dump(), 86400 if anime.status == "finished" else 3600
        return await self._cached(f"anime:{anilist_id}", load)

    async def detail_by_slug(self, slug):
        anilist_id = await asyncio.to_thread(self.store.anilist_id_for_slug, slug)
        if anilist_id is None:
            raise AnimeNotFound()
        return await self.detail(anilist_id)
