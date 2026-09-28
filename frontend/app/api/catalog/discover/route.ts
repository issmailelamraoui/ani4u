import { unstable_rethrow } from "next/navigation";
import { CatalogError, getCatalogPage } from "@/lib/catalog";

export async function GET(request: Request) {
  const page = Number(new URL(request.url).searchParams.get("page") || "1");
  try {
    return Response.json(await getCatalogPage(page), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    unstable_rethrow(error);
    return Response.json({ error: "تعذّر تحميل العناوين." }, { status: error instanceof CatalogError ? error.status : 503, headers: { "Cache-Control": "no-store" } });
  }
}
