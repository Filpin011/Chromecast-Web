"""Server-side play queue, one per device."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from app.models import QueueItem, ResolvedMedia, SourceKind

HISTORY_MAX = 50


@dataclass
class QueueEntry:
    item: QueueItem
    kind: SourceKind | None = None
    # Media resolved when the entry was added. Stream URLs expire (yt-dlp googlevideo
    # links, tokens captured by the headless page), so it is re-resolved from ``input``
    # before playback once older than a few minutes...
    media: ResolvedMedia | None = None
    # ...unless it can't be re-derived from ``input`` (a stream captured by the remote
    # browser: ``input`` is the page URL, the headers live only in ``media``).
    pinned: bool = False
    resolved_at: float = field(default_factory=time.time)


class PlayQueue:
    def __init__(self) -> None:
        self._items: dict[str, list[QueueEntry]] = {}
        self._played: dict[str, list[QueueEntry]] = {}

    def items(self, device_id: str) -> list[QueueItem]:
        return [e.item for e in self._items.get(device_id, [])]

    def add(
        self,
        device_id: str,
        input: str,
        title: str | None,
        thumbnail: str | None = None,
        kind: SourceKind | None = None,
        media: ResolvedMedia | None = None,
        pinned: bool = False,
    ) -> QueueEntry:
        entry = QueueEntry(
            item=QueueItem(id=uuid.uuid4().hex[:12], input=input, title=title or input, thumbnail=thumbnail),
            kind=kind,
            media=media,
            pinned=pinned,
        )
        self._items.setdefault(device_id, []).append(entry)
        return entry

    def remove(self, device_id: str, item_id: str) -> bool:
        items = self._items.get(device_id, [])
        for i, e in enumerate(items):
            if e.item.id == item_id:
                items.pop(i)
                return True
        return False

    def reorder(self, device_id: str, item_ids: list[str]) -> None:
        items = self._items.get(device_id, [])
        by_id = {e.item.id: e for e in items}
        ordered = [by_id.pop(i) for i in item_ids if i in by_id]
        # items not mentioned keep their relative order at the end
        ordered += [e for e in items if e.item.id in by_id]
        self._items[device_id] = ordered

    def pop_next(self, device_id: str) -> QueueEntry | None:
        items = self._items.get(device_id) or []
        return items.pop(0) if items else None

    def push_front(self, device_id: str, entry: QueueEntry) -> None:
        self._items.setdefault(device_id, []).insert(0, entry)

    def record_played(self, device_id: str, entry: QueueEntry) -> None:
        played = self._played.setdefault(device_id, [])
        played.append(entry)
        del played[:-HISTORY_MAX]

    def pop_previous(self, device_id: str) -> QueueEntry | None:
        """Last played entry before the current one (current is the last recorded)."""
        played = self._played.get(device_id) or []
        if len(played) < 2:
            return None
        current = played.pop()
        previous = played.pop()
        self.push_front(device_id, current)
        return previous

    def clear(self, device_id: str) -> None:
        self._items.pop(device_id, None)
        self._played.pop(device_id, None)
