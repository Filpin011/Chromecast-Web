import { QueryClient } from "@tanstack/react-query";
import { currentTranslator, t, type Translator } from "@/i18n";
import { ApiError } from "@/lib/api";
import type { MessageParams } from "@/lib/api/types";

export const qk = {
  health: ["health"] as const,
  playlists: ["playlists"] as const,
  playlist: (id: string) => ["playlists", id] as const,
  channels: (id: string, q: string, group: string | null) => ["playlists", id, "channels", q, group] as const,
  favorites: ["favorites"] as const,
  history: ["history"] as const,
  settings: ["settings"] as const,
  local: (path: string) => ["local", path] as const,
  browserSessions: ["browser", "sessions"] as const,
};

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: true,
        retry: (count, err) => {
          // never retry deterministic API errors (4xx)
          if (err instanceof ApiError && err.status >= 400 && err.status < 500) return false;
          return count < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}

/**
 * Error codes of the API contract (docs/ARCHITECTURE.md). Each has a translation under `errors.<code>`;
 * the backend's `detail` is English/technical and only shown for codes the UI doesn't know.
 */
export const ERROR_CODES = [
  "device_not_found",
  "not_connected",
  "resolve_failed",
  "unsupported_source",
  "local_disabled",
  "playlist_not_found",
  "validation_error",
  "cast_error",
  "queue_empty",
  "queue_item_not_found",
  "not_manual",
  "favorite_not_found",
  "no_source_url",
  "forbidden_path",
  "token_not_found",
  "restream_failed",
  "session_not_found",
  "stream_not_found",
  "browser_limit",
  "browser_disabled",
  "browser_unavailable",
  "browser_error",
  "popup_not_found",
  "internal_error",
  "network_error",
] as const;

/** Finer-grained `reason`s the backend attaches to some errors (`errors.reason.<reason>`). */
export const ERROR_REASONS = [
  "connect_failed",
  "fetch_failed",
  "upstream_http",
  "no_stream_on_page",
  "extract_failed",
  "not_m3u",
  "empty_playlist",
  "local_file_not_found",
  "local_unavailable",
  "malformed_url",
  "unsupported_input",
  "is_playlist",
  "hls_not_playlist",
] as const;

/** Translated message for a stable error code (+ optional reason), or undefined if unknown. */
export function translateErrorCode(
  code: string | undefined,
  reason?: string,
  params?: MessageParams,
  tr: Translator = currentTranslator(),
): string | undefined {
  return (reason && tr.maybe(`errors.reason.${reason}`, params)) || (code ? tr.maybe(`errors.${code}`, params) : undefined);
}

/** Human readable message for any thrown value, in the current language: known API codes are translated. */
export function errorMessage(err: unknown, fallback?: string): string {
  const fb = fallback ?? t("errors.generic");
  if (err instanceof ApiError) return translateErrorCode(err.code, err.reason, err.params) || err.detail || fb;
  if (err instanceof Error && err.message) return err.message;
  return fb;
}

/**
 * Explanation of an API error for an error card: the specific reason when the UI knows it,
 * otherwise the backend's (English, technical) detail.
 */
export function errorDescription(err: ApiError): string {
  return (err.reason && currentTranslator().maybe(`errors.reason.${err.reason}`, err.params)) || err.detail;
}
