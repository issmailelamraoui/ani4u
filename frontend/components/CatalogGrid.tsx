"use client";

import { useEffect, useRef, useState } from "react";
import CatalogCard from "@/components/CatalogCard";
import { parsePage, parseResponse, type AnimePage } from "@/lib/catalog-model";

export default function CatalogGrid({ initial }: { initial: AnimePage }) {
  const [items, setItems] = useState(initial.items);
  const [page, setPage] = useState(initial.page);
  const [hasNext, setHasNext] = useState(initial.hasNextPage);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);

  async function loadMore() {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/catalog/discover?page=${page + 1}`, { signal: controller.signal });
      if (!response.ok) throw new Error("Catalog unavailable");
      const { data } = parseResponse(await response.json(), parsePage);
      if (data.page !== page + 1) throw new Error("Unexpected page");
      const seen = new Set(items.map((item) => item.id));
      const added = data.items.filter((item) => !seen.has(item.id));
      setItems((previous) => [...previous, ...added]);
      setPage(data.page);
      setHasNext(data.hasNextPage && data.page < 100);
      setAnnouncement(`تمت إضافة ${added.length} عنوانًا.`);
    } catch {
      if (!controller.signal.aborted) setError("تعذّر تحميل المزيد. عناوينك الحالية ما زالت هنا؛ حاول مرة أخرى.");
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return <>
    <div className="nova-grid" aria-busy={loading}>{items.map((anime) => <CatalogCard key={anime.id} anime={anime} />)}</div>
    {!items.length && <p className="nova-empty">لا توجد عناوين حاليًا. جرّب العودة بعد قليل.</p>}
    <div className="nova-load-more">
      {error && <p role="alert">{error}</p>}
      <span className="sr-only" role="status">{announcement}</span>
      {hasNext ? <button type="button" className="nova-secondary" disabled={loading} onClick={loadMore}>{loading ? "جارٍ تحميل العناوين…" : error ? "حاول مجددًا" : "المزيد من العوالم"}<span aria-hidden="true">{loading ? "…" : "+"}</span></button> : items.length > 0 && <p>وصلت إلى نهاية هذه القائمة.</p>}
      <small>{items.length} عنوانًا في رحلتك</small>
    </div>
  </>;
}
