import { Thumb } from "@/components/common/thumb";
import type { PlayerState } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/** Artwork with an animated equalizer overlay while playing. */
export function Artwork({
  player,
  className,
  eq = true,
}: {
  player: Pick<PlayerState, "thumbnail" | "title" | "player_state">;
  className?: string;
  eq?: boolean;
}) {
  const playing = player.player_state === "PLAYING";
  return (
    <div className={cn("relative", className)}>
      <Thumb src={player.thumbnail} alt={player.title ?? ""} className="size-full rounded-[inherit]" />
      {eq && playing && (
        <div aria-hidden className="absolute right-1 bottom-1 flex h-3.5 items-end gap-[2px] rounded-sm bg-black/50 p-[3px]">
          {[0, 0.2, 0.4].map((d) => (
            <span key={d} className="animate-eq w-[3px] rounded-full bg-white" style={{ animationDelay: `${d}s`, height: "100%" }} />
          ))}
        </div>
      )}
    </div>
  );
}
