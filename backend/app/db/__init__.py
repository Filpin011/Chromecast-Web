"""SQLite persistence via SQLModel.

All methods are synchronous and fast (local SQLite); the API calls them directly.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, or_
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, col, create_engine, delete, select

from app import models as m


def _now() -> datetime:
    return datetime.now(UTC)


def _id() -> str:
    return uuid.uuid4().hex


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class FavoriteRow(SQLModel, table=True):
    __tablename__ = "favorites"
    id: str = Field(default_factory=_id, primary_key=True)
    kind: str = "media"  # "media" | "site"
    title: str
    input: str
    source_kind: str
    thumbnail: str | None = None
    created_at: datetime = Field(default_factory=_now)


class HistoryRow(SQLModel, table=True):
    __tablename__ = "history"
    id: str = Field(default_factory=_id, primary_key=True)
    title: str
    input: str
    source_kind: str
    thumbnail: str | None = None
    device_id: str | None = None
    played_at: datetime = Field(default_factory=_now, index=True)


class PlaylistRow(SQLModel, table=True):
    __tablename__ = "playlists"
    id: str = Field(default_factory=_id, primary_key=True)
    name: str
    source_url: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ChannelRow(SQLModel, table=True):
    __tablename__ = "channels"
    id: str = Field(default_factory=_id, primary_key=True)
    playlist_id: str = Field(index=True)
    position: int = 0
    name: str
    url: str
    logo: str | None = None
    group_title: str | None = Field(default=None, index=True)
    tvg_id: str | None = None
    headers_json: str | None = None  # JSON object of upstream request headers


class SettingRow(SQLModel, table=True):
    __tablename__ = "settings"
    key: str = Field(primary_key=True)
    value: str


class ManualDeviceRow(SQLModel, table=True):
    __tablename__ = "manual_devices"
    id: str = Field(primary_key=True)
    host: str
    port: int = 8009
    name: str | None = None


class Database:
    def __init__(self, path: Path | None, on_change: Callable[[str], None] | None = None) -> None:
        # Called with "settings" / "favorites" / "history" / "playlists" after every committed change
        # (the StateHub broadcasts it as an ``invalidate`` so other clients refetch).
        self.on_change = on_change
        if path is None:
            self.engine = create_engine(
                "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                f"sqlite:///{path}", connect_args={"check_same_thread": False}
            )
        SQLModel.metadata.create_all(self.engine)
        self._migrate()

    def _migrate(self) -> None:
        """Additive column migrations for DBs created by older versions.

        SQLite fills a column added with a DEFAULT in every existing row, which is the backfill
        (e.g. favorites saved before sites existed become kind "media").
        """
        added = {
            "channels": {"headers_json": "TEXT"},
            "favorites": {"kind": "VARCHAR NOT NULL DEFAULT 'media'"},
        }
        with self.engine.begin() as conn:
            for table, cols in added.items():
                have = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
                for name, typ in cols.items():
                    if name not in have:
                        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
            # one history row per input (older versions stacked a row per replay): keep the latest
            conn.exec_driver_sql(
                "DELETE FROM history WHERE rowid NOT IN (SELECT MAX(rowid) FROM history GROUP BY input)"
            )

    def _changed(self, key: str) -> None:
        if self.on_change is not None:
            self.on_change(key)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine, expire_on_commit=False) as s:
            yield s

    def close(self) -> None:
        self.engine.dispose()

    # ------------------------------------------------------------ settings
    def get_settings(self) -> m.Settings:
        # Cached: read on every remote-browser request (ad blocking), only this process writes it.
        cached = getattr(self, "_settings_cache", None)
        if cached is not None:
            return cached.model_copy(deep=True)
        with self.session() as s:
            rows = s.exec(select(SettingRow)).all()
        data = {r.key: json.loads(r.value) for r in rows}
        settings = m.Settings.model_validate({k: v for k, v in data.items() if k in m.Settings.model_fields})
        self._settings_cache = settings
        return settings.model_copy(deep=True)

    def update_settings(self, patch: dict) -> m.Settings:
        current = self.get_settings().model_dump()
        current.update({k: v for k, v in patch.items() if k in m.Settings.model_fields})
        new = m.Settings.model_validate(current)
        self._settings_cache = None
        with self.session() as s:
            for key, value in new.model_dump().items():
                row = s.get(SettingRow, key)
                if row is None:
                    s.add(SettingRow(key=key, value=json.dumps(value)))
                else:
                    row.value = json.dumps(value)
                    s.add(row)
            s.commit()
        self._settings_cache = None
        self._changed("settings")
        return new

    # ------------------------------------------------------------ favorites
    @staticmethod
    def _fav(row: FavoriteRow) -> m.Favorite:
        return m.Favorite(
            id=row.id,
            kind=row.kind or "media",  # type: ignore[arg-type]
            title=row.title,
            input=row.input,
            source_kind=row.source_kind,  # type: ignore[arg-type]
            thumbnail=row.thumbnail,
            created_at=_aware(row.created_at),
        )

    def list_favorites(self) -> list[m.Favorite]:
        with self.session() as s:
            rows = s.exec(select(FavoriteRow).order_by(col(FavoriteRow.created_at).desc())).all()
        return [self._fav(r) for r in rows]

    def add_favorite(self, data: m.FavoriteIn) -> m.Favorite:
        """Insert, or update the favorite of the same kind with the same input (no duplicates).

        A site and a media favorite may share a URL: the media one casts the page's stream, the
        site one reopens the page in the remote browser.
        """
        with self.session() as s:
            existing = s.exec(
                select(FavoriteRow).where(FavoriteRow.input == data.input, FavoriteRow.kind == data.kind)
            ).first()
            if existing:
                existing.title = data.title
                existing.thumbnail = data.thumbnail or existing.thumbnail
                existing.source_kind = data.source_kind or existing.source_kind
                row = existing
            else:
                row = FavoriteRow(**data.model_dump())
            s.add(row)
            s.commit()
            s.refresh(row)
        self._changed("favorites")
        return self._fav(row)

    def rename_favorite(self, fav_id: str, title: str) -> m.Favorite | None:
        with self.session() as s:
            row = s.get(FavoriteRow, fav_id)
            if not row:
                return None
            row.title = title
            s.add(row)
            s.commit()
            s.refresh(row)
        self._changed("favorites")
        return self._fav(row)

    def delete_favorite(self, fav_id: str) -> bool:
        with self.session() as s:
            row = s.get(FavoriteRow, fav_id)
            if not row:
                return False
            s.delete(row)
            s.commit()
        self._changed("favorites")
        return True

    # ------------------------------------------------------------ history
    def add_history(
        self,
        title: str,
        input: str,
        source_kind: str,
        thumbnail: str | None,
        device_id: str | None,
    ) -> m.HistoryEntry:
        """Record a play. One row per ``input``: replaying moves the existing row to the top with the new
        played_at / title / thumbnail / device instead of stacking a duplicate."""
        with self.session() as s:
            rows = s.exec(
                select(HistoryRow).where(HistoryRow.input == input).order_by(col(HistoryRow.played_at).desc())
            ).all()
            if rows:
                row = rows[0]
                for extra in rows[1:]:
                    s.delete(extra)
                row.title = title
                row.source_kind = source_kind
                row.thumbnail = thumbnail
                row.device_id = device_id
                row.played_at = _now()
            else:
                row = HistoryRow(
                    title=title, input=input, source_kind=source_kind, thumbnail=thumbnail, device_id=device_id
                )
            s.add(row)
            s.commit()
            s.refresh(row)
        self._changed("history")
        return self._hist(row)

    @staticmethod
    def _hist(row: HistoryRow) -> m.HistoryEntry:
        return m.HistoryEntry(
            id=row.id,
            title=row.title,
            input=row.input,
            source_kind=row.source_kind,  # type: ignore[arg-type]
            thumbnail=row.thumbnail,
            device_id=row.device_id,
            played_at=_aware(row.played_at),
        )

    def list_history(self, limit: int = 50) -> list[m.HistoryEntry]:
        with self.session() as s:
            rows = s.exec(
                select(HistoryRow).order_by(col(HistoryRow.played_at).desc()).limit(limit)
            ).all()
        return [self._hist(r) for r in rows]

    def delete_history(self, entry_id: str) -> bool:
        with self.session() as s:
            row = s.get(HistoryRow, entry_id)
            if not row:
                return False
            s.delete(row)
            s.commit()
        self._changed("history")
        return True

    def clear_history(self) -> None:
        with self.session() as s:
            s.exec(delete(HistoryRow))  # type: ignore[call-overload]
            s.commit()
        self._changed("history")

    # ------------------------------------------------------------ playlists
    def _playlist(self, s: Session, row: PlaylistRow) -> m.Playlist:
        count = s.exec(
            select(func.count()).select_from(ChannelRow).where(ChannelRow.playlist_id == row.id)
        ).one()
        groups_rows = s.exec(
            select(ChannelRow.group_title, func.min(ChannelRow.position))
            .where(ChannelRow.playlist_id == row.id, col(ChannelRow.group_title).is_not(None))
            .group_by(ChannelRow.group_title)
            .order_by(func.min(ChannelRow.position))
        ).all()
        return m.Playlist(
            id=row.id,
            name=row.name,
            source_url=row.source_url,
            channel_count=int(count),
            groups=[g for g, _ in groups_rows if g],
            created_at=_aware(row.created_at),
            updated_at=_aware(row.updated_at),
        )

    def list_playlists(self) -> list[m.Playlist]:
        with self.session() as s:
            rows = s.exec(select(PlaylistRow).order_by(col(PlaylistRow.created_at).desc())).all()
            return [self._playlist(s, r) for r in rows]

    def get_playlist(self, playlist_id: str) -> m.Playlist | None:
        with self.session() as s:
            row = s.get(PlaylistRow, playlist_id)
            return self._playlist(s, row) if row else None

    def create_playlist(
        self, name: str, source_url: str | None, channels: Iterable[m.Channel]
    ) -> m.Playlist:
        row = PlaylistRow(name=name, source_url=source_url)
        with self.session() as s:
            s.add(row)
            self._insert_channels(s, row.id, channels)
            s.commit()
            s.refresh(row)
            result = self._playlist(s, row)
        self._changed("playlists")
        return result

    def replace_channels(self, playlist_id: str, channels: Iterable[m.Channel]) -> m.Playlist | None:
        with self.session() as s:
            row = s.get(PlaylistRow, playlist_id)
            if not row:
                return None
            s.exec(delete(ChannelRow).where(ChannelRow.playlist_id == playlist_id))  # type: ignore[call-overload]
            self._insert_channels(s, playlist_id, channels)
            row.updated_at = _now()
            s.add(row)
            s.commit()
            s.refresh(row)
            result = self._playlist(s, row)
        self._changed("playlists")
        return result

    @staticmethod
    def _insert_channels(s: Session, playlist_id: str, channels: Iterable[m.Channel]) -> None:
        for i, ch in enumerate(channels):
            s.add(
                ChannelRow(
                    playlist_id=playlist_id,
                    position=i,
                    name=ch.name,
                    url=ch.url,
                    logo=ch.logo,
                    group_title=ch.group,
                    tvg_id=ch.tvg_id,
                    headers_json=json.dumps(ch.headers) if ch.headers else None,
                )
            )

    def delete_playlist(self, playlist_id: str) -> bool:
        with self.session() as s:
            row = s.get(PlaylistRow, playlist_id)
            if not row:
                return False
            s.exec(delete(ChannelRow).where(ChannelRow.playlist_id == playlist_id))  # type: ignore[call-overload]
            s.delete(row)
            s.commit()
        self._changed("playlists")
        return True

    def list_channels(
        self,
        playlist_id: str,
        q: str | None = None,
        group: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[m.Channel], int]:
        conds = [ChannelRow.playlist_id == playlist_id]
        if q:
            like = f"%{q.lower()}%"
            conds.append(
                or_(
                    func.lower(ChannelRow.name).like(like),
                    func.lower(func.coalesce(ChannelRow.tvg_id, "")).like(like),
                )
            )
        if group:
            conds.append(ChannelRow.group_title == group)
        with self.session() as s:
            total = s.exec(select(func.count()).select_from(ChannelRow).where(*conds)).one()
            rows = s.exec(
                select(ChannelRow)
                .where(*conds)
                .order_by(col(ChannelRow.position))
                .offset(offset)
                .limit(limit)
            ).all()
        items = [
            m.Channel(
                id=r.id,
                playlist_id=r.playlist_id,
                name=r.name,
                url=r.url,
                logo=r.logo,
                group=r.group_title,
                tvg_id=r.tvg_id,
                headers=json.loads(r.headers_json) if r.headers_json else {},
            )
            for r in rows
        ]
        return items, int(total)

    # ------------------------------------------------------------ manual devices
    def list_manual_devices(self) -> list[ManualDeviceRow]:
        with self.session() as s:
            return list(s.exec(select(ManualDeviceRow)).all())

    def add_manual_device(self, device_id: str, host: str, port: int, name: str | None) -> None:
        with self.session() as s:
            row = s.get(ManualDeviceRow, device_id) or ManualDeviceRow(id=device_id, host=host)
            row.host, row.port, row.name = host, port, name
            s.add(row)
            s.commit()

    def delete_manual_device(self, device_id: str) -> bool:
        with self.session() as s:
            row = s.get(ManualDeviceRow, device_id)
            if not row:
                return False
            s.delete(row)
            s.commit()
        return True
