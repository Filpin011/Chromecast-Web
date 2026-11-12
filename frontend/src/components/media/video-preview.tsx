"use client";

import { AlertTriangle, Loader2, RotateCw, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { backendUrl } from "@/lib/config";
import { canPlayNativeHls, isDashSource, isHlsSource } from "@/lib/media";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

type Status = "loading" | "playing" | "error" | "unsupported";

/**
 * In-app preview: hls.js for HLS (native on Safari/iOS), <video> for progressive.
 * Muted autoplay by default; tap the speaker to unmute.
 */
export function VideoPreview({
  src,
  mimeType,
  poster,
  className,
  controls = false,
}: {
  src: string;
  mimeType?: string | null;
  poster?: string | null;
  className?: string;
  controls?: boolean;
}) {
  const tr = useT();
  const ref = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [muted, setMuted] = useState(true);
  /** Bumped by "Retry" to tear the player down and load the source again. */
  const [attempt, setAttempt] = useState(0);
  const url = backendUrl(src);
  const failed = status === "error" || status === "unsupported";

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    let destroyed = false;
    let hls: { destroy: () => void } | null = null;
    const reset = setTimeout(() => !destroyed && setStatus("loading"), 0);

    const start = () => {
      video.play().catch(() => {
        /* autoplay may be blocked; controls/tap will start it */
      });
    };

    if (isDashSource(url, mimeType)) {
      const t = setTimeout(() => !destroyed && setStatus("unsupported"), 0);
      return () => {
        destroyed = true;
        clearTimeout(t);
        clearTimeout(reset);
      };
    }

    if (isHlsSource(url, mimeType) && !canPlayNativeHls(video)) {
      import("hls.js")
        .then(({ default: Hls }) => {
          if (destroyed) return;
          if (!Hls.isSupported()) {
            setStatus("unsupported");
            return;
          }
          const inst = new Hls({ lowLatencyMode: true, backBufferLength: 30, maxBufferLength: 20 });
          hls = inst;
          inst.on(Hls.Events.ERROR, (_e, data) => {
            if (data.fatal && !destroyed) setStatus("error");
          });
          inst.on(Hls.Events.MANIFEST_PARSED, start);
          inst.loadSource(url);
          inst.attachMedia(video);
        })
        .catch(() => !destroyed && setStatus("error"));
    } else {
      video.src = url;
      start();
    }

    return () => {
      destroyed = true;
      clearTimeout(reset);
      hls?.destroy();
      video.removeAttribute("src");
      video.load?.();
    };
  }, [url, mimeType, attempt]);

  return (
    <div className={cn("relative aspect-video overflow-hidden rounded-xl bg-black", className)}>
      <video
        ref={ref}
        data-testid="video-preview"
        // hidden on failure: the message replaces it (native controls would otherwise show through)
        className={cn("size-full object-contain", failed && "invisible")}
        poster={poster ? backendUrl(poster) : undefined}
        muted={muted}
        playsInline
        autoPlay
        controls={controls && !failed}
        onPlaying={() => setStatus("playing")}
        onError={() => setStatus("error")}
      />
      {status === "loading" && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <Loader2 className="size-7 animate-spin text-white/80" />
        </div>
      )}
      {failed && (
        <div role="alert" className="absolute inset-0 grid place-items-center bg-black p-4 text-center text-xs text-white/80">
          <div className="flex flex-col items-center gap-2">
            <AlertTriangle className="size-5" />
            {status === "unsupported"
              ? tr("preview.unsupported")
              : tr("preview.error")}
            {status === "error" && (
              <button
                type="button"
                onClick={() => setAttempt((n) => n + 1)}
                className="mt-1 inline-flex h-9 items-center gap-1.5 rounded-full bg-white/15 px-4 text-xs font-medium text-white active:bg-white/25"
              >
                <RotateCw className="size-3.5" /> {tr("common.retry")}
              </button>
            )}
          </div>
        </div>
      )}
      {!controls && status === "playing" && (
        <button
          type="button"
          aria-label={muted ? tr("preview.unmute") : tr("preview.mute")}
          onClick={() => setMuted((m) => !m)}
          className="absolute right-2 bottom-2 grid size-9 place-items-center rounded-full bg-black/55 text-white backdrop-blur"
        >
          {muted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
        </button>
      )}
    </div>
  );
}
