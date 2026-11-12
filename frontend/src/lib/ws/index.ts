import { wsUrl } from "@/lib/config";
import type {
  BrowserClientMsg,
  BrowserServerMsg,
  ClientMessage,
  ServerMessage,
} from "@/lib/api/types";
import {
  ReconnectingSocket,
  type BackoffOptions,
  type WebSocketFactory,
} from "./reconnecting-socket";

export * from "./reconnecting-socket";

export const PING_INTERVAL_MS = 20_000;
/**
 * The server answers every ping with a pong and rebroadcasts state at least every
 * second while playing, so >2 missed pongs means the link is half-open.
 */
export const STATE_IDLE_TIMEOUT_MS = 45_000;

export interface SocketInit {
  url?: string;
  factory?: WebSocketFactory;
  backoff?: BackoffOptions;
}

/** App-wide state channel `/ws`: receives AppState snapshots & toasts, pings every 20s. */
export class StateSocket extends ReconnectingSocket<ServerMessage, ClientMessage> {
  constructor(init: SocketInit = {}) {
    super({
      url: init.url ?? wsUrl("/ws"),
      factory: init.factory,
      backoff: init.backoff,
      pingIntervalMs: PING_INTERVAL_MS,
      pingMessage: { type: "ping" } satisfies ClientMessage,
      idleTimeoutMs: STATE_IDLE_TIMEOUT_MS,
    });
  }
}

/** Per-session remote-browser channel `/ws/browser/{id}`. */
export class BrowserSocket extends ReconnectingSocket<BrowserServerMsg, BrowserClientMsg> {
  constructor(sessionId: string, init: SocketInit = {}) {
    super({
      url: init.url ?? wsUrl(`/ws/browser/${encodeURIComponent(sessionId)}`),
      factory: init.factory,
      backoff: init.backoff ?? { initialMs: 400, maxMs: 5_000 },
      maxRetries: 8,
    });
  }
}
