"use client";

import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";
import { useActivePlayer } from "@/hooks/use-app-state";
import { selectActiveDevice, useAppStore } from "@/stores/app-store";
import { useIsDesktop } from "@/hooks/use-media-query";
import { useT } from "@/i18n";
import { useUiStore } from "@/stores/ui-store";
import { NowPlayingContent } from "./now-playing";

const FULL = "calc(100dvh - env(safe-area-inset-top) - 0.5rem)";

export function NowPlayingSheet() {
  const t = useT();
  const open = useUiStore((s) => s.nowPlayingOpen);
  const setOpen = useUiStore((s) => s.setNowPlayingOpen);
  // only a boolean here: the per-tick player state is subscribed by the content, mounted while open
  const hasPlayer = useAppStore((s) => {
    const d = selectActiveDevice(s);
    return !!d && !!s.appState?.players[d.id];
  });
  const isDesktop = useIsDesktop();
  const visible = open && hasPlayer;

  return (
    <Drawer
      open={visible}
      onOpenChange={setOpen}
      swipeDirection={isDesktop ? "right" : "down"}
      showSwipeHandle={!isDesktop}
    >
      <DrawerContent
        className="sm:data-[swipe-axis=x]:[--drawer-content-width:28rem]"
        style={isDesktop ? undefined : ({ height: FULL, ["--drawer-content-max-height" as string]: FULL } as React.CSSProperties)}
      >
        <DrawerTitle className="sr-only">{t("player.nowPlaying")}</DrawerTitle>
        {visible && <ActiveNowPlaying onClose={() => setOpen(false)} />}
      </DrawerContent>
    </Drawer>
  );
}

function ActiveNowPlaying({ onClose }: { onClose: () => void }) {
  const { device, player, receivedAt } = useActivePlayer();
  if (!device || !player) return null;
  return <NowPlayingContent device={device} player={player} receivedAt={receivedAt} onClose={onClose} />;
}
