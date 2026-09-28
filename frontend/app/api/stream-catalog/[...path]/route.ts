import { NextRequest, NextResponse } from "next/server";

const BACKEND =
  process.env.API_BASE_URL?.replace(/\/+$/, "") ||
  "http://127.0.0.1:8000";

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const { path } = await context.params;

  const target = new URL(
    `/api/stream-catalog/${path.join("/")}`,
    BACKEND
  );

  target.search = request.nextUrl.search;

  try {
    const response = await fetch(target, {
      method: request.method,
      headers: {
        Accept:
          request.headers.get("accept") ||
          "application/json",
      },
      cache: "no-store",
    });

    const body = await response.arrayBuffer();

    return new NextResponse(body, {
      status: response.status,
      headers: {
        "content-type":
          response.headers.get("content-type") ||
          "application/json",
      },
    });
  } catch (error) {
    console.error("stream-catalog proxy error:", error);

    return NextResponse.json(
      {
        ok: false,
        error: "Backend unavailable",
      },
      { status: 502 }
    );
  }
}

export const GET = proxy;
export const POST = proxy;
