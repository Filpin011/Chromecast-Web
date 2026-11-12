import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { backoffDelay, BrowserSocket, StateSocket, type WebSocketLike } from "@/lib/ws";
import { wsUrl } from "@/lib/config";

class FakeWS implements WebSocketLike {
  static instances: FakeWS[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: ((ev: Event) => unknown) | null = null;
  onclose: ((ev: CloseEvent) => unknown) | null = null;
  onerror: ((ev: Event) => unknown) | null = null;
  onmessage: ((ev: MessageEvent) => unknown) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeWS.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
    this.readyState = 3;
  }
  // test helpers
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  drop() {
    this.readyState = 3;
    this.onclose?.({ code: 1006 } as CloseEvent);
  }
  receive(data: unknown) {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) } as MessageEvent);
  }
}

const factory = (url: string) => new FakeWS(url);
const last = () => FakeWS.instances[FakeWS.instances.length - 1];

beforeEach(() => {
  FakeWS.instances = [];
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("backoffDelay", () => {
  it("grows exponentially and caps", () => {
    const o = { initialMs: 500, maxMs: 4000, factor: 2, jitter: 0 };
    expect([0, 1, 2, 3, 4, 10].map((a) => backoffDelay(a, o))).toEqual([500, 1000, 2000, 4000, 4000, 4000]);
  });
  it("applies bounded jitter", () => {
    expect(backoffDelay(0, { initialMs: 1000, jitter: 0.2 }, () => 0)).toBe(800);
    expect(backoffDelay(0, { initialMs: 1000, jitter: 0.2 }, () => 1)).toBe(1200);
  });
});

describe("StateSocket", () => {
  const backoff = { initialMs: 100, maxMs: 1000, jitter: 0 };

  it("connects, reports status and parses typed messages", () => {
    const s = new StateSocket({ url: "ws://x/ws", factory, backoff });
    const statuses: string[] = [];
    const msgs: unknown[] = [];
    s.onStatus((st) => statuses.push(st));
    s.onMessage((m) => msgs.push(m));
    s.connect();
    last().open();
    last().receive({ type: "pong" });
    last().receive("not json");
    expect(statuses).toEqual(["connecting", "open"]);
    expect(msgs).toEqual([{ type: "pong" }]);
    expect(last().url).toBe("ws://x/ws");
  });

  it("pings every 20s while open", () => {
    const s = new StateSocket({ url: "ws://x/ws", factory, backoff });
    s.connect();
    last().open();
    vi.advanceTimersByTime(19_999);
    expect(last().sent).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(last().sent).toEqual([JSON.stringify({ type: "ping" })]);
    vi.advanceTimersByTime(20_000);
    expect(last().sent).toHaveLength(2);
  });

  it("reconnects with exponential backoff and resets after a successful open", () => {
    const s = new StateSocket({ url: "ws://x/ws", factory, backoff });
    s.connect();
    expect(FakeWS.instances).toHaveLength(1);
    last().drop();
    expect(s.status).toBe("closed");
    vi.advanceTimersByTime(99);
    expect(FakeWS.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeWS.instances).toHaveLength(2);
    last().drop();
    vi.advanceTimersByTime(199);
    expect(FakeWS.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeWS.instances).toHaveLength(3);
    last().open();
    expect(s.retryAttempt).toBe(0);
    last().drop();
    vi.advanceTimersByTime(100);
    expect(FakeWS.instances).toHaveLength(4);
  });

  it("stops pinging when the socket drops", () => {
    const s = new StateSocket({ url: "ws://x/ws", factory, backoff });
    s.connect();
    const first = last();
    first.open();
    first.drop();
    vi.advanceTimersByTime(40_000);
    expect(first.sent).toEqual([]);
    s.close();
  });

  it("close() stops reconnecting for good", () => {
    const s = new StateSocket({ url: "ws://x/ws", factory, backoff });
    s.connect();
    last().open();
    s.close();
    expect(last().closed).toBe(true);
    vi.advanceTimersByTime(10_000);
    expect(FakeWS.instances).toHaveLength(1);
    expect(s.status).toBe("closed");
  });

  it("reconnectNow skips the pending backoff", () => {
    const s = new StateSocket({ url: "ws://x/ws", factory, backoff: { initialMs: 5000, jitter: 0 } });
    s.connect();
    last().drop();
    s.reconnectNow();
    expect(FakeWS.instances).toHaveLength(2);
    vi.advanceTimersByTime(5000);
    expect(FakeWS.instances).toHaveLength(2);
  });

  it("reconnectNow closes and detaches a socket that is still connecting", () => {
    const s = new StateSocket({ url: "ws://x/ws", factory, backoff });
    const msgs: unknown[] = [];
    s.onMessage((m) => msgs.push(m));
    s.connect();
    const orphan = last();
    s.reconnectNow(); // still CONNECTING
    expect(FakeWS.instances).toHaveLength(2);
    expect(orphan.closed).toBe(true);
    expect(orphan.onmessage).toBeNull();
    expect(orphan.onopen).toBeNull();
    const current = last();
    current.open();
    current.receive({ type: "toast", level: "info", message: "x" });
    expect(msgs).toHaveLength(1);
    s.reconnectNow(); // open & fresh: kept, just pinged
    expect(FakeWS.instances).toHaveLength(2);
    expect(current.sent).toEqual([JSON.stringify({ type: "ping" })]);
    s.close();
  });

  it("ignores events from a socket that was replaced", () => {
    const s = new StateSocket({ url: "ws://x/ws", factory, backoff });
    const msgs: unknown[] = [];
    const statuses: string[] = [];
    s.onMessage((m) => msgs.push(m));
    s.connect();
    const orphan = last();
    const { onopen, onmessage } = orphan;
    s.reconnectNow();
    s.onStatus((st) => statuses.push(st));
    // even if a stale handler reference still fires, it must be a no-op
    onopen?.(new Event("open"));
    onmessage?.({ data: JSON.stringify({ type: "pong" }) } as MessageEvent);
    expect(msgs).toEqual([]);
    expect(statuses).toEqual([]);
    vi.advanceTimersByTime(20_000);
    expect(orphan.sent).toEqual([]);
    s.close();
  });

  it("drops a half-open socket when nothing arrives within the idle timeout", () => {
    const s = new StateSocket({ url: "ws://x/ws", factory, backoff });
    s.connect();
    const first = last();
    first.open();
    vi.advanceTimersByTime(30_000);
    first.receive({ type: "pong" }); // activity resets the watchdog
    vi.advanceTimersByTime(44_999);
    expect(first.closed).toBe(false);
    vi.advanceTimersByTime(1);
    expect(first.closed).toBe(true);
    expect(s.status).toBe("closed");
    vi.advanceTimersByTime(100);
    expect(FakeWS.instances).toHaveLength(2);
    s.close();
  });

  it("reconnectNow replaces an OPEN socket that has gone silent", () => {
    const s = new StateSocket({ url: "ws://x/ws", factory, backoff });
    s.connect();
    const first = last();
    first.open();
    // simulate a suspended page: wall clock jumps, timers did not fire
    vi.setSystemTime(Date.now() + 60_000);
    s.reconnectNow();
    expect(first.closed).toBe(true);
    expect(FakeWS.instances).toHaveLength(2);
    s.close();
  });

  it("BrowserSocket has no idle watchdog (the channel can be legitimately quiet)", () => {
    const s = new BrowserSocket("abc", { url: "ws://x", factory });
    s.connect();
    last().open();
    vi.advanceTimersByTime(120_000);
    expect(last().closed).toBe(false);
    s.close();
  });

  it("send() only works while open", () => {
    const s = new BrowserSocket("abc", { url: "ws://x/ws/browser/abc", factory });
    s.connect();
    expect(s.send({ type: "tap", x: 1, y: 2 })).toBe(false);
    last().open();
    expect(s.send({ type: "tap", x: 1, y: 2 })).toBe(true);
    expect(JSON.parse(last().sent[0])).toEqual({ type: "tap", x: 1, y: 2 });
    s.close();
  });

  it("BrowserSocket gives up after maxRetries", () => {
    const s = new BrowserSocket("abc", { url: "ws://x", factory, backoff: { initialMs: 10, maxMs: 10, jitter: 0 } });
    s.connect();
    for (let i = 0; i < 20; i++) {
      last().drop();
      vi.advanceTimersByTime(10);
    }
    expect(FakeWS.instances).toHaveLength(9); // 1 + 8 retries
  });

  it("reports giving up to status listeners and can be retried by hand", () => {
    const s = new BrowserSocket("abc", { url: "ws://x", factory, backoff: { initialMs: 10, maxMs: 10, jitter: 0 } });
    const seen: [string, boolean][] = [];
    s.onStatus((st) => seen.push([st, s.gaveUp]));
    s.connect();
    for (let i = 0; i < 20; i++) {
      last().drop();
      vi.advanceTimersByTime(10);
    }
    expect(s.gaveUp).toBe(true);
    expect(seen[seen.length - 1]).toEqual(["closed", true]);
    const before = FakeWS.instances.length;
    s.retry();
    expect(s.gaveUp).toBe(false);
    expect(FakeWS.instances).toHaveLength(before + 1);
    last().open();
    expect(s.status).toBe("open");
    s.close();
    expect(s.gaveUp).toBe(false);
  });
});

describe("wsUrl", () => {
  it("derives ws(s) URLs from the API base or the page location", () => {
    expect(wsUrl("/ws", "http://localhost:8000")).toBe("ws://localhost:8000/ws");
    expect(wsUrl("/ws", "https://cast.home")).toBe("wss://cast.home/ws");
    expect(wsUrl("ws", "", { protocol: "https:", host: "h:1" })).toBe("wss://h:1/ws");
    expect(wsUrl("/ws", "", { protocol: "http:", host: "192.168.1.10:8000" })).toBe("ws://192.168.1.10:8000/ws");
  });
});
