import type { Metadata } from "next";
import type { CSSProperties } from "react";
import Image from "@/components/CatalogImage";
import Link from "next/link";
import { ArrowIcon } from "@/components/Icons";
import { artworkSources } from "@/lib/artwork";
import { notFound, unstable_rethrow } from "next/navigation";
import ApiErrorState from "@/components/ApiErrorState";
import CatalogEpisodes from "@/components/CatalogEpisodes";
import { CatalogError, getCatalogAnime } from "@/lib/catalog";
import { catalogHref, scoreText, statusText } from "@/lib/catalog-model";
import "../../../catalog.css";

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  try {
    const { data } = await getCatalogAnime((await params).slug);
    const description = data.type === "movie"
      ? `شاهد فيلم الأنمي ${data.title} مترجم أونلاين بجودة عالية وعلى عدة سيرفرات مشاهدة عبر ANI4U.`
      : `شاهد أنمي ${data.title} مترجم أونلاين، واستعرض الحلقات ومعلومات الأنمي وسيرفرات المشاهدة المتاحة على ANI4U.`;
    return { title: data.title, description, alternates: { canonical: catalogHref(data) } };
  } catch (error) {
    unstable_rethrow(error);
    return { title: "تفاصيل الأنمي", robots: { index: false } };
  }
}

export default async function CatalogDetails({ params }: Props) {
  const { slug } = await params;
  let result;
  try {
    result = await getCatalogAnime(slug);
  } catch (error) {
    unstable_rethrow(error);
    if (error instanceof CatalogError && error.status === 404) notFound();
    return <div className="page-shell route-message"><ApiErrorState title="تعذّر تحميل هذا العنوان" message="حاول مجددًا بعد قليل." retryHref={`/anime/catalog/${encodeURIComponent(slug)}`} /></div>;
  }
  const anime = result.data;
  const posters = artworkSources(anime);
  const backdrops = artworkSources(anime, "backdrop");
  const score = scoreText(anime.score);
  const season = ({ winter: "الشتاء", spring: "الربيع", summer: "الصيف", fall: "الخريف" } as Record<string, string>)[anime.season || ""];
  const trailer = anime.trailer && /^https:\/\/www\.youtube\.com\/watch\?v=[\w-]{11}$/.test(anime.trailer) ? anime.trailer : null;
  return <div className="nova-detail page-shell" style={{ "--art-accent": anime.accentColor || "#8d9aaa" } as CSSProperties}>
    <nav className="breadcrumb" aria-label="مسار التنقل"><Link href="/">الرئيسية</Link><span>/</span><Link href="/#discover">المكتبة</Link><span>/</span><span aria-current="page" dir="auto">{anime.title}</span></nav>
    <section className="nova-detail-panel" aria-labelledby="catalog-title">
      {backdrops[0] && <Image className="nova-detail-backdrop" src={backdrops[0]} fallbackSources={backdrops.slice(1)} alt="" fill sizes="100vw" />}
      <div className="nova-detail-poster">{posters[0] ? <Image src={posters[0]} fallbackSources={posters.slice(1)} alt={`ملصق ${anime.title}`} fill sizes="(max-width: 600px) 280px, (max-width: 1050px) 190px, 250px" loading="eager" /> : <span className="nova-art-placeholder">NOVA</span>}</div>
      <div className="nova-detail-copy"><span className="nova-kicker" dir="ltr">A WORLD WORTH EXPLORING</span><h1 id="catalog-title" dir="auto">{anime.title}</h1>
        <div className="nova-hero-meta">{score && <span className="nova-hero-score">★ {score}<small>{anime.score!.provider}</small></span>}<span>{statusText(anime.status)}</span>{anime.type && <span className="nova-format" dir="ltr">{anime.type.toUpperCase()}</span>}</div>
        <div className="nova-hero-genres">{anime.genres.map((genre) => <span key={genre}>{genre}</span>)}</div>
        {anime.description && <p className="nova-detail-synopsis" dir="auto" lang={anime.descriptionLanguage || undefined}>{anime.description}</p>}
        <dl className="nova-facts">
          {[["السنة", anime.year], ["الموسم", season], ["الحلقات المعلنة", anime.episodeCount], ["مدة الحلقة", anime.runtime ? `${anime.runtime} دقيقة` : null], ["الاستوديو", anime.studios.join("، ")], ["البلد", anime.country]].filter(([, value]) => value !== null && value !== undefined && value !== "").map(([label, value]) => <div key={label}><dt>{label}</dt><dd dir="auto">{value}</dd></div>)}
        </dl>
        <div className="nova-detail-actions"><a href="#episodes" className="nova-primary">استعرض الحلقات <span className="nova-arrow-down"><ArrowIcon /></span></a>{trailer && <a className="nova-secondary" href={trailer} target="_blank" rel="noopener noreferrer">الإعلان التشويقي <span aria-hidden="true">▷</span></a>}</div>
        {result.cache.status === "stale" && <p className="nova-cache-note">هذه آخر معلومات محفوظة لهذا العنوان.</p>}
      </div>
    </section>
    <CatalogEpisodes key={anime.slug} slug={anime.slug} title={anime.title} />
    <Link href="/#discover" className="nova-back-link"><ArrowIcon /> العودة إلى الاكتشاف</Link>
  </div>;
}
