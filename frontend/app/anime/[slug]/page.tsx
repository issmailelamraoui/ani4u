import type { Metadata } from "next";
import Link from "next/link";
import { notFound, unstable_rethrow } from "next/navigation";
import AnimeCard from "@/components/AnimeCard";
import ApiErrorState from "@/components/ApiErrorState";
import {
  ApiError,
  getAnime,
  getAnimeEpisodes,
  getAnimeHref,
  getImageSrc,
  getRelatedAnime,
  type Anime,
  type EpisodesResponse,
} from "@/lib/api";
import { getAni4uCatalogAnime, getAni4uEpisodes, toAni4uAnime, type Ani4uCatalogAnime } from "@/lib/ani4u-stream";

type Props = { params: Promise<{ slug: string }> };

function failureMessage(error: unknown) {
  unstable_rethrow(error);
  if (error instanceof ApiError) return error.publicMessage;
  console.error("[Anime detail]", error);
  return "تعذّر تحميل بيانات الأنمي. حاول مرة أخرى بعد قليل.";
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  try {
    const anime = await getAnime(slug);
    if (!anime) throw new Error("Legacy metadata not found");
    const description = `شاهد أنمي ${anime.title} مترجم أونلاين، واستعرض الحلقات ومعلومات الأنمي وسيرفرات المشاهدة المتاحة على ANI4U.`;
    return {
      title: anime.title,
      description,
      alternates: { canonical: getAnimeHref(anime) },
      openGraph: {
        title: anime.title,
        description,
        url: getAnimeHref(anime),
        type: "website",
        images: anime.image ? [{ url: anime.image, alt: anime.title }] : [],
      },
    };
  } catch (error) {
    try {
      const local = await getAni4uCatalogAnime(slug);
      if (!local) throw error;
      const movie = local.content_type === "movie";
      const description = movie
        ? `شاهد فيلم الأنمي ${local.title} مترجم أونلاين بجودة عالية وعلى عدة سيرفرات مشاهدة عبر ANI4U.`
        : `شاهد ${local.title} مترجم أونلاين واستعرض سيرفرات المشاهدة المتاحة على ANI4U.`;
      return { title: local.title, description, alternates: { canonical: `/anime/${encodeURIComponent(local.slug)}` } };
    } catch {
      failureMessage(error);
      return { title: "تعذّر تحميل الأنمي", robots: { index: false } };
    }
  }
}

export default async function AnimePage({ params }: Props) {
  const { slug } = await params;
  let local: Ani4uCatalogAnime | null = null;
  let anime: Anime | null;
  try {
    // Preserve the existing detail API (including poster, metadata, and title)
    // and use local data only when that source has no matching record.
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
      return <div className="page-shell route-message"><h1>تعذّر تحميل الأنمي</h1><ApiErrorState message={failureMessage(error)} retryHref={`/anime/${encodeURIComponent(slug)}`} /></div>;
    }
  }
  if (!anime) notFound();

  const imageSrc = getImageSrc(anime.image);

  let episodes: EpisodesResponse | undefined;
  let episodeError: string | undefined;
  let related: Anime[] | undefined;
  let relatedError: string | undefined;
  try {
    // Keep the old episode response as the base: it contains its original URLs
    // and metadata. Exact local coverage is appended only when absent.
    episodes = await getAnimeEpisodes(slug);
    try {
      local = await getAni4uCatalogAnime(slug);
      const localEpisodes = local && await getAni4uEpisodes(slug);
      if (localEpisodes?.content_type === "series") {
        const merged = new Map(episodes.episodes.map((episode) => [episode.episode, episode]));
        for (const episode of localEpisodes.episodes) {
          if (!merged.has(episode.episode)) merged.set(episode.episode, { episode: episode.episode, title: `الحلقة ${episode.episode}`, url: `local:${slug}:${episode.season}:${episode.episode}` });
        }
        episodes = { ...episodes, count: merged.size, episodes: [...merged.values()].sort((a, b) => a.episode - b.episode) };
      }
    } catch { /* Existing episode data stays available if local enrichment is down. */ }
  } catch (error) {
    try {
      local = local || await getAni4uCatalogAnime(slug);
      const localEpisodes = local && await getAni4uEpisodes(slug);
      if (!localEpisodes) throw error;
      episodes = {
        url: "", count: localEpisodes.count, cached: true,
        episodes: localEpisodes.content_type === "series"
          ? localEpisodes.episodes.map((episode) => ({ episode: episode.episode, title: `الحلقة ${episode.episode}`, url: `local:${slug}:${episode.season}:${episode.episode}` }))
          : [],
      };
    } catch {
      episodeError = failureMessage(error);
    }
  }
  if (anime.url) {
    try {
      related = await getRelatedAnime(anime);
    } catch (error) {
      relatedError = failureMessage(error);
    }
  }

  return (
    <div className="detail-page page-shell">
      <nav className="breadcrumb" aria-label="مسار التنقل">
        <Link href="/">الرئيسية</Link><span aria-hidden="true">/</span>
        <Link href="/search">الأنمي</Link><span aria-hidden="true">/</span>
        <span aria-current="page"><bdi>{anime.title}</bdi></span>
      </nav>
      <section className="detail-hero" aria-labelledby="anime-title">
        {imageSrc && <div className="detail-backdrop" aria-hidden="true"><img src={imageSrc} alt="" /></div>}
        <div className="detail-content">
          <div className="detail-poster">
            {imageSrc
              ? <img src={imageSrc} alt={`ملصق ${anime.title}`} />
              : <div className="poster-placeholder"><span>NOVA</span><small>الملصق غير متاح</small></div>}
          </div>
          <div className="detail-info">
            <span className="detail-kicker" dir="ltr">YOUR NEXT STORY</span>
            <h1 id="anime-title" dir="auto">{anime.title}</h1>
            <div className="detail-meta">
              <span>{anime.kind === "movie" ? "فيلم أنمي" : anime.kind === "special" ? "محتوى خاص" : "مسلسل أنمي"}</span>
              {episodes && <span data-episode-count={episodes.count}>{episodes.count} حلقة متاحة</span>}
            </div>
            <p>استكشف الحلقات المتاحة والعناوين المرتبطة بهذه الحكاية.</p>
            {local && local.content_type !== "series" ? <Link className="primary-button" href={`/watch/${encodeURIComponent(slug)}/0`}>شاهد الآن</Link> : episodes && episodes.count > 0 && <a className="primary-button" href="#episodes">استعرض الحلقات</a>}
          </div>
        </div>
      </section>

      <section id="episodes" className="episode-section" aria-labelledby="episodes-title">
        <div className="section-heading">
          <div><span className="eyebrow" dir="ltr">EPISODES</span><h2 id="episodes-title">حلقات الأنمي</h2></div>
          {episodes && <span className="result-count">{episodes.count} حلقة</span>}
        </div>
        {episodeError && <ApiErrorState title="تعذّر تحميل الحلقات" message={episodeError} retryHref={getAnimeHref(anime)} />}
        {episodes && (episodes.count > 0 ? (
          <>
            <p className="episode-note">اختر حلقة لفتح صفحة المشاهدة وتحديد السيرفر المناسب.</p>
            <div className="episode-grid">
              {episodes.episodes.map((episode) => (
                <Link
                  className="episode-tile"
                  data-episode={episode.episode}
                  href={`/watch/${encodeURIComponent(slug)}/${encodeURIComponent(String(episode.episode))}`}
                  key={episode.url}
                  prefetch={false}
                >
                  <span className="episode-number" aria-hidden="true">{String(episode.episode).padStart(2, "0")}</span>
                  <div><h3>الحلقة {episode.episode}</h3>{episode.title !== `الحلقة ${episode.episode}` && <p dir="auto">{episode.title}</p>}</div>
                </Link>
              ))}
            </div>
          </>
        ) : <div className="empty-state"><h3>{local?.content_type === "special" ? "محتوى خاص قابل للمشاهدة" : "لا توجد حلقات متاحة حالياً"}</h3><p>{local && local.content_type !== "series" ? "استخدم زر المشاهدة أعلاه لفتح المشغّل؛ لا يُسجّل الفيلم أو المحتوى الخاص كحلقة مرقمة." : anime.kind === "movie" ? "هذا عنوان فيلم، ولم يوفّر المصدر قائمة حلقات له." : "لم يوفّر المصدر حلقات لهذا العنوان بعد."}</p></div>)}
      </section>

      {(relatedError || (related && related.length > 0)) && (
        <section className="related-section" aria-labelledby="related-title">
          <div className="section-heading"><div><span className="eyebrow" dir="ltr">MORE TO EXPLORE</span><h2 id="related-title">مواسم وعناوين مرتبطة</h2><p>عناوين تحمل اسماً مشابهاً، دون ترتيب زمني مفترض.</p></div></div>
          {relatedError && <ApiErrorState title="تعذّر تحميل العناوين المرتبطة" message={relatedError} retryHref={getAnimeHref(anime)} />}
          {related && <div className="anime-grid">{related.map((entry) => <AnimeCard key={entry.slug} anime={entry} />)}</div>}
        </section>
      )}
    </div>
  );
}
