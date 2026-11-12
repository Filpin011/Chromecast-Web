import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;
  readonly detail: string;

  constructor(status: number, detail: string, code?: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code;
  }

  static isCode(err: unknown, code: string): boolean {
    return err instanceof ApiError && err.code === code;
  }
}

export type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

function buildQuery(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

async function parseError(res: Response): Promise<ApiError> {
  let detail = res.statusText || `HTTP ${res.status}`;
  let code: string | undefined;
  try {
    const body = (await res.json()) as Partial<ApiErrorBody> | { detail?: unknown };
    if (body && typeof body === "object") {
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "Richiesta non valida";
      if ("code" in body && typeof body.code === "string") code = body.code;
    }
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, detail, code);
}

/** Thin JSON-over-fetch client. All API classes share one instance. */
export class HttpClient {
  constructor(
    private readonly base: string = "",
    private readonly fetchImpl: FetchLike = (input, init) => fetch(input, init),
  ) {}

  url(path: string, query?: Query): string {
    return `${this.base}${path}${buildQuery(query)}`;
  }

  async request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    let body: BodyInit | undefined;
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.body);
    }
    let res: Response;
    try {
      res = await this.fetchImpl(this.url(path, opts.query), {
        method,
        headers,
        body,
        signal: opts.signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new ApiError(0, "Server non raggiungibile", "network_error");
    }
    if (!res.ok) throw await parseError(res);
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }

  get<T>(path: string, opts?: RequestOptions) {
    return this.request<T>("GET", path, opts);
  }
  post<T>(path: string, body?: unknown, opts?: RequestOptions) {
    return this.request<T>("POST", path, { ...opts, body });
  }
  put<T>(path: string, body?: unknown, opts?: RequestOptions) {
    return this.request<T>("PUT", path, { ...opts, body });
  }
  delete<T = void>(path: string, opts?: RequestOptions) {
    return this.request<T>("DELETE", path, opts);
  }
}
