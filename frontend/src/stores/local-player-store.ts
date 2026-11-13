import { create } from "zustand";

/** What the local player needs to play something on this device. */
export interface LocalSource {
  /** Same-origin path or absolute URL the browser can load (normally a backend `/proxy` path). */
  src: string;
  mimeType?: string | null;
}

export interface LocalMedia {
  title: string;
  /** Second line under the title (site, playlist group, …). */
  subtitle?: string | null;
  poster?: string | null;
  /** The source, or how to get it (e.g. ask the resolver for a playable `preview_url`). */
  source: LocalSource | ((signal: AbortSignal) => Promise<LocalSource>);
  /** Seconds to start from (on-demand media only; ignored for live streams). */
  startAt?: number | null;
  /**
   * "Send to TV": plays the same item on the Chromecast. `resumeAt` is the local position for on-demand
   * media (null for live), so the TV can carry on from there. Missing = no such button.
   */
  onCast?: (resumeAt: number | null) => void;
}

interface LocalPlayerStore {
  media: LocalMedia | null;
  open: (media: LocalMedia) => void;
  close: () => void;
}

/** The "Watch here" player: one at a time, mounted by the app shell, openable from any screen. */
export const useLocalPlayerStore = create<LocalPlayerStore>()((set) => ({
  media: null,
  open: (media) => set({ media }),
  close: () => set({ media: null }),
}));

export function openLocalPlayer(media: LocalMedia) {
  useLocalPlayerStore.getState().open(media);
}
