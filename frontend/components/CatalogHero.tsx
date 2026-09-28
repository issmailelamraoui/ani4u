"use client";

import Image from "@/components/CatalogImage";
import Link from "next/link";
import { ArrowIcon } from "@/components/Icons";
import { artworkSources } from "@/lib/artwork";
import { useEffect, useState, type CSSProperties } from "react";
import { catalogHref, scoreText, statusText, type NovaAnime } from "@/lib/catalog-model";

export default function CatalogHero({ anime }: { anime: NovaAnime[] }) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const active = anime[index];

  useEffect(() => {
    if (paused || hovered || focused || anime.length < 2) return;
    const timer = window.setInterval(() => {
      if (!document.hidden && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) setIndex((i) => (i + 1) % anime.length);
    }, 9000);
    return () => window.clearInterval(timer);
  }, [paused, hovered, focused, anime.length, index]);

  if (!active) return null;
  const step = (direction: number) => setIndex((i) => (i + direction + anime.length) % anime.length);
  const score = scoreText(active.score);
  const posters = artworkSources(active);
  const backdrops = artworkSources(active, "backdrop");
  return (
    <section className="nova-hero" style={{ "--art-accent": active.accentColor || "#8d9aaa" } as CSSProperties} aria-label="عناوين تحت الضوء" aria-roledescription="عرض شرائح" onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} onFocusCapture={() => setFocused(true)} onBlurCapture={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(false); }}>
      <div className="nova-hero-scene" key={active.id}>
        {backdrops[0] && <Image className={`nova-hero-backdrop${active.seasonBackdrop || active.banner || active.animeBackdrop ? "" : " is-poster"}`} src={backdrops[0]} fallbackSources={backdrops.slice(1)} alt="" fill sizes="(max-width: 1320px) 100vw, 1240px" loading={index === 0 ? "eager" : "lazy"} fetchPriority={index === 0 ? "high" : "auto"} />}
        <div className="nova-hero-scrim" />
        <div className="nova-hero-orbit" aria-hidden="true" />
        <div className="nova-hero-copy" aria-live={paused || focused ? "polite" : "off"} aria-atomic="true">
          <div className="nova-hero-label"><span className="nova-live-dot" /><span>تحت الضوء</span><span className="nova-label-rule" /><span dir="ltr">NOVA SPOTLIGHT</span></div>
          <div className="nova-hero-meta">
            {score && <span className="nova-hero-score" title={`تقييم ${active.score!.provider}`}><span aria-hidden="true">★</span> {score}<small>/ 10</small></span>}
            {active.year && <span>{active.year}</span>}
            {active.type && <span className="nova-format" dir="ltr">{active.type.toUpperCase()}</span>}
            {active.episodeCount != null && <span>{active.episodeCount} حلقة</span>}
          </div>
          <h1 dir="auto">{active.title}</h1>
          <div className="nova-hero-genres">{active.genres.slice(0, 3).map((genre) => <span key={genre}>{genre}</span>)}</div>
          {active.description && <p className="nova-hero-synopsis" lang={active.descriptionLanguage || undefined} dir="auto">{active.description}</p>}
          <div className="nova-hero-actions"><Link href={catalogHref(active)} className="nova-primary" prefetch={false}>اكتشف الحكاية <span className="nova-arrow-diagonal"><ArrowIcon /></span></Link><a href="#discover" className="nova-quiet-link">تصفح المكتبة <span className="nova-arrow-down"><ArrowIcon /></span></a></div>
        </div>
        <div className="nova-hero-art" aria-hidden="true">
          <div className="nova-art-coordinate" dir="ltr">N° {String(index + 1).padStart(2, "0")} <span>THE NEXT WORLD</span></div>
          <div className="nova-hero-poster">{posters[0] ? <Image src={posters[0]} fallbackSources={posters.slice(1)} alt="" fill sizes="(max-width: 600px) 280px, (max-width: 800px) 1px, 260px" loading={index === 0 ? "eager" : "lazy"} /> : <span className="nova-art-placeholder">NOVA</span>}</div>
          <div className="nova-art-caption"><span>{statusText(active.status)}</span><span dir="ltr">{active.type?.toUpperCase()}</span></div>
        </div>
      </div>
      <div className="nova-hero-bottom">
        <div className="nova-slide-nav" aria-label="اختيار عنوان">{anime.map((item, i) => <button key={item.id} type="button" className={i === index ? "is-active" : ""} onClick={() => setIndex(i)} aria-label={`عرض ${item.title}`} aria-pressed={i === index}><span /></button>)}</div>
        <div className="nova-hero-controls"><span dir="ltr" className="nova-slide-count">{String(index + 1).padStart(2, "0")} <span>/ {String(anime.length).padStart(2, "0")}</span></span><button type="button" onClick={() => step(-1)} aria-label="العنوان السابق"><span className="nova-arrow-right"><ArrowIcon /></span></button><button type="button" onClick={() => step(1)} aria-label="العنوان التالي"><ArrowIcon /></button><button type="button" onClick={() => setPaused(!paused)} aria-label={paused ? "تشغيل العرض التلقائي" : "إيقاف العرض التلقائي"} aria-pressed={paused}>{paused ? "▷" : "Ⅱ"}</button></div>
      </div>
    </section>
  );
}
