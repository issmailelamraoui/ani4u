type StreamServer = {
  source: string;
  host: string;
  type: "direct" | "iframe";
  url: string;
  tested?: boolean;
  working?: boolean;
  validation?: string;
};

type WatchResponse = {
  anime: string;
  slug: string;
  season: number;
  episode: number;
  server_count: number;
  servers: StreamServer[];
  default_server: StreamServer | null;
};

const BACKEND =
  process.env.ANI4U_BACKEND_URL?.replace(/\/+$/, "") ||
  process.env.API_BASE_URL?.replace(/\/+$/, "") ||
  "http://127.0.0.1:8000";

export default async function StreamTestPage({
  params,
}: {
  params: Promise<{
    slug: string;
    season: string;
    episode: string;
  }>;
}) {
  const { slug, season, episode } = await params;

  const apiUrl =
    `${BACKEND}/api/stream-catalog/watch/` +
    `${encodeURIComponent(slug)}/` +
    `${encodeURIComponent(season)}/` +
    `${encodeURIComponent(episode)}`;

  let response: Response;

  try {
    response = await fetch(apiUrl, {
      cache: "no-store",
    });
  } catch (error) {
    console.error("Stream catalog fetch failed:", error);

    return (
      <main
        style={{
          minHeight: "100vh",
          padding: 40,
          color: "white",
          background: "#08080c",
        }}
      >
        <h1>Backend unavailable</h1>
        <p>Unable to connect to the stream catalog.</p>
      </main>
    );
  }

  if (!response.ok) {
    return (
      <main
        style={{
          minHeight: "100vh",
          padding: 40,
          color: "white",
          background: "#08080c",
        }}
      >
        <h1>Episode not found</h1>
        <p>Backend status: {response.status}</p>
      </main>
    );
  }

  const data: WatchResponse = await response.json();

  const server =
    data.default_server ||
    data.servers?.find((item) => item.working !== false) ||
    data.servers?.[0];

  if (!server) {
    return (
      <main
        style={{
          minHeight: "100vh",
          padding: 40,
          color: "white",
          background: "#08080c",
        }}
      >
        <h1>{data.anime}</h1>

        <p>
          Season {data.season} · Episode {data.episode}
        </p>

        <p>No working servers found.</p>
      </main>
    );
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#08080c",
        color: "white",
        padding: "32px",
      }}
    >
      <div
        style={{
          maxWidth: "1100px",
          margin: "0 auto",
        }}
      >
        <h1>{data.anime}</h1>

        <p>
          Season {data.season} · Episode {data.episode}
        </p>

        <div
          style={{
            marginTop: 24,
            width: "100%",
            aspectRatio: "16 / 9",
            background: "black",
            borderRadius: 16,
            overflow: "hidden",
          }}
        >
          {server.type === "direct" ? (
            <video
              src={server.url}
              controls
              playsInline
              style={{
                width: "100%",
                height: "100%",
                background: "black",
              }}
            />
          ) : (
            <iframe
              src={server.url}
              title={`${data.anime} - Episode ${data.episode}`}
              allow="autoplay; fullscreen; picture-in-picture"
              allowFullScreen
              referrerPolicy="no-referrer-when-downgrade"
              style={{
                border: 0,
                width: "100%",
                height: "100%",
                background: "black",
              }}
            />
          )}
        </div>

        <div
          style={{
            marginTop: 20,
            padding: 16,
            background: "#15151c",
            borderRadius: 12,
          }}
        >
          <p>Source: {server.source}</p>
          <p>Host: {server.host}</p>
          <p>Type: {server.type}</p>
          <p>Servers: {data.server_count}</p>

          {server.validation ? (
            <p>Validation: {server.validation}</p>
          ) : null}
        </div>
      </div>
    </main>
  );
}
