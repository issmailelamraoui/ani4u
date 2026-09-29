import "server-only";
import type { Anime } from "@/lib/api";

export type Ani4uContentType = "series" | "movie" | "special";

export type Ani4uStreamServer = {
  source: string;
  host: string;
  type: "direct" | "iframe" | "hls";
  url: string;
  tested?: boolean;
  working?: boolean;
};

export type Ani4uCatalogAnime = {
  title: string;
  slug: string;
  content_type: Ani4uContentType;
  seasons: number[];
  episode_count: number;
  server_count: number;
  playback: { season: number; episode: number } | null;
};

export type Ani4uStreamWatch = {
  anime: string;
  slug: string;
  content_type: Ani4uContentType;
  season: number;
  episode: number;
  server_count: number;
  servers: Ani4uStreamServer[];
  default_server: Ani4uStreamServer;
};

export type Ani4uStreamEpisode = { season: number; episode: number; server_count: number };
export type Ani4uEpisodeList = {
  title: string;
  slug: string;
  content_type: Ani4uContentType;
  count: number;
  episodes: Ani4uStreamEpisode[];
  playback: { season: number; episode: number } | null;
};

export function toAni4uAnime(content: Ani4uCatalogAnime): Anime {
  return {
    title: content.title,
    slug: content.slug,
    // Local catalog entries intentionally have no fabricated source URL or artwork.
    url: "",
    image: null,
    kind: content.content_type === "series" ? "anime" : content.content_type,
  };
}

const BACKEND = process.env.ANI4U_EXTERNAL_BACKEND_URL?.replace(/\/+$/, "") || process.env.ANI4U_BACKEND_URL?.replace(/\/+$/, "") || process.env.API_BASE_URL?.replace(/\/+$/, "") || "http://127.0.0.1:8000";

async function request<T>(path: string): Promise<T | null> {
  const response = await fetch(`${BACKEND}/api/stream-catalog${path}`, { cache: "no-store", headers: { Accept: "application/json" }, signal: AbortSignal.timeout(12_000) });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`ANI4U stream catalog returned ${response.status}`);
  return response.json() as Promise<T>;
}

function validContent(value: unknown): value is Ani4uCatalogAnime {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.title === "string" && /^[a-z0-9-]{1,220}$/.test(String(item.slug)) && (item.content_type === "series" || item.content_type === "movie" || item.content_type === "special") && Array.isArray(item.seasons) && typeof item.episode_count === "number";
}

export async function getAni4uCatalog(): Promise<Ani4uCatalogAnime[]> {
  const response = await request<{ anime?: unknown }>("/anime");
  if (!response || !Array.isArray(response.anime) || !response.anime.every(validContent)) throw new Error("Invalid ANI4U catalog response");
  return response.anime;
}

export async function getAni4uCatalogAnime(slug: string): Promise<Ani4uCatalogAnime | null> {
  if (!/^[a-z0-9-]{1,220}$/.test(slug)) return null;
  const response = await request<unknown>(`/anime/${encodeURIComponent(slug)}`);
  if (response === null) return null;
  if (!validContent(response)) throw new Error("Invalid ANI4U content response");
  return response;
}

export async function getAni4uEpisodes(slug: string): Promise<Ani4uEpisodeList | null> {
  const response = await request<unknown>(`/anime/${encodeURIComponent(slug)}/episodes`);
  if (response === null) return null;
  if (!response || typeof response !== "object") throw new Error("Invalid ANI4U episode response");
  const data = response as Record<string, unknown>;
  if (typeof data.title !== "string" || !Array.isArray(data.episodes) || !["series", "movie", "special"].includes(String(data.content_type))) throw new Error("Invalid ANI4U episode response");
  const episodes = data.episodes as unknown[];
  if (!episodes.every((item) => item && typeof item === "object" && Number.isInteger((item as Ani4uStreamEpisode).season) && Number.isInteger((item as Ani4uStreamEpisode).episode) && Number.isInteger((item as Ani4uStreamEpisode).server_count))) throw new Error("Invalid ANI4U episode rows");
  return { title: data.title, slug: String(data.slug), content_type: data.content_type as Ani4uContentType, count: Number(data.count), episodes: episodes as Ani4uStreamEpisode[], playback: data.playback as Ani4uEpisodeList["playback"] };
}

export async function getAni4uStream(slug: string, episode: number, season?: number): Promise<Ani4uStreamWatch | null> {
  const content = await getAni4uCatalogAnime(slug);
  if (!content) return null;
  let resolvedSeason = season;
  let resolvedEpisode = episode;
  if (content.content_type === "series") {
    const list = await getAni4uEpisodes(slug);
    const matches = (list?.episodes ?? []).filter((item) => item.episode === episode && (season === undefined || item.season === season));
    // Public URLs contain no season. Keep the legacy source fallback for an
    // ambiguous number rather than choosing a potentially different season.
    if (matches.length !== 1) return null;
    resolvedSeason = matches[0].season;
  } else {
    if (episode !== 0) return null;
    resolvedSeason = content.playback?.season ?? 0;
    resolvedEpisode = content.playback?.episode ?? 0;
  }
  const data = await request<unknown>(`/watch/${encodeURIComponent(slug)}/${resolvedSeason}/${resolvedEpisode}`);
  if (!data || typeof data !== "object") return null;
  const watch = data as Ani4uStreamWatch;
  if (!Array.isArray(watch.servers) || !watch.default_server || !["series", "movie", "special"].includes(watch.content_type)) throw new Error("Invalid ANI4U watch response");
  return watch;
}
