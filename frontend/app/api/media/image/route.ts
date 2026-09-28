import { isIP } from "node:net";
import { NextRequest } from "next/server";

export const runtime = "nodejs";

const USER_AGENT =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/140.0 Safari/537.36";

function safeRemoteUrl(raw: string | null): URL | null {
  if (!raw) return null;

  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }

  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    return null;
  }

  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  if (
    !host ||
    host === "localhost" ||
    host.endsWith(".localhost") ||
    host.endsWith(".local") ||
    host.endsWith(".internal") ||
    isIP(host) !== 0
  ) {
    return null;
  }

  return url;
}

export async function GET(request: NextRequest) {
  const remote = safeRemoteUrl(request.nextUrl.searchParams.get("url"));
  if (!remote) {
    return new Response("Invalid image URL", { status: 400 });
  }

  try {
    const response = await fetch(remote, {
      cache: "force-cache",
      headers: {
        Accept: "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        Referer: "https://w1.anime4up.rest/",
        "User-Agent": USER_AGENT,
      },
      redirect: "follow",
      signal: AbortSignal.timeout(15_000),
    });

    if (!response.ok) {
      return new Response("Image upstream error", { status: 502 });
    }

    const contentType = response.headers.get("content-type") || "";
    if (!contentType.toLowerCase().startsWith("image/")) {
      return new Response("Upstream response is not an image", { status: 415 });
    }

    const contentLength = Number(response.headers.get("content-length") || 0);
    if (Number.isFinite(contentLength) && contentLength > 12 * 1024 * 1024) {
      return new Response("Image is too large", { status: 413 });
    }

    return new Response(response.body, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
      },
    });
  } catch (error) {
    console.error("[NOVA image proxy]", remote.href, error);
    return new Response("Could not load image", { status: 502 });
  }
}
