import type { BrowserServerMsg, BrowserSession, CapturedStream, PopupRequest, Viewport } from "@/lib/api/types";
import { upsertCaptured } from "@/lib/captured";
import type { SocketStatus } from "@/lib/ws/reconnecting-socket";

/** Defaults (contract): used for desktop mode and when the page isn't shown full-width on a phone. */
export const VIEWPORTS = {
  mobile: { width: 390, height: 844 },
  desktop: { width: 1280, height: 720 },
} as const satisfies Record<string, Viewport>;

export type ViewportMode = keyof typeof VIEWPORTS;

/** The backend emulates a mobile device (UA, touch) below this width. */
export const MOBILE_MAX_WIDTH = 799;
/** Below this width the workspace is the phone layout: the remote page spans the whole screen width. */
export const PHONE_LAYOUT_MAX = 767;
/** Remote browser chrome on phones: top bar (h-14) + bottom toolbar (h-13), safe areas excluded. */
export const BROWSER_CHROME_PX = 56 + 52;

export interface ScreenInfo {
  width: number;
  height: number;
  insetTop: number;
  insetBottom: number;
}

export function viewportMode(v: Viewport | null | undefined): ViewportMode {
  return v && v.width > MOBILE_MAX_WIDTH ? "desktop" : "mobile";
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Math.round(v)));

/**
 * Viewport to request for a new session so the remote page is drawn 1:1 in the space the phone actually
 * has (no letterboxing / down-scaling). Desktop mode and tablet/desktop layouts keep the contract defaults.
 */
export function fitViewport(mode: ViewportMode, screen: ScreenInfo | null): Viewport {
  if (mode === "desktop" || !screen || screen.width <= 0 || screen.width > PHONE_LAYOUT_MAX) return { ...VIEWPORTS[mode] };
  return {
    width: clamp(screen.width, 200, MOBILE_MAX_WIDTH),
    height: clamp(screen.height - BROWSER_CHROME_PX - screen.insetTop - screen.insetBottom, 200, 2560),
  };
}

/**
 * Mode for new sessions: the saved choice, else desktop on wide (tablet/desktop layout) screens, where a
 * phone-sized page would sit letterboxed in a large empty area, and mobile on phones.
 */
export function initialViewportMode(saved: string | null, screen: ScreenInfo | null): ViewportMode {
  if (saved === "desktop" || saved === "mobile") return saved;
  return screen && screen.width > PHONE_LAYOUT_MAX ? "desktop" : "mobile";
}

/** True when the session's viewport no longer matches the space available (e.g. after rotating the phone). */
export function viewportMismatch(current: Viewport, fitted: Viewport, tolerance = 0.12): boolean {
  const off = (a: number, b: number) => Math.abs(a - b) / Math.max(1, b);
  return off(current.width, fitted.width) > tolerance || off(current.height, fitted.height) > tolerance;
}

/** Current window size and safe-area insets (browser only). */
export function measureScreen(): ScreenInfo | null {
  if (typeof window === "undefined") return null;
  let insetTop = 0;
  let insetBottom = 0;
  try {
    const probe = document.createElement("div");
    probe.style.cssText =
      "position:fixed;visibility:hidden;pointer-events:none;padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)";
    document.body.appendChild(probe);
    const cs = getComputedStyle(probe);
    insetTop = parseFloat(cs.paddingTop) || 0;
    insetBottom = parseFloat(cs.paddingBottom) || 0;
    probe.remove();
  } catch {
    /* no DOM */
  }
  const vv = window.visualViewport;
  return {
    width: Math.round(vv?.width ?? window.innerWidth),
    height: Math.round(window.innerHeight),
    insetTop,
    insetBottom,
  };
}

export type BrowserLinkStatus = SocketStatus | "failed";

export interface BrowserViewState {
  session: BrowserSession | null;
  captured: CapturedStream[];
  /** Intrinsic size of the last frame (may differ from the viewport by the device pixel ratio). */
  frameSize: { width: number; height: number } | null;
  /** Live socket status; "failed" once it stopped reconnecting (manual retry needed). */
  status: BrowserLinkStatus;
  closed: boolean;
}

export const initialBrowserView: BrowserViewState = {
  session: null,
  captured: [],
  frameSize: null,
  status: "idle",
  closed: false,
};

export type BrowserViewAction =
  | BrowserServerMsg
  | { type: "init"; session: BrowserSession }
  | { type: "popup_resolved"; id: string }
  | { type: "status"; status: BrowserLinkStatus };

/** Pure reducer for the remote browser view (frames are drawn outside React; only their size lands here). */
export function browserViewReducer(state: BrowserViewState, action: BrowserViewAction): BrowserViewState {
  switch (action.type) {
    case "init":
      return { ...initialBrowserView, session: action.session, captured: action.session.captured ?? [] };
    case "session": {
      // The snapshot's list is authoritative: the backend prunes streams (MAX_CAPTURED, by score) and
      // acting on a pruned id would 404. Fields the snapshot omits (`thumbnail`) are merged from what
      // we already have for the same id.
      const fresh = action.data.captured;
      if (!fresh) return { ...state, session: action.data };
      const known = new Map(state.captured.map((c) => [c.id, c]));
      const captured = fresh.map((c) => {
        const prev = known.get(c.id);
        return prev ? { ...prev, ...c } : c;
      });
      return { ...state, session: action.data, captured };
    }
    case "captured":
      return { ...state, captured: upsertCaptured(state.captured, action.data) };
    case "frame":
      if (state.frameSize && state.frameSize.width === action.width && state.frameSize.height === action.height) {
        return state;
      }
      return { ...state, frameSize: { width: action.width, height: action.height } };
    case "blocked":
      if (!state.session || state.session.blocked_count === action.count) return state;
      return { ...state, session: { ...state.session, blocked_count: action.count } };
    case "popup": {
      if (!state.session) return state;
      const pending = state.session.pending_popups ?? [];
      if (pending.some((p) => p.id === action.data.id)) return state;
      return { ...state, session: { ...state.session, pending_popups: [...pending, action.data] } };
    }
    case "popup_resolved": {
      if (!state.session) return state;
      const pending = (state.session.pending_popups ?? []).filter((p) => p.id !== action.id);
      return { ...state, session: { ...state.session, pending_popups: pending } };
    }
    case "closed":
      return { ...state, closed: true };
    case "status":
      return state.status === action.status ? state : { ...state, status: action.status };
    default:
      return state;
  }
}

/** Size (CSS px) of the remote page used for coordinate mapping. */
export function pageSize(state: Pick<BrowserViewState, "session" | "frameSize">): { width: number; height: number } | null {
  return state.session?.viewport ?? state.frameSize ?? null;
}

/** Oldest popup/redirect prompt still waiting for a decision. */
export function nextPopup(session: Pick<BrowserSession, "pending_popups"> | null | undefined): PopupRequest | null {
  return session?.pending_popups?.[0] ?? null;
}
