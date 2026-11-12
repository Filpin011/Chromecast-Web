import type { AppState, CapturedStream, Device, PlayerState } from "@/lib/api/types";

export function makeDevice(over: Partial<Device> = {}): Device {
  return {
    id: "dev-1",
    name: "Salotto",
    model: "Chromecast Ultra",
    host: "192.168.1.50",
    port: 8009,
    cast_type: "cast",
    manufacturer: "Google Inc.",
    manual: false,
    online: true,
    ...over,
  };
}

export function makePlayer(over: Partial<PlayerState> = {}): PlayerState {
  return {
    device_id: "dev-1",
    connected: true,
    app_name: "Default Media Receiver",
    player_state: "PLAYING",
    idle_reason: null,
    title: "Rai 1 HD",
    thumbnail: null,
    media_url: "http://x/live.m3u8",
    original_input: "http://x/live.m3u8",
    stream_type: "LIVE",
    current_time: 10,
    duration: null,
    seekable: false,
    volume_level: 0.5,
    muted: false,
    tracks: [],
    active_track_ids: [],
    queue: [],
    showing_idle_image: false,
    updated_at: "2026-11-12T10:00:00Z",
    ...over,
  };
}

export function makeAppState(over: Partial<AppState> = {}): AppState {
  const device = makeDevice();
  return {
    devices: [device],
    active_device_id: device.id,
    players: { [device.id]: makePlayer() },
    discovering: false,
    version: 1,
    ...over,
  };
}

export function makeCaptured(over: Partial<CapturedStream> = {}): CapturedStream {
  return {
    id: "s1",
    url: "https://cdn.example.com/live/master.m3u8",
    mime_type: "application/vnd.apple.mpegurl",
    kind: "hls",
    page_url: "https://site.example.com/watch",
    frame_url: null,
    headers: { Referer: "https://site.example.com/" },
    detected_at: "2026-11-12T10:00:00Z",
    is_master: true,
    title: "Partita in diretta",
    thumbnail: null,
    quality: null,
    width: 1280,
    height: 720,
    is_live: true,
    score: 10,
    ...over,
  };
}
