import type { Metadata } from "next";
import Link from "next/link";
import { notFound, unstable_rethrow } from "next/navigation";
import ApiErrorState from "@/components/ApiErrorState";
import HlsPlayer from "@/components/HlsPlayer";
import { ArrowIcon } from "@/components/Icons";
import {
  ApiError,
  getAnime,
  getAnimeEpisodes,
  getAnimeHref,
  getEpisodePlayer,
  getCatalogEpisodeServers,
  getEpisodeServers,
  getEpisodeDownloads,
  type Anime,
  type DownloadsResponse,
  type EpisodeProvider,
  type EpisodesResponse,
  type PlayerResponse,
  type ServersResponse,
} from "@/lib/api";
import { getAni4uCatalogAnime, getAni4uEpisodes, getAni4uStream, toAni4uAnime, type Ani4uCatalogAnime, type Ani4uStreamWatch } from "@/lib/ani4u-stream";
import { getCatalogAnime } from "@/lib/catalog";
import { mergeStreamServers, selectStreamServer } from "@/lib/stream-server-merge";

type Props = {
  params: Promise<{ slug: string; episode: string }>;
  searchParams: Promise<{ server?: string | string[]; downloads?: string; provider?: string | string[]; source?: string | string[]; episode_url?: string | string[] }>;
};

type PlayerReferrerPolicy =
  | "no-referrer"
  | "no-referrer-when-downgrade"
  | "origin"
  | "origin-when-cross-origin"
  | "same-origin"
  | "strict-origin"
  | "strict-origin-when-cross-origin"
  | "unsafe-url";

function normalizeReferrerPolicy(value: string | null): PlayerReferrerPolicy | undefined {
  const allowed = new Set<PlayerReferrerPolicy>([
    "no-referrer",
    "no-referrer-when-downgrade",
    "origin",
    "origin-when-cross-origin",
    "same-origin",
    "strict-origin",
    "strict-origin-when-cross-origin",
    "unsafe-url",
  ]);

  return value && allowed.has(value as PlayerReferrerPolicy)
    ? (value as PlayerReferrerPolicy)
    : undefined;
}

function first(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}


function message(error: unknown) {
  unstable_rethrow(error);
  if (error instanceof ApiError) return error.publicMessage;
  console.error("[Watch page]", error);
  return "تعذّر تحميل المشاهدة الآن. حاول مرة أخرى بعد قليل.";
}

function episodeHref(slug: string, episode: number) {
  return `/watch/${encodeURIComponent(slug)}/${encodeURIComponent(String(episode))}`;
}

function provider(value: string | undefined): EpisodeProvider | null {
  return value === "anime4up" || value === "witanime" ? value : null;
}

async function catalogWatchAnime(slug: string): Promise<Anime | null> {
  const result = await getCatalogAnime(slug);
  const anime = result.data;
  return {
    title: anime.title,
    slug: anime.slug,
    url: "",
    image: anime.image || null,
    kind: anime.type === "movie" ? "movie" : anime.type === "special" ? "special" : "anime",
  };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug, episode } = await params;
  const episodeNumber = Number(episode);

  try {
    const anime = await getAnime(slug);
    if (!anime || !Number.isFinite(episodeNumber)) throw new Error("Legacy metadata not found");

    return {
      title: `الحلقة ${episodeNumber} — ${anime.title}`,
      description: `شاهد الحلقة ${episodeNumber} من أنمي ${anime.title} مترجمة أونلاين واختر من سيرفرات المشاهدة المتاحة على ANI4U.`,
      robots: { index: false, follow: true },
    };
  } catch {
    try {
      const catalog = await catalogWatchAnime(slug);
      if (catalog && Number.isFinite(episodeNumber)) {
        return {
          title: `الحلقة ${episodeNumber} — ${catalog.title}`,
          description: `شاهد الحلقة ${episodeNumber} من أنمي ${catalog.title} واختر من سيرفرات المشاهدة المتاحة.`,
          robots: { index: false, follow: true },
        };
      }
      const local = await getAni4uCatalogAnime(slug);
      if (!local || !Number.isFinite(episodeNumber)) return { title: "المشاهدة", robots: { index: false } };
      const movie = local.content_type === "movie";
      const series = local.content_type === "series";
      return {
        title: series ? `الحلقة ${episodeNumber} — ${local.title}` : `${movie ? "فيلم" : "المحتوى الخاص"} ${local.title}`,
        description: series
          ? `شاهد الحلقة ${episodeNumber} من أنمي ${local.title} مترجمة أونلاين واختر من سيرفرات المشاهدة المتاحة على ANI4U.`
          : movie
            ? `شاهد فيلم الأنمي ${local.title} مترجم أونلاين بجودة عالية وعلى عدة سيرفرات مشاهدة عبر ANI4U.`
            : `شاهد المحتوى الخاص من أنمي ${local.title} مترجم أونلاين عبر ANI4U.`,
        robots: { index: false, follow: true },
      };
    } catch {
      return { title: "المشاهدة", robots: { index: false } };
    }
  }
}

export default async function WatchPage({ params, searchParams }: Props) {
  const { slug, episode } = await params;
  const options = await searchParams;
  const requestedServer = first(options.server)?.trim();
  const requestedProvider = provider(first(options.provider)?.trim());
  const requestedEpisodeUrl = first(options.episode_url)?.trim();
  const providerContext = requestedProvider && requestedEpisodeUrl
    ? { provider: requestedProvider, episodeUrl: requestedEpisodeUrl }
    : null;
  const requestedSource = first(options.source)?.trim();
  const providerQuery = providerContext
    ? { provider: providerContext.provider, episode_url: providerContext.episodeUrl, ...(requestedSource ? { source: requestedSource } : {}) }
    : {};
  const currentWatchHref = `${episodeHref(slug, Number(episode))}${Object.keys(providerQuery).length ? `?${new URLSearchParams(providerQuery)}` : ""}`;
  const showDownloads = options.downloads === "1";
  const episodeNumber = Number(episode);

  if (!Number.isFinite(episodeNumber) || episodeNumber < 0) {
    notFound();
  }

  let local: Ani4uCatalogAnime | null = null;
  let anime: Anime | null = null;
  if (providerContext) {
    try { anime = await catalogWatchAnime(slug); } catch { /* Legacy metadata remains the fallback. */ }
  }
  if (!anime) {
    try {
      // Metadata, artwork, and the canonical title always come from the existing
      // API first. The stream catalog is only a playback supplement/fallback.
      anime = await getAnime(slug);
      if (!anime) {
        local = await getAni4uCatalogAnime(slug);
        anime = local ? toAni4uAnime(local) : null;
      }
    } catch (error) {
      try {
        local = await getAni4uCatalogAnime(slug);
        anime = local ? toAni4uAnime(local) : null;
      } catch {
        return <div className="page-shell route-message"><h1>تعذّر تحميل الحلقة</h1><ApiErrorState message={message(error)} retryHref={episodeHref(slug, episodeNumber)} /></div>;
      }
    }
  }
  if (!anime) notFound();

  let episodes: EpisodesResponse;
  let legacyEpisodes: EpisodesResponse | undefined;

  if (providerContext) {
    // The catalog link already carries a provider-validated public episode
    // reference. Do not reinterpret a WitAnime URL as Anime4Up.
    episodes = {
      url: providerContext.episodeUrl, count: 1, cached: true,
      episodes: [{ episode: episodeNumber, title: `الحلقة ${episodeNumber}`, url: providerContext.episodeUrl }],
    };
  } else try {
    legacyEpisodes = await getAnimeEpisodes(slug);
    episodes = legacyEpisodes;
    // Add exact same-slug local coverage without replacing legacy titles, URLs,
    // or its complete episode grid.
    try {
      local = await getAni4uCatalogAnime(slug);
      const localEpisodes = local && await getAni4uEpisodes(slug);
      if (localEpisodes?.content_type === "series") {
        const merged = new Map(legacyEpisodes.episodes.map((item) => [item.episode, item]));
        for (const item of localEpisodes.episodes) {
          if (!merged.has(item.episode)) merged.set(item.episode, { episode: item.episode, title: `الحلقة ${item.episode}`, url: `local:${slug}:${item.season}:${item.episode}` });
        }
        episodes = { ...legacyEpisodes, count: merged.size, episodes: [...merged.values()].sort((a, b) => a.episode - b.episode) };
      }
    } catch {
      // The legacy episode list is complete enough to render without local enrichment.
    }
  } catch (error) {
    try {
      local = local || await getAni4uCatalogAnime(slug);
      const localEpisodes = local && await getAni4uEpisodes(slug);
      if (!localEpisodes) throw error;
      episodes = {
        url: "", count: localEpisodes.count, cached: true,
        episodes: localEpisodes.content_type === "series"
          ? localEpisodes.episodes.map((item) => ({ episode: item.episode, title: `الحلقة ${item.episode}`, url: `local:${slug}:${item.season}:${item.episode}` }))
          : [{ episode: 0, title: localEpisodes.content_type === "movie" ? "الفيلم" : "المحتوى الخاص", url: `local:${slug}:0:0` }],
      };
    } catch {
      return <div className="page-shell route-message"><h1>تعذّر تحميل الحلقة</h1><ApiErrorState message={message(error)} retryHref={getAnimeHref(anime)} /></div>;
    }
  }

  const currentIndex = episodes.episodes.findIndex(
    (item) => item.episode === episodeNumber,
  );

  if (currentIndex < 0) notFound();

  const previousEpisode = episodes.episodes[currentIndex - 1];
  const nextEpisode = episodes.episodes[currentIndex + 1];

  let catalogStream: Ani4uStreamWatch | null = null;
  let catalogError: string | undefined;

  try {
    catalogStream = await getAni4uStream(slug, episodeNumber);
  } catch (error) {
    console.error("[ANI4U stream catalog]", error);
    catalogError = "تعذّر تحميل سيرفرات ANI4U.";
  }

  let servers: ServersResponse | undefined;
  let witanimeServers: ServersResponse | undefined;
  let serverError: string | undefined;
  const legacyEpisodeExists = !providerContext && legacyEpisodes?.episodes.some((item) => item.episode === episodeNumber) === true;

  // A catalog reference always retains its source provider. Legacy links keep
  // their original Anime4Up resolver and response shape.
  if (providerContext) {
    try {
      const resolved = await getCatalogEpisodeServers(providerContext.provider, providerContext.episodeUrl);
      if (resolved.provider === "witanime") witanimeServers = { ...resolved, cached: true };
      else servers = { ...resolved, cached: true };
    } catch (error) {
      serverError = message(error);
    }
  } else if (legacyEpisodeExists) {
    try {
      servers = await getEpisodeServers(slug, episodeNumber);
    } catch (error) {
      serverError = message(error);
    }
  }

  const unifiedServers = mergeStreamServers(catalogStream?.servers ?? [], servers?.servers ?? [], witanimeServers?.servers ?? []);
  const selectedUnified = selectStreamServer(unifiedServers, requestedServer);
  const selectedLegacy = selectedUnified?.source === "legacy" ? selectedUnified.server : undefined;

  let player: PlayerResponse | undefined;
  let playerError: string | undefined;

  if (selectedLegacy && !providerContext) {
    try {
      player = await getEpisodePlayer(
        slug,
        episodeNumber,
        selectedLegacy.name,
        selectedLegacy.id || undefined,
      );
    } catch (error) {
      playerError = message(error);
    }
  }

  let downloads: DownloadsResponse | undefined;
  let downloadError: string | undefined;
  if (showDownloads && legacyEpisodeExists) {
    try { downloads = await getEpisodeDownloads(slug, episodeNumber); }
    catch (error) { downloadError = message(error); }
  }
  const downloadHref = `${episodeHref(slug, episodeNumber)}?${new URLSearchParams({ downloads: "1", ...(selectedUnified ? { server: selectedUnified.id } : {}) })}#downloads`;
  const watchLabel = local?.content_type === "movie"
    ? "الفيلم"
    : local?.content_type === "special"
      ? "المحتوى الخاص"
      : `الحلقة ${episodeNumber}`;

  return (
    <div className="watch-page page-shell">
      <nav className="breadcrumb" aria-label="مسار التنقل">
        <Link href="/">الرئيسية</Link>
        <span aria-hidden="true">/</span>
        <Link href={getAnimeHref(anime)}>{anime.title}</Link>
        <span aria-hidden="true">/</span>
        <span aria-current="page">{watchLabel}</span>
      </nav>

      <header className="watch-head">
        <div>
          <span className="eyebrow" dir="ltr">NOW WATCHING</span>
          <h1 dir="auto">{anime.title}</h1>
          <p>{watchLabel}</p>
        </div>
        <Link className="secondary-button" href={getAnimeHref(anime)}>
          جميع الحلقات
        </Link>
      </header>

      <section className="watch-player-shell" aria-label={watchLabel}>
        {selectedUnified?.source === "fansub" ? (
          selectedUnified.type === "direct" ? (
            <video
              className="watch-player"
              src={selectedUnified.url}
              title={`${anime.title} — ${watchLabel}`}
              controls
              playsInline
              preload="metadata"
            />
          ) : selectedUnified.type === "hls" ? (
            <HlsPlayer
              className="watch-player"
              src={selectedUnified.url}
              title={`${anime.title} — ${watchLabel}`}
            />
          ) : (
            <iframe
              className="watch-player"
              src={selectedUnified.url}
              title={`${anime.title} — ${watchLabel}`}
              allow="autoplay; fullscreen; picture-in-picture"
              allowFullScreen
              loading="eager"
              referrerPolicy="strict-origin-when-cross-origin"
            />
          )
        ) : player ? (
          <iframe
            className="watch-player"
            src={player.embedUrl}
            title={`${anime.title} — ${watchLabel}`}
            allow={player.allow || "autoplay *; encrypted-media *; picture-in-picture *; fullscreen *"}
            sandbox={player.sandbox || undefined}
            referrerPolicy={normalizeReferrerPolicy(player.referrerPolicy)}
            allowFullScreen
            loading="eager"
          />
        ) : selectedUnified && selectedUnified.server.embedUrl ? (
          <iframe
            className="watch-player"
            src={selectedUnified.server.embedUrl}
            title={`${anime.title} — ${watchLabel}`}
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            referrerPolicy="strict-origin-when-cross-origin"
            allowFullScreen
            loading="eager"
          />
        ) : (
          <div className="watch-player-empty">
            <span className="eyebrow" dir="ltr">PLAYER UNAVAILABLE</span>
            <h2>تعذّر فتح المشغّل</h2>
            <p>
              {catalogError ||
                playerError ||
                serverError ||
                "لم يُرجع المصدر سيرفر مشاهدة متاحاً لهذه الحلقة."}
            </p>
          </div>
        )}
      </section>

      {(playerError || (unifiedServers.length === 0 && (catalogError || serverError))) && (
        <ApiErrorState
          title="مشكلة في سيرفر المشاهدة"
          message={playerError || catalogError || serverError || "تعذّر تحميل السيرفر."}
          retryHref={currentWatchHref}
        />
      )}

      {unifiedServers.length > 0 ? (
        <section className="watch-servers" aria-labelledby="servers-title">
          <div className="section-heading">
            <div>
              <span className="eyebrow" dir="ltr">STREAM SERVERS</span>
              <h2 id="servers-title">سيرفرات المشاهدة</h2>
            </div>

            <span className="result-count">{unifiedServers.length} سيرفر</span>
          </div>

          <div className="server-list">
            {unifiedServers.map((server) => <Link
              key={server.id}
              className={`server-pill${selectedUnified?.id === server.id ? " is-active" : ""}`}
              href={`${episodeHref(slug, episodeNumber)}?${new URLSearchParams({ ...providerQuery, server: server.id, ...(showDownloads ? { downloads: "1" } : {}) })}`}
              prefetch={false}
            >{server.name}</Link>)}
          </div>
        </section>
      ) : null}

      {legacyEpisodeExists && <section id="downloads" className="watch-servers watch-downloads" aria-labelledby="downloads-title">
        <div className="section-heading"><div><span className="eyebrow" dir="ltr">DOWNLOAD SERVERS</span><h2 id="downloads-title">سيرفرات التحميل</h2></div></div>
        {!showDownloads && <Link className="secondary-button" href={downloadHref} prefetch={false}><ArrowIcon direction="down" /> عرض روابط التحميل</Link>}
        {downloadError && <ApiErrorState title="تعذّر تحميل الروابط" message={downloadError} retryHref={downloadHref} />}
        {downloads && (downloads.downloads.length ? <div className="server-list">{downloads.downloads.map((item) => <a className="server-pill download-link" key={item.url} href={item.url} target="_blank" rel="nofollow noopener noreferrer"><ArrowIcon direction="down" /><span><strong dir="ltr">{item.server}</strong><small>{[item.quality, item.language].filter(Boolean).join(" · ")}</small></span></a>)}</div> : <p>لا توجد روابط تحميل معلنة لهذه الحلقة حاليًا.</p>)}
      </section>}

      <nav className="episode-navigation" aria-label="التنقل بين الحلقات">
        {previousEpisode ? (
          <Link className="secondary-button" href={episodeHref(slug, previousEpisode.episode)} prefetch={false}>
            <ArrowIcon direction="right" /> الحلقة السابقة {previousEpisode.episode}
          </Link>
        ) : <span />}

        {nextEpisode && (
          <Link className="primary-button" href={episodeHref(slug, nextEpisode.episode)} prefetch={false}>
            الحلقة التالية {nextEpisode.episode} <ArrowIcon />
          </Link>
        )}
      </nav>
    </div>
  );
}
