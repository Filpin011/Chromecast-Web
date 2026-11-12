import { LiveBadge } from "@/components/player/live-badge";
import { Badge } from "@/components/ui/badge";
import type { CapturedStream } from "@/lib/api/types";
import { KIND_LABEL, qualityLabel } from "@/lib/captured";

export function StreamBadges({ stream }: { stream: CapturedStream }) {
  const q = qualityLabel(stream);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {stream.is_live && <LiveBadge />}
      {q && <Badge variant="secondary">{q}</Badge>}
      <Badge variant="outline" data-testid="kind-badge">
        {KIND_LABEL[stream.kind]}
        {stream.kind === "hls" && stream.is_master ? " master" : ""}
      </Badge>
    </div>
  );
}
