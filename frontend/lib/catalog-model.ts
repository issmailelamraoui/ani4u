/** NOVA's normalized contract. Components never consume AniList response fields. */
export type NovaAnime = {
  id: string;
  slug: string;
  providerIds: Record<string, number>;
  title: string;
  alternativeTitles: string[];
  description: string | null;
  descriptionLanguage: string | null;
  image: string | null;
  banner: string | null;
  seasonPoster?: string | null;
  animePoster?: string | null;
  seasonBackdrop?: string | null;
  animeBackdrop?: string | null;
  accentColor: string | null;
  score: { value: number; scale: number; provider: string } | null;
  genres: string[];
  year: number | null;
  season: string | null;
  status: string;
  type: string | null;
  episodeCount: number | null;
  runtime: number | null;
  country: string | null;
  studios: string[];
  trailer: string | null;
  popularity: number | null;
  metadataUpdatedAt: number;
  availability: "unknown";
  availableEpisodeCount: number | null;
  sourceMappings: { source: string; slug: string; status: "verified"; verifiedAt: number }[];
};
export type AnimePage = { items: NovaAnime[]; page: number; perPage: number; hasNextPage: boolean };
export type CatalogHome = { featured: NovaAnime[]; topRated: NovaAnime[]; discover: AnimePage };
export type CatalogResponse<T> = {
  data: T;
  cache: { status: "miss" | "fresh" | "stale"; updatedAt: number; expiresAt: number; staleUntil: number };
};

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid catalog object");
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("Invalid catalog text");
  return value;
}
function number(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error("Invalid catalog number");
  return value;
}
function nullable<T>(value: unknown, parse: (v: unknown) => T): T | null {
  return value == null ? null : parse(value);
}
function list<T>(value: unknown, parse: (v: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new Error("Invalid catalog list");
  return value.map(parse);
}
function artwork(value: unknown): string | null {
  if (!value) return null;
  const url = new URL(text(value));
  // The image optimizer has the same explicit CDN allowlist.
  return url.protocol === "https:" && ["s4.anilist.co", "s3.anilist.co"].includes(url.hostname) && url.pathname.startsWith("/file/") && !url.username && !url.password && !url.port ? url.href : null;
}

export function parseAnime(value: unknown): NovaAnime {
  const a = record(value);
  const slug = text(a.slug);
  if (!/^[a-z0-9-]{1,220}$/.test(slug)) throw new Error("Invalid catalog slug");
  const score = a.score == null ? null : record(a.score);
  const rating = score ? { value: number(score.value), scale: number(score.scale), provider: text(score.provider) } : null;
  if (rating && (rating.scale <= 0 || rating.value < 0 || rating.value > rating.scale)) throw new Error("Invalid rating");
  return {
    id: text(a.id), slug, title: text(a.title),
    providerIds: Object.fromEntries(Object.entries(record(a.providerIds)).map(([key, value]) => [key, number(value)])),
    alternativeTitles: list(a.alternativeTitles, text),
    description: nullable(a.description, text), descriptionLanguage: nullable(a.descriptionLanguage, text),
    image: artwork(a.image), banner: artwork(a.banner),
    seasonPoster: artwork(a.seasonPoster), animePoster: artwork(a.animePoster),
    seasonBackdrop: artwork(a.seasonBackdrop), animeBackdrop: artwork(a.animeBackdrop),
    accentColor: typeof a.accentColor === "string" && /^#[0-9a-f]{6}$/i.test(a.accentColor) ? a.accentColor : null,
    score: rating, genres: list(a.genres, text), year: nullable(a.year, number),
    season: nullable(a.season, text), status: text(a.status), type: nullable(a.type, text),
    episodeCount: nullable(a.episodeCount, number), runtime: nullable(a.runtime, number),
    country: nullable(a.country, text), studios: list(a.studios, text), trailer: nullable(a.trailer, text),
    popularity: nullable(a.popularity, number), metadataUpdatedAt: number(a.metadataUpdatedAt),
    availability: "unknown", availableEpisodeCount: nullable(a.availableEpisodeCount, number),
    sourceMappings: list(a.sourceMappings, (value) => {
      const mapping = record(value);
      const sourceSlug = text(mapping.slug);
      if (mapping.status !== "verified" || !/^[\p{L}\p{N}_-]{1,220}$/u.test(sourceSlug)) throw new Error("Invalid source mapping");
      return { source: text(mapping.source), slug: sourceSlug, status: "verified", verifiedAt: number(mapping.verifiedAt) };
    }),
  };
}

export function parsePage(value: unknown): AnimePage {
  const page = record(value);
  if (typeof page.hasNextPage !== "boolean") throw new Error("Invalid pagination");
  const current = number(page.page), size = number(page.perPage);
  if (!Number.isInteger(current) || current < 1 || current > 100 || !Number.isInteger(size) || size < 1 || size > 30) throw new Error("Invalid pagination bounds");
  const items = list(page.items, parseAnime);
  if (items.length > size) throw new Error("Catalog page exceeds requested size");
  return { items, page: current, perPage: size, hasNextPage: page.hasNextPage };
}
export function parseHome(value: unknown): CatalogHome {
  const home = record(value);
  return { featured: list(home.featured, parseAnime).slice(0, 5), topRated: list(home.topRated, parseAnime).slice(0, 10), discover: parsePage(home.discover) };
}
export function parseResponse<T>(value: unknown, parse: (v: unknown) => T): CatalogResponse<T> {
  const response = record(value), info = record(response.cache);
  if (info.status !== "miss" && info.status !== "fresh" && info.status !== "stale") throw new Error("Invalid cache status");
  return { data: parse(response.data), cache: { status: info.status, updatedAt: number(info.updatedAt), expiresAt: number(info.expiresAt), staleUntil: number(info.staleUntil) } };
}
export function catalogHref(anime: Pick<NovaAnime, "slug">) {
  return `/anime/catalog/${encodeURIComponent(anime.slug)}`;
}
export function scoreText(score: NovaAnime["score"]): string | null {
  return score ? ((score.value / score.scale) * 10).toFixed(1) : null;
}
export function statusText(status: string) {
  return ({ announced: "قريبًا", releasing: "يُعرض الآن", finished: "مكتمل", cancelled: "ملغى", hiatus: "متوقف مؤقتًا" } as Record<string, string>)[status] || "";
}
