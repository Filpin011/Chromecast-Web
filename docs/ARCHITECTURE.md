# Chromecast Web — Architecture & API contract

This file is the **single source of truth** shared by `backend/` and `frontend/`.
If you change a model or endpoint, change it here first, then in both sides.

## Goals

Control a Chromecast (primary target: Chromecast Ultra) from any browser (mostly phones),
with the UI **kept in sync in real time** across every open tab/device.
Cast any source: direct URL (HLS/DASH/MP4/TS), a web page containing a video
(headless browser, may need to click "play"), M3U/IPTV playlists, YouTube & other sites (yt-dlp),
local files from the server. Mostly live streams, sometimes seekable VOD.

## Deployment model

- Runs on a home server with **Coolify**, on the **same LAN** as the Chromecast.
- **One Docker image**: FastAPI backend + Next.js frontend built as a **static export** and
  served by FastAPI at `/`. Same origin ⇒ no CORS, WebSocket just works.
- Container uses `network_mode: host` (required for mDNS discovery and so the Chromecast
  can reach the stream proxy).
- `PUBLIC_BASE_URL` (e.g. `http://192.168.1.10:8000`) is the URL **the Chromecast** uses to reach
  the proxy. If unset, the backend auto-detects its LAN IP.
- Devices can also be added manually by IP (fallback when mDNS doesn't work).

## Repository layout

```
backend/            FastAPI app (Python 3.12+)
  app/
    main.py         app factory, mounts routers, static frontend, /ws
    config.py       pydantic-settings
    models/         Pydantic schemas (API) — mirror of the contract below
    db/             SQLModel/SQLite persistence (favorites, history, playlists, settings, manual devices)
    services/
      cast/         CastDriver protocol + PyChromecastDriver + FakeCastDriver (CAST_DRIVER=fake)
      resolver/     source resolvers: direct, ytdlp, webpage (playwright), m3u, local
      proxy/        HLS-rewriting proxy + passthrough + ffmpeg restream
      state.py      StateHub: in-memory AppState, broadcasts on every change
      queue.py      server-side play queue per device
    api/            routers
  tests/            pytest (no real Chromecast/network needed: fake driver + mocks)
  scripts/          dev tooling, not shipped: demo.py (fake driver + fictional demo data), screenshots.py, brand.py
frontend/           Next.js (App Router, TypeScript strict, Tailwind v4, shadcn/ui)
  src/
    app/            pages
    components/     reusable UI components
    lib/api/        typed REST client + types mirroring the contract
    lib/ws/         WebSocket client with auto-reconnect
    stores/         client state (zustand) fed by the WebSocket
    i18n/           en.ts (source of truth, default/fallback) + it.ts dictionaries, t()/useT()/useLocale()
  tests/            vitest + Testing Library
Dockerfile          multi-stage: build frontend static export → python image serving it
docker-compose.yml  for Coolify (network_mode: host, volume for /data)
```

## Environment variables (backend)

| Var | Default | Meaning |
|---|---|---|
| `CAST_DRIVER` | `pychromecast` | `fake` for dev/tests (simulated devices) |
| `PUBLIC_BASE_URL` | auto LAN IP + port | base URL reachable by the Chromecast |
| `PORT` | `8000` | |
| `DATA_DIR` | `./data` | SQLite DB + temp restream files |
| `MEDIA_ROOT` | unset | root dir for local file browsing (disabled if unset) |
| `FRONTEND_DIR` | `../frontend/out` | static export to serve at `/` |
| `ENABLE_PLAYWRIGHT` | `true` | web-page extraction |
| `FILTERS_AUTO_UPDATE` | `true` | download/refresh the uBO default filter lists every 24h (bundled fallback list is always loaded) |
| `FFMPEG_PATH` / `FFPROBE_PATH` | `ffmpeg` / ffprobe next to it | used by `/restream` |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | comma-separated extra origins (dev only; prod is same-origin) |
| `CORS_ORIGIN_REGEX` | private-LAN hosts (localhost, 10/8, 172.16/12, 192.168/16, `*.local`), any port | so `make dev` works from a phone at `http://<lan-ip>:3000`; set `""` to disable |

## Data models (JSON, snake_case)

```ts
type SourceKind = "direct" | "webpage" | "m3u" | "ytdlp" | "local";
type StreamType = "LIVE" | "BUFFERED";
type PlayerStateName = "IDLE" | "PLAYING" | "PAUSED" | "BUFFERING" | "UNKNOWN";

interface Device {
  id: string;              // cast uuid (or "manual-<host>")
  name: string;            // friendly name
  model: string | null;    // e.g. "Chromecast Ultra"
  host: string;
  port: number;
  cast_type: string | null;   // "cast" | "audio" | "group"
  manufacturer: string | null;
  manual: boolean;          // added by IP
  online: boolean;          // manual devices are always true (connectable; reachability is only known on connect)
}

interface Subtitle { url: string; lang: string | null; label: string }

interface ResolvedMedia {
  url: string;               // original resolved media URL
  cast_url: string;          // URL actually sent to the Chromecast (may be proxied)
  preview_url: string;       // URL usable by the browser preview (same-origin proxy path when needed)
  title: string;
  mime_type: string;         // e.g. application/x-mpegURL, video/mp4, video/mp2t
  stream_type: StreamType;
  thumbnail: string | null;
  source_kind: SourceKind;
  original_input: string;
  proxied: boolean;
  subtitles: Subtitle[];
  // HLS only, from the first segment's bytes (fallback: #EXT-X-MAP / segment extensions) of the first
  // variant, or of its audio rendition when that is packed audio (YouTube: ID3+ADTS named .ts); null = MPEG-TS.
  // Sent in the LOAD as hlsSegmentFormat (+ hlsVideoSegmentFormat "fmp4"): the Default Media
  // Receiver assumes TS otherwise and fMP4/CMAF or packed-audio HLS fails to play. One value covers every
  // variant, so a master mixing video codec families (YouTube: avc1/TS + vp09/fMP4) is always proxied and the
  // proxy serves it with only the variants of the first variant's family (see /proxy).
  hls_segment_format: "fmp4" | "aac" | "mp3" | "ac3" | "e_ac3" | null;
  // HLS only: "fmp4" when the (first variant's) video segments are fMP4, also when hls_segment_format names the
  // container of a separate audio rendition (fMP4 video + packed AAC audio); sent as hlsVideoSegmentFormat.
  // null = MPEG-TS video.
  hls_video_segment_format: "fmp4" | null;
}

interface Channel {          // one M3U entry
  id: string;
  playlist_id: string | null;
  name: string;
  url: string;
  logo: string | null;
  group: string | null;
  tvg_id: string | null;
  headers: Record<string, string>;   // upstream headers the channel needs ({} if none), parsed from
                                     // #EXTVLCOPT http-referrer/http-user-agent, #EXTHTTP, EXTINF user-agent=,
                                     // Kodi "url|Referer=..&User-Agent=.." (url is always stored without the pipe).
                                     // Send them back as `headers` when playing/queueing the channel.
}

interface Playlist {
  id: string;
  name: string;
  source_url: string | null;
  channel_count: number;
  groups: string[];
  created_at: string;        // ISO 8601
  updated_at: string;
}

type ResolveResult =
  | { type: "media"; media: ResolvedMedia }
  | { type: "playlist"; name: string; channels: Channel[] };   // un-saved preview of an M3U

interface Favorite { id: string; title: string; input: string; source_kind: SourceKind; thumbnail: string | null; created_at: string }
interface HistoryEntry { id: string; title: string; input: string; source_kind: SourceKind; thumbnail: string | null; device_id: string | null; played_at: string }

interface MediaTrack { id: number; type: "TEXT" | "AUDIO" | "VIDEO"; name: string | null; language: string | null }

interface QueueItem { id: string; input: string; title: string; thumbnail: string | null }

interface PlayerState {
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
  current_time: number;      // seconds, extrapolated server-side at updated_at
  duration: number | null;   // null for live
  seekable: boolean;
  volume_level: number;      // 0..1
  muted: boolean;
  tracks: MediaTrack[];
  active_track_ids: number[];
  queue: QueueItem[];
  showing_idle_image: boolean;
  updated_at: string;
}

interface Settings {
  idle_image_url: string | null;      // shown on connect / on stop when show_idle_on_stop
  show_idle_on_connect: boolean;
  show_idle_on_stop: boolean;
  default_device_id: string | null;
  public_base_url: string | null;     // override; null = auto
  force_proxy: boolean;               // always proxy streams
}

interface AppState {
  devices: Device[];
  active_device_id: string | null;
  players: Record<string, PlayerState>;   // keyed by device id, only connected ones
  discovering: boolean;
  version: number;                         // monotonically increasing
}

interface ApiError {
  detail: string;                          // English, technical (logs / fallback text only)
  code?: string;                           // stable machine code (list below) — the UI translates by it
  reason?: string;                         // optional finer-grained stable code (list below)
  params?: Record<string, string | number>; // values for the translated message, e.g. {host}, {status}
}
// Every error response has this shape, including unexpected ones (500, code "internal_error").
// Malformed URLs → 400 unsupported_source/malformed_url; an unreachable host → 502 resolve_failed/connect_failed
// ("Could not connect to …", params {host}).
```

## REST API (prefix `/api`)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/health` | | `{status:"ok", driver:string, version:string}` |
| GET | `/api/state` | | `AppState` |
| GET | `/api/devices` | | `Device[]` |
| POST | `/api/devices/discover` | | `Device[]` (runs discovery ~5s, non-blocking for other requests) |
| POST | `/api/devices/manual` | `{host, port?=8009, name?}` | `Device` |
| DELETE | `/api/devices/{id}` | | 204 (manual devices only) |
| POST | `/api/devices/{id}/connect` | | `PlayerState` (becomes `active_device_id`; shows idle image if enabled) |
| POST | `/api/devices/{id}/disconnect` | | 204 |
| POST | `/api/resolve` | `{input, kind?: SourceKind, headers?}` | `ResolveResult` |
| POST | `/api/devices/{id}/play` | `{input, kind?, title?, enqueue?: false, headers?}` | `PlayerState` (resolves + casts; if `enqueue` adds to queue) |
| POST | `/api/devices/{id}/control` | `{action, value?}` | `PlayerState` |
| POST | `/api/devices/{id}/tracks` | `{active_track_ids: number[]}` | `PlayerState` |
| POST | `/api/devices/{id}/idle` | | `PlayerState` (shows idle image) |
| POST | `/api/devices/{id}/queue` | `{input, kind?, title?, headers?}` | `PlayerState` (auto-connects) |
| DELETE | `/api/devices/{id}/queue/{item_id}` | | `PlayerState` |
| PUT | `/api/devices/{id}/queue` | `{item_ids: string[]}` (reorder) | `PlayerState` |
| GET | `/api/playlists` | | `Playlist[]` |
| POST | `/api/playlists` | `{url?, content?, name?}` | `Playlist` (import & persist) |
| GET | `/api/playlists/{id}` | | `Playlist` |
| GET | `/api/playlists/{id}/channels` | query `q, group, offset=0, limit=100` | `{items: Channel[], total: number}` |
| POST | `/api/playlists/{id}/refresh` | | `Playlist` |
| DELETE | `/api/playlists/{id}` | | 204 |
| GET | `/api/favorites` | | `Favorite[]` |
| POST | `/api/favorites` | `{title, input, source_kind, thumbnail?}` | `Favorite` |
| DELETE | `/api/favorites/{id}` | | 204 |
| GET | `/api/history` | query `limit=50` | `HistoryEntry[]` |
| DELETE | `/api/history` | | 204 (clear) |
| GET | `/api/settings` | | `Settings` |
| PUT | `/api/settings` | `Partial<Settings>` | `Settings` |
| GET | `/api/local` | query `path=""` | `{path, entries: {name, path, is_dir, size, mime_type}[]}` (404 code `local_disabled` if no MEDIA_ROOT) |

`control.action` ∈ `play | pause | toggle | stop | seek | seek_relative | go_live | volume | volume_relative | mute | unmute | next | previous`.
`value`: seconds for `seek`/`seek_relative`, 0..1 for `volume`, delta for `volume_relative`.
`previous` replays the item played before the current one on that device; with no such item it
restarts the current item (seek to 0), so it never fails just because there is no history. The UI
therefore enables "Previous" whenever something is playing (labelled as previous / restart).

Errors: non-2xx with `ApiError`. Codes include `device_not_found`, `not_connected`,
`resolve_failed`, `unsupported_source`, `local_disabled`, `playlist_not_found`
(backend also uses: `validation_error` 422, `cast_error` 502, `queue_empty` 409, `queue_item_not_found`,
`not_manual` 400, `favorite_not_found`, `no_source_url` 400, `forbidden_path` 403, `token_not_found`,
`restream_failed` 502, `session_not_found`, `stream_not_found`, `browser_limit` 429 (params `{max}`), `browser_disabled` 503,
`browser_unavailable` 503, `browser_error` 502, `popup_not_found` 404, `internal_error` 500). The frontend adds
`network_error` for a server it can't reach.

`reason` values (stable; params in braces):
- `resolve_failed`: `connect_failed` {host}, `fetch_failed` {host}, `upstream_http` {status}, `no_stream_on_page`
  (web page with no detectable stream: suggest the interactive browser), `extract_failed` (yt-dlp), `not_m3u`,
  `empty_playlist`, `local_file_not_found`;
- `unsupported_source`: `malformed_url`, `unsupported_input`, `local_unavailable`, `is_playlist` (an M3U given to
  play: import it), `hls_not_playlist` (an HLS stream given to the playlist import).

All backend text (`detail`, toast `message`) is **English**; user-facing wording lives in the frontend dictionaries,
keyed by `code` / `reason`. Clients must fall back to `detail` / `message` for codes they don't know.

`headers?: Record<string,string>` (play/queue/resolve) = upstream request headers (Referer, User-Agent, Origin,
Cookie, Authorization) e.g. `Channel.headers`. The backend folds them into the input using the Kodi syntax
`url|Referer=<urlencoded>&User-Agent=<urlencoded>`, which is also accepted directly as `input`; that form is what
history/queue/favorites store, so replaying an entry sends the headers again.

Backend behaviour notes (implemented in `backend/`):
- `play`, browser `cast`, `enqueue: true` and `POST .../queue` **auto-connect** the device if needed;
  `control`/`tracks`/`idle` return 409 `not_connected`.
- Every LOAD goes to the **Default Media Receiver** (launched first if another app such as YouTube is in front).
- On connect the media status is fetched before deciding about the idle image; `show_idle_on_connect` only casts
  it when no app is running (Backdrop) or the Default Media Receiver is idle — never over another app or media
  already playing. Connecting to an idle device does not launch any receiver app.
- While the driver reconnects after a network blip the player stays in `players` with `connected: false` (and stays
  the active device); it is removed only when the connection is given up or on disconnect. pychromecast's per-attempt
  `FAILED`/`FAILED_RESOLVE` don't end the session, only `DISCONNECTED` does; after the first connect (2 tries) the
  reconnect loop gets 60 tries (several minutes). pychromecast backs off exponentially between those tries, so
  while a session is not connected the driver also probes the device's port (after 10 s, then every 5 s) and opens
  a fresh connection as soon as it answers (a rebooted TV is back within seconds, not minutes).
- Connecting to a manual device not seen by mDNS first checks that `host:port` accepts TCP (3 s, then 502), then
  reads the device's `eureka_info` for its real name (replacing the default `Chromecast @ <ip>`, never a name the
  user chose), model and manufacturer.
- A manual device keeps its `manual-<host>` id even when mDNS later discovers the same host (one row per host, the
  manual row enriched with the discovered name/model); ids stay valid for every endpoint.
- `enqueue: true` (play or browser cast) and `POST .../queue` start playback immediately when the device is idle
  (or showing the idle image); otherwise the item is appended to the queue. The queue advances on `FINISHED`;
  when it is empty and `show_idle_on_stop` is on, the idle image is shown. `stop` clears the queue (and shows the
  idle image when `show_idle_on_stop`). `go_live` reloads a LIVE stream (jumps to the live edge).
  It also advances (with an error toast) when media we loaded ends in `IDLE` / `ERROR` (LOAD accepted, then the URL
  turned out dead). A LOAD the receiver rejects is reported only by the request's 502; an `IDLE` / `ERROR` it
  broadcasts for that LOAD neither toasts nor advances the queue. Queue/previous entries older than 3 min are
  resolved again from their input before playback
  (yt-dlp/page URLs expire); browser-captured streams are played as captured.
- HLS whose CORS can't be verified (probed with `Origin: https://www.gstatic.com` on the playlist, first variant,
  audio rendition and their first segments; a CDN answering that Origin with an HTTP error is probed again without
  it, for master/live/segment format, and proxied), DASH whose manifest doesn't answer that Origin, any source needing
  Referer/Origin/Cookie/Authorization, any input whose User-Agent was given explicitly (`url|User-Agent=…`, playlist
  `#EXTVLCOPT:http-user-agent`; the Chromecast would send its own CrKey UA — the UA yt-dlp or the headless browser
  add on their own does not count), and everything when `force_proxy` is on, are cast through `/proxy`; `preview_url` is always a same-origin path for
  HLS/DASH. A DASH `type="dynamic"` MPD is LIVE. A URL ending in `.m3u8` whose body is an IPTV channel list (has
  `#EXTINF`, no HLS tags) is returned as a playlist, like `.m3u`.
- Playback changes on a device (play, LOAD from the queue on FINISHED, enqueue-when-idle, stop/next/previous/go_live)
  are serialized per device; a FINISHED that arrives after something else was loaded is ignored. Connects to the
  same device are serialized in the driver (one pychromecast connection per device).
- Casting a `/restream` URL starts ffmpeg right away and waits up to probe + startup time (~80 s) for the LOAD
  answer instead of the default 25 s.
  Raw MPEG-TS/FLV/AVI over HTTP, RTMP/RTSP/UDP and local `.avi/.ts/.flv/.wmv` go through `/restream`.
  Extension-less URLs answered as `application/octet-stream` (Xtream `/user/pass/123`) are recognised by their first
  bytes (TS sync byte 0x47 at 0/188/376, `FLV`, RIFF/AVI, ASF, `ftyp`, EBML); no Content-Length ⇒ LIVE.
- Unreachable hosts (connect refused / connect timeout) give 502 `resolve_failed` for media URLs too (`.m3u8`, `.mpd`,
  `.mp4`, `.ts`…), not only for pages; an HTTP error from a reachable host is still cast.
- Every upstream request (probes, `/proxy`, ffmpeg) sends a desktop-browser `User-Agent` unless the source captured
  or specified its own.
- Matroska (`.mkv`, `video/x-matroska`) is announced to the receiver as `video/mp4` (its `canPlayType` rejects
  `video/x-matroska`, while the demuxer plays H.264/AAC MKV).
- yt-dlp: muxed formats are preferred; when a site only offers split video/audio (current YouTube), the HLS
  format's `manifest_url` (master playlist with the audio renditions) is cast.
- The Docker image ships yt-dlp's JavaScript runtime (deno) and its EJS challenge-solver scripts (`yt-dlp-ejs`), at
  the versions of yt-dlp's `default` + `pin-deno` extras, so YouTube extraction does not depend on the deprecated
  JS-less client; CI checks both are found in the built image.

## Media/proxy endpoints (no `/api` prefix, consumed by the Chromecast and by the browser preview)

- `GET /proxy/{token}/{path}` — HLS-rewriting proxy. The backend registers a token → `{url, headers}`.
  Playlists (`.m3u8`) are fetched with the stored headers (Referer, User-Agent, Cookie captured
  from the page) and every URI inside is rewritten to go through the proxy. Playlists are recognised by
  content-type/extension **or by sniffing the body for `#EXTM3U`** (CDNs serve them as text/plain,
  octet-stream, `stream.php?id=`…) and are always answered as `application/vnd.apple.mpegurl`.
  Segments/keys are streamed through. Adds `Access-Control-Allow-Origin: *`. Supports Range requests for MP4.
  A master whose variants mix video codec families (by `CODECS`: avc1/avc3, hvc1/hev1, vp09, av01…) keeps only
  the variants (and I-frame playlists) of the first variant's family, plus audio-only/codec-less ones: the LOAD's
  `hlsSegmentFormat` is probed on the first variant and the receiver must not switch to another container.
  **DASH** manifests (by content-type/`.mpd` or a `<MPD` body) are rewritten too, into *clear* proxy paths
  `/proxy/{token}/a/{scheme}/{host}/{path}[?query]` so segment templates (`$Number%05d$`) and relative/`../`
  paths keep working inside the token: MPD-level `<BaseURL>`s are made absolute (one pointing at the manifest is
  inserted when missing), absolute or host-relative `<BaseURL>`/`media`/`initialization`/`index`/`sourceURL`/
  `<Location>` values are mapped, relative ones are left to the player. A malformed `u/<b64>`/`a/` path → 404
  `token_not_found`.
- `GET /restream/{token}/index.m3u8` — ffmpeg to HLS for sources the Chromecast cannot play directly (raw TS
  over HTTP, RTMP, odd containers). The video codec is probed with ffprobe: only H.264 is copied, anything else
  (MPEG-4 Part 2/Xvid, MPEG-2, VC-1/WMV, FLV1…) is transcoded to H.264 (if the probe fails: copy, then transcode
  when ffmpeg can't produce a playlist). **Live** inputs get a sliding window (restarts continue the media
  sequence with `append_list`); **files/VOD** (local files, HTTP files with a Content-Length) are read at native
  speed (`-re`) into an `EVENT` playlist that keeps every segment and gets `#EXT-X-ENDLIST` at the end; a finished
  job is served as is, never restarted. Idle jobs (no request for 60 s) are cleaned up only when their URL is no
  longer loaded on a device; a loaded (e.g. paused) VOD job is left alone, a loaded live job only has ffmpeg stopped
  (its window is kept so the restart appends). When a device loads other media, shows the idle image or stops, the
  job behind its previous `/restream` URL is released at once unless another device has it loaded: ffmpeg (and a
  running ffprobe) is stopped so single-connection IPTV accounts can open the next channel, the output is kept for
  the reaper, and playlist requests that would restart it answer 502 `restream_failed` until it is cast again.
- `GET /local/{path}` — serves files under `MEDIA_ROOT` with Range support.
  `?as=vtt` on a `.srt` file answers it converted to WebVTT (UTF-8, or cp1252 for legacy files). Resolving a local
  video attaches the sidecar subtitles next to it as `subtitles` (`Film.vtt`, `Film.srt`, `Film.<lang>[.x].srt|vtt`,
  case-insensitive; `lang` = the first dotted part); `.srt`/`.vtt` files are not listed by `GET /api/local`.
- `OPTIONS` on `/proxy/…`, `/restream/…`, `/local/…`, `/idle.jpg` answers any origin's CORS preflight (204,
  `Access-Control-Allow-Origin: *`, methods `GET, HEAD, OPTIONS`, headers incl. `Range`): the receiver
  (`Origin: https://www.gstatic.com`) preflights its Range XHRs. The dev-only CORS policy applies to the rest.
- `GET /idle.jpg` — default idle image if none configured.

## WebSocket `/ws`

Server → client messages (JSON):

```ts
type ServerMessage =
  | { type: "state"; data: AppState }                       // full snapshot: on connect and after every change
  | { type: "toast"; level: "info" | "success" | "error"; message: string;   // English fallback text
      code?: string; params?: Record<string, string | number> }               // translate by code when known
  | { type: "pong" };
```

Toast codes (always sent with `params`, possibly `{}`):
- `cast_error` {detail} — driver/receiver error (detail is technical English);
- `playback_failed` {title} — the receiver accepted a LOAD and then gave up (dead / expired URL);
- `queue_skipped` {title, detail, error_code, error_reason, …the error's own params} — a queued entry could not be
  played and was skipped; the UI translates `error_code`/`error_reason` like an `ApiError`.

Client → server: `{ "type": "ping" }` (every 20s). All commands go through REST; every mutation
results in a `state` broadcast to **all** clients, which is how every open UI stays in sync.
While any device is PLAYING the server re-broadcasts at least every 1s (for the progress bar).

## Interactive remote browser ("Browser" feature)

The user gives a URL; the backend opens it in a real Chromium (Playwright) on the server, streams the
viewport to the UI, and forwards the user's taps/typing. Meanwhile it **sniffs every network request**
and captures media streams (by URL pattern `.m3u8 .mpd .mp4 .ts .webm .flv`, by response content-type
`application/vnd.apple.mpegurl application/x-mpegurl application/dash+xml video/*`, including requests made
by workers/iframes and blob-backed MSE players whose manifests are fetched over the network). Each captured
stream keeps the request headers (Referer, Origin, User-Agent, Cookie) so it can be cast through the proxy.

```ts
interface CapturedStream {
  id: string;
  url: string;
  mime_type: string | null;
  kind: "hls" | "dash" | "progressive" | "unknown";
  page_url: string;
  frame_url: string | null;
  headers: Record<string, string>;
  detected_at: string;
  is_master: boolean | null;          // HLS master vs media playlist when known
}

interface BrowserSession {
  id: string;
  url: string;                        // current page URL
  title: string | null;
  viewport: { width: number; height: number };
  captured: CapturedStream[];
  created_at: string;
}
```

REST:

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/browser/sessions` | `{url, viewport?: {width,height}}` (default 390x844 mobile, or 1280x720 desktop) | `BrowserSession` |
| GET | `/api/browser/sessions` | | `BrowserSession[]` |
| GET | `/api/browser/sessions/{id}` | | `BrowserSession` |
| POST | `/api/browser/sessions/{id}/navigate` | `{url}` or `{action: "back"\|"forward"\|"reload"}` | `BrowserSession` |
| DELETE | `/api/browser/sessions/{id}` | | 204 |
| POST | `/api/browser/sessions/{id}/cast` | `{stream_id, device_id}` | `PlayerState` (cast via proxy with captured headers; recorded in history) |

Max 2 concurrent sessions (a 3rd create first reaps idle ones, else 429 `browser_limit`); sessions with no
connected `/ws/browser` viewer and no input for 10 minutes are closed. Casting/bookmarking a captured stream records
the **page URL** (`source_kind: "webpage"`) in history/favorites, because captured stream URLs carry expiring
tokens/cookies; the queue keeps the already-resolved media (with headers) for playback.

WebSocket `/ws/browser/{id}`:

```ts
// server → client
type BrowserServerMsg =
  | { type: "frame"; data: string /* base64 JPEG */; width: number; height: number }
  | { type: "session"; data: BrowserSession }        // on URL/title change. The first one after connecting is
                                                      // complete; later ones OMIT the `thumbnail` key of each
                                                      // captured stream (already sent in "captured") → merge, don't replace
  | { type: "captured"; data: CapturedStream }        // a new stream was found; re-sent with the SAME id once
                                                      // quality/is_live/thumbnail are probed → clients upsert by id
  | { type: "closed" };
// client → server (coordinates in page CSS pixels of the viewport)
type BrowserClientMsg =
  | { type: "click"; x: number; y: number; button?: "left" | "right" }
  | { type: "tap"; x: number; y: number }
  | { type: "scroll"; x: number; y: number; dx: number; dy: number }
  | { type: "key"; key: string }                      // Playwright key name, e.g. "Enter"
  | { type: "text"; text: string }
  | { type: "mousemove"; x: number; y: number };
```

Frames come from CDP `Page.startScreencast` (JPEG, quality ~60, everyNthFrame tuned) — fallback to periodic screenshots.
While a captured stream's thumbnail is taken (clipped `page.screenshot`), Chromium emits screencast frames sized like
the clip: those are dropped, and the screencast is restarted afterwards so viewers get a fresh full-viewport frame
(a static page sends none on its own).
Popups/new tabs opened by the page are followed into the same session (ad popups closed automatically, but their
traffic is still sniffed). Tests mock Playwright entirely.

### Browser UX reference (added by the user after the build started — reviewers: check this is implemented)

The user's reference is a mobile "web video caster" style app. Required behaviour:

- Top bar: menu, URL field (shows host, tap to edit), reload, and a **cast icon** that opens the device sheet.
- Device sheet is minimal and fast: title "Invia video a…", list of devices (cast icon + name, active one highlighted),
  "Aggiorna elenco" (rediscover) row, "Annulla". Same sheet reused app-wide.
  When a cast needs a target (no connected active device), the client picks the active/default device or asks
  via this sheet but does **not** call `/connect` first: play / queue / browser cast auto-connect, and an explicit
  connect would LOAD the idle image just before the media. Picking from the header icon still connects.
- The remote page view fills the space between top bar and bottom toolbar.
- **When a stream is detected**, a bottom panel slides up over the page (dismissable with ×) with:
  thumbnail of the video (use a frame snapshot of the page/video element), the page title as stream title,
  **quality** (e.g. "720p HD", derived from HLS master RESOLUTION / probed size) and a **Live** badge when live,
  and four big actions: **Cast**, **Queue** (add to queue), **Play** (preview in-app), **Bookmark** (favorite).
  If several streams were captured, the panel lets you switch between them (best quality first, ads/short segments deprioritized).
- Bottom toolbar: back, forward, home, sessions/tabs count, new session, more menu.

Contract additions (optional/nullable fields, backward compatible) on `CapturedStream`:

```ts
  title: string | null;          // page title at detection time
  thumbnail: string | null;      // data URL (small JPEG) or proxy URL
  quality: string | null;        // e.g. "720p HD", "1080p FHD", "SD"
  width: number | null; height: number | null;
  is_live: boolean | null;       // HLS without EXT-X-ENDLIST ⇒ live
  score: number;                 // ranking: higher = more likely the main video
  preview_url: string | null;    // (backend addition) same-origin /proxy path replaying the captured headers,
                                 // usable directly by the in-app "Play" preview
```

`POST /api/browser/sessions/{id}/cast` also accepts `{stream_id, device_id, enqueue?: boolean}`;
`POST /api/browser/sessions/{id}/favorite` `{stream_id}` → `Favorite`.

## Ad blocking, popup control, quick close (HARD REQUIREMENT — added by the user, reviewers must enforce)

Modelled on **uBlock Origin**:

- **Network filtering engine** compatible with uBO/ABP filter syntax. Use Brave's `adblock` engine (pip `adblock`,
  Rust bindings) fed with the same default lists uBO ships: uBlock filters (+ badware, privacy, unbreak,
  quick-fixes), EasyList, EasyPrivacy, Peter Lowe's list, and EasyList Italy. Lists are downloaded to `DATA_DIR/filters`,
  refreshed every 24h, with a small **bundled fallback list** in the repo (used offline and in tests).
  Every request of the browser context goes through `context.route("**/*")` → engine check (with request type and
  source frame URL, like uBO) → `route.abort()` if blocked. Redirect resources (e.g. noop.js) when the engine says so.
- **Cosmetic filtering**: inject the engine's hide selectors / generic cosmetic CSS per frame (and scriptlets when
  supported by the engine) so overlays and fake "play" ad layers disappear.
- **Never block the real stream**: media manifests/segments that the sniffer recognises are still captured even if a
  filter matches; blocked requests count as blocked but stream detection runs before the abort decision.
- **Per-site toggle** like uBO's big power button: "Blocco pubblicità attivo su questo sito" (persisted allowlist of
  hostnames in settings). A badge shows the **blocked-requests count** for the current page.
- **Popups / new tabs**: every `context.on("page")` (window.open, target=_blank, tab-under) is held, never shown
  automatically. Policy from settings `popup_policy`: `"ask"` (default) | `"block"` | `"allow"`.
  - A popup whose URL matches the ad filters (uBO `$popup` semantics) is **closed automatically** (still sniffed first) and counted.
  - Otherwise in `ask` mode the UI shows a compact prompt "La pagina vuole aprire: <host> — Apri / Blocca / Blocca sempre per questo sito".
  - Top-level navigations away from the page's site triggered without a user gesture (redirect-ads) are blocked and also prompt.
- **Quick close / panic**: the browser screen always shows a prominent close (×) control in the top bar; one tap closes
  the session immediately (no confirmation) and returns to the previous screen. Also "Stop" for page audio/video.
  Closing must kill the Playwright page/context within ~1s.

Contract additions (backward compatible):

```ts
interface BrowserSession {
  // ...existing fields
  adblock_enabled: boolean;       // effective for current site
  blocked_count: number;          // for current page load
  pending_popups: PopupRequest[];
}
interface PopupRequest { id: string; url: string; host: string; opener_url: string; created_at: string }

interface Settings {
  // ...existing fields
  adblock_enabled: boolean;               // global default true
  adblock_disabled_hosts: string[];       // per-site allowlist (uBO "power button off")
  popup_policy: "ask" | "block" | "allow";
  popup_blocked_hosts: string[];          // "Blocca sempre per questo sito"
}
```

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/browser/sessions/{id}/adblock` | `{enabled: boolean}` (toggles for current host, persisted) | `BrowserSession` |
| POST | `/api/browser/sessions/{id}/popups/{popup_id}` | `{decision: "open" \| "block" \| "block_always"}` | `BrowserSession` (`open` switches the session view to the popup page) |
| POST | `/api/filters/refresh` | | `{lists: {name, rules, updated_at}[]}` |
| GET | `/api/filters` | | same as above |

`updated_at` is `string | null` (null for the bundled fallback list, which is always the first entry).

Implementation notes (integration pass):
- `window.open` and `target=_blank` clicks are intercepted **inside the page** by an init script (all frames) and
  reported through `context.expose_binding("__cwPopup")`, so no real tab is created before the policy decides
  (with request interception active, a real popup tab stalls the opener's nested iframes in Chromium).
  `context.on("page")` + the route handler remain as fallback (a popup's first navigation has no frame in
  Playwright; it is treated as a popup). A popup URL that is itself media is captured as a stream.
- "Blocca sempre per questo sito" stores the **opener** page host in `popup_blocked_hosts`.
- `POST .../adblock` reloads the page so the new state applies; `blocked_count` resets on each top-level page load.
- The `webpage` resolver uses the same engine + popup guard (when ad blocking is enabled globally / for the host).
- Cosmetic filtering injects host-specific hide selectors and the generic class/id selectors matching each frame;
  scriptlet injection is not supported (uBO scriptlet resources are not bundled).

WebSocket `/ws/browser/{id}` additions:
server → `{type:"popup"; data: PopupRequest}`, `{type:"blocked"; count: number}`;
client → `{type:"popup_decision"; id: string; decision: "open"|"block"|"block_always"}`, `{type:"stop_media"}`.

Tests: engine blocks a known ad URL from the bundled list and allows a stream URL; popup held → decision applied;
ad popup auto-closed; per-host toggle persisted; quick close tears down the page (fake Playwright objects);
plus in the `@pytest.mark.browser` fixture site, an ad iframe + `window.open` popup that must be blocked while the
real m3u8 is still captured.

## Dynamic / JavaScript-heavy pages (HARD REQUIREMENT — added by the user, reviewers must enforce)

Real target sites (e.g. live-sport streaming pages) build the player **with JavaScript**: the video URL is never in
the static HTML. It is produced by obfuscated/packed scripts, fetched via XHR/fetch, injected into nested
**cross-origin iframes** (often 2–3 levels deep), played through MSE with `blob:` URLs, and gated behind overlays,
ad popups and a "play" click. Therefore:

- **Never** resolve a web page by downloading its HTML with httpx/requests and regex-searching it. The `webpage`
  resolver and the interactive browser both use a real Chromium (Playwright) executing JavaScript.
- Detection happens at the **network layer** of the whole browser context (all frames, iframes, popups, workers):
  `context.on("request"/"response")` + CDP `Network` events where needed. `blob:` players are handled because their
  manifests/segments are still fetched over the network. Also inspect `<video>.src/currentSrc` in every frame as a fallback.
- Don't wait for `networkidle` (live pages never go idle): navigate with `domcontentloaded`, then poll for captures
  up to a timeout (e.g. 25s), while trying to start playback: click centre of the largest `<video>`/player element
  **in every frame**, common play selectors (`.vjs-big-play-button`, `.jw-icon-playback`, `[aria-label*=play i]`,
  `.plyr__control--overlaid`, `button[class*=play]`), dismiss overlays, close ad popups (but sniff them first).
- Look like a normal browser: realistic desktop/mobile User-Agent and headers, no `HeadlessChrome` brand in the
  `Sec-CH-UA` client hints / `navigator.userAgentData` (the full Chromium in new headless mode, `channel="chromium"`,
  not chromium-headless-shell), `navigator.webdriver` hidden, locale
  `it-IT`, timezone `Europe/Rome`, viewport set; launch Chromium with sane flags (`--autoplay-policy=no-user-gesture-required`).
- Capture **request headers actually sent** (Referer/Origin of the iframe, Cookie, UA) per stream — iframe-origin
  Referer is usually what the CDN checks — and replay them through the proxy when casting.
- Ranking: prefer HLS master playlists > media playlists > progressive; ignore ad domains/very short VOD (pre-rolls);
  dedupe by URL without volatile query params.
  In the remote browser: a URL is the same stream when it only differs by volatile params (`_HLS_msn`/`_HLS_part`,
  `token`, `_`, `t`, `expires`…; other params such as `?ch=2` still distinguish streams). Segments are never
  captured: `.m4s`/`.aac`/CMAF, segment-named `.ts`/`.mp4` (`seg-12-…`, `fileSequence123`, `chunk_3`, `init…mp4`)
  or `video/mp2t` bodies, and any progressive hit in a frame that already loaded an HLS/DASH manifest.
  Viewers' socket queues coalesce screencast frames (only the latest waits), so frames never push out
  `captured`/`popup`/`blocked` messages. Thumbnails are capped at ~120 KB.
- If the automatic resolve finds nothing, the API returns `resolve_failed` with a hint and the UI offers
  **"Apri nel browser interattivo"** with the same URL so the user can click through manually.
- **Integration test (required)**: a local fixture site served by a test HTTP server where the page loads, after a
  delay and only after clicking a play button, a cross-origin-style **nested iframe** whose obfuscated script
  (e.g. built with `atob`/string concatenation) fetches a JSON and then requests a `.m3u8` with a required Referer.
  The real Playwright resolver must capture that m3u8 and its Referer. Mark it `@pytest.mark.browser`; it runs when
  Chromium is installed (`playwright install chromium`) and is skipped otherwise. The Verify step must run it.

## Testing rules

- `cd backend && pytest` must pass with **no network and no Chromecast** (fake driver, mocked HTTP via respx, yt-dlp/playwright mocked).
- `cd frontend && npm test` (vitest) and `npm run lint` and `npm run typecheck` and `npm run build` must pass.

## Internationalisation (frontend)

- Languages: **English** (default and fallback) and **Italian** (full localisation). No locale route segments or
  middleware (static export): the language is client state.
- `src/i18n/en.ts` is the source of truth (flat dotted keys, `as const`); `it.ts` is typed `Messages`, so it must have
  exactly the same keys. `{name}` placeholders; plurals as `<key>_one` / `<key>_other` read with `t.plural(key, n)`
  (Intl.PluralRules). Dates, relative times and numbers use `Intl` with the current locale.
- Initial locale: saved choice (`localStorage["cw.locale"]`) → `navigator.language` starting with `it` → `en`.
  The static HTML is English; an inline `<head>` script (`i18n/locale-bootstrap.ts`) sets `<html lang>` and, for a
  non-English locale, hides the body until `LocaleSync` has applied it (no English flash; revealed anyway 1.5 s after
  `load` / 10 s max). `LocaleSync` keeps `<html lang>` in sync and follows changes made in other tabs (`storage` event).
  Switching (Settings → Language, or the remote browser's menu) is instant, without reload.
- Every user-visible string goes through the dictionaries; API errors and server toasts are translated by `code` /
  `reason` (see above). The web manifest name/description stay English. Tests enforce identical key sets, no empty
  values, matching placeholders, and scan `src/app` + `src/components` for hard-coded Italian.
