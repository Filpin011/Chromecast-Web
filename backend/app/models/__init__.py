"""Pydantic API schemas — mirror of docs/ARCHITECTURE.md."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SourceKind = Literal["direct", "webpage", "m3u", "ytdlp", "local"]
StreamType = Literal["LIVE", "BUFFERED"]
PlayerStateName = Literal["IDLE", "PLAYING", "PAUSED", "BUFFERING", "UNKNOWN"]
StreamKind = Literal["hls", "dash", "progressive", "unknown"]
# Cast hlsSegmentFormat (None = MPEG-TS, the receiver default)
HlsSegmentFormat = Literal["fmp4", "aac", "mp3", "ac3", "e_ac3"]
ControlAction = Literal[
    "play",
    "pause",
    "toggle",
    "stop",
    "seek",
    "seek_relative",
    "go_live",
    "volume",
    "volume_relative",
    "mute",
    "unmute",
    "next",
    "previous",
]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Device(Model):
    id: str
    name: str
    model: str | None = None
    host: str
    port: int = 8009
    cast_type: str | None = None
    manufacturer: str | None = None
    manual: bool = False
    online: bool = True


class Subtitle(Model):
    url: str
    lang: str | None = None
    label: str


class ResolvedMedia(Model):
    url: str
    cast_url: str
    preview_url: str
    title: str
    mime_type: str
    stream_type: StreamType
    thumbnail: str | None = None
    source_kind: SourceKind
    original_input: str
    proxied: bool = False
    subtitles: list[Subtitle] = Field(default_factory=list)
    # HLS only: segment container when not MPEG-TS (sent as hlsSegmentFormat in the LOAD)
    hls_segment_format: HlsSegmentFormat | None = None
    # HLS only: "fmp4" when the video segments are fMP4 (sent as hlsVideoSegmentFormat), also
    # when hls_segment_format names a packed audio rendition; None = MPEG-TS video
    hls_video_segment_format: Literal["fmp4"] | None = None


class Channel(Model):
    id: str
    playlist_id: str | None = None
    name: str
    url: str
    logo: str | None = None
    group: str | None = None
    tvg_id: str | None = None
    # upstream request headers the channel needs (#EXTVLCOPT http-referrer/user-agent,
    # #EXTHTTP, Kodi "url|Referer=..."); send them back as PlayIn.headers
    headers: dict[str, str] = Field(default_factory=dict)


class Playlist(Model):
    id: str
    name: str
    source_url: str | None = None
    channel_count: int
    groups: list[str]
    created_at: datetime
    updated_at: datetime


class MediaResult(Model):
    type: Literal["media"] = "media"
    media: ResolvedMedia


class PlaylistResult(Model):
    type: Literal["playlist"] = "playlist"
    name: str
    channels: list[Channel]


ResolveResult = Annotated[MediaResult | PlaylistResult, Field(discriminator="type")]


class Favorite(Model):
    id: str
    title: str
    input: str
    source_kind: SourceKind
    thumbnail: str | None = None
    created_at: datetime


class HistoryEntry(Model):
    id: str
    title: str
    input: str
    source_kind: SourceKind
    thumbnail: str | None = None
    device_id: str | None = None
    played_at: datetime


class MediaTrack(Model):
    id: int
    type: Literal["TEXT", "AUDIO", "VIDEO"]
    name: str | None = None
    language: str | None = None


class QueueItem(Model):
    id: str
    input: str
    title: str
    thumbnail: str | None = None


class PlayerState(Model):
    device_id: str
    connected: bool = False
    app_name: str | None = None
    player_state: PlayerStateName = "UNKNOWN"
    idle_reason: str | None = None
    title: str | None = None
    thumbnail: str | None = None
    media_url: str | None = None
    original_input: str | None = None
    stream_type: StreamType | None = None
    current_time: float = 0.0
    duration: float | None = None
    seekable: bool = False
    volume_level: float = 1.0
    muted: bool = False
    tracks: list[MediaTrack] = Field(default_factory=list)
    active_track_ids: list[int] = Field(default_factory=list)
    queue: list[QueueItem] = Field(default_factory=list)
    showing_idle_image: bool = False
    updated_at: datetime = Field(default_factory=utcnow)


PopupPolicy = Literal["ask", "block", "allow"]
PopupDecision = Literal["open", "block", "block_always"]


class Settings(Model):
    idle_image_url: str | None = None
    show_idle_on_connect: bool = True
    show_idle_on_stop: bool = True
    default_device_id: str | None = None
    public_base_url: str | None = None
    force_proxy: bool = False
    # ad blocking / popups (remote browser)
    adblock_enabled: bool = True
    adblock_disabled_hosts: list[str] = Field(default_factory=list)
    popup_policy: PopupPolicy = "ask"
    popup_blocked_hosts: list[str] = Field(default_factory=list)


class SettingsUpdate(Model):
    idle_image_url: str | None = None
    show_idle_on_connect: bool | None = None
    show_idle_on_stop: bool | None = None
    default_device_id: str | None = None
    public_base_url: str | None = None
    force_proxy: bool | None = None
    adblock_enabled: bool | None = None
    adblock_disabled_hosts: list[str] | None = None
    popup_policy: PopupPolicy | None = None
    popup_blocked_hosts: list[str] | None = None


class AppState(Model):
    devices: list[Device] = Field(default_factory=list)
    active_device_id: str | None = None
    players: dict[str, PlayerState] = Field(default_factory=dict)
    discovering: bool = False
    version: int = 0


# ---------------------------------------------------------------- requests


class ManualDeviceIn(Model):
    host: str = Field(min_length=1)
    port: int = 8009
    name: str | None = None


class ResolveIn(Model):
    input: str = Field(min_length=1)
    kind: SourceKind | None = None
    headers: dict[str, str] | None = None  # upstream headers (e.g. Channel.headers)


class PlayIn(Model):
    input: str = Field(min_length=1)
    kind: SourceKind | None = None
    title: str | None = None
    enqueue: bool = False
    headers: dict[str, str] | None = None  # upstream headers (e.g. Channel.headers)


class QueueIn(Model):
    input: str = Field(min_length=1)
    kind: SourceKind | None = None
    title: str | None = None
    headers: dict[str, str] | None = None  # upstream headers (e.g. Channel.headers)


class QueueReorderIn(Model):
    item_ids: list[str]


class ControlIn(Model):
    action: ControlAction
    value: float | None = None


class TracksIn(Model):
    active_track_ids: list[int]


class PlaylistIn(Model):
    url: str | None = None
    content: str | None = None
    name: str | None = None


class ChannelPage(Model):
    items: list[Channel]
    total: int


class FavoriteIn(Model):
    title: str
    input: str
    source_kind: SourceKind
    thumbnail: str | None = None


class LocalEntry(Model):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    mime_type: str | None = None


class LocalListing(Model):
    path: str
    entries: list[LocalEntry]


class Health(Model):
    status: Literal["ok"] = "ok"
    driver: str
    version: str


# ---------------------------------------------------------------- browser


class Viewport(Model):
    width: int = Field(default=390, ge=200, le=2560)
    height: int = Field(default=844, ge=200, le=2560)


class CapturedStream(Model):
    id: str
    url: str
    mime_type: str | None = None
    kind: StreamKind = "unknown"
    page_url: str
    frame_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=utcnow)
    is_master: bool | None = None
    # UX additions (backward compatible)
    title: str | None = None
    thumbnail: str | None = None
    quality: str | None = None
    width: int | None = None
    height: int | None = None
    is_live: bool | None = None
    score: float = 0.0
    preview_url: str | None = None  # same-origin proxy path for the in-app preview


class PopupRequest(Model):
    id: str
    url: str
    host: str
    opener_url: str
    created_at: datetime = Field(default_factory=utcnow)


class BrowserSession(Model):
    id: str
    url: str
    title: str | None = None
    viewport: Viewport
    captured: list[CapturedStream] = Field(default_factory=list)
    created_at: datetime
    adblock_enabled: bool = True
    blocked_count: int = 0
    pending_popups: list[PopupRequest] = Field(default_factory=list)


class BrowserSessionIn(Model):
    url: str = Field(min_length=1)
    viewport: Viewport | None = None


class BrowserNavigateIn(Model):
    url: str | None = None
    action: Literal["back", "forward", "reload"] | None = None


class BrowserCastIn(Model):
    stream_id: str
    device_id: str
    enqueue: bool = False


class BrowserFavoriteIn(Model):
    stream_id: str


class BrowserAdblockIn(Model):
    enabled: bool


class PopupDecisionIn(Model):
    decision: PopupDecision


class FilterListInfo(Model):
    name: str
    rules: int
    updated_at: datetime | None = None


class FilterLists(Model):
    lists: list[FilterListInfo]
