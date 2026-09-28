import "server-only";
import { unstable_rethrow } from "next/navigation";
import { CatalogError, getCatalogHome } from "@/lib/catalog";

export async function getDiscovery() {
  try {
    return { result: await getCatalogHome(), error: null };
  } catch (error) {
    unstable_rethrow(error);
    return { result: null, error: error instanceof CatalogError ? error.publicMessage : "تعذّر تحميل المكتبة الآن." };
  }
}
