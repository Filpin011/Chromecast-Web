"use client";

import { Star } from "lucide-react";
import { useSiteFavorite } from "@/hooks/queries";
import { useT } from "@/i18n";
import { haptic } from "@/lib/haptics";
import { cn } from "@/lib/utils";

/** Star inside the URL pill: saves the current page as a site favorite, filled (tap = remove) when saved. */
export function SiteFavoriteButton({ sessionId, url }: { sessionId: string; url: string }) {
  const t = useT();
  const { saved, toggle, busy } = useSiteFavorite(sessionId, url);
  if (!/^https?:/i.test(url)) return null;
  return (
    <button
      type="button"
      onClick={() => {
        haptic(8);
        toggle();
      }}
      disabled={busy}
      aria-pressed={saved}
      aria-label={saved ? t("sites.remove") : t("sites.add")}
      title={saved ? t("sites.remove") : t("sites.add")}
      className={cn(
        "grid size-11 shrink-0 place-items-center rounded-full active:bg-foreground/10 disabled:opacity-60",
        saved ? "text-amber-500" : "text-muted-foreground",
      )}
    >
      <Star className="size-4.5" fill={saved ? "currentColor" : "none"} />
    </button>
  );
}
