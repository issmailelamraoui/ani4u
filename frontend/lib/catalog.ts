import "server-only";
import { cache } from "react";
import { unstable_rethrow } from "next/navigation";
import { parseAnime, parseHome, parsePage, parseResponse } from "./catalog-model";

export class CatalogError extends Error {
  constructor(public status: number, public publicMessage = "تعذّر تحميل المكتبة الآن. حاول مرة أخرى بعد قليل.") {
    super(`Catalog request failed (${status})`);
  }
}

async function request<T>(path: string, params: Record<string, string>, parse: (v: unknown) => T) {
  try {
    const url = new URL(`/api/catalog/${path}`, process.env.API_BASE_URL || "http://127.0.0.1:8000");
    url.search = new URLSearchParams(params).toString();
    const response = await fetch(url, { cache: "no-store", headers: { Accept: "application/json" }, signal: AbortSignal.timeout(18_000) });
    if (!response.ok) throw new CatalogError(response.status);
    return parseResponse(await response.json(), parse);
  } catch (error) {
    unstable_rethrow(error);
    if (error instanceof CatalogError) throw error;
    throw new CatalogError(503);
  }
}

export const getCatalogHome = cache(() => request("home", {}, parseHome));
export const getCatalogAnime = cache((slug: string) => {
  if (!/^[a-z0-9-]{1,220}$/.test(slug)) throw new CatalogError(404);
  return request("anime", { slug }, parseAnime);
});
export const getCatalogPage = cache((page = 1, query?: string) => {
  if (!Number.isInteger(page) || page < 1 || page > 100) throw new CatalogError(422, "رقم الصفحة غير صالح.");
  if (query !== undefined && (query.trim().length < 2 || query.length > 100)) throw new CatalogError(422, "اكتب اسمًا من حرفين إلى 100 حرف.");
  return request(query === undefined ? "discover" : "search", { page: String(page), per_page: "24", ...(query === undefined ? {} : { q: query.trim() }) }, parsePage);
});
