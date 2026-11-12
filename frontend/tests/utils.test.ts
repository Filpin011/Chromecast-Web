import { describe, expect, it } from "vitest";
import { parseHostInput } from "@/components/devices/device-picker";
import { columnsFor } from "@/components/playlists/channel-list";
import { nextActiveTracks } from "@/components/player/track-picker";
import { backendUrl } from "@/lib/config";
import { formatBytes, formatTime, hostOf } from "@/lib/format";
import { detectInput } from "@/lib/input-detect";
import { isDashSource, isHlsSource } from "@/lib/media";
import { extrapolatePosition, isLive, optimisticPatch } from "@/lib/player";
import { normalizeUrl } from "@/lib/url";
import { makePlayer } from "./fixtures";

describe("detectInput", () => {
  it.each([
    ["", "empty"],
    ["https://www.youtube.com/watch?v=abc", "youtube"],
    ["youtu.be/abc", "youtube"],
    ["http://iptv.example/get.php?username=a&type=m3u_plus", "m3u"],
    ["https://x.y/list.m3u", "m3u"],
    ["#EXTM3U\n#EXTINF:-1,Rai 1\nhttp://a/b.ts", "m3u"],
    ["https://cdn.x/live/index.m3u8?token=1", "stream"],
    ["rtmp://live.x/app/key", "stream"],
    ["https://www.raiplay.it/dirette/rai1", "url"],
    ["example.com/live", "url"],
    ["hello world", "invalid"],
    ["ftp://x/y", "invalid"],
  ])("%s → %s", (raw, kind) => {
    expect(detectInput(raw).kind).toBe(kind);
  });

  it("suggests backend kinds only when confident", () => {
    expect(detectInput("https://youtu.be/x").sourceKind).toBe("ytdlp");
    expect(detectInput("https://a.b/c.m3u8").sourceKind).toBe("direct");
    expect(detectInput("https://a.b/page").sourceKind).toBeUndefined();
  });
});

describe("normalizeUrl", () => {
  it("adds schemes and turns words into a search", () => {
    expect(normalizeUrl("example.com")).toBe("https://example.com");
    expect(normalizeUrl("192.168.1.2:8080/x")).toBe("http://192.168.1.2:8080/x");
    expect(normalizeUrl("http://a.b")).toBe("http://a.b");
    expect(normalizeUrl("calcio live")).toBe("https://duckduckgo.com/?q=calcio%20live");
    expect(normalizeUrl("  ")).toBeNull();
  });
});

describe("format", () => {
  it("formats times and sizes", () => {
    expect(formatTime(0)).toBe("0:00");
    expect(formatTime(65.7)).toBe("1:05");
    expect(formatTime(3725)).toBe("1:02:05");
    expect(formatTime(null)).toBe("0:00");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
    expect(hostOf("https://www.example.com/x")).toBe("example.com");
  });
});

describe("player helpers", () => {
  it("extrapolates position only while playing and caps at duration", () => {
    const p = makePlayer({ current_time: 10, duration: 12, stream_type: "BUFFERED" });
    expect(extrapolatePosition(p, 1000, 2500)).toBeCloseTo(11.5);
    expect(extrapolatePosition(p, 1000, 9000)).toBe(12);
    expect(extrapolatePosition({ ...p, player_state: "PAUSED" }, 1000, 9000)).toBe(10);
    expect(extrapolatePosition(null, 0, 0)).toBe(0);
  });

  it("detects live", () => {
    expect(isLive(makePlayer())).toBe(true);
    expect(isLive(makePlayer({ stream_type: "BUFFERED", duration: 100 }))).toBe(false);
  });

  it("computes optimistic patches", () => {
    const p = makePlayer({ volume_level: 0.5, current_time: 30 });
    expect(optimisticPatch(p, "toggle")).toEqual({ player_state: "PAUSED" });
    expect(optimisticPatch({ ...p, player_state: "PAUSED" }, "toggle")).toEqual({ player_state: "PLAYING" });
    expect(optimisticPatch(p, "volume", 1.4)).toEqual({ volume_level: 1, muted: false });
    expect(optimisticPatch(p, "volume_relative", -0.7)).toEqual({ volume_level: 0 });
    expect(optimisticPatch(p, "seek_relative", -40)).toEqual({ current_time: 0 });
    // relative seeks start from the position the user sees (extrapolated), not the stale snapshot value
    expect(optimisticPatch(p, "seek_relative", 10, 25)).toEqual({ current_time: 35 });
    expect(optimisticPatch(p, "mute")).toEqual({ muted: true });
    expect(optimisticPatch(p, "go_live")).toBeNull();
  });
});

describe("misc", () => {
  it("parses host input for manual devices", () => {
    expect(parseHostInput("192.168.1.9")).toEqual({ host: "192.168.1.9", port: undefined });
    expect(parseHostInput("tv.local:8009")).toEqual({ host: "tv.local", port: 8009 });
    expect(parseHostInput("bad host")).toBeNull();
    expect(parseHostInput("x:99999")).toBeNull();
  });

  it("keeps one active track per type", () => {
    const tracks = [
      { id: 1, type: "TEXT" as const, name: "it", language: "it" },
      { id: 2, type: "TEXT" as const, name: "en", language: "en" },
      { id: 3, type: "AUDIO" as const, name: "it", language: "it" },
    ];
    expect(nextActiveTracks(tracks, [1, 3], "TEXT", 2)).toEqual([3, 2]);
    expect(nextActiveTracks(tracks, [1, 3], "TEXT", null)).toEqual([3]);
  });

  it("chooses grid columns by width", () => {
    expect(columnsFor(375)).toBe(3);
    expect(columnsFor(600)).toBe(4);
    expect(columnsFor(800)).toBe(5);
    expect(columnsFor(1200)).toBe(6);
  });

  it("classifies preview sources and resolves backend URLs", () => {
    expect(isHlsSource("https://a/b.m3u8?x=1")).toBe(true);
    expect(isHlsSource("/proxy/tok/live", "application/x-mpegURL")).toBe(true);
    expect(isHlsSource("https://a/b.mp4", "video/mp4")).toBe(false);
    expect(isDashSource("https://a/b.mpd")).toBe(true);
    expect(backendUrl("/proxy/t/i.m3u8", "http://localhost:8000")).toBe("http://localhost:8000/proxy/t/i.m3u8");
    expect(backendUrl("https://cdn/x.jpg", "http://localhost:8000")).toBe("https://cdn/x.jpg");
    expect(backendUrl("data:image/jpeg;base64,xx", "http://b")).toBe("data:image/jpeg;base64,xx");
  });
});

describe("errorMessage", () => {
  it("translates contract error codes and falls back to the detail", async () => {
    const { ApiError } = await import("@/lib/api");
    const { errorMessage } = await import("@/lib/query");
    expect(errorMessage(new ApiError(409, "Device not connected", "not_connected"))).toBe("Nessun dispositivo connesso");
    expect(errorMessage(new ApiError(429, "too many", "browser_limit"))).toBe("Troppe sessioni browser aperte");
    expect(errorMessage(new ApiError(500, "boom", "weird_code"))).toBe("boom");
    expect(errorMessage(new ApiError(500, ""), "Fallito")).toBe("Fallito");
    expect(errorMessage("x", "Fallito")).toBe("Fallito");
  });
});

describe("getApiBase", () => {
  it("prefers NEXT_PUBLIC_API_BASE, else the page host with NEXT_PUBLIC_API_PORT (phone on the LAN)", async () => {
    const { getApiBase } = await import("@/lib/config");
    const prev = { base: process.env.NEXT_PUBLIC_API_BASE, port: process.env.NEXT_PUBLIC_API_PORT };
    try {
      delete process.env.NEXT_PUBLIC_API_BASE;
      delete process.env.NEXT_PUBLIC_API_PORT;
      expect(getApiBase({ protocol: "http:", hostname: "192.168.1.20" })).toBe("");
      process.env.NEXT_PUBLIC_API_PORT = "8000";
      expect(getApiBase({ protocol: "http:", hostname: "192.168.1.20" })).toBe("http://192.168.1.20:8000");
      process.env.NEXT_PUBLIC_API_BASE = "http://srv:9000/";
      expect(getApiBase({ protocol: "http:", hostname: "192.168.1.20" })).toBe("http://srv:9000");
    } finally {
      if (prev.base === undefined) delete process.env.NEXT_PUBLIC_API_BASE;
      else process.env.NEXT_PUBLIC_API_BASE = prev.base;
      if (prev.port === undefined) delete process.env.NEXT_PUBLIC_API_PORT;
      else process.env.NEXT_PUBLIC_API_PORT = prev.port;
    }
  });
});
