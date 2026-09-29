export type EpisodeProvider = "anime4up" | "witanime";
export type EpisodeSource = { provider: EpisodeProvider; slug: string; title: string; verified: boolean };
export type ProviderAvailabilityState = "unknown" | "available" | "unavailable";
export type ProviderAvailability = Record<EpisodeProvider, { status: ProviderAvailabilityState; lastStatus: number | null }>;
export type SourceChoices = { sources: EpisodeSource[]; selectedSource: string | null; availability: ProviderAvailability };
export type EpisodeCursor = { page: number; offset: number };
export type EpisodeReference = { provider: EpisodeProvider; sourceSlug: string; episodeUrl: string };
export type RequestedEpisodeSource = { provider: EpisodeProvider; sourceSlug: string };
export type EpisodeList = {
  sourceSlug: string; sourceProvider: EpisodeProvider; sourceTitle: string; verified: boolean;
  items: { episode: number; title: string; sources: EpisodeReference[] }[];
  page: number; offset: number; totalPages: number; next: EpisodeCursor | null;
  requestedSource: RequestedEpisodeSource | null;
  availability: ProviderAvailability;
  externalUnavailable: false;
};
export type EpisodeProviderUnavailable = Omit<EpisodeList, "externalUnavailable"> & { externalUnavailable: true };
export type EpisodeUnavailable = {
  items: [];
  sources: [];
  selectedSource: null;
  page: number;
  offset: number;
  totalPages: number;
  next: null;
  availability: ProviderAvailability;
  externalUnavailable: true;
};
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid episode data");
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("Invalid episode text");
  return value;
}
function sourceSlug(value: unknown): string {
  const slug = text(value);
  if (!/^[\p{L}\p{N}_-]{1,220}$/u.test(slug)) throw new Error("Invalid source slug");
  return slug;
}
function provider(value: unknown): EpisodeProvider {
  // Old cached catalog responses did not include provider because Anime4Up was
  // the only source. Their meaning remains Anime4Up.
  if (value === undefined || value === "anime4up") return "anime4up";
  if (value === "witanime") return "witanime";
  throw new Error("Invalid episode provider");
}
function requestedSource(value: unknown): RequestedEpisodeSource | null {
  if (value == null) return null;
  const source = object(value);
  return { provider: provider(source.provider), sourceSlug: sourceSlug(source.sourceSlug) };
}
function referenceUrl(value: unknown, source: EpisodeProvider): string {
  const url = new URL(text(value));
  const anime4up = source === "anime4up"
    && (url.hostname === "anime4up.rest" || url.hostname.endsWith(".anime4up.rest"))
    && /^\/episode\/[^/]+\/?$/.test(url.pathname);
  const witanime = source === "witanime"
    && (url.hostname === "witanime.site" || url.hostname.endsWith(".witanime.site"))
    && /^\/watch\/.+/.test(url.pathname);
  if (url.protocol !== "https:" || url.username || url.password || url.port || url.search || url.hash || (!anime4up && !witanime)) {
    throw new Error("Invalid episode reference");
  }
  return url.href;
}
function integer(value: unknown, min: number, max: number): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < min || value > max) throw new Error("Invalid episode range");
  return value;
}
function availability(value: unknown): ProviderAvailability {
  const defaults: ProviderAvailability = {
    anime4up: { status: "unknown", lastStatus: null },
    witanime: { status: "unknown", lastStatus: null },
  };
  if (value === undefined) return defaults;
  const data = object(value);
  for (const name of ["anime4up", "witanime"] as const) {
    const item = object(data[name]);
    const status = item.status;
    // The FastAPI payload uses snake_case. The server-side Next.js adapter
    // normalizes it to camelCase before the browser validates the same payload
    // again, so both representations are valid at this boundary.
    const lastStatus = "last_status" in item ? item.last_status : item.lastStatus;
    if (status !== "unknown" && status !== "available" && status !== "unavailable") throw new Error("Invalid provider availability");
    if (lastStatus !== null && (typeof lastStatus !== "number" || !Number.isInteger(lastStatus) || lastStatus < 100 || lastStatus > 599)) throw new Error("Invalid provider status");
    defaults[name] = { status, lastStatus };
  }
  return defaults;
}
export function externalProvidersUnavailable(value: ProviderAvailability) {
  return value.anime4up.status === "unavailable" && value.witanime.status === "unavailable";
}
export function parseSources(value: unknown): SourceChoices {
  const data = object(value);
  if (!Array.isArray(data.sources)) throw new Error("Invalid sources");
  const sources = data.sources.map((v): EpisodeSource => {
    const source = object(v);
    return { provider: provider(source.provider), slug: sourceSlug(source.slug), title: text(source.title), verified: source.verified === true };
  });
  const selectedSource = data.selectedSource == null ? null : sourceSlug(data.selectedSource);
  if (selectedSource && !sources.some((source) => source.slug === selectedSource && source.verified)) throw new Error("Unverified default source");
  return { sources, selectedSource, availability: availability(data.availability) };
}
export function parseEpisodes(value: unknown, expectedSource?: EpisodeSource | string): EpisodeList | EpisodeProviderUnavailable | EpisodeUnavailable {
  const data = object(value);
  const providerAvailability = availability(data.availability);
  if (data.externalUnavailable === true && data.sourceSlug === undefined) {
    if (!Array.isArray(data.items) || data.items.length || !Array.isArray(data.sources) || data.sources.length || data.selectedSource !== null) throw new Error("Invalid unavailable episode response");
    return {
      items: [], sources: [], selectedSource: null,
      page: integer(data.page, 1, 1000), offset: integer(data.offset, 0, 30000), totalPages: integer(data.totalPages, 1, 1000), next: null,
      availability: providerAvailability, externalUnavailable: true,
    };
  }
  const selected = sourceSlug(data.sourceSlug);
  const selectedProvider = provider(data.sourceProvider);
  const requested = requestedSource(data.requestedSource);
  if (typeof expectedSource === "string" && selected !== expectedSource) throw new Error("Episode source mismatch");
  if (typeof expectedSource === "object") {
    const selectedMatches = selected === expectedSource.slug && selectedProvider === expectedSource.provider;
    const fallbackMatches = requested?.sourceSlug === expectedSource.slug && requested.provider === expectedSource.provider;
    if (!selectedMatches && !fallbackMatches) throw new Error("Episode source mismatch");
  }
  if (!Array.isArray(data.items) || data.items.length > 30) throw new Error("Invalid episode page size");
  const next = data.next == null ? null : object(data.next);
  const numbers = new Set<number>();
  const parsed = {
    sourceSlug: selected, sourceProvider: selectedProvider, sourceTitle: text(data.sourceTitle), verified: data.verified === true,
    items: data.items.map((item) => {
      const episode = object(item);
      if (typeof episode.episode !== "number" || !Number.isFinite(episode.episode) || episode.episode < 0) throw new Error("Invalid episode number");
      if (numbers.has(episode.episode)) throw new Error("Duplicate episode number");
      numbers.add(episode.episode);
      // Older cached responses contain only the source slug and episode number.
      const references = episode.sources ?? [];
      if (!Array.isArray(references)) throw new Error("Invalid episode references");
      const identities = new Set<string>();
      const sources = references.map((value): EpisodeReference => {
        const ref = object(value);
        const source = provider(ref.provider);
        const refSlug = sourceSlug(ref.sourceSlug);
        if (source !== selectedProvider || refSlug !== selected) throw new Error("Episode reference belongs to another source");
        const url = referenceUrl(ref.episodeUrl, source);
        const identity = `${source}:${refSlug}:${episode.episode}`;
        if (identities.has(identity)) throw new Error("Duplicate episode reference");
        identities.add(identity);
        return { provider: source, sourceSlug: refSlug, episodeUrl: url };
      });
      return { episode: episode.episode, title: text(episode.title), sources };
    }),
    page: integer(data.page, 1, 1000), offset: integer(data.offset, 0, 30000), totalPages: integer(data.totalPages, 1, 1000),
    next: next ? { page: integer(next.page, 1, 1000), offset: integer(next.offset, 0, 30000) } : null,
    requestedSource: requested,
    availability: providerAvailability,
  };
  // The source identity stays available for a mapped title even when both
  // public providers reject this runtime. The panel uses this signal to
  // distinguish an upstream block from a genuinely empty grid.
  return data.externalUnavailable === true
    ? { ...parsed, externalUnavailable: true }
    : { ...parsed, externalUnavailable: false };
}
export function episodeHref(source: string, episode: number) {
  return `/watch/${encodeURIComponent(source)}/${encodeURIComponent(String(episode))}`;
}

export function catalogEpisodeHref(catalogSlug: string, episode: number, reference?: EpisodeReference) {
  if (!reference) return episodeHref(catalogSlug, episode);
  const query = new URLSearchParams({
    provider: reference.provider,
    source: reference.sourceSlug,
    episode_url: reference.episodeUrl,
  });
  return `${episodeHref(catalogSlug, episode)}?${query}`;
}
