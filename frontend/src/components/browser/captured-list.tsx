"use client";

import { Bookmark, Cast, ListPlus, Play, Radar } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Thumb } from "@/components/common/thumb";
import { Button } from "@/components/ui/button";
import type { CapturedStream } from "@/lib/api/types";
import { hostOf, shortUrl } from "@/lib/format";
import { StreamBadges } from "./stream-meta";

/** Live list of every stream captured by the session (ranked best first). */
export function CapturedList({
  streams,
  snapshots = {},
  onPreview,
  onCast,
  onQueue,
  onBookmark,
  busy,
}: {
  streams: CapturedStream[];
  snapshots?: Record<string, string>;
  onPreview: (s: CapturedStream) => void;
  onCast: (s: CapturedStream) => void;
  /** Add to the device queue (same actions as the stream panel). */
  onQueue?: (s: CapturedStream) => void;
  onBookmark?: (s: CapturedStream) => void;
  busy?: boolean;
}) {
  if (!streams.length) {
    return (
      <div className="flex flex-col items-center gap-3 px-6 py-10 text-center text-sm text-muted-foreground">
        <div className="relative grid size-14 place-items-center rounded-2xl bg-muted">
          <Radar className="size-6 animate-pulse" />
        </div>
        <p>
          In ascolto del traffico della pagina…
          <br />
          Avvia il video nella pagina: gli stream compariranno qui.
        </p>
      </div>
    );
  }
  return (
    <ul className="space-y-2" aria-label="Stream catturati">
      <AnimatePresence initial={false}>
        {streams.map((s) => (
          <motion.li
            key={s.id}
            layout
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="space-y-2 rounded-xl border bg-card p-2.5"
          >
            <div className="flex gap-2.5">
              <Thumb src={s.thumbnail ?? snapshots[s.id] ?? null} className="aspect-video w-20" />
              <div className="min-w-0 flex-1 space-y-1">
                <StreamBadges stream={s} />
                <p className="truncate text-xs text-muted-foreground" title={s.url}>
                  {shortUrl(s.url, 48)}
                </p>
                {s.frame_url && s.frame_url !== s.page_url && (
                  <p className="truncate text-[0.68rem] text-muted-foreground/80">iframe: {hostOf(s.frame_url)}</p>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button variant="secondary" className="gap-1.5" onClick={() => onPreview(s)} aria-label={`Anteprima ${shortUrl(s.url, 30)}`}>
                <Play className="size-4" /> Anteprima
              </Button>
              <Button className="gap-1.5" disabled={busy} onClick={() => onCast(s)} aria-label={`Trasmetti ${shortUrl(s.url, 30)}`}>
                <Cast className="size-4" /> Cast
              </Button>
              {onQueue && (
                <Button variant="secondary" className="gap-1.5" disabled={busy} onClick={() => onQueue(s)} aria-label={`Aggiungi alla coda ${shortUrl(s.url, 30)}`}>
                  <ListPlus className="size-4" /> Coda
                </Button>
              )}
              {onBookmark && (
                <Button variant="secondary" className="gap-1.5" onClick={() => onBookmark(s)} aria-label={`Aggiungi ai preferiti ${shortUrl(s.url, 30)}`}>
                  <Bookmark className="size-4" /> Preferito
                </Button>
              )}
            </div>
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}
