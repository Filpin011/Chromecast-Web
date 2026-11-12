export type SocketStatus = "idle" | "connecting" | "open" | "closed";

/** Minimal WebSocket surface we depend on (lets tests inject a fake). */
export interface WebSocketLike {
  readonly readyState: number;
  onopen: ((ev: Event) => unknown) | null;
  onclose: ((ev: CloseEvent) => unknown) | null;
  onerror: ((ev: Event) => unknown) | null;
  onmessage: ((ev: MessageEvent) => unknown) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

export type WebSocketFactory = (url: string) => WebSocketLike;

export interface BackoffOptions {
  initialMs?: number;
  maxMs?: number;
  factor?: number;
  /** 0..1 — fraction of random jitter applied (0 = deterministic). */
  jitter?: number;
}

/** Exponential backoff: initial * factor^attempt, capped, with optional jitter. */
export function backoffDelay(attempt: number, opts: BackoffOptions = {}, rand: () => number = Math.random): number {
  const { initialMs = 500, maxMs = 15_000, factor = 2, jitter = 0.2 } = opts;
  const base = Math.min(maxMs, initialMs * Math.pow(factor, Math.max(0, attempt)));
  if (!jitter) return base;
  const delta = base * jitter;
  return Math.max(0, Math.round(base - delta + rand() * 2 * delta));
}

export interface ReconnectingSocketOptions {
  url: string;
  factory?: WebSocketFactory;
  backoff?: BackoffOptions;
  /** Interval for keep-alive pings, 0 disables. */
  pingIntervalMs?: number;
  /** Payload sent as keep-alive. */
  pingMessage?: unknown;
  /** Stop reconnecting after this many consecutive failures (default: infinite). */
  maxRetries?: number;
  /**
   * Treat an open socket as dead when nothing at all arrives for this long
   * (0/undefined disables). Catches half-open sockets after sleep / Wi-Fi changes,
   * which keep reporting OPEN without ever delivering anything.
   */
  idleTimeoutMs?: number;
}

const OPEN = 1;

/**
 * WebSocket wrapper with typed JSON messages, auto-reconnect with exponential
 * backoff, and periodic keep-alive pings. Generic over inbound/outbound message types.
 */
export class ReconnectingSocket<In, Out> {
  private ws: WebSocketLike | null = null;
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private lastActivity = 0;
  private stopped = true;
  private _gaveUp = false;
  private _status: SocketStatus = "idle";
  private readonly messageListeners = new Set<(msg: In) => void>();
  private readonly statusListeners = new Set<(s: SocketStatus) => void>();
  private readonly factory: WebSocketFactory;

  constructor(protected readonly opts: ReconnectingSocketOptions) {
    this.factory = opts.factory ?? ((url) => new WebSocket(url) as unknown as WebSocketLike);
  }

  get status(): SocketStatus {
    return this._status;
  }

  get retryAttempt(): number {
    return this.attempt;
  }

  /** True once `maxRetries` consecutive failures made the socket stop reconnecting (see `retry()`). */
  get gaveUp(): boolean {
    return this._gaveUp;
  }

  /** Start over after giving up: resets the backoff and reconnects now. */
  retry(): void {
    this._gaveUp = false;
    this.attempt = 0;
    this.stopped = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (!this.ws) this.open();
  }

  connect(): void {
    this.stopped = false;
    if (this.ws) return;
    this.open();
  }

  /** Close for good (no reconnect). */
  close(): void {
    this.stopped = true;
    this.clearTimers();
    this.discard(1000, "client closed");
    this.setStatus("closed");
  }

  /**
   * Force an immediate reconnect attempt (e.g. when the tab becomes visible or the
   * network comes back). An OPEN socket is kept unless it has been silent for longer
   * than `idleTimeoutMs` (half-open after sleep); anything else (CONNECTING, CLOSING)
   * is detached and closed first so it can never deliver messages twice.
   */
  reconnectNow(): void {
    if (this.stopped) return;
    if (this.ws && this.ws.readyState === OPEN && !this.isStale()) {
      // nudge the server so a silently-dead link is detected by the idle timeout
      if (this.opts.pingMessage !== undefined) this.ws.send(JSON.stringify(this.opts.pingMessage));
      return;
    }
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.discard(4000, "reconnecting");
    this.open();
  }

  send(msg: Out): boolean {
    if (!this.ws || this.ws.readyState !== OPEN) return false;
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  onMessage(fn: (msg: In) => void): () => void {
    this.messageListeners.add(fn);
    return () => this.messageListeners.delete(fn);
  }

  onStatus(fn: (s: SocketStatus) => void): () => void {
    this.statusListeners.add(fn);
    return () => this.statusListeners.delete(fn);
  }

  protected parse(data: unknown): In | null {
    if (typeof data !== "string") return null;
    try {
      return JSON.parse(data) as In;
    } catch {
      return null;
    }
  }

  private open(): void {
    this.setStatus("connecting");
    let ws: WebSocketLike;
    try {
      ws = this.factory(this.opts.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.attempt = 0;
      this.setStatus("open");
      this.startPing();
      this.touch();
    };
    ws.onmessage = (ev) => {
      if (this.ws !== ws) return;
      this.touch();
      const msg = this.parse(ev.data);
      if (msg !== null) this.messageListeners.forEach((fn) => fn(msg));
    };
    ws.onerror = () => {
      /* onclose follows */
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.stopPing();
      this.stopIdle();
      if (this.stopped) {
        this.setStatus("closed");
        return;
      }
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    // decide before notifying, so status listeners can already read `gaveUp`
    if (!this.stopped && this.opts.maxRetries !== undefined && this.attempt >= this.opts.maxRetries) {
      this.stopped = true;
      this._gaveUp = true;
    }
    this.setStatus("closed");
    if (this.stopped) return;
    const delay = backoffDelay(this.attempt, this.opts.backoff);
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.stopped) this.open();
    }, delay);
  }

  private startPing(): void {
    this.stopPing();
    const every = this.opts.pingIntervalMs ?? 0;
    if (!every || this.opts.pingMessage === undefined) return;
    const payload = JSON.stringify(this.opts.pingMessage);
    this.pingTimer = setInterval(() => {
      if (this.ws && this.ws.readyState === OPEN) this.ws.send(payload);
    }, every);
  }

  /** Detach all handlers from the current socket and close it (no reconnect scheduling). */
  private discard(code: number, reason: string): void {
    const ws = this.ws;
    this.ws = null;
    this.stopPing();
    this.stopIdle();
    if (!ws) return;
    ws.onopen = ws.onclose = ws.onerror = ws.onmessage = null;
    try {
      ws.close(code, reason);
    } catch {
      /* ignore */
    }
  }

  private isStale(): boolean {
    const idle = this.opts.idleTimeoutMs ?? 0;
    return idle > 0 && Date.now() - this.lastActivity > idle;
  }

  /** Something arrived (or the socket just opened): restart the idle watchdog. */
  private touch(): void {
    this.lastActivity = Date.now();
    const idle = this.opts.idleTimeoutMs ?? 0;
    if (!idle) return;
    this.stopIdle();
    this.idleTimer = setTimeout(() => {
      this.idleTimer = null;
      if (this.stopped || !this.ws) return;
      // half-open: drop it ourselves and go through the normal backoff path
      this.discard(4000, "idle timeout");
      this.scheduleReconnect();
    }, idle);
  }

  private stopIdle(): void {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = null;
  }

  private stopPing(): void {
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = null;
  }

  private clearTimers(): void {
    this.stopPing();
    this.stopIdle();
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private setStatus(s: SocketStatus): void {
    if (this._status === s) return;
    this._status = s;
    this.statusListeners.forEach((fn) => fn(s));
  }
}
