import { unstable_rethrow } from "next/navigation";
import { CatalogError } from "@/lib/catalog";
import { getEpisodeCatalog } from "@/lib/episode-catalog";

export async function GET(request: Request) {
  try {
    return Response.json(await getEpisodeCatalog(new URL(request.url).searchParams, request.signal), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    unstable_rethrow(error);
    const status = error instanceof CatalogError ? error.status : 502;
    const detail = error instanceof CatalogError
      ? error.publicMessage
      : error instanceof Error ? error.message : "Unknown episode error";
    console.error(`[catalog episodes route] status=${status} detail=${detail}`);
    return Response.json(
      { error: "تعذّر تحميل الحلقات.", detail, status },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
