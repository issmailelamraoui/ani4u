import "server-only";

import { cache } from "react";
import { unstable_rethrow } from "next/navigation";

export type Anime = {
  title: string;
  url: string;
  image: string | null;
  slug: string;
  kind: "anime" | "movie" | "special";
};
export type SearchResponse = { query: string; count: number; cached: boolean; results: Anime[] };
export type Episode = { episode: number; title: string; url: string };
export type EpisodesResponse = { url: string; count: number; cached: boolean; episodes: Episode[] };
export type EpisodeServer = {
  name: string;
  id: string | null;
  attributes: Record<string, string>;
  embedUrl: string | null;
};
export type ServersResponse = { url: string; count: number; cached: boolean; servers: EpisodeServer[] };
export type EpisodeProvider = "anime4up" | "witanime";
export type ProviderServersResponse = { provider: EpisodeProvider; url: string; count: number; servers: EpisodeServer[] };
export type EpisodeDownload = { url: string; server: string; quality: string | null; language: string | null };
export type DownloadsResponse = { url: string; downloads: EpisodeDownload[] };
export type PlayerResponse = {
  url: string;
  server: string;
  serverId: string | null;
  embedUrl: string;
  sandbox: string | null;
  referrerPolicy: string | null;
  allow: string | null;
};
export type LatestEpisode = {
  episode: number;
  title: string;
  url: string;
  anime: Anime;
};
export type HomeFeed = {
  cached: boolean;
  featured: Anime[];
  pinned: Anime[];
  latestAnime: Anime[];
  latestEpisodes: LatestEpisode[];
};

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly publicMessage = "تعذّر تحميل بيانات الأنمي الآن. حاول مرة أخرى بعد قليل.",
    public readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ApiError";
  }
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected a JSON object");
  return value as Record<string, unknown>;
}

function string(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`Missing or invalid ${field}`);
  return value;
}

function sourceHost(hostname: string) {
  const host = hostname.toLowerCase();
  return host === "anime4up.rest" || host.endsWith(".anime4up.rest");
}

function witanimeHost(hostname: string) {
  const host = hostname.toLowerCase();
  return host === "witanime.site" || host.endsWith(".witanime.site");
}

function sourceUrl(value: unknown, paths: string[]): URL {
  const url = new URL(string(value, "source URL"));
  if (url.protocol !== "https:" || !sourceHost(url.hostname)
    || !paths.some((path) => url.pathname.startsWith(path))) {
    throw new Error(`Unsupported source URL: ${url.href}`);
  }
  return url;
}

function providerEpisodeUrl(provider: EpisodeProvider, value: string): URL {
  const url = new URL(value);
  const valid = provider === "anime4up"
    ? sourceHost(url.hostname) && url.pathname.startsWith("/episode/")
    : witanimeHost(url.hostname) && url.pathname.startsWith("/watch/");
  if (url.protocol !== "https:" || url.username || url.password || url.port || url.search || url.hash || !valid) {
    throw new Error(`Unsupported ${provider} episode URL: ${url.href}`);
  }
  return url;
}

function imageUrl(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  const url = new URL(string(value, "image"));
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error(`Unsupported image URL: ${url.href}`);
  return url.href;
}

export function getImageSrc(image: string | null): string | null {
  if (!image) return null;
  return `/api/media/image?url=${encodeURIComponent(image)}`;
}

export function getSlug(url: string): string {
  return decodeURIComponent(new URL(url).pathname.split("/").filter(Boolean).at(-1) || "");
}

export function getAnimeHref(anime: Pick<Anime, "slug">): string {
  return `/anime/${encodeURIComponent(anime.slug)}`;
}

function parseAnime(value: unknown): Anime {
  const data = object(value);
  const url = sourceUrl(data.url, ["/anime/"]);
  const kind = data.kind === "movie" ? "movie" : "anime";
  return {
    title: string(data.title, "title"),
    url: url.href,
    image: imageUrl(data.image),
    slug: getSlug(url.href),
    kind,
  };
}

function parseList<T>(data: Record<string, unknown>, key: string, parse: (v: unknown) => T): T[] {
  const values = data[key];
  if (!Array.isArray(values)) throw new Error(`Invalid ${key} array`);
  return values.map(parse);
}

async function request<T>(path: string, params: Record<string, string>, parse: (v: unknown) => T): Promise<T> {
  let endpoint = path;
  try {
    const base = (process.env.ANI4U_EXTERNAL_BACKEND_URL || process.env.ANI4U_BACKEND_URL || process.env.API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
    const url = new URL(`${base}${path}`);
    url.search = new URLSearchParams(params).toString();
    endpoint = url.href;
    const configuredTimeout = Number(process.env.API_TIMEOUT_MS || 120_000);
    const timeout = Number.isFinite(configuredTimeout) && configuredTimeout > 0 ? configuredTimeout : 120_000;
    const response = await fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(timeout),
    }).catch((cause: unknown) => {
      throw new ApiError(`Cannot reach anime backend at ${url.origin}`,
        "تعذّر الاتصال بخدمة الأنمي الآن. حاول مرة أخرى بعد قليل.", 503, { cause });
    });
    if (!response.ok) {
      const detail = (await response.text()).slice(0, 500);
      throw new ApiError(
        `GET ${endpoint}: HTTP ${response.status}: ${detail}`,
        response.status >= 500
          ? "مصدر الأنمي غير متاح مؤقتاً. حاول إعادة التحميل بعد قليل."
          : response.status === 404
            ? "لم نعثر على هذا الأنمي أو الحلقة."
            : "تعذّر تنفيذ طلب الأنمي. حاول مرة أخرى.",
        response.status,
      );
    }
    return parse(await response.json());
  } catch (cause) {
    unstable_rethrow(cause);
    const error = cause instanceof ApiError ? cause : new ApiError(
      `GET ${endpoint} failed: ${cause instanceof Error ? cause.message : String(cause)}`,
      "تعذّر الاتصال بخدمة الأنمي أو قراءة بياناتها. تأكد من تشغيل الـbackend ثم أعد المحاولة.",
      undefined,
      { cause },
    );
    // Expected service outages are rendered by the page's retry state.
    // Keep a server diagnostic without triggering Next's console-error overlay.
    if (cause instanceof ApiError) console.warn("[Anime API]", error.message);
    else console.error("[Anime API]", error.message, error.cause || "");
    throw error;
  }
}

export const getHomeFeed = cache(async (): Promise<HomeFeed> => request("/api/home", {}, (value) => {
  const data = object(value);
  const featured = parseList(data, "featured", parseAnime);
  const pinned = parseList(data, "pinned", parseAnime);
  const latestAnime = parseList(data, "latest_anime", parseAnime);
  const latestEpisodes = parseList(data, "latest_episodes", (value): LatestEpisode => {
    const item = object(value);
    if (typeof item.episode !== "number" || !Number.isFinite(item.episode)) throw new Error("Invalid episode number");
    return {
      episode: item.episode,
      title: string(item.title, "latest episode title"),
      url: sourceUrl(item.url, ["/episode/"]).href,
      anime: parseAnime(item.anime),
    };
  });
  return { cached: data.cached === true, featured, pinned, latestAnime, latestEpisodes };
}));

export const searchAnime = cache(async (query: string): Promise<SearchResponse> => {
  const q = query.trim();
  if (q.length < 2 || q.length > 100) {
    throw new ApiError("Search must contain 2–100 characters", "اكتب اسم أنمي من حرفين إلى 100 حرف.", 400);
  }
  return request("/api/search", { q }, (value) => {
    const data = object(value);
    const results = parseList(data, "results", parseAnime);
    return { query: string(data.query, "query"), count: results.length, cached: data.cached === true, results };
  });
});

export const getAnime = cache(async (slug: string): Promise<Anime | null> => {
  if (!slug.trim() || slug.length > 220 || slug.includes("/") || slug.includes("\\") || slug.includes("..")) return null;
  try {
    return await request("/api/anime", { slug }, (value) => parseAnime(object(value).anime));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
});

export async function getRelatedAnime(anime: Anime): Promise<Anime[]> {
  const query = anime.title.split(/[!:]/)[0].trim().split(/\s+/).slice(0, 3).join(" ");
  if (query.length < 2) return [];
  const result = await searchAnime(query);
  const seen = new Set([anime.slug]);
  return result.results.filter((entry) => {
    if (seen.has(entry.slug)) return false;
    seen.add(entry.slug);
    return true;
  }).slice(0, 10);
}

export const getAnimeEpisodes = cache(async (slug: string): Promise<EpisodesResponse> => {
  const anime = await getAnime(slug);
  if (!anime) throw new ApiError(`Anime not found: ${slug}`, "لم نعثر على هذا الأنمي.", 404);
  return request("/api/episodes", { url: anime.url }, (value) => {
    const data = object(value);
    const episodes = parseList(data, "episodes", (value): Episode => {
      const item = object(value);
      if (typeof item.episode !== "number" || !Number.isFinite(item.episode) || item.episode < 0) throw new Error("Invalid episode number");
      return {
        episode: Number(item.episode),
        title: string(item.title, "episode title"),
        url: sourceUrl(item.url, ["/episode/"]).href,
      };
    });
    return { url: string(data.url, "url"), count: episodes.length, cached: data.cached === true, episodes };
  });
});

export async function getEpisodeServers(slug: string, episode: number): Promise<ServersResponse> {
  const data = await getAnimeEpisodes(slug);
  const selected = data.episodes.find((item) => item.episode === episode);
  if (!selected) throw new ApiError(`Episode not found: ${slug}/${episode}`, "هذه الحلقة غير متاحة.", 404);
  return request("/api/servers", { url: selected.url }, (value) => {
    const data = object(value);
    const servers = parseList(data, "servers", (value): EpisodeServer => {
      const item = object(value);
      const attributes = object(item.attributes ?? {});
      if (Object.values(attributes).some((v) => typeof v !== "string")) throw new Error("Invalid server attributes");
      let embedUrl: string | null = null;
      if (item.embed_url != null && item.embed_url !== "") {
        const embed = new URL(string(item.embed_url, "server embed URL"));
        if (!['http:', 'https:'].includes(embed.protocol)) throw new Error("Unsupported server embed URL");
        embedUrl = embed.href;
      }
      return {
        name: string(item.name, "server name"),
        id: item.id == null ? null : String(item.id),
        attributes: attributes as Record<string, string>,
        embedUrl,
      };
    });
    return { url: string(data.url, "url"), count: servers.length, cached: data.cached === true, servers };
  });
}

/** Resolve only a public server list for a catalog episode with explicit provider identity. */
export async function getCatalogEpisodeServers(provider: EpisodeProvider, episodeUrl: string): Promise<ProviderServersResponse> {
  const validated = providerEpisodeUrl(provider, episodeUrl);
  return request("/api/catalog/episode-servers", { provider, url: validated.href }, (value) => {
    const data = object(value);
    if (data.provider !== provider) throw new Error("Provider mismatch");
    if (providerEpisodeUrl(provider, string(data.url, "episode URL")).href !== validated.href) throw new Error("Episode URL mismatch");
    const servers = parseList(data, "servers", (value): EpisodeServer => {
      const item = object(value);
      const attributes = object(item.attributes ?? {});
      if (Object.values(attributes).some((v) => typeof v !== "string")) throw new Error("Invalid server attributes");
      const embed = new URL(string(item.embed_url, "server embed URL"));
      if (!['http:', 'https:'].includes(embed.protocol) || embed.username || embed.password) throw new Error("Unsupported server embed URL");
      return {
        name: string(item.name, "server name"),
        id: item.id == null ? null : String(item.id),
        attributes: attributes as Record<string, string>,
        embedUrl: embed.href,
      };
    });
    return { provider, url: validated.href, count: servers.length, servers };
  });
}

export async function getEpisodeDownloads(slug: string, episode: number): Promise<DownloadsResponse> {
  const list = await getAnimeEpisodes(slug);
  const selected = list.episodes.find((item) => item.episode === episode);
  if (!selected) throw new ApiError("Episode not found", "هذه الحلقة غير متاحة.", 404);
  return request("/api/downloads", { url: selected.url }, (value) => {
    const data = object(value);
    if (sourceUrl(data.url, ["/episode/"]).href !== selected.url) throw new Error("Download episode mismatch");
    const downloads = parseList(data, "downloads", (value): EpisodeDownload => {
      const row = object(value);
      const url = new URL(string(row.url, "download URL"));
      if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || sourceHost(url.hostname)) throw new Error("Invalid download link");
      return { url: url.href, server: string(row.server, "download server"),
        quality: row.quality == null ? null : string(row.quality, "quality"),
        language: row.language == null ? null : string(row.language, "language") };
    });
    return { url: selected.url, downloads };
  });
}

export async function getEpisodePlayer(
  slug: string,
  episode: number,
  server?: string,
  serverId?: string,
): Promise<PlayerResponse> {
  const data = await getAnimeEpisodes(slug);
  const selected = data.episodes.find((item) => item.episode === episode);
  if (!selected) throw new ApiError(`Episode not found: ${slug}/${episode}`, "هذه الحلقة غير متاحة.", 404);

  const params: Record<string, string> = { url: selected.url };
  if (server?.trim()) params.server = server.trim();
  if (serverId?.trim()) params.server_id = serverId.trim();

  return request("/api/player", params, (value) => {
    const data = object(value);
    const embed = new URL(string(data.embed_url, "embed URL"));
    if (!['http:', 'https:'].includes(embed.protocol)) throw new Error(`Unsupported embed URL: ${embed.href}`);

    const host = embed.hostname.toLowerCase();
    if (sourceHost(host)) throw new Error(`Anime4up internal frame rejected: ${embed.href}`);

    return {
      url: string(data.url, "url"),
      server: string(data.server, "server name"),
      serverId: data.server_id == null ? null : String(data.server_id),
      embedUrl: embed.href,
      sandbox: data.sandbox == null ? null : String(data.sandbox),
      referrerPolicy: data.referrer_policy == null ? null : String(data.referrer_policy),
      allow: data.allow == null ? null : String(data.allow),
    };
  });
}
