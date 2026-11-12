import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";

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

/** Italian messages for the contract's error codes (the backend's `detail` is English/technical). */
export const ERROR_MESSAGES: Record<string, string> = {
  device_not_found: "Dispositivo non trovato",
  not_connected: "Nessun dispositivo connesso",
  resolve_failed: "Impossibile trovare un video a questo indirizzo",
  unsupported_source: "Sorgente non supportata",
  local_disabled: "File locali disattivati sul server",
  playlist_not_found: "Playlist non trovata",
  validation_error: "Richiesta non valida",
  cast_error: "Il Chromecast non è riuscito ad avviare il video",
  queue_empty: "La coda è vuota",
  queue_item_not_found: "Elemento non più in coda",
  not_manual: "Solo i dispositivi aggiunti a mano possono essere rimossi",
  favorite_not_found: "Preferito non trovato",
  no_source_url: "Questa playlist non ha un indirizzo da aggiornare",
  forbidden_path: "Percorso non consentito",
  token_not_found: "Stream scaduto: riprova",
  restream_failed: "Conversione dello stream non riuscita",
  session_not_found: "Sessione browser non più attiva",
  stream_not_found: "Stream non più disponibile",
  browser_limit: "Troppe sessioni browser aperte",
  browser_disabled: "Browser interattivo disattivato sul server",
  browser_unavailable: "Browser interattivo non disponibile sul server",
  browser_error: "Errore del browser sul server",
  popup_not_found: "Popup non più disponibile",
  network_error: "Server non raggiungibile",
};

/** Human readable (Italian) message for any thrown value: known API codes are translated. */
export function errorMessage(err: unknown, fallback = "Qualcosa è andato storto"): string {
  if (err instanceof ApiError) return (err.code && ERROR_MESSAGES[err.code]) || err.detail || fallback;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}
