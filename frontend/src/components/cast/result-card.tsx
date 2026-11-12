"use client";

import { AlertCircle, Compass, Download, ListVideo, Play, RotateCw, ShieldCheck, Subtitles } from "lucide-react";
import { motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Thumb } from "@/components/common/thumb";
import { VideoPreview } from "@/components/media/video-preview";
import { LiveBadge } from "@/components/player/live-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAddFavorite, useImportPlaylist } from "@/hooks/queries";
import { channelRequest, useCast } from "@/hooks/use-cast";
import { ApiError } from "@/lib/api";
import type { Channel, ResolvedMedia } from "@/lib/api/types";
import { useT } from "@/i18n";
import { hostOf, SOURCE_LABEL_KEY } from "@/lib/format";
import { errorDescription } from "@/lib/query";
import { cn } from "@/lib/utils";
import { MediaActions } from "./media-actions";

export function browserHref(url: string): string {
  return `/browser/?url=${encodeURIComponent(url)}`;
}

const cardMotion = {
  initial: { opacity: 0, y: 12, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -8 },
  transition: { type: "spring" as const, stiffness: 380, damping: 32 },
};

/**
 * Tap-to-preview: the phone only pulls the stream when asked to. IPTV providers often allow a single
 * connection, so an autoplaying preview would compete with the Chromecast (and double the bandwidth).
 */
function PreviewArea({
  media,
  previewing,
  onStart,
}: {
  media: ResolvedMedia;
  previewing: boolean;
  onStart: () => void;
}) {
  const t = useT();
  if (previewing) {
    return <VideoPreview src={media.preview_url} mimeType={media.mime_type} poster={media.thumbnail} className="rounded-none" />;
  }
  return (
    <div className="relative aspect-video w-full bg-black">
      <Thumb src={media.thumbnail} className="size-full rounded-none bg-neutral-900" />
      <button
        type="button"
        onClick={onStart}
        aria-label={t("result.previewOnPhone")}
        className="absolute inset-0 grid place-items-center bg-black/25 text-white transition-colors active:bg-black/40"
      >
        <span className="grid size-14 place-items-center rounded-full bg-black/55 backdrop-blur">
          <Play className="size-6 translate-x-px" fill="currentColor" />
        </span>
      </button>
    </div>
  );
}

export function MediaResultCard({ media }: { media: ResolvedMedia }) {
  const t = useT();
  const { cast, busy } = useCast();
  const [previewing, setPreviewing] = useState(false);
  const addFav = useAddFavorite();
  const router = useRouter();
  const live = media.stream_type === "LIVE";
  const input = media.original_input;
  const isWeb = /^https?:/i.test(input);

  return (
    <motion.article {...cardMotion} className="overflow-hidden rounded-2xl border bg-card shadow-sm">
      <PreviewArea media={media} previewing={previewing} onStart={() => setPreviewing(true)} />
      <div className="space-y-4 p-4">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {live ? <LiveBadge /> : <Badge variant="secondary">{t("result.vod")}</Badge>}
            <Badge variant="outline">{t(SOURCE_LABEL_KEY[media.source_kind])}</Badge>
            {media.proxied && (
              <Badge variant="outline" className="gap-1">
                <ShieldCheck className="size-3" /> {t("result.proxy")}
              </Badge>
            )}
            {media.subtitles.length > 0 && (
              <Badge variant="outline" className="gap-1">
                <Subtitles className="size-3" /> {media.subtitles.length}
              </Badge>
            )}
          </div>
          <h2 className="line-clamp-2 text-lg leading-snug font-semibold">{media.title}</h2>
          <p className="truncate text-xs text-muted-foreground">{hostOf(input)}</p>
        </div>
        <MediaActions
          busy={busy}
          onCast={() => {
            // release the stream before the Chromecast opens it (single-connection IPTV)
            setPreviewing(false);
            void cast({ input, kind: media.source_kind, title: media.title });
          }}
          onQueue={() => cast({ input, kind: media.source_kind, title: media.title, enqueue: true })}
          onFavorite={() =>
            addFav.mutate({ title: media.title, input, source_kind: media.source_kind, thumbnail: media.thumbnail })
          }
          onOpenBrowser={isWeb ? () => router.push(browserHref(input)) : undefined}
        />
      </div>
    </motion.article>
  );
}

export function PlaylistResultCard({
  name,
  channels,
  input,
}: {
  name: string;
  channels: Channel[];
  input: string;
}) {
  const t = useT();
  const { cast, busy } = useCast();
  const importPl = useImportPlaylist();
  const router = useRouter();
  const isUrl = /^https?:/i.test(input);
  const doImport = () =>
    importPl.mutate(isUrl ? { url: input, name } : { content: input, name }, {
      onSuccess: (p) => router.push(`/playlists/view/?id=${encodeURIComponent(p.id)}`),
    });

  return (
    <motion.article {...cardMotion} className="overflow-hidden rounded-2xl border bg-card shadow-sm">
      <div className="flex items-center gap-3 border-b p-4">
        <div className="grid size-12 place-items-center rounded-xl bg-primary/15 text-primary">
          <ListVideo className="size-6" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-semibold">{name || t("result.m3uPlaylist")}</h2>
          <p className="text-sm text-muted-foreground">{t.plural("playlists.channels", channels.length)}</p>
        </div>
        <Button onClick={doImport} disabled={importPl.isPending} className="gap-1.5 rounded-xl">
          <Download className="size-4" />
          {t("playlists.importShort")}
        </Button>
      </div>
      <ul className="divide-y">
        {channels.slice(0, 6).map((c) => (
          <li key={c.id}>
            <button
              type="button"
              disabled={busy}
              onClick={() => cast(channelRequest(c))}
              className="flex min-h-14 w-full items-center gap-3 px-4 text-left active:bg-muted"
            >
              <Thumb src={c.logo} className="size-9" fit="contain" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{c.name}</span>
                {c.group && <span className="block truncate text-xs text-muted-foreground">{c.group}</span>}
              </span>
              <Play className="size-4 text-muted-foreground" />
            </button>
          </li>
        ))}
      </ul>
      {channels.length > 6 && (
        <p className="px-4 py-3 text-center text-xs text-muted-foreground">
          {t("result.importToSeeAll", { count: channels.length })}
        </p>
      )}
    </motion.article>
  );
}

/** Reasons where the backend never got a page: the interactive browser would fail the same way. */
const UNREACHABLE_REASONS = new Set(["connect_failed", "fetch_failed"]);

export function ResolveErrorCard({
  error,
  input,
  onRetry,
  retrying = false,
}: {
  error: unknown;
  input: string;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  const t = useT();
  const router = useRouter();
  const { cast, busy } = useCast();
  const isWeb = /^https?:/i.test(input);
  const apiErr = error instanceof ApiError ? error : null;
  const detail = apiErr ? errorDescription(apiErr) : t("result.analyseFailed");
  const reason = apiErr?.reason;
  const unreachable = reason !== undefined && UNREACHABLE_REASONS.has(reason);
  const httpError = reason === "upstream_http";
  // the site itself failed: retrying is the main action (a real browser may still get past an HTTP error)
  const siteFailed = unreachable || httpError;
  const heading = unreachable ? t("result.siteUnreachable") : httpError ? t("result.siteError") : t("result.noVideoFound");
  const showBrowser = isWeb && !unreachable;
  // stacked full-width on phones (fixed h-12), side by side from sm; `flex-1` in a column would collapse the height
  const btn = "w-full rounded-xl sm:w-auto sm:flex-1";

  return (
    <motion.article
      {...cardMotion}
      data-testid="resolve-error"
      className="space-y-4 rounded-2xl border border-destructive/30 bg-destructive/5 p-4"
    >
      <div className="flex gap-3">
        <AlertCircle className="mt-0.5 size-5 shrink-0 text-destructive" />
        <div className="min-w-0 space-y-1">
          <p className="font-medium">{heading}</p>
          <p className="text-sm break-words text-muted-foreground">{detail}</p>
        </div>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {siteFailed && onRetry && (
          <Button size="lg" onClick={onRetry} disabled={retrying} className={cn(btn, "gap-2")}>
            <RotateCw className="size-5" />
            {t("common.retry")}
          </Button>
        )}
        {showBrowser && (
          <Button
            size="lg"
            variant={siteFailed ? "outline" : "default"}
            onClick={() => router.push(browserHref(input))}
            className={cn(btn, "gap-2")}
          >
            <Compass className="size-5" />
            {t("result.openInteractive")}
          </Button>
        )}
        <Button
          size="lg"
          variant={siteFailed && !onRetry ? "default" : "secondary"}
          disabled={busy}
          onClick={() => cast({ input })}
          className={btn}
        >
          {t("result.castAnyway")}
        </Button>
      </div>
    </motion.article>
  );
}

export function ResultSkeleton() {
  const t = useT();
  return (
    <div className="overflow-hidden rounded-2xl border bg-card" aria-busy="true" aria-label={t("result.analysing")}>
      <div className="aspect-video animate-pulse bg-muted" />
      <div className="space-y-3 p-4">
        <div className="h-4 w-24 animate-pulse rounded bg-muted" />
        <div className="h-5 w-3/4 animate-pulse rounded bg-muted" />
        <div className="h-12 animate-pulse rounded-xl bg-muted" />
      </div>
    </div>
  );
}

