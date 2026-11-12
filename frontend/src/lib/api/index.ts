import { getApiBase } from "@/lib/config";
import {
  BrowserApi,
  DevicesApi,
  FavoritesApi,
  FiltersApi,
  HistoryApi,
  LocalApi,
  PlayerApi,
  PlaylistsApi,
  ResolveApi,
  SettingsApi,
  SystemApi,
} from "./clients";
import { HttpClient, type FetchLike } from "./http";

export * from "./types";
export { ApiError, HttpClient } from "./http";
export * from "./clients";

/** Aggregate of all typed resource clients. */
export class Api {
  readonly http: HttpClient;
  readonly system: SystemApi;
  readonly devices: DevicesApi;
  readonly player: PlayerApi;
  readonly resolver: ResolveApi;
  readonly playlists: PlaylistsApi;
  readonly favorites: FavoritesApi;
  readonly history: HistoryApi;
  readonly settings: SettingsApi;
  readonly local: LocalApi;
  readonly browser: BrowserApi;
  readonly filters: FiltersApi;

  constructor(base: string = getApiBase(), fetchImpl?: FetchLike) {
    this.http = new HttpClient(base, fetchImpl);
    this.system = new SystemApi(this.http);
    this.devices = new DevicesApi(this.http);
    this.player = new PlayerApi(this.http);
    this.resolver = new ResolveApi(this.http);
    this.playlists = new PlaylistsApi(this.http);
    this.favorites = new FavoritesApi(this.http);
    this.history = new HistoryApi(this.http);
    this.settings = new SettingsApi(this.http);
    this.local = new LocalApi(this.http);
    this.browser = new BrowserApi(this.http);
    this.filters = new FiltersApi(this.http);
  }
}

export const api = new Api();
