import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";
const nativeRequire = createRequire(import.meta.url);

const source = readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function client(responses, env = {}) {
  const calls = [];
  const serverModule = { exports: {} };
  const sandbox = {
    module: serverModule,
    exports: serverModule.exports,
    require(name) {
      if (name === "server-only") return {};
      if (name === "react") return { cache: (fn) => fn };
      if (name === "next/navigation") return nativeRequire(name);
      throw new Error(`Unexpected dependency: ${name}`);
    },
    process: { env }, URL, URLSearchParams, AbortSignal, Error,
    console: { error() {}, warn() {} },
    async fetch(url, options) {
      calls.push({ url: new URL(url), options });
      assert.ok(responses.length, `Unexpected request: ${url}`);
      const response = responses.shift();
      if (response instanceof Error) throw response;
      return response instanceof Response ? response : Response.json(response);
    },
  };
  vm.runInNewContext(compiled, sandbox, { filename: "lib/api.ts" });
  return { api: serverModule.exports, calls };
}

const onePiece = {
  title: "One Piece",
  url: "https://w1.anime4up.rest/anime/one-piece-gfjgfh/",
  image: "https://w1.anime4up.rest/wp-content/uploads/one-piece.jpg",
  kind: "anime",
};
const episode = {
  episode: 1173,
  title: "One Piece الحلقة 1173",
  url: "https://w1.anime4up.rest/episode/one-piece-الحلقة-1173/",
};

test("search accepts Anime4up entries", async () => {
  const { api, calls } = client([{ query: "One Piece", count: 1, cached: false, results: [onePiece] }]);
  const result = await api.searchAnime("One Piece");
  assert.equal(calls[0].url.pathname, "/api/search");
  assert.equal(result.results[0].slug, "one-piece-gfjgfh");
  assert.equal(api.getAnimeHref(result.results[0]), "/anime/one-piece-gfjgfh");
});

test("image helper proxies remote posters through NOVA", () => {
  const { api } = client([]);
  assert.equal(
    api.getImageSrc(onePiece.image),
    `/api/media/image?url=${encodeURIComponent(onePiece.image)}`,
  );
  assert.equal(api.getImageSrc(null), null);
});

test("anime detail uses the exact source slug endpoint", async () => {
  const { api, calls } = client([{ cached: false, anime: onePiece }]);
  const result = await api.getAnime("one-piece-gfjgfh");
  assert.equal(result.title, "One Piece");
  assert.equal(calls[0].url.pathname, "/api/anime");
  assert.equal(calls[0].url.searchParams.get("slug"), "one-piece-gfjgfh");
});

test("episodes preserve the public Anime4up episode URL", async () => {
  const { api, calls } = client([
    { cached: false, anime: onePiece },
    { url: onePiece.url, count: 1, cached: false, episodes: [episode] },
  ]);
  const result = await api.getAnimeEpisodes("one-piece-gfjgfh");
  assert.equal(result.episodes[0].episode, 1173);
  assert.equal(calls[1].url.pathname, "/api/episodes");
  assert.equal(calls[1].url.searchParams.get("url"), onePiece.url);
});

test("server and player requests use the exact scraped episode URL", async () => {
  const server = { name: "megamax", id: "0", attributes: {}, embed_url: "https://share4max.com/e/abc" };
  const responses = [
    { cached: false, anime: onePiece },
    { url: onePiece.url, count: 1, cached: false, episodes: [episode] },
    { url: episode.url, count: 1, cached: false, servers: [server] },
  ];
  const first = client(responses);
  const servers = await first.api.getEpisodeServers("one-piece-gfjgfh", 1173);
  assert.equal(servers.servers[0].embedUrl, "https://share4max.com/e/abc");

  const second = client([
    { cached: false, anime: onePiece },
    { url: onePiece.url, count: 1, cached: false, episodes: [episode] },
    { url: episode.url, server: "megamax", server_id: "0", embed_url: "https://share4max.com/e/abc", sandbox: null, referrer_policy: "origin", allow: null },
  ]);
  const player = await second.api.getEpisodePlayer("one-piece-gfjgfh", 1173, "megamax", "0");
  assert.equal(player.embedUrl, "https://share4max.com/e/abc");
  assert.equal(second.calls.at(-1).url.pathname, "/api/player");
});

test("provider-aware catalog server requests preserve a public WitAnime episode URL", async () => {
  const witEpisode = "https://witanime.site/watch/one-piece/7/";
  const { api, calls } = client([{
    provider: "witanime", url: witEpisode, count: 1,
    servers: [{ name: "Wit player", id: "1", attributes: {}, embed_url: "https://player.example/e/7" }],
  }]);
  const result = await api.getCatalogEpisodeServers("witanime", witEpisode);
  assert.equal(result.provider, "witanime");
  assert.equal(result.servers[0].embedUrl, "https://player.example/e/7");
  assert.equal(calls[0].url.pathname, "/api/catalog/episode-servers");
  assert.equal(calls[0].url.searchParams.get("provider"), "witanime");
  await assert.rejects(api.getCatalogEpisodeServers("witanime", episode.url));
});

test("home feed parses latest and featured anime", async () => {
  const { api } = client([{
    cached: false,
    featured: [onePiece],
    pinned: [onePiece],
    latest_anime: [onePiece],
    latest_episodes: [{ ...episode, anime: onePiece }],
  }]);
  const home = await api.getHomeFeed();
  assert.equal(home.featured[0].slug, "one-piece-gfjgfh");
  assert.equal(home.latestEpisodes[0].episode, 1173);
});

test("backend connection failure is an explicit retryable service error", async () => {
  const { api } = client([new Error("fetch failed")]);
  await assert.rejects(api.getAnime("sousou-no-frieren-jfgt"), error => error instanceof api.ApiError && error.status === 503);
});

test("download requests reuse the selected episode URL and preserve public host links", async () => {
  const { api, calls } = client([
    { anime: onePiece }, { url: onePiece.url, episodes: [episode] },
    { url: episode.url, downloads: [{ url: "https://mega.nz/#!file!public-key", server: "mega.nz", quality: "FHD 1080p", language: "مترجم" }] },
  ]);
  const result = await api.getEpisodeDownloads("one-piece-gfjgfh", 1173);
  assert.equal(calls.at(-1).url.pathname, "/api/downloads");
  assert.equal(calls.at(-1).url.searchParams.get("url"), new URL(episode.url).href);
  assert.equal(result.downloads[0].url, "https://mega.nz/#!file!public-key");
  assert.equal(result.downloads[0].quality, "FHD 1080p");
});

test("downloads cannot be attached to a different episode or unsafe link", async () => {
  for (const response of [
    { url: "https://w1.anime4up.rest/episode/other/", downloads: [] },
    { url: episode.url, downloads: [{ url: "javascript:alert(1)", server: "Invalid" }] },
  ]) {
    const { api } = client([{ anime: onePiece }, { url: onePiece.url, episodes: [episode] }, response]);
    await assert.rejects(api.getEpisodeDownloads("one-piece-gfjgfh", 1173));
  }
});
