"use client";

import { Bookmark, Cast, ListPlus, MonitorPlay, Play, X } from "lucide-react";
import { motion } from "motion/react";
import { Thumb } from "@/components/common/thumb";
import { Button } from "@/components/ui/button";
import type { CapturedStream } from "@/lib/api/types";
import { qualityLabel } from "@/lib/captured";
import { hostOf } from "@/lib/format";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { StreamBadges } from "./stream-meta";

export interface StreamPanelProps {
  /** Ranked streams, best first. */
  streams: CapturedStream[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Client-side snapshots used when the backend gave no thumbnail. */
  snapshots: Record<string, string>;
  pageTitle: string | null;
  onDismiss: () => void;
  onCast: (s: CapturedStream) => void;
  onQueue: (s: CapturedStream) => void;
  onPlay: (s: CapturedStream) => void;
  onBookmark: (s: CapturedStream) => void;
  /** Play it in the full local player on this device. */
  onWatch?: (s: CapturedStream) => void;
  busy?: boolean;
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
  primary,
  disabled,
}: {
  icon: typeof Cast;
  label: string;
  onClick: () => void;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex min-h-16 min-w-0 flex-col items-center justify-center gap-1 rounded-2xl text-xs font-semibold transition active:scale-95 disabled:opacity-50",
        primary ? "bg-primary text-primary-foreground shadow-lg shadow-primary/25" : "bg-muted text-foreground",
      )}
    >
      <Icon className="size-5" />
      <span className="max-w-full truncate px-1">{label}</span>
    </button>
  );
}

/** Slides up over the remote page when a video stream is detected. */
export function StreamPanel({
  streams,
  selectedId,
  onSelect,
  snapshots,
  pageTitle,
  onDismiss,
  onCast,
  onQueue,
  onPlay,
  onBookmark,
  onWatch,
  busy,
}: StreamPanelProps) {
  const t = useT();
  const stream = streams.find((s) => s.id === selectedId) ?? streams[0];
  if (!stream) return null;
  const title = stream.title || pageTitle || hostOf(stream.page_url);
  return (
    <motion.section
      role="region"
      aria-label={t("panel.detected")}
      initial={{ y: "110%" }}
      animate={{ y: 0 }}
      exit={{ y: "110%" }}
      transition={{ type: "spring", stiffness: 380, damping: 36 }}
      className="absolute inset-x-0 bottom-0 z-20 rounded-t-3xl border-t bg-popover/95 p-4 pb-3 shadow-[0_-12px_40px_-12px_rgba(0,0,0,0.5)] backdrop-blur-xl"
    >
      <div className="flex gap-3">
        <Thumb src={stream.thumbnail ?? snapshots[stream.id] ?? null} className="aspect-video w-32 shrink-0 rounded-xl" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="text-[0.68rem] font-semibold tracking-wider text-primary uppercase">{t("panel.detected")}</p>
          <h3 className="line-clamp-2 text-sm leading-snug font-semibold" data-testid="stream-title">
            {title}
          </h3>
          <StreamBadges stream={stream} />
        </div>
        <Button variant="ghost" size="icon" aria-label={t("panel.close")} onClick={onDismiss} className="-mt-1 -mr-1">
          <X className="size-5" />
        </Button>
      </div>

      {streams.length > 1 && (
        <div className="-mx-4 mt-3 flex gap-2 overflow-x-auto px-4 no-scrollbar" role="tablist" aria-label={t("browser.detectedStreams")}>
          {streams.map((s, i) => (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={s.id === stream.id}
              onClick={() => onSelect(s.id)}
              className={cn(
                "h-9 shrink-0 rounded-full border px-3 text-xs font-medium transition-colors",
                s.id === stream.id ? "border-primary bg-primary/15 text-primary" : "text-muted-foreground",
              )}
            >
              {qualityLabel(s) ?? t("panel.streamN", { n: i + 1 })}
              {s.is_live ? ` · ${t("player.live")}` : ""}
            </button>
          ))}
        </div>
      )}

      <div className={cn("mt-3 grid gap-2", onWatch ? "grid-cols-5" : "grid-cols-4")}>
        <ActionButton icon={Cast} label={t("common.cast")} primary onClick={() => onCast(stream)} disabled={busy} />
        <ActionButton icon={ListPlus} label={t("common.queue")} onClick={() => onQueue(stream)} disabled={busy} />
        <ActionButton icon={Play} label={t("common.preview")} onClick={() => onPlay(stream)} />
        {onWatch && <ActionButton icon={MonitorPlay} label={t("localPlayer.watchHere")} onClick={() => onWatch(stream)} />}
        <ActionButton icon={Bookmark} label={t("common.favorite")} onClick={() => onBookmark(stream)} />
      </div>
    </motion.section>
  );
}
