"use client";

import type { ReactNode } from "react";
import { DevicePickerSheet } from "@/components/devices/device-picker-sheet";
import { MiniPlayer } from "@/components/player/mini-player";
import { NowPlayingSheet } from "@/components/player/now-playing-sheet";
import { isActivePlayback } from "@/hooks/use-app-state";
import { useIsDesktop } from "@/hooks/use-media-query";
import { selectActiveDevice, selectPlayer, useAppStore, type AppData } from "@/stores/app-store";
import { useUiStore } from "@/stores/ui-store";
import { AppToaster } from "./app-toaster";
import { BottomTabBar } from "./bottom-tab-bar";
import { ConnectionBanner } from "./connection-banner";
import { SidebarNav } from "./sidebar-nav";

/** Whether the active device has something worth a mini player (a boolean, so the shell doesn't re-render every tick). */
export function selectHasMiniPlayer(s: AppData): boolean {
  const p = selectPlayer(s, selectActiveDevice(s)?.id);
  return !!p?.connected && (isActivePlayback(p) || p.showing_idle_image || p.queue.length > 0);
}

export function AppShell({ children }: { children: ReactNode }) {
  const isDesktop = useIsDesktop();
  const hasMini = useAppStore(selectHasMiniPlayer);
  // The remote browser has its own top bar + bottom toolbar: on phones it gets the whole height.
  const immersive = useUiStore((s) => s.immersive) && !isDesktop;
  const showMini = hasMini && !immersive;

  return (
    <div data-mini={showMini ? "on" : "off"} data-tabbar={immersive ? "off" : "on"} className="flex min-h-dvh">
      <SidebarNav />
      <div className="flex min-w-0 flex-1 flex-col md:pl-(--sidebar-w)">
        {/* The immersive browser fills 100dvh itself and has its own reconnect overlay. */}
        {!immersive && <ConnectionBanner />}
        <main className="flex min-h-0 flex-1 flex-col">{children}</main>
      </div>
      <MiniPlayer visible={showMini} />
      {!immersive && <BottomTabBar />}
      <NowPlayingSheet />
      <DevicePickerSheet />
      {/* Inside the shell element so its --tabbar-h / --mini-h overrides reach the toast offsets. */}
      <AppToaster isDesktop={isDesktop} immersive={immersive} />
    </div>
  );
}
