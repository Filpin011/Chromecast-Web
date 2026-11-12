import { describe, expect, it } from "vitest";
import {
  browserViewReducer,
  fitViewport,
  initialBrowserView,
  nextPopup,
  pageSize,
  viewportMismatch,
  viewportMode,
} from "@/lib/browser-session";
import { qualityLabel, rankCaptured, upsertCaptured } from "@/lib/captured";
import type { BrowserSession, CapturedStream } from "@/lib/api/types";
import { makeCaptured } from "./fixtures";

const session: BrowserSession = {
  id: "b1",
  url: "https://site.example.com/",
  title: "Site",
  viewport: { width: 390, height: 844 },
  captured: [],
  created_at: "2026-11-12T10:00:00Z",
  adblock_enabled: true,
  blocked_count: 0,
  pending_popups: [],
};

describe("browserViewReducer", () => {
  it("initialises from the session and tracks captured streams", () => {
    let s = browserViewReducer(initialBrowserView, { type: "init", session: { ...session, captured: [makeCaptured()] } });
    expect(s.captured).toHaveLength(1);
    s = browserViewReducer(s, { type: "captured", data: makeCaptured({ id: "s2", kind: "progressive" }) });
    s = browserViewReducer(s, { type: "captured", data: makeCaptured({ id: "s1", quality: "720p HD" }) });
    expect(s.captured.map((c) => c.id)).toEqual(["s1", "s2"]);
    expect(s.captured[0].quality).toBe("720p HD");
  });

  it("updates the session and merges its captured list", () => {
    let s = browserViewReducer(initialBrowserView, { type: "init", session });
    s = browserViewReducer(s, { type: "session", data: { ...session, url: "https://other/", captured: [makeCaptured({ id: "z" })] } });
    expect(s.session?.url).toBe("https://other/");
    expect(s.captured.map((c) => c.id)).toEqual(["z"]);
  });

  it("drops streams the backend pruned and keeps known thumbnails the snapshot omits", () => {
    let s = browserViewReducer(initialBrowserView, { type: "init", session });
    s = browserViewReducer(s, { type: "captured", data: makeCaptured({ id: "keep", thumbnail: "data:image/jpeg;base64,AA" }) });
    s = browserViewReducer(s, { type: "captured", data: makeCaptured({ id: "pruned" }) });
    // later snapshots omit `thumbnail`; "pruned" fell out of MAX_CAPTURED server-side
    const withoutThumb: Partial<CapturedStream> = makeCaptured({ id: "keep", quality: "1080p" });
    delete withoutThumb.thumbnail;
    s = browserViewReducer(s, {
      type: "session",
      data: { ...session, captured: [withoutThumb as CapturedStream, makeCaptured({ id: "new" })] },
    });
    expect(s.captured.map((c) => c.id)).toEqual(["keep", "new"]);
    expect(s.captured[0].thumbnail).toBe("data:image/jpeg;base64,AA");
    expect(s.captured[0].quality).toBe("1080p");
  });

  it("only changes state when the frame size changes", () => {
    const a = browserViewReducer(initialBrowserView, { type: "frame", data: "x", width: 390, height: 844 });
    const b = browserViewReducer(a, { type: "frame", data: "y", width: 390, height: 844 });
    expect(b).toBe(a);
    expect(browserViewReducer(b, { type: "frame", data: "y", width: 780, height: 1688 }).frameSize).toEqual({ width: 780, height: 1688 });
  });

  it("marks closed and tracks socket status", () => {
    let s = browserViewReducer(initialBrowserView, { type: "closed" });
    expect(s.closed).toBe(true);
    s = browserViewReducer(s, { type: "status", status: "open" });
    expect(s.status).toBe("open");
  });

  it("prefers the session viewport for coordinate mapping", () => {
    expect(pageSize({ session, frameSize: { width: 780, height: 1688 } })).toEqual({ width: 390, height: 844 });
    expect(pageSize({ session: null, frameSize: { width: 10, height: 20 } })).toEqual({ width: 10, height: 20 });
    expect(viewportMode({ width: 1280, height: 720 })).toBe("desktop");
    expect(viewportMode(session.viewport)).toBe("mobile");
  });
});

describe("viewport fitting", () => {
  const phone = { width: 390, height: 844, insetTop: 47, insetBottom: 34 };

  it("fills the phone's free space instead of a fixed 390x844 (no letterboxing)", () => {
    // 844 - 56 (top bar) - 52 (toolbar) - safe areas
    expect(fitViewport("mobile", phone)).toEqual({ width: 390, height: 655 });
    expect(fitViewport("mobile", { width: 360, height: 640, insetTop: 0, insetBottom: 0 })).toEqual({ width: 360, height: 532 });
    expect(viewportMode(fitViewport("mobile", phone))).toBe("mobile");
  });

  it("keeps the defaults for desktop mode and wide layouts", () => {
    expect(fitViewport("desktop", phone)).toEqual({ width: 1280, height: 720 });
    expect(fitViewport("mobile", { width: 1024, height: 768, insetTop: 0, insetBottom: 0 })).toEqual({ width: 390, height: 844 });
    expect(fitViewport("mobile", null)).toEqual({ width: 390, height: 844 });
  });

  it("clamps to the backend's accepted range", () => {
    expect(fitViewport("mobile", { width: 150, height: 250, insetTop: 0, insetBottom: 0 })).toEqual({ width: 200, height: 200 });
  });

  it("detects a stale viewport after rotation", () => {
    expect(viewportMismatch({ width: 390, height: 655 }, { width: 390, height: 660 })).toBe(false);
    expect(viewportMismatch({ width: 390, height: 655 }, { width: 700, height: 250 })).toBe(true);
  });
});

describe("captured ranking", () => {
  it("orders by score, then resolution, master, kind", () => {
    const list = [
      makeCaptured({ id: "ad", score: -5, height: 1080 }),
      makeCaptured({ id: "sd", score: 5, height: 480 }),
      makeCaptured({ id: "hd", score: 5, height: 720 }),
      makeCaptured({ id: "mp4", score: 5, height: 720, kind: "progressive", is_master: null }),
      makeCaptured({ id: "best", score: 9, height: null }),
    ];
    expect(rankCaptured(list).map((s) => s.id)).toEqual(["best", "hd", "mp4", "sd", "ad"]);
  });

  it("derives quality labels", () => {
    expect(qualityLabel({ quality: "1080p FHD", height: 1 })).toBe("1080p FHD");
    expect(qualityLabel({ quality: null, height: 720 })).toBe("720p HD");
    expect(qualityLabel({ quality: null, height: 2160 })).toBe("4K UHD");
    expect(qualityLabel({ quality: null, height: 360 })).toBe("360p SD");
    expect(qualityLabel({ quality: null, height: null })).toBeNull();
  });

  it("upserts by id", () => {
    const l = upsertCaptured([makeCaptured()], makeCaptured({ id: "s1", title: "new" }));
    expect(l).toHaveLength(1);
    expect(l[0].title).toBe("new");
  });
});

describe("ad blocking / popups in the browser view", () => {
  const popup = {
    id: "p1",
    url: "https://ads.example.net/win",
    host: "ads.example.net",
    opener_url: session.url,
    created_at: "2026-11-12T10:00:01Z",
  };

  it("tracks the blocked-requests count", () => {
    let s = browserViewReducer(initialBrowserView, { type: "init", session });
    s = browserViewReducer(s, { type: "blocked", count: 7 });
    expect(s.session?.blocked_count).toBe(7);
    expect(browserViewReducer(s, { type: "blocked", count: 7 })).toBe(s);
  });

  it("queues popup prompts once and resolves them", () => {
    let s = browserViewReducer(initialBrowserView, { type: "init", session });
    expect(nextPopup(s.session)).toBeNull();
    s = browserViewReducer(s, { type: "popup", data: popup });
    s = browserViewReducer(s, { type: "popup", data: popup });
    s = browserViewReducer(s, { type: "popup", data: { ...popup, id: "p2" } });
    expect(s.session?.pending_popups.map((p) => p.id)).toEqual(["p1", "p2"]);
    expect(nextPopup(s.session)?.id).toBe("p1");
    s = browserViewReducer(s, { type: "popup_resolved", id: "p1" });
    expect(nextPopup(s.session)?.id).toBe("p2");
  });
});
