import { Thumb } from "@/components/common/thumb";
import { Spinner } from "@/components/ui/spinner";
import type { PlayerState } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/** Artwork with an animated equalizer overlay while playing, or a spinner while `loading`. */
export function Artwork({
  player,
  className,
  eq = true,
  loading = false,
  spinnerClassName = "size-5",
}: {
  player: Pick<PlayerState, "thumbnail" | "title" | "player_state">;
  className?: string;
  eq?: boolean;
  loading?: boolean;
  spinnerClassName?: string;
}) {
  const playing = player.player_state === "PLAYING";
  return (
    <div className={cn("relative", className)}>
      <Thumb src={player.thumbnail} alt={player.title ?? ""} className="size-full rounded-[inherit]" />
      {eq && playing && !loading && (
        <div aria-hidden className="absolute right-1 bottom-1 flex h-3.5 items-end gap-[2px] rounded-sm bg-black/50 p-[3px]">
          {[0, 0.2, 0.4].map((d) => (
            <span key={d} className="animate-eq w-[3px] rounded-full bg-white" style={{ animationDelay: `${d}s`, height: "100%" }} />
          ))}
        </div>
      )}
      {/* Overlay, not a replacement: the artwork keeps its size, so nothing around it moves. */}
      <div
        aria-hidden
        data-testid="artwork-spinner"
        data-visible={loading}
        className={cn(
          "pointer-events-none absolute inset-0 grid place-items-center rounded-[inherit] bg-black/45 transition-opacity duration-300",
          loading ? "opacity-100" : "opacity-0",
        )}
      >
        {loading && <Spinner className={cn("text-white drop-shadow", spinnerClassName)} />}
      </div>
    </div>
  );
}
