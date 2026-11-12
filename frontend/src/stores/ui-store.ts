import { create } from "zustand";

type DeviceResolver = (deviceId: string | null) => void;

/** Dictionary key of the app-wide device sheet title (same minimal sheet everywhere, per the Browser UX reference). */
export const DEVICE_SHEET_TITLE = "devices.sheetTitle";

interface UiStore {
  nowPlayingOpen: boolean;
  devicePickerOpen: boolean;
  /** Resolver of a pending `requestDevice()` call. */
  pendingDevice: DeviceResolver | null;
  /**
   * True while the remote browser workspace is mounted: it brings its own top bar and bottom toolbar,
   * so the shell hides the phone tab bar (and the mini player) to give the page the full height.
   */
  immersive: boolean;
  setNowPlayingOpen: (open: boolean) => void;
  setDevicePickerOpen: (open: boolean) => void;
  /** Open the device sheet and resolve with the device the user connects to (or null if dismissed). */
  requestDevice: () => Promise<string | null>;
  /** Called by the device sheet after a successful connect. */
  resolveDevice: (deviceId: string | null) => void;
  setImmersive: (on: boolean) => void;
}

export const useUiStore = create<UiStore>()((set, get) => ({
  nowPlayingOpen: false,
  devicePickerOpen: false,
  pendingDevice: null,
  immersive: false,
  setNowPlayingOpen: (nowPlayingOpen) => set({ nowPlayingOpen }),
  setDevicePickerOpen: (open) => {
    if (!open) get().resolveDevice(null);
    set({ devicePickerOpen: open });
  },
  requestDevice: () =>
    new Promise<string | null>((resolve) => {
      get().pendingDevice?.(null);
      set({ pendingDevice: resolve, devicePickerOpen: true });
    }),
  resolveDevice: (deviceId) => {
    const p = get().pendingDevice;
    if (p) {
      set({ pendingDevice: null });
      p(deviceId);
    }
  },
  setImmersive: (immersive) => set({ immersive }),
}));

export function openDevicePicker() {
  useUiStore.setState({ devicePickerOpen: true });
}
