import { describe, expect, it, vi } from "vitest";
import { Api, ApiError, HttpClient } from "@/lib/api";

function jsonResponse(body: unknown, status = 200) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HttpClient", () => {
  it("builds query strings and skips empty params", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    const api = new Api("http://srv:8000", fetch);
    await api.playlists.channels("p 1", { q: "rai", group: null, offset: 0, limit: 50 });
    expect(fetch).toHaveBeenCalledWith(
      "http://srv:8000/api/playlists/p%201/channels?q=rai&offset=0&limit=50",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("sends JSON bodies", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ device_id: "d" }));
    const api = new Api("", fetch);
    await api.player.play("d1", { input: "http://a/b.m3u8", enqueue: false });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/devices/d1/play");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ input: "http://a/b.m3u8", enqueue: false });
  });

  it("omits value for control actions without one", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({})));
    const api = new Api("", fetch);
    await api.player.control("d1", "toggle");
    await api.player.control("d1", "seek", 42);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ action: "toggle" });
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ action: "seek", value: 42 });
  });

  it("returns undefined for 204", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    const api = new Api("", fetch);
    await expect(api.favorites.remove("f1")).resolves.toBeUndefined();
    expect(fetch.mock.calls[0][1].method).toBe("DELETE");
  });

  it("throws ApiError with detail and code", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ detail: "MEDIA_ROOT non configurato", code: "local_disabled" }, 404));
    const api = new Api("", fetch);
    const err = await api.local.list("").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.code).toBe("local_disabled");
    expect(err.detail).toBe("MEDIA_ROOT non configurato");
    expect(ApiError.isCode(err, "local_disabled")).toBe(true);
  });

  it("handles FastAPI validation errors and non-JSON bodies", async () => {
    const http = new HttpClient("", vi.fn().mockResolvedValue(jsonResponse({ detail: [{ loc: ["body"] }] }, 422)));
    await expect(http.get("/x")).rejects.toMatchObject({ status: 422, detail: "Invalid request" });
    const http2 = new HttpClient("", vi.fn().mockResolvedValue(new Response("boom", { status: 500, statusText: "Server Error" })));
    await expect(http2.get("/x")).rejects.toMatchObject({ status: 500, detail: "Server Error" });
  });

  it("maps network failures to ApiError(network_error)", async () => {
    const http = new HttpClient("", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(http.get("/x")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("re-throws aborts untouched", async () => {
    const abort = new DOMException("aborted", "AbortError");
    const http = new HttpClient("", vi.fn().mockRejectedValue(abort));
    await expect(http.get("/x")).rejects.toBe(abort);
  });

  it("covers browser endpoints from the contract", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({})));
    const api = new Api("", fetch);
    await api.browser.create("https://a.b", { width: 390, height: 844 });
    await api.browser.navigate("s1", { action: "back" });
    await api.browser.cast("s1", { stream_id: "x", device_id: "d", enqueue: true });
    await api.browser.favorite("s1", "x");
    const calls = fetch.mock.calls.map(([u, i]) => [i.method, u, i.body && JSON.parse(i.body)]);
    expect(calls).toEqual([
      ["POST", "/api/browser/sessions", { url: "https://a.b", viewport: { width: 390, height: 844 } }],
      ["POST", "/api/browser/sessions/s1/navigate", { action: "back" }],
      ["POST", "/api/browser/sessions/s1/cast", { stream_id: "x", device_id: "d", enqueue: true }],
      ["POST", "/api/browser/sessions/s1/favorite", { stream_id: "x" }],
    ]);
  });

  it("covers queue, tracks and settings endpoints", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({})));
    const api = new Api("", fetch);
    await api.player.reorderQueue("d", ["b", "a"]);
    await api.player.removeFromQueue("d", "a");
    await api.player.setTracks("d", [2]);
    await api.settings.update({ force_proxy: true });
    await api.history.list(10);
    const calls = fetch.mock.calls.map(([u, i]) => [i.method, u, i.body && JSON.parse(i.body)]);
    expect(calls).toEqual([
      ["PUT", "/api/devices/d/queue", { item_ids: ["b", "a"] }],
      ["DELETE", "/api/devices/d/queue/a", undefined],
      ["POST", "/api/devices/d/tracks", { active_track_ids: [2] }],
      ["PUT", "/api/settings", { force_proxy: true }],
      ["GET", "/api/history?limit=10", undefined],
    ]);
  });
});
