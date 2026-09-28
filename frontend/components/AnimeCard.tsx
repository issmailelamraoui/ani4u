import Link from "next/link";
import { ArrowIcon } from "@/components/Icons";
import { getAnimeHref, getImageSrc, type Anime } from "@/lib/api";

export default function AnimeCard({ anime }: { anime: Anime }) {
  const imageSrc = getImageSrc(anime.image);

  return (
    <Link href={getAnimeHref(anime)} className="anime-card" prefetch={false}>
      <div className="anime-poster">
        {imageSrc ? (
          <img src={imageSrc} alt={`ملصق ${anime.title}`} loading="lazy" />
        ) : (
          <div className="poster-placeholder"><span dir="ltr">NOVA</span><small>الملصق غير متاح</small></div>
        )}
        <div className="poster-overlay" />
        <span className="type-chip">{anime.kind === "movie" ? "فيلم" : anime.kind === "special" ? "خاصة" : "أنمي"}</span>
        <span className="card-action">اكتشف التفاصيل<ArrowIcon /></span>
      </div>
      <h3 dir="auto">{anime.title}</h3>
      <span className="card-caption">{anime.kind === "movie" ? "فيلم أنمي" : anime.kind === "special" ? "حلقة أو أوفا خاصة" : "استكشف المواسم والحلقات"}</span>
    </Link>
  );
}
