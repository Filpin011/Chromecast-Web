import type { Favorite } from "@/lib/api/types";

/** Favorites saved as web pages (reopened in the remote browser), in list order. */
export const siteFavorites = (favs: Favorite[] | undefined): Favorite[] => (favs ?? []).filter((f) => f.kind === "site");

/** Favorites to cast. Rows from an older backend without `kind` count as media. */
export const mediaFavorites = (favs: Favorite[] | undefined): Favorite[] => (favs ?? []).filter((f) => f.kind !== "site");

/** The site favorite saved for exactly this page URL, if any. */
export const siteFavoriteFor = (favs: Favorite[] | undefined, url: string): Favorite | undefined =>
  (favs ?? []).find((f) => f.kind === "site" && f.input === url);

/** Deep link that opens `url` in a new remote-browser session. */
export const browserHref = (url: string): string => `/browser/?url=${encodeURIComponent(url)}`;
