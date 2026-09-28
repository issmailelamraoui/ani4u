import { unstable_rethrow } from "next/navigation";
import { CatalogError } from "@/lib/catalog";
import { getEpisodeCatalog } from "@/lib/episode-catalog";

export async function GET(request: Request) {
  try {
    return Response.json(await getEpisodeCatalog(new URL(request.url).searchParams, request.signal), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    unstable_rethrow(error);
    return Response.json({ error: "تعذّر تحميل الحلقات. حاول مجددًا بعد قليل." }, { status: error instanceof CatalogError ? error.status : 502, headers: { "Cache-Control": "no-store" } });
  }
}
