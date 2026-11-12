"use client";

import { AnimatePresence, motion } from "motion/react";
import { Cast, ImageIcon } from "lucide-react";
import { isActivePlayback, useActivePlayer } from "@/hooks/use-app-state";
import { useCommand } from "@/hooks/use-command";
import { useNow } from "@/hooks/use-now";
import { extrapolatePosition, isLive } from "@/lib/player";

import { useUiStore } from "@/stores/ui-store";
import { Artwork } from "./artwork";
import { LiveBadge } from "./live-badge";
import { PlayPauseButton } from "./play-pause-button";

/** Thin progress line for VOD at the top of the mini player. */
function MiniProgress({ position, duration }: { position: number; duration: number }) {
  const pct = duration > 0 ? Math.min(100, (position / duration) * 100) : 0;
  return (
    <div className="absolute inset-x-3 top-0 h-0.5 overflow-hidden rounded-full bg-foreground/10">
      <div className="h-full bg-primary transition-[width] duration-500 ease-linear" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Persistent compact player above the tab bar; tap to expand into "Now Playing". */
export function MiniPlayer({ visible }: { visible: boolean }) {
  const { device, player, receivedAt } = useActivePlayer();
  const { run } = useCommand(device?.id);
  const open = useUiStore((s) => s.setNowPlayingOpen);
  const playing = player?.player_state === "PLAYING";
  const now = useNow(1000, visible && playing);

  return (
    <AnimatePresence>
      {visible && player && device && (
        <motion.div
          key="mini"
          initial={{ y: 24, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 24, opacity: 0 }}
          transition={{ type: "spring", stiffness: 420, damping: 34 }}
          className="fixed right-0 bottom-(--tabbar-h) left-0 z-40 px-2 pb-2 md:left-(--sidebar-w) md:px-6 md:pb-4"
        >
          {/* The open area is a real <button> and play/pause is its sibling, not a nested control:
              keyboard activation of either one only does that one thing (and no nested-interactive). */}
          <div className="relative mx-auto flex h-16 max-w-3xl items-center rounded-2xl border bg-popover/90 pr-1.5 shadow-xl shadow-black/20 backdrop-blur-xl transition-transform has-[[data-slot=mini-open]:active]:scale-[0.99]">
            {!isLive(player) && player.duration ? (
              <MiniProgress position={extrapolatePosition(player, receivedAt, now)} duration={player.duration} />
            ) : null}
            <button
              type="button"
              data-slot="mini-open"
              aria-label="Apri player"
              onClick={() => open(true)}
              className="flex h-full min-w-0 flex-1 items-center gap-3 rounded-2xl pr-2 pl-2 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <Artwork player={player} className="size-12 rounded-lg" />
              <span className="block min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold" data-testid="mini-title">
                  {player.showing_idle_image && !isActivePlayback(player) ? "Immagine di attesa" : (player.title ?? "Senza titolo")}
                </span>
                <span className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
                  {player.showing_idle_image && !isActivePlayback(player) ? (
                    <ImageIcon className="size-3" />
                  ) : (
                    <Cast className="size-3 text-primary" />
                  )}
                  <span className="truncate">{device.name}</span>
                  {isActivePlayback(player) && isLive(player) && <LiveBadge className="h-4 px-1.5 text-[0.55rem]" />}
                </span>
              </span>
            </button>
            {isActivePlayback(player) && (
              <PlayPauseButton state={player.player_state} onToggle={() => run("toggle")} />
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

