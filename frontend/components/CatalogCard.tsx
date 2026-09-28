import Image from "@/components/CatalogImage";
import Link from "next/link";
import { catalogHref, scoreText, statusText, type NovaAnime } from "@/lib/catalog-model";

export default function CatalogCard({ anime, rank }: { anime: NovaAnime; rank?: number }) {
  const score = scoreText(anime.score);
  return (
    <Link className="nova-card" href={catalogHref(anime)} prefetch={false}>
      <div className="nova-card-art">
        {anime.image ? <Image src={anime.image} alt={`ملصق ${anime.title}`} fill sizes="(max-width: 540px) 43vw, (max-width: 900px) 28vw, 200px" /> : <span className="nova-art-placeholder">NOVA</span>}
        <span className="nova-card-shade" />
        {score && <span className="nova-rating" title={`${anime.score!.provider}: ${anime.score!.value}/${anime.score!.scale}`} aria-label={`تقييم ${anime.score!.provider}: ${score} من 10`}><span aria-hidden="true">★</span> {score}</span>}
        <span className="nova-card-type" dir="ltr">{anime.type?.toUpperCase() || "ANIME"}</span>
        <span className="nova-card-reveal">استكشف الحكاية <span aria-hidden="true">↗</span></span>
      </div>
      <div className="nova-card-caption">
        {rank !== undefined && <span className="nova-rank" aria-label={`الترتيب ${rank}`}>{String(rank).padStart(2, "0")}</span>}
        <div><h3 dir="auto">{anime.title}</h3><p>{anime.year && <span>{anime.year}</span>}<span>{statusText(anime.status)}</span></p></div>
      </div>
    </Link>
  );
}
