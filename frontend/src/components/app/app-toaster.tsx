"use client";

import type { ToasterProps } from "sonner";
import { Toaster } from "@/components/ui/sonner";

/** Height of the remote-browser top bar (h-14) — immersive toasts sit just below it. */
const BROWSER_TOPBAR = "3.5rem";

type Placement = Pick<ToasterProps, "position" | "offset" | "mobileOffset">;

/**
 * Where toasts go so they never hide the controls they report on:
 * - phones: at the bottom, stacked above the tab bar + mini player (the page headers with the
 *   cast/device and menu buttons stay free);
 * - immersive remote browser (no tab bar, but a bottom toolbar and the stream panel): just below
 *   the 56px top bar, so the always-visible close (×) button stays reachable;
 * - desktop: bottom-right, away from page headers.
 * Offsets use the shell's --tabbar-h / --mini-h, so the Toaster must render inside the shell element.
 */
export function toasterPlacement(isDesktop: boolean, immersive: boolean): Placement {
  if (isDesktop) return { position: "bottom-right", offset: 16 };
  if (immersive) {
    const top = `calc(env(safe-area-inset-top) + ${BROWSER_TOPBAR} + 8px)`;
    return { position: "top-center", offset: { top }, mobileOffset: { top, left: 12, right: 12 } };
  }
  const bottom = "calc(var(--tabbar-h) + var(--mini-h) + 12px)";
  return { position: "bottom-center", offset: { bottom }, mobileOffset: { bottom, left: 12, right: 12 } };
}

export function AppToaster({ isDesktop, immersive }: { isDesktop: boolean; immersive: boolean }) {
  return <Toaster richColors closeButton {...toasterPlacement(isDesktop, immersive)} />;
}
