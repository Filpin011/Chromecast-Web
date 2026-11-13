"use client";

import { Cast, Compass, ListPlus, MonitorPlay, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

/** Shrinkable primary column + one `auto` column per icon button (static strings for Tailwind). */
const COLUMNS = [
  "grid-cols-[minmax(0,1fr)]",
  "grid-cols-[minmax(0,1fr)_auto]",
  "grid-cols-[minmax(0,1fr)_auto_auto]",
  "grid-cols-[minmax(0,1fr)_auto_auto_auto]",
  "grid-cols-[minmax(0,1fr)_auto_auto_auto_auto]",
];

/**
 * The primary actions for any castable item (cast, plus the optional icon buttons).
 *
 * The primary column is `minmax(0,1fr)` (a plain `1fr` cannot shrink below the label's min-content
 * width and pushes the icon buttons out of the card on 360px phones). It is a container so the
 * label can drop "now" and its padding on narrow cards; `truncate` is the last-resort guarantee.
 */
export function MediaActions({
  onCast,
  onQueue,
  onFavorite,
  onOpenBrowser,
  onWatch,
  busy,
  favorited,
  className,
}: {
  onCast: () => void;
  onQueue?: () => void;
  onFavorite?: () => void;
  onOpenBrowser?: () => void;
  /** Play it in the full local player on this device. */
  onWatch?: () => void;
  busy?: boolean;
  favorited?: boolean;
  className?: string;
}) {
  const t = useT();
  const icons = [onWatch, onQueue, onFavorite, onOpenBrowser].filter(Boolean).length;
  return (
    <div className={cn("@container grid gap-2", COLUMNS[icons], className)}>
      <Button
        size="lg"
        onClick={onCast}
        disabled={busy}
        aria-label={t("media.castNow")}
        data-testid="cast-now"
        className="min-w-0 gap-2 rounded-xl px-3 @[22rem]:px-5"
      >
        <Cast className="size-5" />
        <span className="truncate @[22rem]:hidden">{t("media.castShort")}</span>
        <span className="hidden truncate @[22rem]:inline">{t("media.castNow")}</span>
      </Button>
      {onWatch && (
        <Button size="icon-lg" variant="secondary" aria-label={t("localPlayer.watchHere")} title={t("localPlayer.watchHere")} onClick={onWatch} className="rounded-xl">
          <MonitorPlay className="size-5" />
        </Button>
      )}
      {onQueue && (
        <Button size="icon-lg" variant="secondary" aria-label={t("media.addToQueue")} onClick={onQueue} disabled={busy} className="rounded-xl">
          <ListPlus className="size-5" />
        </Button>
      )}
      {onFavorite && (
        <Button
          size="icon-lg"
          variant="secondary"
          aria-label={t("media.addToFavorites")}
          aria-pressed={favorited}
          onClick={onFavorite}
          className="rounded-xl"
        >
          <Star className={cn("size-5", favorited && "fill-amber-400 text-amber-400")} />
        </Button>
      )}
      {onOpenBrowser && (
        <Button size="icon-lg" variant="secondary" aria-label={t("media.openInBrowser")} onClick={onOpenBrowser} className="rounded-xl">
          <Compass className="size-5" />
        </Button>
      )}
    </div>
  );
}
