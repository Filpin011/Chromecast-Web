"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { VideoPreview } from "@/components/media/video-preview";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { CapturedStream } from "@/lib/api/types";
import { useT } from "@/i18n";
import { shortUrl } from "@/lib/format";
import { StreamBadges } from "./stream-meta";

/**
 * In-app playback of a captured stream. The backend gives each captured stream a same-origin
 * `preview_url` (a `/proxy` path replaying the captured Referer/Cookie). Only when it is missing do we
 * ask the resolver for one, falling back to the raw URL.
 */
export function PreviewDialog({
  stream,
  title,
  onOpenChange,
}: {
  stream: CapturedStream | null;
  title?: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useT();
  const q = useQuery({
    queryKey: ["preview", stream?.url],
    queryFn: ({ signal }) => api.resolver.resolve(stream!.url, "direct", signal),
    enabled: !!stream && !stream.preview_url,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const media = q.data?.type === "media" ? q.data.media : null;
  const src = stream?.preview_url ?? media?.preview_url ?? (q.isError ? stream?.url : null);
  return (
    <Dialog open={!!stream} onOpenChange={onOpenChange}>
      <DialogContent className="gap-3 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="line-clamp-1 pr-8">{title || stream?.title || t("common.preview")}</DialogTitle>
          <DialogDescription className="truncate">{stream ? shortUrl(stream.url, 70) : ""}</DialogDescription>
        </DialogHeader>
        {stream && <StreamBadges stream={stream} />}
        {src ? (
          <VideoPreview src={src} mimeType={media?.mime_type ?? stream?.mime_type} controls />
        ) : (
          <div className="grid aspect-video place-items-center rounded-xl bg-black">
            <Loader2 className="size-7 animate-spin text-white/70" />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
