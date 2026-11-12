/**
 * Types mirroring docs/ARCHITECTURE.md (the binding contract).
 * Keep this file in sync with the backend Pydantic models.
 */

export type SourceKind = "direct" | "webpage" | "m3u" | "ytdlp" | "local";
export type StreamType = "LIVE" | "BUFFERED";
export type PlayerStateName = "IDLE" | "PLAYING" | "PAUSED" | "BUFFERING" | "UNKNOWN";

export interface Device {
  id: string;
  name: string;
  model: string | null;
  host: string;
  port: number;
  cast_type: string | null;
  manufacturer: string | null;
  manual: boolean;
  online: boolean;
}

export interface Subtitle {
  url: string;
  lang: string | null;
  label: string;
}

export interface ResolvedMedia {
  url: string;
  cast_url: string;
  preview_url: string;
  title: string;
  mime_type: string;
  stream_type: StreamType;
  thumbnail: string | null;
  source_kind: SourceKind;
  original_input: string;
  proxied: boolean;
  subtitles: Subtitle[];
  /** HLS segment container sent to the receiver as hlsSegmentFormat; null for TS / non-HLS. */
  hls_segment_format: HlsSegmentFormat | null;
}

export type HlsSegmentFormat = "fmp4" | "aac" | "mp3" | "ac3" | "e_ac3";

export interface Channel {
  id: string;
  playlist_id: string | null;
  name: string;
  url: string;
  logo: string | null;
  group: string | null;
  tvg_id: string | null;
  /** Upstream request headers the channel needs (#EXTVLCOPT http-referrer/user-agent, Kodi `url|Referer=`).
   *  Sent back as `PlayRequest.headers` when playing the channel. Optional: older servers omit it. */
  headers?: Record<string, string>;
}

export interface Playlist {
  id: string;
  name: string;
  source_url: string | null;
  channel_count: number;
  groups: string[];
  created_at: string;
  updated_at: string;
}

export type ResolveResult =
  | { type: "media"; media: ResolvedMedia }
  | { type: "playlist"; name: string; channels: Channel[] };

export interface Favorite {
  id: string;
  title: string;
  input: string;
  source_kind: SourceKind;
  thumbnail: string | null;
  created_at: string;
}

export interface HistoryEntry {
  id: string;
  title: string;
  input: string;
  source_kind: SourceKind;
  thumbnail: string | null;
  device_id: string | null;
  played_at: string;
}

export interface MediaTrack {
  id: number;
  type: "TEXT" | "AUDIO" | "VIDEO";
  name: string | null;
  language: string | null;
}

export interface QueueItem {
  id: string;
  input: string;
  title: string;
  thumbnail: string | null;
}

export interface PlayerState {
  device_id: string;
  connected: boolean;
  app_name: string | null;
  player_state: PlayerStateName;
  idle_reason: string | null;
  title: string | null;
  thumbnail: string | null;
  media_url: string | null;
  original_input: string | null;
  stream_type: StreamType | null;
  current_time: number;
  duration: number | null;
  seekable: boolean;
  volume_level: number;
  muted: boolean;
  tracks: MediaTrack[];
  active_track_ids: number[];
  queue: QueueItem[];
  showing_idle_image: boolean;
  updated_at: string;
}

export type PopupPolicy = "ask" | "block" | "allow";
export type PopupDecision = "open" | "block" | "block_always";

export interface Settings {
  idle_image_url: string | null;
  show_idle_on_connect: boolean;
  show_idle_on_stop: boolean;
  default_device_id: string | null;
  public_base_url: string | null;
  force_proxy: boolean;
  /* ad blocking / popups (remote browser) */
  adblock_enabled: boolean;
  adblock_disabled_hosts: string[];
  popup_policy: PopupPolicy;
  popup_blocked_hosts: string[];
}

export interface AppState {
  devices: Device[];
  active_device_id: string | null;
  players: Record<string, PlayerState>;
  discovering: boolean;
  version: number;
}

export interface ApiErrorBody {
  detail: string;
  code?: string;
}

export interface Health {
  status: "ok";
  driver: string;
  version: string;
}

export interface LocalEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
  mime_type: string | null;
}

export interface LocalListing {
  path: string;
  entries: LocalEntry[];
}

export interface Page<T> {
  items: T[];
  total: number;
}

export type ControlAction =
  | "play"
  | "pause"
  | "toggle"
  | "stop"
  | "seek"
  | "seek_relative"
  | "go_live"
  | "volume"
  | "volume_relative"
  | "mute"
  | "unmute"
  | "next"
  | "previous";

export interface PlayRequest {
  input: string;
  kind?: SourceKind;
  title?: string;
  enqueue?: boolean;
  /** Upstream headers (e.g. `Channel.headers`) replayed by the proxy. */
  headers?: Record<string, string> | null;
}

export type QueueRequest = Omit<PlayRequest, "enqueue">;

export interface ManualDeviceRequest {
  host: string;
  port?: number;
  name?: string;
}

export interface PlaylistImportRequest {
  url?: string;
  content?: string;
  name?: string;
}

export interface FavoriteCreate {
  title: string;
  input: string;
  source_kind: SourceKind;
  thumbnail?: string | null;
}

export interface ChannelQuery {
  q?: string;
  group?: string | null;
  offset?: number;
  limit?: number;
}

/* ---------------- Remote browser ---------------- */

export type CapturedKind = "hls" | "dash" | "progressive" | "unknown";

export interface CapturedStream {
  id: string;
  url: string;
  mime_type: string | null;
  kind: CapturedKind;
  page_url: string;
  frame_url: string | null;
  headers: Record<string, string>;
  detected_at: string;
  is_master: boolean | null;
  // Backward-compatible additions (see "Browser UX reference")
  title?: string | null;
  thumbnail?: string | null;
  quality?: string | null;
  width?: number | null;
  height?: number | null;
  is_live?: boolean | null;
  score?: number;
  /** Same-origin `/proxy` path replaying the captured headers, playable by the in-app preview. */
  preview_url?: string | null;
}

export interface Viewport {
  width: number;
  height: number;
}

export interface PopupRequest {
  id: string;
  url: string;
  host: string;
  opener_url: string;
  created_at: string;
}

export interface BrowserSession {
  id: string;
  url: string;
  title: string | null;
  viewport: Viewport;
  captured: CapturedStream[];
  created_at: string;
  /** Ad blocking effective for the current site. */
  adblock_enabled: boolean;
  /** Requests blocked on the current page load. */
  blocked_count: number;
  pending_popups: PopupRequest[];
}

export interface FilterListInfo {
  name: string;
  rules: number;
  updated_at: string | null;
}

export interface FilterLists {
  lists: FilterListInfo[];
}

export type NavigateRequest = { url: string } | { action: "back" | "forward" | "reload" };

export interface BrowserCastRequest {
  stream_id: string;
  device_id: string;
  enqueue?: boolean;
}

/* ---------------- WebSocket messages ---------------- */

export type ToastLevel = "info" | "success" | "error";

export type ServerMessage =
  | { type: "state"; data: AppState }
  | { type: "toast"; level: ToastLevel; message: string }
  | { type: "pong" };

export type ClientMessage = { type: "ping" };

export type BrowserServerMsg =
  | { type: "frame"; data: string; width: number; height: number }
  | { type: "session"; data: BrowserSession }
  | { type: "captured"; data: CapturedStream }
  | { type: "popup"; data: PopupRequest }
  | { type: "blocked"; count: number }
  | { type: "closed" };

export type BrowserClientMsg =
  | { type: "click"; x: number; y: number; button?: "left" | "right" }
  | { type: "tap"; x: number; y: number }
  | { type: "scroll"; x: number; y: number; dx: number; dy: number }
  | { type: "key"; key: string }
  | { type: "text"; text: string }
  | { type: "mousemove"; x: number; y: number }
  | { type: "popup_decision"; id: string; decision: PopupDecision }
  | { type: "stop_media" };
