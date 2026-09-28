import "server-only";
import { unstable_rethrow } from "next/navigation";
import { CatalogError } from "./catalog";
import { parseEpisodes, parseSources } from "./episode-model";

const EPISODE_LOOKUP_TIMEOUT_MS = 60_000;

/** Only the detail-page episode panel calls this client; it never resolves servers. */
export async function getEpisodeCatalog(params: URLSearchParams, requestSignal?: AbortSignal) {
  const slug = params.get("slug") || "";
  const mode = params.get("mode") || "sources";
  const source = params.get("source");
  const provider = params.get("provider");
  const page = Number(params.get("page") || "1");
  const offset = Number(params.get("offset") || "0");
  const query = params.get("q")?.trim();
  if (!/^[a-z0-9-]{1,220}$/.test(slug) || !["sources", "episodes"].includes(mode)
      || (source !== null && !/^[\p{L}\p{N}_-]{1,220}$/u.test(source))
      || (provider !== null && !["anime4up", "witanime"].includes(provider))
      || !Number.isInteger(page) || page < 1 || page > 1000
      || !Number.isInteger(offset) || offset < 0 || offset > 30000 || offset % 30 !== 0
      || (query !== undefined && (query.length < 2 || query.length > 100))) throw new CatalogError(422);
  const url = new URL(`/api/catalog/${mode === "sources" ? "sources" : "episode-list"}`, process.env.API_BASE_URL || "http://127.0.0.1:8000");
  url.searchParams.set("slug", slug);
  if (query) url.searchParams.set("q", query);
  if (mode === "episodes") {
    if (source) url.searchParams.set("source", source);
    if (provider) url.searchParams.set("provider", provider);
    url.searchParams.set("page", String(page));
    url.searchParams.set("offset", String(offset));
  }
  try {
    // Keep the proxy's deadline aligned with the client panel and stop upstream
    // work when its browser request is cancelled.
    const signal = requestSignal
      ? AbortSignal.any([requestSignal, AbortSignal.timeout(EPISODE_LOOKUP_TIMEOUT_MS)])
      : AbortSignal.timeout(EPISODE_LOOKUP_TIMEOUT_MS);
    const response = await fetch(url, { cache: "no-store", headers: { Accept: "application/json" }, signal });
    if (!response.ok) throw new CatalogError(response.status);
    const data = await response.json();
    return mode === "sources" ? parseSources(data) : parseEpisodes(data);
  } catch (error) {
    unstable_rethrow(error);
    if (error instanceof CatalogError) throw error;
    throw new CatalogError(502);
  }
}
