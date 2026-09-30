import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function load(path, imports = {}, globals = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const compiledModule = { exports: {} };
  vm.runInNewContext(code, { module: compiledModule, exports: compiledModule.exports, URL, URLSearchParams, AbortSignal, Response, Error,
    require(name) {
      if (name in imports) return imports[name];
      throw new Error(`Unexpected dependency: ${name}`);
    }, ...globals }, { filename: path });
  return compiledModule.exports;
}
const model = load("../lib/catalog-model.ts");
const artwork = load("../lib/artwork.ts");
const episodes = load("../lib/episode-model.ts");
const streamServers = load("../lib/stream-server-merge.ts");
const anime = {
  id: "nova_example", slug: "one-piece-21", providerIds: { anilist: 21, mal: 21 },
  title: "One Piece", alternativeTitles: ["ONE PIECE"], description: "An adventure.", descriptionLanguage: "en",
  image: "https://s4.anilist.co/file/anilistcdn/media/anime/cover/example.jpg", banner: null, accentColor: "#abcdef",
  score: { value: 88, scale: 100, provider: "anilist" }, genres: ["Adventure"], year: 1999, season: "fall",
  status: "releasing", type: "tv", episodeCount: null, runtime: 24, country: "JP", studios: ["Toei"],
  trailer: null, popularity: 100, metadataUpdatedAt: 123, availability: "unknown", availableEpisodeCount: null,
  sourceMappings: [],
};
const page = { items: [anime], page: 1, perPage: 24, hasNextPage: true };
const cache = { status: "fresh", updatedAt: 123, expiresAt: 456, staleUntil: 789 };
const envelope = (data) => ({ data, cache });
function client(responses) {
  const calls = [];
  const api = load("../lib/catalog.ts", {
    "server-only": {}, "react": { cache: (fn) => fn },
    "next/navigation": { unstable_rethrow() {} }, "./catalog-model": model,
  }, {
    process: { env: { API_BASE_URL: "http://backend.test:8000" } },
    async fetch(url, options) {
      calls.push({ url, options });
      assert.ok(responses.length, `Unexpected request: ${url}`);
      const response = responses.shift();
      return response instanceof Response ? response : Response.json(response);
    },
  });
  return { api, calls };
}

test("Home, Search and Discover use only catalog routes", async () => {
  const { api, calls } = client([envelope({ featured: [anime], topRated: [anime], discover: page }), envelope(page), envelope({ ...page, page: 2 })]);
  await api.getCatalogHome();
  await api.getCatalogPage(1, "One Piece");
  await api.getCatalogPage(2);
  assert.deepEqual(calls.map((call) => call.url.pathname), ["/api/catalog/home", "/api/catalog/search", "/api/catalog/discover"]);
  assert.equal(calls[1].url.searchParams.get("q"), "One Piece");
  assert.equal(calls[2].url.searchParams.get("page"), "2");
  assert.equal(calls[2].url.searchParams.get("per_page"), "24");
  assert.ok(calls.every(({ options }) => options.cache === "no-store" && options.signal));
});

test("Catalog detail uses canonical slug without invoking the source resolver", async () => {
  const { api, calls } = client([envelope(anime)]);
  const response = await api.getCatalogAnime(anime.slug);
  assert.equal(calls[0].url.pathname, "/api/catalog/anime");
  assert.equal(calls[0].url.searchParams.get("slug"), "one-piece-21");
  assert.equal(model.catalogHref(response.data), "/anime/catalog/one-piece-21");
  assert.equal(response.data.availability, "unknown");
});

test("Provider outage never falls back to source scraping", async () => {
  const { api, calls } = client([new Response("Unavailable", { status: 503 })]);
  await assert.rejects(api.getCatalogHome(), (error) => error instanceof api.CatalogError && error.status === 503);
  assert.equal(calls.length, 1);
});

test("Unknown catalog title preserves 404 without guessing a source slug", async () => {
  const { api, calls } = client([new Response("Missing", { status: 404 })]);
  await assert.rejects(api.getCatalogAnime("unknown-123"), (error) => error.status === 404);
  assert.equal(calls.length, 1);
});

test("Invalid search, slug and pagination make zero backend calls", () => {
  const { api, calls } = client([]);
  for (const value of [0, -1, 1.5, 101, NaN]) assert.throws(() => api.getCatalogPage(value));
  for (const value of [" ", "x", "x".repeat(101)]) assert.throws(() => api.getCatalogPage(1, value));
  assert.throws(() => api.getCatalogAnime("../watch"));
  assert.equal(calls.length, 0);
});

test("Scores retain attribution; unknown counts and scores are not fabricated", () => {
  const result = model.parseAnime(anime);
  assert.equal(model.scoreText(result.score), "8.8");
  assert.equal(result.score.provider, "anilist");
  assert.equal(result.episodeCount, null);
  assert.equal(model.scoreText(null), null);
  assert.equal(model.scoreText({ value: 0, scale: 100, provider: "anilist" }), "0.0");
  assert.throws(() => model.parseAnime({ ...anime, score: { value: 200, scale: 100, provider: "anilist" } }));
});

test("Artwork is constrained to the configured CDN and accents to hex colors", () => {
  const result = model.parseAnime({ ...anime, image: "https://untrusted.test/poster.jpg", banner: "javascript:alert(1)", accentColor: "red; background:url(x)" });
  assert.equal(result.image, null);
  assert.equal(result.banner, null);
  assert.equal(result.accentColor, null);
});

test("Artwork preserves season identity and uses poster-first / backdrop-first fallbacks", () => {
  const art = { seasonPoster: "season-cover", animePoster: "anime-cover", seasonBackdrop: "season-wide", animeBackdrop: "anime-wide" };
  assert.equal(artwork.artworkSources(art).join(","), "season-cover,anime-cover,season-wide,anime-wide");
  assert.equal(artwork.artworkSources(art, "backdrop").join(","), "season-wide,anime-wide,season-cover,anime-cover");
  assert.equal(artwork.artworkSources({ ...art, seasonPoster: null }).join(","), "anime-cover,season-wide,anime-wide");
  assert.equal(artwork.artworkSources({ image: "current-season", animePoster: "parent", banner: "current-backdrop" })[0], "current-season");
  assert.equal(artwork.artworkSources({}).length, 0);
  const parsed = model.parseAnime({ ...anime, seasonPoster: anime.image, animePoster: "https://untrusted.test/cover.jpg" });
  assert.equal(parsed.seasonPoster, anime.image);
  assert.equal(parsed.animePoster, null);
});

test("Episode source references remain tied to their season and fractional episode", () => {
  const source = { provider: "anime4up", sourceSlug: "season-two", episodeUrl: "https://w1.anime4up.rest/episode/season-two-12.5/" };
  const data = { sourceSlug: "season-two", sourceTitle: "Season 2", verified: true, items: [{ episode: 12.5, title: "Special", sources: [source] }], page: 1, offset: 0, totalPages: 1, next: null };
  const result = episodes.parseEpisodes(data, "season-two");
  assert.equal(result.items[0].sources[0].episodeUrl, source.episodeUrl);
  assert.equal(episodes.episodeHref(result.sourceSlug, result.items[0].episode), "/watch/season-two/12.5");
  assert.throws(() => episodes.parseEpisodes(data, "season-one"));
  for (const invalid of [{ ...source, sourceSlug: "season-one" }, { ...source, episodeUrl: "https://untrusted.test/video.mp4" }, { ...source, episodeUrl: "https://w1.anime4up.rest/episode/special/?token=temporary" }]) {
    assert.throws(() => episodes.parseEpisodes({ ...data, items: [{ ...data.items[0], sources: [invalid] }] }));
  }
  assert.throws(() => episodes.parseEpisodes({ ...data, items: [data.items[0], data.items[0]] }));
  assert.equal(episodes.parseEpisodes({ ...data, items: [{ episode: 1, title: "Cached episode" }] }).items[0].sources.length, 0);
});

test("Episode contracts distinguish public-provider unavailability from an empty list", () => {
  const unavailable = episodes.parseSources({
    sources: [], selectedSource: null,
    availability: {
      anime4up: { status: "unavailable", last_status: 403 },
      witanime: { status: "unavailable", last_status: 403 },
    },
  });
  assert.equal(episodes.externalProvidersUnavailable(unavailable.availability), true);
  const roundTrippedSources = episodes.parseSources(unavailable);
  assert.equal(roundTrippedSources.availability.anime4up.lastStatus, 403);

  const blocked = episodes.parseEpisodes({
    items: [], sources: [], selectedSource: null, page: 1, offset: 0, totalPages: 1, next: null,
    externalUnavailable: true,
    availability: {
      anime4up: { status: "unavailable", last_status: 403 },
      witanime: { status: "unavailable", last_status: 403 },
    },
  });
  assert.equal(blocked.externalUnavailable, true);
  assert.equal(blocked.items.length, 0);
  assert.equal(episodes.parseEpisodes(blocked).externalUnavailable, true);

  const empty = episodes.parseEpisodes({
    sourceSlug: "one-piece", sourceProvider: "anime4up", sourceTitle: "One Piece", verified: true,
    items: [], page: 1, offset: 0, totalPages: 1, next: null,
    availability: {
      anime4up: { status: "available", last_status: 200 },
      witanime: { status: "unknown", last_status: null },
    },
  }, "one-piece");
  assert.equal(empty.externalUnavailable, false);
  assert.equal(empty.items.length, 0);
});

test("Source defaults use provider and slug as one identity", () => {
  const sharedSlug = "mushoku-tensei-iii-isekai-ittara-honki-dasu";
  const payload = {
    sources: [
      { provider: "anime4up", slug: sharedSlug, title: "Mushoku Tensei III", verified: true },
      { provider: "witanime", slug: sharedSlug, title: "Mushoku Tensei III", verified: true },
    ],
    selectedSource: sharedSlug,
    availability: {
      anime4up: { status: "available", last_status: 200 },
      witanime: { status: "unknown", last_status: null },
    },
  };
  assert.throws(() => episodes.parseSources(payload), /Ambiguous default source identity/);
  const parsed = episodes.parseSources({ ...payload, selectedProvider: "anime4up" });
  assert.equal(parsed.selectedSource, sharedSlug);
  assert.equal(parsed.selectedProvider, "anime4up");
});

test("WitAnime references retain provider identity through the catalog watch link", () => {
  const source = { provider: "witanime", sourceSlug: "one-piece", episodeUrl: "https://witanime.site/watch/one-piece/7/" };
  const data = { sourceSlug: "one-piece", sourceProvider: "witanime", sourceTitle: "One Piece", verified: true, items: [{ episode: 7, title: "الحلقة 7", sources: [source] }], page: 1, offset: 0, totalPages: 1, next: null };
  const result = episodes.parseEpisodes(data, { provider: "witanime", slug: "one-piece", title: "One Piece", verified: true });
  assert.equal(result.sourceProvider, "witanime");
  assert.equal(
    episodes.catalogEpisodeHref("one-piece-21", 7, result.items[0].sources[0]),
    "/watch/one-piece-21/7?provider=witanime&source=one-piece&episode_url=https%3A%2F%2Fwitanime.site%2Fwatch%2Fone-piece%2F7%2F",
  );
  assert.throws(() => episodes.parseEpisodes({ ...data, sourceProvider: "anime4up" }));
  assert.throws(() => episodes.parseEpisodes({ ...data, items: [{ ...data.items[0], sources: [source, source] }] }));
});

test("An intentional WitAnime fallback satisfies the original Anime4Up request", () => {
  const requested = { provider: "anime4up", slug: "mushoku-tensei-iii-isekai-ittara-honki-dasu", title: "Mushoku Tensei Season 3", verified: true };
  const fallback = {
    sourceSlug: "mushoku-tensei-iii-isekai-ittara-honki-dasu", sourceProvider: "witanime",
    sourceTitle: "Mushoku Tensei III", verified: true,
    requestedSource: { provider: "anime4up", sourceSlug: requested.slug },
    items: [{ episode: 1, title: "الحلقة 1", sources: [{
      provider: "witanime", sourceSlug: requested.slug,
      episodeUrl: "https://witanime.site/watch/mushoku-tensei-iii-isekai-ittara-honki-dasu/1",
    }] }],
    page: 1, offset: 0, totalPages: 1, next: null,
    availability: {
      anime4up: { status: "unavailable", last_status: 403 },
      witanime: { status: "available", last_status: 200 },
    },
    externalUnavailable: false,
  };
  const parsed = episodes.parseEpisodes(fallback, requested);
  assert.equal(parsed.items.length, 1);
  assert.equal(parsed.sourceProvider, "witanime");
  assert.equal(
    episodes.catalogEpisodeHref("mushoku-tensei-jobless-reincarnation-season-3-178789", 1, parsed.items[0].sources[0], parsed.requestedSource),
    "/watch/mushoku-tensei-jobless-reincarnation-season-3-178789/1?provider=witanime&source=mushoku-tensei-iii-isekai-ittara-honki-dasu&episode_url=https%3A%2F%2Fwitanime.site%2Fwatch%2Fmushoku-tensei-iii-isekai-ittara-honki-dasu%2F1&requested_provider=anime4up&requested_source=mushoku-tensei-iii-isekai-ittara-honki-dasu",
  );
  assert.throws(() => episodes.parseEpisodes({ ...fallback, requestedSource: undefined }, requested));
  // The Next route and browser intentionally validate this response twice.
  assert.equal(episodes.parseEpisodes(parsed, requested).items.length, 1);
});

test("Invalid mapping paths cannot become source links", () => {
  assert.throws(() => model.parseAnime({ ...anime, sourceMappings: [{ source: "anime4up", slug: "../episode/x", status: "verified", verifiedAt: 1 }] }));
  const result = model.parseAnime({ ...anime, sourceMappings: [{ source: "anime4up", slug: "one-piece-الحلقة", status: "verified", verifiedAt: 1 }] });
  assert.equal(result.availability, "unknown");
  assert.equal(result.sourceMappings.length, 1);
});

test("Oversized or malformed pages fail before rendering", () => {
  assert.throws(() => model.parsePage({ ...page, perPage: 1000 }));
  assert.throws(() => model.parsePage({ ...page, perPage: 1, items: [anime, anime] }));
  assert.throws(() => model.parsePage({ ...page, hasNextPage: "yes" }));
});

test("Stale state survives the frontend adapter", async () => {
  const { api } = client([{ data: page, cache: { ...cache, status: "stale" } }]);
  assert.equal((await api.getCatalogPage()).cache.status, "stale");
});

test("Load More endpoint uses fixed catalog path and rejects excessive pagination", async () => {
  const { api, calls } = client([envelope({ ...page, page: 2 })]);
  const route = load("../app/api/catalog/discover/route.ts", { "@/lib/catalog": api, "next/navigation": { unstable_rethrow() {} } });
  const response = await route.GET(new Request("http://nova.test/api/catalog/discover?page=2&url=https://untrusted.test"));
  assert.equal(response.status, 200);
  assert.equal(calls[0].url.pathname, "/api/catalog/discover");
  assert.equal(calls[0].url.searchParams.has("url"), false);
  const invalid = await route.GET(new Request("http://nova.test/api/catalog/discover?page=999"));
  assert.equal(invalid.status, 422);
  assert.equal(calls.length, 1);
});

test("Fansub servers are first, then Anime4Up, then WitAnime; public URLs deduplicate", () => {
  const fansub = [
    { source: "asahi", host: "dl.dropboxusercontent.com", type: "direct", url: "https://video.test/a.mp4", tested: true, working: true },
    { source: "omarhidan", host: "google-drive", type: "iframe", url: "https://drive.google.com/file/d/abc/preview", tested: true, working: true },
  ];
  const legacy = [
    { name: "Dropbox mirror", id: "1", attributes: {}, embedUrl: "https://video.test/a.mp4", type: "direct" },
    { name: "Vidmoly", id: "2", attributes: {}, embedUrl: "https://vidmoly.test/e/abc", type: "iframe" },
    { name: "Vidmoly", id: "3", attributes: {}, embedUrl: "https://vidmoly.test/e/def", type: "iframe" },
  ];
  const witanime = [
    { name: "same display name", id: "w1", attributes: {}, embedUrl: "https://vidmoly.test/e/abc#ignored", type: "iframe" },
    { name: "Wit player", id: "w2", attributes: {}, embedUrl: "https://streamwish.test/e/xyz", type: "iframe" },
  ];
  const merged = streamServers.mergeStreamServers(fansub, legacy, witanime);
  assert.equal(merged.map((server) => server.source).join(","), "fansub,fansub,legacy,legacy,witanime");
  assert.equal(merged[0].type, "direct");
  assert.equal(merged[2].server.id, "2");
  assert.equal(streamServers.selectStreamServer(merged, "legacy:Vidmoly:3").server.id, "3");
  assert.equal(streamServers.selectStreamServer(merged, "Vidmoly").server.id, "2");
});

test("Images remain direct instead of using Next's optimizer", () => {
  const config = readFileSync(new URL("../next.config.ts", import.meta.url), "utf8");
  assert.match(config, /images:\s*\{[\s\S]*?unoptimized:\s*true/);
});
