import Image from "next/image";

/** Supplied ANI4U artwork, framed to exclude its surrounding empty canvas. */
export default function BrandLogo({ header = false }: { header?: boolean }) {
  if (header) return <span className="ani4u-logo ani4u-logo--header"><Image src="/brand/ani4u-header-logo.png" alt="ANI4U — Anime for You" width={1774} height={887} sizes="136px" loading="eager" /></span>;
  return <span className="ani4u-logo"><Image src="/brand/ani4u-logo.png" alt="ANI4U — Anime for You" width={164} height={123} sizes="164px" /></span>;
}
