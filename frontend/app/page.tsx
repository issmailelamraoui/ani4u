import type { Metadata } from "next";
import Link from "next/link";
import CatalogCard from "@/components/CatalogCard";
import CatalogHero from "@/components/CatalogHero";
import CatalogGrid from "@/components/CatalogGrid";
import ApiErrorState from "@/components/ApiErrorState";
import SearchForm from "@/components/SearchForm";
import { getDiscovery } from "@/lib/discovery";
import "./catalog.css";

export const metadata: Metadata = { alternates: { canonical: "/" } };
export const dynamic = "force-dynamic";

export default async function Home() {
  const { result, error } = await getDiscovery();
  return (
    <div className="nova-home page-shell">
      <div className="nova-home-intro"><span dir="ltr">A UNIVERSE OF STORIES</span><p>عالمك القادم، أقرب مما تتخيّل.</p></div>
      {result?.data.featured.length ? <CatalogHero anime={result.data.featured} /> : <section className="nova-welcome"><span className="nova-kicker" dir="ltr">WELCOME TO NOVA</span><h1>لكل حكاية عالم.<br />اكتشف عالمك القادم.</h1><p>مسلسلات، أفلام، وحكايات تستحق وقتك.</p></section>}
      <div className="nova-search-strip"><div><span className="nova-kicker" dir="ltr">FOLLOW YOUR CURIOSITY</span><h2>أيّ عالم تبحث عنه؟</h2></div><SearchForm id="home-search" /></div>
      {error && <ApiErrorState title="المكتبة غير متاحة مؤقتًا" message={error} retryHref="/" />}
      {result?.cache.status === "stale" && <p className="nova-cache-note" role="status">نعرض آخر تحديث محفوظ للمكتبة. بعض المعلومات قد تتأخر قليلًا.</p>}
      {result && <>
        {result.data.topRated.length > 0 && <section className="nova-section" aria-labelledby="top-rated-title">
          <div className="nova-section-heading"><div><span className="nova-kicker" dir="ltr">THE ONES THAT STAY WITH YOU</span><h2 id="top-rated-title">حكايات تركت أثرًا<span className="nova-heading-dot">.</span></h2><p>الأعلى تقييمًا لدى مجتمع AniList</p></div><span className="nova-section-number" aria-hidden="true">01 / TOP RATED</span></div>
          <div className="nova-ranked-row" tabIndex={0} role="region" aria-label="الأعلى تقييمًا، مرر لمزيد من العناوين">{result.data.topRated.map((anime, i) => <CatalogCard key={anime.id} anime={anime} rank={i + 1} />)}</div>
        </section>}
        <section id="discover" className="nova-section nova-discover" aria-labelledby="discover-title">
          <div className="nova-section-heading"><div><span className="nova-kicker" dir="ltr">THERE IS ALWAYS ANOTHER WORLD</span><h2 id="discover-title">مساحة للاكتشاف<span className="nova-heading-dot">.</span></h2><p>عناوين محبوبة، وبدايات لمغامرتك التالية.</p></div><Link href="/search" className="nova-quiet-link">ابحث عن عنوان <span aria-hidden="true">↗</span></Link></div>
          <CatalogGrid initial={result.data.discover} />
        </section>
      </>}
      <div className="nova-endnote"><span dir="ltr">NOVA</span><p>ابقَ فضوليًا. الحكاية التالية تستحق.</p><span aria-hidden="true">✦</span></div>
    </div>
  );
}
