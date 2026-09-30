"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { catalogEpisodeHref, externalProvidersUnavailable, parseEpisodes, parseSources, type EpisodeCursor, type EpisodeList, type EpisodeSource } from "@/lib/episode-model";

type EpisodeStatus = "loading" | "ready" | "empty" | "unavailable" | "choose-source" | "error";
const REQUEST_TIMEOUT_MS = 60_000;
const sourceKey = (source: EpisodeSource) => `${source.provider}:${source.slug}`;

async function request(params: Record<string, string>, controller: AbortController) {
  const timeout = new AbortController();
  const timer = window.setTimeout(() => timeout.abort(), REQUEST_TIMEOUT_MS);
  const abort = () => timeout.abort();
  controller.signal.addEventListener("abort", abort, { once: true });
  try {
    const url = `/api/catalog/episodes?${new URLSearchParams(params)}`;
    console.info(`[catalog episodes] frontend request ${url}`);
    const response = await fetch(url, { signal: timeout.signal, cache: "no-store" });
    const payload = await response.json();
    console.info(`[catalog episodes] frontend response status=${response.status}`, payload);
    if (!response.ok) {
      const detail = payload && typeof payload === "object" && typeof payload.detail === "string"
        ? payload.detail
        : "Episode lookup failed";
      throw new Error(`HTTP ${response.status}: ${detail}`);
    }
    return payload;
  } finally {
    window.clearTimeout(timer);
    controller.signal.removeEventListener("abort", abort);
  }
}

export default function CatalogEpisodes({ slug, title }: { slug: string; title: string }) {
  const [sources, setSources] = useState<EpisodeSource[]>([]);
  const [selected, setSelected] = useState("");
  const [data, setData] = useState<EpisodeList | null>(null);
  const [status, setStatus] = useState<EpisodeStatus>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [query, setQuery] = useState("");
  const [revision, setRevision] = useState(0);
  const [history, setHistory] = useState<EpisodeCursor[]>([]);
  const [failedCursor, setFailedCursor] = useState<EpisodeCursor | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const pending = useRef<AbortController | null>(null);
  const failedDirection = useRef<"forward" | "back" | "reset">("reset");
  const storageKey = `nova-episode-source:${slug}`;

  useEffect(() => {
    setHydrated(true);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    pending.current?.abort();
    pending.current = controller;
    async function resolve() {
      try {
        // Defer this transition until the effect is active. This avoids a
        // synchronous cascading render and lets an immediately superseded
        // effect exit without changing the panel.
        await Promise.resolve();
        if (controller.signal.aborted) return;
        setStatus("loading");
        setErrorMessage("");
        const choices = parseSources(await request({ slug, mode: "sources", ...(query ? { q: query } : {}) }, controller));
        if (controller.signal.aborted) return;
        setSources(choices.sources);
        let remembered = "";
        try { remembered = localStorage.getItem(storageKey) || ""; } catch { /* Storage is optional. */ }
        const rememberedByIdentity = choices.sources.find((item) => sourceKey(item) === remembered);
        const legacyRemembered = choices.sources.filter((item) => item.slug === remembered);
        const source = choices.sources.find((item) => item.slug === choices.selectedSource
          && item.provider === choices.selectedProvider && item.verified)
          || rememberedByIdentity
          || (legacyRemembered.length === 1 ? legacyRemembered[0] : undefined);
        setSelected(source ? sourceKey(source) : "");
        if (!choices.sources.length) {
          if (!controller.signal.aborted) setStatus(externalProvidersUnavailable(choices.availability) ? "unavailable" : "empty");
          return;
        }
        if (!source) {
          if (!controller.signal.aborted) setStatus("choose-source");
          return;
        }
        if (source) {
          const list = parseEpisodes(await request({
            slug,
            mode: "episodes",
            source: source.slug,
            provider: source.provider,
            page: "1",
            offset: "0",
            ...(query ? { q: query } : {}),
          }, controller), source);
          if (!controller.signal.aborted) {
            setData(list.externalUnavailable ? null : list);
            setStatus(list.externalUnavailable ? "unavailable" : list.items.length ? "ready" : "empty");
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setErrorMessage(error instanceof Error ? error.message : "Unknown episode error");
          setStatus("error");
        }
      } finally {
        // A future parser or transport failure must never strand this panel in
        // its loading copy. Aborted stale effects are owned by their successor.
        if (!controller.signal.aborted) setStatus((current) => current === "loading" ? "error" : current);
      }
    }
    void resolve();
    return () => controller.abort();
  }, [slug, query, revision, storageKey]);
  useEffect(() => () => pending.current?.abort(), []);

  async function load(source: EpisodeSource, cursor: EpisodeCursor, direction: "forward" | "back" | "reset" | "retry") {
    if (direction !== "retry") failedDirection.current = direction;
    const action = direction === "retry" ? failedDirection.current : direction;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setSelected(sourceKey(source));
    setStatus("loading");
    setErrorMessage("");
    setFailedCursor(cursor);
    if (direction === "reset") { setData(null); setHistory([]); }
    try {
      const list = parseEpisodes(await request({ slug, mode: "episodes", source: source.slug, provider: source.provider, page: String(cursor.page), offset: String(cursor.offset), ...(query ? { q: query } : {}) }, controller), source);
      if (controller.signal.aborted) return;
      if (list.externalUnavailable) {
        setData(null);
        setFailedCursor(null);
        setStatus("unavailable");
        return;
      }
      if (action === "forward" && data) setHistory((previous) => [...previous, { page: data.page, offset: data.offset }]);
      if (action === "back") setHistory((previous) => previous.slice(0, -1));
      setData(list);
      setFailedCursor(null);
      setStatus(list.items.length ? "ready" : "empty");
      try { localStorage.setItem(storageKey, sourceKey(source)); } catch { /* Storage is optional. */ }
    } catch (error) {
      if (!controller.signal.aborted) {
        setErrorMessage(error instanceof Error ? error.message : "Unknown episode error");
        setStatus("error");
      }
    } finally {
      if (!controller.signal.aborted) setStatus((current) => current === "loading" ? "error" : current);
    }
  }

  const selectedSource = sources.find((source) => sourceKey(source) === selected);

  return <section id="episodes" className="nova-episodes" aria-labelledby="episodes-heading">
    <div className="nova-section-heading"><div><span className="nova-kicker" dir="ltr">YOUR STORY STARTS HERE</span><h2 id="episodes-heading">حلقات الأنمي</h2><p>اختر حلقة للانتقال إلى المشاهدة.</p></div>{data && <span className="nova-episode-range">{data.items.length ? `${data.items[0].episode} – ${data.items.at(-1)!.episode}` : ""}</span>}</div>
    {sources.length > 0 && <div className="nova-source-picker"><label htmlFor="episode-source">{selected ? "العنوان المرتبط بالحلقات" : "اختر العنوان والموسم المطابق"}</label><select id="episode-source" value={selected} disabled={hydrated && status === "loading"} onChange={(event) => { const source = sources.find((item) => sourceKey(item) === event.target.value); if (source) void load(source, { page: 1, offset: 0 }, "reset"); }}><option value="" disabled>اختر عنوانًا لعرض حلقاته</option>{sources.map((source) => <option key={sourceKey(source)} value={sourceKey(source)}>{source.title}{source.verified ? " — مطابق" : ""}</option>)}</select></div>}
    {status === "loading" && <p className="nova-episode-message" role="status">جارٍ تحميل قائمة الحلقات…</p>}
    {status === "unavailable" && <p className="nova-episode-message" role="status">سيرفرات الحلقات الخارجية غير متاحة حالياً.</p>}
    {status === "error" && <div className="nova-episode-error" role="alert"><p>تعذّر تحميل الحلقات. {errorMessage && <small dir="ltr">{errorMessage}</small>}</p><button className="nova-secondary" type="button" onClick={() => {
      if (failedCursor && selectedSource) void load(selectedSource, failedCursor, "retry");
      else { setStatus("loading"); setErrorMessage(""); setRevision((value) => value + 1); }
    }}>حاول مجددًا</button></div>}
    {status === "choose-source" && <p className="nova-episode-message">وجدنا هذه العناوين. اختر الموسم المقصود لعرض حلقاته.</p>}
    {status === "empty" && !data && <p className="nova-episode-message">لم نعثر على مصدر حلقات مطابق لهذا الأنمي. جرّب اسمًا بديلًا أدناه.</p>}
    {data && <>
      <div className="nova-episode-toolbar"><span dir="auto">{data.sourceTitle}</span><label>مجموعة الحلقات <select aria-label="مجموعة الحلقات" value={data.page} disabled={hydrated && status === "loading"} onChange={(event) => selectedSource && void load(selectedSource, { page: Number(event.target.value), offset: 0 }, "reset")}>{Array.from({ length: data.totalPages }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1} / {data.totalPages}</option>)}</select></label></div>
      <div className="nova-episode-grid" aria-busy={status === "loading"}>{data.items.map((episode) => <Link key={episode.episode} href={catalogEpisodeHref(slug, episode.episode, episode.sources[0], data.requestedSource)} prefetch={false} className="nova-episode-tile"><span className="nova-episode-number" dir="ltr">{episode.episode}</span><span><strong>الحلقة {episode.episode}</strong><small dir="auto">{episode.title}</small></span><span aria-hidden="true">▷</span></Link>)}</div>
      {!data.items.length && <p className="nova-episode-message">لا توجد حلقات منشورة في هذه المجموعة حتى الآن.</p>}
      <nav className="nova-episode-pagination" aria-label="التنقل بين مجموعات الحلقات"><button type="button" className="nova-secondary" disabled={!history.length || !selectedSource || (hydrated && status === "loading")} onClick={() => selectedSource && void load(selectedSource, history.at(-1)!, "back")}>الحلقات السابقة</button><span>{data.items.length} حلقة معروضة</span><button type="button" className="nova-secondary" disabled={!data.next || !selectedSource || (hydrated && status === "loading")} onClick={() => data.next && selectedSource && void load(selectedSource, data.next, "forward")}>الحلقات التالية</button></nav>
    </>}
    <details className="nova-source-search"><summary>لم تجد الموسم المطلوب؟ ابحث باسم آخر</summary><form onSubmit={(event) => {
      event.preventDefault();
      const value = String(new FormData(event.currentTarget).get("q") || "").trim();
      if (value.length < 2) return;
      setStatus("loading"); setData(null); setSelected(""); setHistory([]); setFailedCursor(null); setSources([]); setQuery(value); setRevision((previous) => previous + 1);
    }}><label htmlFor="source-search">اسم الأنمي أو الموسم</label><div><input id="source-search" name="q" type="search" defaultValue={title.slice(0, 100)} minLength={2} maxLength={100} required dir="auto" /><button type="submit" className="nova-secondary" disabled={hydrated && status === "loading"}>بحث عن الحلقات</button></div></form></details>
    <noscript><p className="nova-episode-message">فعّل JavaScript لتحميل قائمة الحلقات واختيار الموسم.</p></noscript>
  </section>;
}
