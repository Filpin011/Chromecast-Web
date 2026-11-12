import type { HttpClient } from "./http";
import type {
  AppState,
  BrowserCastRequest,
  BrowserSession,
  Channel,
  ChannelQuery,
  ControlAction,
  Device,
  Favorite,
  FavoriteCreate,
  FilterLists,
  Health,
  HistoryEntry,
  LocalListing,
  ManualDeviceRequest,
  NavigateRequest,
  Page,
  PlayerState,
  PlayRequest,
  QueueRequest,
  Playlist,
  PopupDecision,
  PlaylistImportRequest,
  ResolveResult,
  Settings,
  SourceKind,
  Viewport,
} from "./types";

const enc = encodeURIComponent;

abstract class Resource {
  constructor(protected readonly http: HttpClient) {}
}

export class SystemApi extends Resource {
  health() {
    return this.http.get<Health>("/api/health");
  }
  state() {
    return this.http.get<AppState>("/api/state");
  }
}

export class DevicesApi extends Resource {
  list() {
    return this.http.get<Device[]>("/api/devices");
  }
  discover() {
    return this.http.post<Device[]>("/api/devices/discover");
  }
  addManual(req: ManualDeviceRequest) {
    return this.http.post<Device>("/api/devices/manual", req);
  }
  remove(id: string) {
    return this.http.delete(`/api/devices/${enc(id)}`);
  }
  connect(id: string) {
    return this.http.post<PlayerState>(`/api/devices/${enc(id)}/connect`);
  }
  disconnect(id: string) {
    return this.http.post<void>(`/api/devices/${enc(id)}/disconnect`);
  }
}

export class PlayerApi extends Resource {
  play(deviceId: string, req: PlayRequest) {
    return this.http.post<PlayerState>(`/api/devices/${enc(deviceId)}/play`, req);
  }
  control(deviceId: string, action: ControlAction, value?: number) {
    const body = value === undefined ? { action } : { action, value };
    return this.http.post<PlayerState>(`/api/devices/${enc(deviceId)}/control`, body);
  }
  setTracks(deviceId: string, activeTrackIds: number[]) {
    return this.http.post<PlayerState>(`/api/devices/${enc(deviceId)}/tracks`, {
      active_track_ids: activeTrackIds,
    });
  }
  showIdle(deviceId: string) {
    return this.http.post<PlayerState>(`/api/devices/${enc(deviceId)}/idle`);
  }
  enqueue(deviceId: string, req: QueueRequest) {
    return this.http.post<PlayerState>(`/api/devices/${enc(deviceId)}/queue`, req);
  }
  removeFromQueue(deviceId: string, itemId: string) {
    return this.http.delete<PlayerState>(`/api/devices/${enc(deviceId)}/queue/${enc(itemId)}`);
  }
  reorderQueue(deviceId: string, itemIds: string[]) {
    return this.http.put<PlayerState>(`/api/devices/${enc(deviceId)}/queue`, {
      item_ids: itemIds,
    });
  }
}

export class ResolveApi extends Resource {
  resolve(input: string, kind?: SourceKind, signal?: AbortSignal) {
    return this.http.post<ResolveResult>(
      "/api/resolve",
      kind ? { input, kind } : { input },
      { signal },
    );
  }
}

export class PlaylistsApi extends Resource {
  list() {
    return this.http.get<Playlist[]>("/api/playlists");
  }
  get(id: string) {
    return this.http.get<Playlist>(`/api/playlists/${enc(id)}`);
  }
  import(req: PlaylistImportRequest) {
    return this.http.post<Playlist>("/api/playlists", req);
  }
  channels(id: string, q: ChannelQuery = {}, signal?: AbortSignal) {
    return this.http.get<Page<Channel>>(`/api/playlists/${enc(id)}/channels`, {
      query: { q: q.q, group: q.group, offset: q.offset ?? 0, limit: q.limit ?? 100 },
      signal,
    });
  }
  refresh(id: string) {
    return this.http.post<Playlist>(`/api/playlists/${enc(id)}/refresh`);
  }
  remove(id: string) {
    return this.http.delete(`/api/playlists/${enc(id)}`);
  }
}

export class FavoritesApi extends Resource {
  list() {
    return this.http.get<Favorite[]>("/api/favorites");
  }
  add(req: FavoriteCreate) {
    return this.http.post<Favorite>("/api/favorites", req);
  }
  remove(id: string) {
    return this.http.delete(`/api/favorites/${enc(id)}`);
  }
}

export class HistoryApi extends Resource {
  list(limit = 50) {
    return this.http.get<HistoryEntry[]>("/api/history", { query: { limit } });
  }
  clear() {
    return this.http.delete("/api/history");
  }
}

export class SettingsApi extends Resource {
  get() {
    return this.http.get<Settings>("/api/settings");
  }
  update(patch: Partial<Settings>) {
    return this.http.put<Settings>("/api/settings", patch);
  }
}

export class LocalApi extends Resource {
  list(path = "") {
    return this.http.get<LocalListing>("/api/local", { query: { path } });
  }
}

export class BrowserApi extends Resource {
  create(url: string, viewport?: Viewport) {
    return this.http.post<BrowserSession>(
      "/api/browser/sessions",
      viewport ? { url, viewport } : { url },
    );
  }
  list() {
    return this.http.get<BrowserSession[]>("/api/browser/sessions");
  }
  get(id: string) {
    return this.http.get<BrowserSession>(`/api/browser/sessions/${enc(id)}`);
  }
  navigate(id: string, req: NavigateRequest) {
    return this.http.post<BrowserSession>(`/api/browser/sessions/${enc(id)}/navigate`, req);
  }
  close(id: string) {
    return this.http.delete(`/api/browser/sessions/${enc(id)}`);
  }
  cast(id: string, req: BrowserCastRequest) {
    return this.http.post<PlayerState>(`/api/browser/sessions/${enc(id)}/cast`, req);
  }
  favorite(id: string, streamId: string) {
    return this.http.post<Favorite>(`/api/browser/sessions/${enc(id)}/favorite`, {
      stream_id: streamId,
    });
  }
  /** uBO-style "power button" for the current site (persisted server-side, page reloads). */
  setAdblock(id: string, enabled: boolean) {
    return this.http.post<BrowserSession>(`/api/browser/sessions/${enc(id)}/adblock`, { enabled });
  }
  popupDecision(id: string, popupId: string, decision: PopupDecision) {
    return this.http.post<BrowserSession>(
      `/api/browser/sessions/${enc(id)}/popups/${enc(popupId)}`,
      { decision },
    );
  }
}

export class FiltersApi extends Resource {
  list() {
    return this.http.get<FilterLists>("/api/filters");
  }
  refresh() {
    return this.http.post<FilterLists>("/api/filters/refresh");
  }
}
