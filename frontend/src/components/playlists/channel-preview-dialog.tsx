"use client";

import { useQuery } from "@tanstack/react-query";
import { Cast, ListPlus, Loader2 } from "lucide-react";
import { VideoPreview } from "@/components/media/video-preview";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { Channel } from "@/lib/api/types";
import { channelInput } from "@/lib/channels";
import { shortUrl } from "@/lib/format";
import { useT } from "@/i18n";
import { errorMessage } from "@/lib/query";

/**
 * Preview a playlist channel in the app before sending it to the TV. The resolver turns the channel
 * (with its headers folded into the input) into a same-origin `preview_url` that replays them.
 */
export function ChannelPreviewDialog({
  channel,
  onOpenChange,
  onCast,
  onQueue,
  busy,
}: {
  channel: Channel | null;
  onOpenChange: (open: boolean) => void;
  onCast: (c: Channel) => void;
  onQueue: (c: Channel) => void;
  busy?: boolean;
}) {
  const t = useT();
  const input = channel ? channelInput(channel) : null;
  const q = useQuery({
    queryKey: ["preview", input],
    queryFn: ({ signal }) => api.resolver.resolve(input as string, undefined, signal),
    enabled: !!input,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const media = q.data?.type === "media" ? q.data.media : null;
  return (
    <Dialog open={!!channel} onOpenChange={onOpenChange}>
      <DialogContent className="gap-3 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="line-clamp-1 pr-8">{channel?.name ?? t("common.preview")}</DialogTitle>
          <DialogDescription className="truncate">{channel ? shortUrl(channel.url, 70) : ""}</DialogDescription>
        </DialogHeader>
        {media?.preview_url ? (
          <VideoPreview src={media.preview_url} mimeType={media.mime_type} poster={channel?.logo} controls />
        ) : q.isError || (q.isSuccess && !media?.preview_url) ? (
          <div className="grid aspect-video place-items-center rounded-xl bg-black p-4 text-center text-xs text-white/80">
            {q.isError ? errorMessage(q.error, t("channels.previewUnavailable")) : t("channels.previewUnavailableChannel")}
          </div>
        ) : (
          <div className="grid aspect-video place-items-center rounded-xl bg-black">
            <Loader2 className="size-7 animate-spin text-white/70" />
          </div>
        )}
        {channel && (
          <DialogFooter className="grid grid-cols-[1fr_auto] gap-2 sm:flex">
            <Button size="lg" className="gap-2" disabled={busy} onClick={() => onCast(channel)}>
              <Cast className="size-5" /> {t("media.castNow")}
            </Button>
            <Button size="lg" variant="secondary" className="gap-2" disabled={busy} onClick={() => onQueue(channel)}>
              <ListPlus className="size-5" /> {t("common.queue")}
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
