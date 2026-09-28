"use client";

import Image, { type ImageProps } from "next/image";
import { useState } from "react";

/** Keep artwork failures local: a missing CDN image must not break a title card. */
export default function CatalogImage({ src, fallbackSources = [], alt, ...props }: Omit<ImageProps, "src"> & { src: string; fallbackSources?: string[] }) {
  const [failed, setFailed] = useState<string[]>([]);
  const current = [src, ...fallbackSources].find((candidate) => candidate && !failed.includes(candidate));
  if (!current) return <span className={`nova-art-placeholder ${props.className || ""}`} role={alt ? "img" : undefined} aria-label={alt ? `${alt} — الصورة غير متاحة` : undefined} aria-hidden={alt ? undefined : true}>NOVA</span>;
  return <Image {...props} src={current} alt={alt} onError={() => setFailed((previous) => [...previous, current])} />;
}
