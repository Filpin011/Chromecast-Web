"use client";

import { AlertCircle, Compass, Download, ListVideo, Play, ShieldCheck, Subtitles } from "lucide-react";
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
import { hostOf, SOURCE_LABEL } from "@/lib/format";
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
  if (previewing) {
    return <VideoPreview src={media.preview_url} mimeType={media.mime_type} poster={media.thumbnail} className="rounded-none" />;
  }
  return (
    <div className="relative aspect-video w-full bg-black">
      <Thumb src={media.thumbnail} className="size-full rounded-none bg-neutral-900" />
      <button
        type="button"
        onClick={onStart}
        aria-label="Anteprima sul telefono"
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
            {live ? <LiveBadge /> : <Badge variant="secondary">VOD</Badge>}
            <Badge variant="outline">{SOURCE_LABEL[media.source_kind]}</Badge>
            {media.proxied && (
              <Badge variant="outline" className="gap-1">
                <ShieldCheck className="size-3" /> Proxy
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
          <h2 className="truncate font-semibold">{name || "Playlist M3U"}</h2>
          <p className="text-sm text-muted-foreground">{channels.length} canali</p>
        </div>
        <Button onClick={doImport} disabled={importPl.isPending} className="gap-1.5 rounded-xl">
          <Download className="size-4" />
          Importa
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
          Importa la playlist per vedere tutti i {channels.length} canali
        </p>
      )}
    </motion.article>
  );
}

export function ResolveErrorCard({ error, input }: { error: unknown; input: string }) {
  const router = useRouter();
  const { cast, busy } = useCast();
  const isWeb = /^https?:/i.test(input);
  const detail = error instanceof ApiError ? error.detail : "Impossibile analizzare il link";
  return (
    <motion.article {...cardMotion} className="space-y-4 rounded-2xl border border-destructive/30 bg-destructive/5 p-4">
      <div className="flex gap-3">
        <AlertCircle className="mt-0.5 size-5 shrink-0 text-destructive" />
        <div className="space-y-1">
          <p className="font-medium">Nessun video trovato automaticamente</p>
          <p className="text-sm text-muted-foreground">{detail}</p>
        </div>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        {isWeb && (
          <Button size="lg" onClick={() => router.push(browserHref(input))} className="flex-1 gap-2 rounded-xl">
            <Compass className="size-5" />
            Apri nel browser interattivo
          </Button>
        )}
        <Button size="lg" variant="secondary" disabled={busy} onClick={() => cast({ input })} className="flex-1 rounded-xl">
          Trasmetti comunque
        </Button>
      </div>
    </motion.article>
  );
}

export function ResultSkeleton() {
  return (
    <div className="overflow-hidden rounded-2xl border bg-card" aria-busy="true" aria-label="Analisi in corso">
      <div className="aspect-video animate-pulse bg-muted" />
      <div className="space-y-3 p-4">
        <div className="h-4 w-24 animate-pulse rounded bg-muted" />
        <div className="h-5 w-3/4 animate-pulse rounded bg-muted" />
        <div className="h-12 animate-pulse rounded-xl bg-muted" />
      </div>
    </div>
  );
}

