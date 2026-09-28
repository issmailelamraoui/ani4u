import type { Metadata } from "next";
import Link from "next/link";
import { unstable_rethrow } from "next/navigation";
import CatalogCard from "@/components/CatalogCard";
import ApiErrorState from "@/components/ApiErrorState";
import { SearchIcon } from "@/components/Icons";
import SearchForm from "@/components/SearchForm";
import { CatalogError, getCatalogPage } from "@/lib/catalog";
import type { AnimePage, CatalogResponse } from "@/lib/catalog-model";
import "../catalog.css";

type SearchPageProps = { searchParams: Promise<{ q?: string | string[]; page?: string | string[] }> };

function getQuery(value: string | string[] | undefined) {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? "";
}

export async function generateMetadata({ searchParams }: SearchPageProps): Promise<Metadata> {
  const query = getQuery((await searchParams).q);
  return { title: query ? `نتائج البحث عن ${query}` : "ابحث عن عالمك القادم", robots: { index: false, follow: true } };
}

export default async function SearchPage({ searchParams }: SearchPageProps) {
  const params = await searchParams;
  const query = getQuery(params.q);
  const page = Number(getQuery(params.page) || "1");
  let result: CatalogResponse<AnimePage> | undefined;
  let errorMessage: string | undefined;
  if (query) {
    try {
      result = await getCatalogPage(page, query);
    } catch (error) {
      unstable_rethrow(error);
      errorMessage = error instanceof CatalogError ? error.publicMessage : "تعذّر إتمام البحث الآن. يرجى المحاولة مجددًا بعد قليل.";
    }
  }
  return (
    <div className="search-page nova-search-page page-shell">
      <div className="search-head">
        <span className="eyebrow" dir="ltr">FIND YOUR NEXT WORLD</span>
        <h1>حكاية جديدة تنتظرك.</h1>
        <p>ابحث عن أنمي تحبّه، موسم تنتظره، أو مغامرة لم تكتشفها بعد.</p>
        <SearchForm query={query} />
        <div className="quick-links"><span>جرّب البحث عن</span>{["Haikyuu", "Black Clover", "One Piece", "Bleach"].map((title) => <Link key={title} href={`/search?q=${encodeURIComponent(title)}`} dir="ltr">{title}</Link>)}</div>
      </div>
      {errorMessage && <ApiErrorState message={errorMessage} title="تعذّر تحميل نتائج البحث" retryHref={`/search?q=${encodeURIComponent(query)}`} />}
      {result?.cache.status === "stale" && <p className="nova-cache-note">نعرض آخر نتائج محفوظة لهذا البحث.</p>}
      {result && (
        <section aria-labelledby="search-results-title">
          <div className="results-title"><h2 id="search-results-title">نتائج البحث عن <bdi>{query}</bdi></h2><span className="result-count" data-testid="result-count" data-result-count={result.data.items.length}>{result.data.items.length} نتيجة في الصفحة {page}</span></div>
          {result.data.items.length > 0 ? (
            <div className="nova-grid">{result.data.items.map((anime) => <CatalogCard key={anime.id} anime={anime} />)}</div>
          ) : (
            <div className="empty-state"><span className="empty-icon"><SearchIcon /></span><h2>لم نجد عنوانًا بهذا الاسم</h2><p>جرّب الاسم بالإنجليزية، أو ابحث بجزء أقصر من العنوان.</p></div>
          )}
          <nav className="nova-pagination" aria-label="صفحات نتائج البحث">
            {page > 1 && <Link className="nova-secondary" prefetch={false} href={`/search?q=${encodeURIComponent(query)}&page=${page - 1}`}>الصفحة السابقة</Link>}
            <span>الصفحة {page}</span>
            {result.data.hasNextPage && page < 100 && <Link className="nova-secondary" prefetch={false} href={`/search?q=${encodeURIComponent(query)}&page=${page + 1}`}>الصفحة التالية</Link>}
          </nav>
        </section>
      )}
      {!query && <div className="search-invitation"><span className="empty-icon"><SearchIcon /></span><h2>كل عالم يبدأ باسم</h2><p>اكتب اسم الأنمي في الأعلى لتستكشف المواسم والأفلام المتاحة.</p><span dir="ltr" className="invitation-wordmark" aria-hidden="true">DISCOVER. EXPLORE. REPEAT.</span></div>}
    </div>
  );
}
