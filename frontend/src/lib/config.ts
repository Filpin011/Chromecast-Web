type Loc = Pick<Location, "protocol" | "hostname">;

/**
 * Runtime endpoints. In production the frontend is served by FastAPI on the same origin, so the base is empty.
 * In dev (`next dev` on :3000, backend on :8000):
 * - `NEXT_PUBLIC_API_PORT=8000` → the backend on the **same host the page was opened from**, so
 *   `http://<lan-ip>:3000` on a phone talks to `http://<lan-ip>:8000` (what `make dev` uses);
 * - `NEXT_PUBLIC_API_BASE=http://host:8000` → a fixed backend URL (takes precedence).
 */
export function getApiBase(loc: Loc | undefined = typeof window !== "undefined" ? window.location : undefined): string {
  const env = process.env.NEXT_PUBLIC_API_BASE;
  if (env) return env.replace(/\/+$/, "");
  const port = process.env.NEXT_PUBLIC_API_PORT;
  if (port && loc?.hostname) return `${loc.protocol === "https:" ? "https:" : "http:"}//${loc.hostname}:${port}`;
  return "";
}

/** Turn a backend-relative path (e.g. "/proxy/abc/index.m3u8") into a URL the browser can load. */
export function backendUrl(pathOrUrl: string, base: string = getApiBase()): string {
  if (/^(https?:|data:|blob:)/i.test(pathOrUrl)) return pathOrUrl;
  const path = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${base}${path}`;
}

/** Build a ws:// or wss:// URL for a backend path. */
export function wsUrl(
  path: string,
  base: string = getApiBase(),
  loc: Pick<Location, "protocol" | "host"> | undefined = typeof window !== "undefined"
    ? window.location
    : undefined,
): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  if (base) {
    return base.replace(/^http(s?):/i, (_m, s: string) => `ws${s}:`) + p;
  }
  if (!loc) return `ws://localhost${p}`;
  const proto = loc.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${loc.host}${p}`;
}
