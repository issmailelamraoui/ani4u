import { ArrowIcon, SearchIcon } from "@/components/Icons";

export default function SearchForm({ query = "", id = "anime-search" }: { query?: string; id?: string }) {
  return (
    <form action="/search" method="get" className="search-form" role="search">
      <label className="sr-only" htmlFor={id}>اسم الأنمي أو الفيلم</label>
      <SearchIcon />
      <input id={id} type="search" name="q" defaultValue={query} placeholder="اسم الأنمي… ابدأ حكايتك هنا" minLength={2} maxLength={100} required dir="auto" />
      <button type="submit"><span>بحث</span><ArrowIcon /></button>
    </form>
  );
}
