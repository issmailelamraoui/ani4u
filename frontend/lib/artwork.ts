/** Existing image/banner fields belong to the current title (including sequels). */
export type Artwork = {
  image?: string | null;
  banner?: string | null;
  seasonPoster?: string | null;
  animePoster?: string | null;
  seasonBackdrop?: string | null;
  animeBackdrop?: string | null;
};

export function artworkSources(art: Artwork, layout: "poster" | "backdrop" = "poster") {
  const seasonPoster = art.seasonPoster || art.image;
  const seasonBackdrop = art.seasonBackdrop || art.banner;
  const candidates = layout === "poster"
    ? [seasonPoster, art.animePoster, seasonBackdrop, art.animeBackdrop]
    : [seasonBackdrop, art.animeBackdrop, seasonPoster, art.animePoster];
  return [...new Set(candidates.filter((src): src is string => Boolean(src)))];
}
