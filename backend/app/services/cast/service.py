"""CastService: glue between the REST API, the cast driver, the queue and the StateHub."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.db import Database
from app.errors import AppError
from app.models import ControlAction, Device, PlayerState, QueueItem, ResolvedMedia, SourceKind, utcnow
from app.services.cast.base import CastDriver, CastError, DeviceStatus, DriverEvent, MediaRequest
from app.services.proxy.restream import WORST_STARTUP
from app.services.queue import PlayQueue, QueueEntry
from app.services.resolver.service import Resolver
from app.services.state import StateHub

log = logging.getLogger(__name__)

# A restreamed source answers the receiver's first playlist request only once ffmpeg
# has probed the input and written a segment: wait for that, not the default timeout.
RESTREAM_LOAD_TIMEOUT = WORST_STARTUP + 15.0
# Controls that change what is loaded: serialized with queue advance / play / enqueue.
PLAYBACK_ACTIONS = ("stop", "go_live", "next", "previous")
# Queue/previous entries older than this are resolved again before playback: stream URLs
# (yt-dlp googlevideo, page tokens) expire, and a dead URL stalls the queue on the TV.
RERESOLVE_AFTER = 180.0
# Auto-recovery of a stream the receiver dropped mid-playback (IDLE / ERROR after it had
# played): wait this long before each reload attempt; len() = number of attempts.
RECOVERY_BACKOFF = (2.0, 5.0, 10.0)
# Media that is not LIVE is recovered only after it had been PLAYING this long (a VOD that
# errors in its first seconds is a dead URL). It is also how long a recovered stream must
# play again before its attempt budget is refilled (no endless reload loop).
RECOVERY_MIN_PLAYED = 20.0
# How long a reload attempt may take to reach PLAYING before it counts as failed.
RECOVERY_OUTCOME_TIMEOUT = 30.0
# BUFFERING longer than this is reported as PlayerState.stalled_since.
STALL_AFTER = 4.0
# A stall ends only after PLAYING this long without buffering: a receiver starved by a stalled
# source flips BUFFERING -> PLAYING -> BUFFERING every few seconds (it skips the segment it
# can't get), and those blips must not reset the stall. Also how long a recovery reload must
# play before it counts as successful.
STEADY_AFTER = 3.0
# A LIVE stream of ours stalled this long is reloaded (live edge) by the recovery even though
# the receiver never gives up on it (it keeps retrying, reporting non-fatal network errors).
LIVE_STALL_RELOAD = 25.0


@dataclass
class _Meta:
    """What *we* cast on a device (the receiver doesn't know the original input)."""

    media_url: str | None = None
    original_input: str | None = None
    title: str | None = None
    thumbnail: str | None = None
    showing_idle: bool = False
    request: MediaRequest | None = None
    # The receiver rejected this LOAD (already reported by the HTTP call): an IDLE/ERROR
    # it broadcasts for it must not toast again nor advance the queue.
    load_failed: bool = False
    # What is needed to resolve the media again during a recovery (see _play_media).
    kind: SourceKind | None = None
    pinned: bool = False
    resolved_at: float = 0.0
    # Playback accounting (monotonic clock), fed by build_player's status observations.
    playing_since: float | None = None
    played_total: float = 0.0
    last_run: float = 0.0
    # Auto-recovery of a dropped stream (see CastService._recover).
    recovering: bool = False
    recovery_attempt: int = 0
    recovery_waiter: asyncio.Future[bool] | None = None

    def mark_playing(self, playing: bool, now: float) -> None:
        if playing and self.playing_since is None:
            self.playing_since = now
        elif not playing and self.playing_since is not None:
            self.last_run = now - self.playing_since
            self.played_total += self.last_run
            self.playing_since = None


@dataclass
class _Stall:
    """One stall of a device's player (BUFFERING, possibly with short PLAYING blips)."""

    started: float
    since: datetime
    reported: bool = False
    blips: int = 0
    report: asyncio.TimerHandle | None = None
    steady: asyncio.TimerHandle | None = None
    watchdog: asyncio.TimerHandle | None = None

    def cancel(self) -> None:
        for timer in (self.report, self.steady, self.watchdog):
            if timer is not None:
                timer.cancel()
        self.report = self.steady = self.watchdog = None


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - outside the event loop (sync callers)
        return None


class CastService:
    def __init__(
        self,
        driver: CastDriver,
        hub: StateHub,
        db: Database,
        resolver: Resolver,
        base_url: Callable[[], str],
        queue: PlayQueue | None = None,
        discovery_seconds: float = 5.0,
    ) -> None:
        self.driver = driver
        self.hub = hub
        self.db = db
        self.resolver = resolver
        self.base_url = base_url
        self.queue = queue or PlayQueue()
        self.discovery_seconds = discovery_seconds
        self._meta: dict[str, _Meta] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._discover_task: asyncio.Task[list[Device]] | None = None
        # Per device: one playback change (LOAD / queue advance / stop) at a time, and an
        # epoch bumped by every LOAD so a stale "finished" event can't advance the queue.
        self._play_locks: dict[str, asyncio.Lock] = {}
        self._epoch: dict[str, int] = {}
        self._recovery_tasks: dict[str, asyncio.Task[None]] = {}
        # Per device: the current stall (see _observe) and the timer confirming that a
        # recovery reload keeps playing.
        self._stalls: dict[str, _Stall] = {}
        self._confirm_timers: dict[str, asyncio.TimerHandle] = {}

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self.driver.set_listener(self._on_event)
        await self.driver.start()
        for row in self.db.list_manual_devices():
            try:
                await self.driver.add_manual(row.host, row.port, row.name)
            except Exception:  # pragma: no cover
                log.exception("could not restore manual device %s", row.host)
        self.hub.set_devices(self.driver.devices())

    async def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        for stall in self._stalls.values():
            stall.cancel()
        self._stalls.clear()
        for h in self._confirm_timers.values():
            h.cancel()
        self._confirm_timers.clear()
        await self.driver.stop()

    def _spawn(self, coro) -> asyncio.Task[None]:  # type: ignore[no-untyped-def]
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _dev(self, device_id: str) -> str:
        """Device as written in log lines: ``"<friendly name>" (<id[:8]>)``."""
        dev = self.driver.find_device(device_id)
        return f'"{dev.name if dev else device_id}" ({device_id[:8]})'

    # ------------------------------------------------------------ driver events
    def _on_event(self, event: DriverEvent, device_id: str | None, message: str | None) -> None:
        if event == "devices":
            self.hub.set_devices(self.driver.devices())
        elif event == "status" and device_id:
            self._push(device_id)
        elif event == "finished" and device_id:
            self._spawn(self._on_finished(device_id, self._epoch.get(device_id, 0), message or "FINISHED"))
        elif event == "error":
            detail = message or "Cast error"
            self.hub.toast("error", detail, "cast_error", {"detail": detail})
            if device_id:
                self._push(device_id)

    def _push(self, device_id: str) -> None:
        # is_connected = a session is held; while the driver reconnects after a blip the
        # player stays (with connected=false) and the device stays active.
        if self.driver.is_connected(device_id):
            self.hub.set_player(self.build_player(device_id))
        elif device_id in self.hub.players:
            self.hub.remove_player(device_id)

    def _observe(self, device_id: str, st: DeviceStatus, meta: _Meta, ours: bool) -> datetime | None:
        """Track what the receiver reports (playing time of our media, stalls) and return
        ``stalled_since``. Called for every status the service turns into a player.

        A stall starts with BUFFERING and ends after STEADY_AFTER of uninterrupted PLAYING (or
        on IDLE / PAUSED): short PLAYING blips between BUFFERINGs belong to the same stall."""
        now = time.monotonic()
        state = st.player_state
        loop = _running_loop()
        if ours and not meta.showing_idle:
            meta.mark_playing(state == "PLAYING", now)
            waiter = meta.recovery_waiter
            if state == "PLAYING" and waiter is not None and not waiter.done():
                if device_id not in self._confirm_timers and loop is not None:
                    self._confirm_timers[device_id] = loop.call_later(
                        STEADY_AFTER, self._confirm_playing, device_id, waiter
                    )
            elif (timer := self._confirm_timers.pop(device_id, None)) is not None:
                timer.cancel()
        stall = self._stalls.get(device_id)
        if (ours and meta.showing_idle) or state not in ("BUFFERING", "PLAYING"):
            if stall is not None:
                self._end_stall(device_id, "state " + state)
            return None
        if state == "BUFFERING":
            if stall is None:
                stall = self._stalls[device_id] = _Stall(now, utcnow())
                if loop is not None:
                    stall.report = loop.call_later(STALL_AFTER + 0.05, self._on_stall_timer, device_id)
                    live = (meta.request is not None and meta.request.stream_type == "LIVE") or st.stream_type == "LIVE"
                    if ours and live:
                        stall.watchdog = loop.call_later(LIVE_STALL_RELOAD, self._on_live_stall, device_id)
            elif stall.steady is not None:
                stall.steady.cancel()
                stall.steady = None
                stall.blips += 1
        elif stall is not None and stall.steady is None and loop is not None:  # PLAYING during a stall
            stall.steady = loop.call_later(STEADY_AFTER, self._on_steady, device_id)
        if stall is None:
            return None
        return stall.since if now - stall.started >= STALL_AFTER else None

    def _end_stall(self, device_id: str, why: str) -> None:
        stall = self._stalls.pop(device_id, None)
        if stall is None:
            return
        stall.cancel()
        if stall.reported:
            log.info(
                "player stall ended device=%s after=%.0fs why=%s blips=%d",
                self._dev(device_id),
                time.monotonic() - stall.started,
                why,
                stall.blips,
            )

    def _on_stall_timer(self, device_id: str) -> None:
        stall = self._stalls.get(device_id)
        if stall is None:
            return
        stall.report = None
        stall.reported = True
        log.info("player stalled device=%s buffering_for=%.0fs", self._dev(device_id), STALL_AFTER)
        self._push(device_id)

    def _on_steady(self, device_id: str) -> None:
        if (stall := self._stalls.get(device_id)) is not None:
            stall.steady = None
            self._end_stall(device_id, "playing again")
            self._push(device_id)

    def _confirm_playing(self, device_id: str, waiter: asyncio.Future[bool]) -> None:
        self._confirm_timers.pop(device_id, None)
        if not waiter.done() and self.driver.status(device_id).player_state == "PLAYING":
            waiter.set_result(True)

    def _on_live_stall(self, device_id: str) -> None:
        """A LIVE stream of ours has been stalled for LIVE_STALL_RELOAD: reload it."""
        stall = self._stalls.get(device_id)
        meta = self._meta.get(device_id)
        if stall is None or meta is None:
            return
        stall.watchdog = None
        if meta.recovering or meta.showing_idle or meta.load_failed or meta.request is None:
            return
        if self.driver.status(device_id).media_url not in (None, meta.media_url):
            return
        if self._should_recover(device_id, meta):
            log.info(
                "live stream stalled device=%s stalled_for=%.0fs blips=%d: reloading",
                self._dev(device_id),
                time.monotonic() - stall.started,
                stall.blips,
            )
            self._start_recovery(device_id, meta)
            return
        log.info("live stream stalled device=%s: recovery attempts used up, giving up", self._dev(device_id))
        self._spawn(self._give_up(device_id, meta))

    def build_player(self, device_id: str) -> PlayerState:
        st = self.driver.status(device_id)
        meta = self._meta.get(device_id) or _Meta()
        # while recovering the receiver may have dropped the media: keep showing ours
        ours = meta.media_url is not None and (st.media_url == meta.media_url or meta.recovering)
        showing_idle = ours and meta.showing_idle
        stalled_since = self._observe(device_id, st, meta, ours)
        return PlayerState(
            device_id=device_id,
            connected=st.connected,
            app_name=st.app_name,
            player_state=st.player_state,
            idle_reason=st.idle_reason,
            title=None if showing_idle else (st.title or (meta.title if ours else None)),
            thumbnail=None if showing_idle else (st.thumbnail or (meta.thumbnail if ours else None)),
            media_url=st.media_url,
            original_input=meta.original_input if ours and not showing_idle else None,
            stream_type=None if showing_idle else st.stream_type,
            current_time=0.0 if showing_idle else st.position_now(),
            duration=None if showing_idle else st.duration,
            seekable=False if showing_idle else st.seekable,
            volume_level=st.volume_level,
            muted=st.muted,
            tracks=[] if showing_idle else list(st.tracks),
            active_track_ids=[] if showing_idle else list(st.active_track_ids),
            queue=self.queue.items(device_id),
            showing_idle_image=showing_idle,
            recovering=meta.recovering,
            recovery_attempt=meta.recovery_attempt if meta.recovering else 0,
            stalled_since=stalled_since,
            updated_at=utcnow(),
        )

    def loaded_urls(self) -> set[str]:
        """Media URLs currently loaded on a device (ours, or as the receiver reports them),
        including paused media. The restream reaper keeps the matching jobs."""
        urls: set[str] = set()
        for device_id, meta in self._meta.items():
            if meta.media_url and not meta.showing_idle and self.driver.is_connected(device_id):
                urls.add(meta.media_url)
        for device_id in self.hub.players:
            if url := self.driver.status(device_id).media_url:
                urls.add(url)
        return urls

    async def _release_restream(self, device_id: str, new_url: str | None = None) -> None:
        """``device_id`` is about to replace (or stop) its media: stop the ffmpeg behind
        the restreamed URL it had loaded unless another device still plays it. Waiting
        for the idle reaper would hold the upstream connection for about a minute, and
        single-connection IPTV accounts then reject the next channel."""
        restream = self.resolver.restream
        new_job = restream.job_for_url(new_url) if new_url else None
        meta = self._meta.get(device_id)
        old_urls = {meta.media_url if meta else None, self.driver.status(device_id).media_url}
        others: set[str] = set()
        for other in set(self._meta) | set(self.hub.players):
            if other == device_id:
                continue
            other_meta = self._meta.get(other)
            if other_meta and other_meta.media_url and not other_meta.showing_idle:
                others.add(other_meta.media_url)
            if url := self.driver.status(other).media_url:
                others.add(url)
        for url in old_urls:
            job = restream.job_for_url(url) if url else None
            if job is None or job is new_job:
                continue
            if any(restream.job_for_url(u) is job for u in others):
                continue
            await restream.release(job)

    def _play_lock(self, device_id: str) -> asyncio.Lock:
        return self._play_locks.setdefault(device_id, asyncio.Lock())

    def _bump_epoch(self, device_id: str) -> None:
        self._epoch[device_id] = self._epoch.get(device_id, 0) + 1

    async def _on_finished(self, device_id: str, epoch: int, reason: str = "FINISHED") -> None:
        async with self._play_lock(device_id):
            if self._epoch.get(device_id, 0) != epoch:
                return  # something else was loaded since this media finished
            meta = self._meta.get(device_id)
            if meta and (meta.showing_idle or meta.load_failed):
                return
            if reason == "ERROR":
                # the receiver accepted the LOAD and then gave up (dead / expired URL, or a
                # live stream it dropped mid-playback)
                st = self.driver.status(device_id)
                if meta is None or (st.media_url not in (None, meta.media_url)):
                    return  # not media we loaded
                if meta.recovering:
                    # a recovery reload failed: _recover moves on to the next attempt
                    if meta.recovery_waiter is not None and not meta.recovery_waiter.done():
                        log.info(
                            "recovery attempt failed device=%s attempt=%d step=playback",
                            self._dev(device_id),
                            meta.recovery_attempt,
                        )
                        meta.recovery_waiter.set_result(False)
                    return
                if self._should_recover(device_id, meta):
                    self._start_recovery(device_id, meta)
                    return
                self._toast_playback_failed(meta)
                await self._play_next(device_id)
                return
            self._cancel_recovery(device_id)
            if await self._play_next(device_id):
                return
            if self.db.get_settings().show_idle_on_stop:
                try:
                    await self._show_idle(device_id)
                except AppError as exc:
                    log.info("idle image after finish failed: %s", exc.detail)

    def _toast_playback_failed(self, meta: _Meta) -> None:
        title = meta.title or meta.media_url or ""
        self.hub.toast("error", f"Playback failed on the Chromecast: “{title}”", "playback_failed", {"title": title})

    # ------------------------------------------------------------ auto-recovery
    def _should_recover(self, device_id: str, meta: _Meta) -> bool:
        """An IDLE/ERROR of media we loaded: reload it instead of skipping it when it is a
        LIVE stream that had played, or any media that had played for a while."""
        if meta.request is None:
            return False
        meta.mark_playing(False, time.monotonic())  # close a run the status didn't end
        live = meta.request.stream_type == "LIVE" or self.driver.status(device_id).stream_type == "LIVE"
        if not ((live and meta.played_total > 0) or meta.played_total >= RECOVERY_MIN_PLAYED):
            return False
        if meta.last_run >= RECOVERY_MIN_PLAYED:
            meta.recovery_attempt = 0  # it played long enough since the last recovery
        return meta.recovery_attempt < len(RECOVERY_BACKOFF)

    def _start_recovery(self, device_id: str, meta: _Meta) -> None:
        self._cancel_recovery(device_id)
        meta.recovering = True
        log.info(
            "recovery started device=%s title=%r played=%.0fs stream_type=%s",
            self._dev(device_id),
            meta.title,
            meta.played_total,
            meta.request.stream_type if meta.request else None,
        )
        self._recovery_tasks[device_id] = self._spawn(self._recover(device_id, meta))
        self._push(device_id)

    def _cancel_recovery(self, device_id: str) -> None:
        """A user action (or new media) replaces what is being recovered."""
        task = self._recovery_tasks.pop(device_id, None)
        meta = self._meta.get(device_id)
        if meta is not None and meta.recovering:
            meta.recovering = False
            log.info("recovery cancelled device=%s title=%r", self._dev(device_id), meta.title)
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    async def _recover(self, device_id: str, meta: _Meta) -> None:
        """Reload ``meta``'s media with backoff until it plays again or attempts run out."""
        lock = self._play_lock(device_id)
        total = len(RECOVERY_BACKOFF)
        title = meta.title or meta.media_url or ""
        try:
            while meta.recovery_attempt < total:
                delay = RECOVERY_BACKOFF[meta.recovery_attempt]
                meta.recovery_attempt += 1
                attempt = meta.recovery_attempt
                self.hub.toast(
                    "info",
                    f"Stream interrupted, reconnecting… ({attempt}/{total})",
                    "stream_reconnecting",
                    {"title": title, "attempt": attempt, "max": total},
                )
                self._push(device_id)
                await asyncio.sleep(delay)
                async with lock:
                    if self._meta.get(device_id) is not meta or not meta.recovering:
                        return  # a user action replaced it
                    waiter = await self._recovery_load(device_id, meta, attempt)
                if waiter is None:
                    continue
                timeout = max(RECOVERY_OUTCOME_TIMEOUT, (meta.request.load_timeout or 0) if meta.request else 0)
                try:
                    played = await asyncio.wait_for(waiter, timeout)
                except TimeoutError:
                    played = False
                    log.info(
                        "recovery attempt timed out device=%s attempt=%d/%d timeout=%.0fs",
                        self._dev(device_id),
                        attempt,
                        total,
                        timeout,
                    )
                if self._meta.get(device_id) is not meta or not meta.recovering:
                    return
                if played:
                    meta.recovering = False
                    meta.recovery_waiter = None
                    log.info("recovery succeeded device=%s attempt=%d/%d", self._dev(device_id), attempt, total)
                    self.hub.toast("success", "Stream restored", "stream_restored", {"title": title})
                    self._push(device_id)
                    return
            async with lock:
                if self._meta.get(device_id) is not meta or not meta.recovering:
                    return
                meta.recovering = False
                meta.recovery_waiter = None
                log.info("recovery gave up device=%s title=%r attempts=%d", self._dev(device_id), meta.title, total)
                await self._give_up_locked(device_id, meta)
        finally:
            if self._recovery_tasks.get(device_id) is asyncio.current_task():
                self._recovery_tasks.pop(device_id, None)

    async def _give_up(self, device_id: str, meta: _Meta) -> None:
        async with self._play_lock(device_id):
            if self._meta.get(device_id) is meta and not meta.recovering:
                await self._give_up_locked(device_id, meta)

    async def _give_up_locked(self, device_id: str, meta: _Meta) -> None:
        """The stream can't be recovered (caller holds the play lock): toast, then the next
        queued item, the idle image or just the current state."""
        self._end_stall(device_id, "gave up")
        self._toast_playback_failed(meta)
        if await self._play_next(device_id):
            return
        if self.db.get_settings().show_idle_on_stop:
            try:
                await self._show_idle(device_id)
            except AppError as exc:
                log.info("idle image after recovery failed device=%s detail=%s", self._dev(device_id), exc.detail)
        else:
            try:
                await self.driver.stop_media(device_id)
            except Exception as exc:  # the receiver may already be gone
                log.debug("stop after give-up failed device=%s: %s", self._dev(device_id), exc)
            self._push(device_id)

    async def _recovery_load(self, device_id: str, meta: _Meta, attempt: int) -> asyncio.Future[bool] | None:
        """One reload attempt (caller holds the play lock). Returns a future resolved when the
        receiver reports PLAYING (True) or IDLE/ERROR (False); None when the LOAD itself (or
        resolving the input again) failed."""
        assert meta.request is not None
        stale = time.time() - meta.resolved_at > RERESOLVE_AFTER
        # the same media first; resolved again when it is old (expired tokens) or a plain
        # reload already failed, unless it can't be derived from its input (browser capture)
        reresolve = (stale or attempt > 1) and not meta.pinned and bool(meta.original_input)
        if reresolve:
            try:
                media = await self.resolver.resolve_media(meta.original_input or "", meta.kind, meta.title)
            except AppError as exc:
                log.info(
                    "recovery attempt failed device=%s attempt=%d step=resolve detail=%s",
                    self._dev(device_id),
                    attempt,
                    exc.detail,
                )
                return None
            if meta.thumbnail and not media.thumbnail:
                media.thumbnail = meta.thumbnail
            await self._release_restream(device_id, media.cast_url)
            meta.request = self._media_request(media)
            meta.media_url = media.cast_url
            meta.resolved_at = time.time()
        elif job := self.resolver.restream.job_for_url(meta.request.url):
            self.resolver.restream.warm(job)
        log.info(
            "recovery attempt device=%s attempt=%d/%d reresolved=%s",
            self._dev(device_id),
            attempt,
            len(RECOVERY_BACKOFF),
            reresolve,
        )
        waiter: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        meta.recovery_waiter = waiter
        meta.load_failed = False
        self._bump_epoch(device_id)
        try:
            await self._load(device_id, meta.request)
        except AppError as exc:
            log.info(
                "recovery attempt failed device=%s attempt=%d step=load detail=%s",
                self._dev(device_id),
                attempt,
                exc.detail,
            )
            meta.recovery_waiter = None
            return None
        self._push(device_id)
        return waiter

    async def _play_next(self, device_id: str) -> bool:
        """Play the next queued entry (caller holds the device's play lock)."""
        while (entry := self.queue.pop_next(device_id)) is not None:
            try:
                await self._play_entry(device_id, entry)
                return True
            except AppError as exc:
                self.hub.toast(
                    "error",
                    f"Skipping “{entry.item.title}”: {exc.detail}",
                    "queue_skipped",
                    {
                        **(exc.params or {}),
                        "title": entry.item.title,
                        "detail": exc.detail,
                        "error_code": exc.code or "",
                        "error_reason": exc.reason or "",
                    },
                )
        return False

    # ------------------------------------------------------------ devices
    def get_device(self, device_id: str) -> Device:
        dev = self.driver.find_device(device_id)
        if dev is not None:
            return dev
        raise AppError(404, f"Device {device_id} not found", "device_not_found")

    async def discover(self) -> list[Device]:
        if self._discover_task is None or self._discover_task.done():
            self._discover_task = asyncio.create_task(self._discover())
        return await asyncio.shield(self._discover_task)

    async def _discover(self) -> list[Device]:
        self.hub.set_discovering(True)
        try:
            return await self.driver.discover(self.discovery_seconds)
        finally:
            self.hub.devices = self.driver.devices()
            self.hub.set_discovering(False)

    async def add_manual(self, host: str, port: int, name: str | None) -> Device:
        dev = await self.driver.add_manual(host, port, name)
        self.db.add_manual_device(dev.id, host, port, name)
        self.hub.set_devices(self.driver.devices())
        return dev

    async def remove_device(self, device_id: str) -> None:
        dev = self.get_device(device_id)
        if not dev.manual:
            raise AppError(400, "Only manually added devices can be removed", "not_manual")
        self._cancel_recovery(device_id)
        await self.driver.remove_device(device_id)
        self.db.delete_manual_device(device_id)
        self.queue.clear(device_id)
        self._meta.pop(device_id, None)
        self.hub.devices = self.driver.devices()
        self.hub.remove_player(device_id)

    # ------------------------------------------------------------ connection
    async def connect(self, device_id: str) -> PlayerState:
        self.get_device(device_id)
        was_connected = self.driver.is_connected(device_id)
        try:
            await self.driver.connect(device_id)
        except CastError as exc:
            raise AppError(502, str(exc), "cast_error") from exc
        self.hub.active_device_id = device_id
        self._push(device_id)
        st = self.driver.status(device_id)
        if (
            not was_connected
            and st.free_for_idle_image()  # never over another app or over media already playing
            and self.db.get_settings().show_idle_on_connect
        ):
            try:
                await self.show_idle(device_id)
            except AppError as exc:  # pragma: no cover - idle image is best effort
                log.info("idle image on connect failed: %s", exc.detail)
        return self.player(device_id)

    async def disconnect(self, device_id: str) -> None:
        self.get_device(device_id)
        self._cancel_recovery(device_id)
        await self.driver.disconnect(device_id)
        self._meta.pop(device_id, None)
        self.hub.remove_player(device_id)

    def player(self, device_id: str) -> PlayerState:
        return self.build_player(device_id)

    async def _ensure_connected(self, device_id: str, auto: bool) -> None:
        self.get_device(device_id)
        if self.driver.is_connected(device_id):
            return
        if not auto:
            raise AppError(409, "Device not connected", "not_connected")
        try:
            await self.driver.connect(device_id)
        except CastError as exc:
            raise AppError(502, str(exc), "cast_error") from exc
        self.hub.active_device_id = device_id
        self._push(device_id)

    # ------------------------------------------------------------ playback
    async def play(
        self,
        device_id: str,
        input: str,
        kind: SourceKind | None = None,
        title: str | None = None,
        enqueue: bool = False,
    ) -> PlayerState:
        await self._ensure_connected(device_id, auto=True)
        if enqueue and self._busy(device_id):
            return await self.enqueue(device_id, input, kind, title)
        media = await self.resolver.resolve_media(input, kind, title)
        async with self._play_lock(device_id):
            if enqueue and self._busy(device_id):  # something started while we resolved
                self._queue_add(device_id, input, kind, title, media, None)
                self._push_any(device_id)
                return self.player(device_id)
            await self._play_media(device_id, media)
        return self.player(device_id)

    def _busy(self, device_id: str) -> bool:
        p = self.build_player(device_id)
        return not p.showing_idle_image and p.player_state in ("PLAYING", "PAUSED", "BUFFERING")

    async def play_media(
        self,
        device_id: str,
        media: ResolvedMedia,
        history_input: str | None = None,
        history_kind: SourceKind | None = None,
        pinned: bool | None = None,
    ) -> None:
        """Cast an already resolved media, record history, update state."""
        await self._ensure_connected(device_id, auto=True)
        async with self._play_lock(device_id):
            await self._play_media(device_id, media, history_input, history_kind, pinned)

    async def _play_media(
        self,
        device_id: str,
        media: ResolvedMedia,
        history_input: str | None = None,
        history_kind: SourceKind | None = None,
        pinned: bool | None = None,
    ) -> None:
        """play_media body (caller holds the device's play lock).

        ``pinned``: ``media`` can't be re-resolved from the recorded input (browser capture
        recorded under its page URL); by default that is the case when the history input
        differs from the media's own input."""
        await self._ensure_connected(device_id, auto=True)
        self._cancel_recovery(device_id)
        await self._release_restream(device_id, media.cast_url)
        req = self._media_request(media)
        is_pinned = (history_input not in (None, media.original_input)) if pinned is None else pinned
        self._bump_epoch(device_id)
        self._meta[device_id] = _Meta(
            media_url=media.cast_url,
            original_input=history_input or media.original_input,
            title=media.title,
            thumbnail=media.thumbnail,
            request=req,
            kind=history_kind or media.source_kind,
            pinned=is_pinned,
            resolved_at=time.time(),
        )
        # new media starts with a clean slate: the BUFFERING of a channel switched within
        # STEADY_AFTER of the previous LOAD is not a stall (nor a reason for the watchdog)
        self._end_stall(device_id, "new media")
        await self._load(device_id, req)
        entry = QueueEntry(
            item=QueueItem(
                id=uuid.uuid4().hex[:12],
                input=history_input or media.original_input,
                title=media.title,
                thumbnail=media.thumbnail,
            ),
            kind=history_kind or media.source_kind,
            media=media,
            pinned=is_pinned,
            resolved_at=time.time(),
        )
        self.queue.record_played(device_id, entry)
        self.db.add_history(
            title=media.title,
            input=history_input or media.original_input,
            source_kind=history_kind or media.source_kind,
            thumbnail=media.thumbnail if (media.thumbnail or "").startswith("http") else None,
            device_id=device_id,
        )
        self.hub.active_device_id = device_id
        self._push(device_id)

    def _media_request(self, media: ResolvedMedia) -> MediaRequest:
        load_timeout = None
        job = self.resolver.restream.job_for_url(media.cast_url)
        if job is not None:
            # start ffmpeg now (overlaps with the receiver launching), and give the LOAD
            # enough time for the probe + first segment
            self.resolver.restream.warm(job)
            load_timeout = RESTREAM_LOAD_TIMEOUT
        return MediaRequest(
            url=media.cast_url,
            mime_type=media.mime_type,
            title=media.title,
            thumbnail=media.thumbnail,
            stream_type=media.stream_type,
            subtitles=list(media.subtitles),
            hls_segment_format=media.hls_segment_format,
            hls_video_segment_format=media.hls_video_segment_format,
            load_timeout=load_timeout,
        )

    async def _load(self, device_id: str, req: MediaRequest) -> None:
        """Send the LOAD (epoch already bumped, meta set). A rejected LOAD is reported once,
        by the caller's 502: a "finished" event the receiver also emits for it (IDLE/ERROR,
        before or after the rejection arrives) must not toast nor skip to the next item."""
        try:
            await self.driver.play_media(device_id, req)
        except CastError as exc:
            self._bump_epoch(device_id)  # drops finished events queued under this LOAD
            meta = self._meta.get(device_id)
            if meta is not None and meta.request is req:
                meta.load_failed = True  # and those emitted after the rejection
            raise AppError(502, str(exc), "cast_error") from exc

    async def _play_entry(self, device_id: str, entry: QueueEntry) -> None:
        media = entry.media
        stale = time.time() - entry.resolved_at > RERESOLVE_AFTER
        if media is None or (stale and not entry.pinned):
            media = await self.resolver.resolve_media(entry.item.input, entry.kind, entry.item.title)
            if entry.item.thumbnail and not media.thumbnail:
                media.thumbnail = entry.item.thumbnail
        await self._play_media(
            device_id, media, history_input=entry.item.input, history_kind=entry.kind, pinned=entry.pinned
        )

    async def show_idle(self, device_id: str) -> PlayerState:
        await self._ensure_connected(device_id, auto=False)
        async with self._play_lock(device_id):
            return await self._show_idle(device_id)

    async def _show_idle(self, device_id: str) -> PlayerState:
        """show_idle body (caller holds the device's play lock)."""
        await self._ensure_connected(device_id, auto=False)
        settings = self.db.get_settings()
        url = settings.idle_image_url or f"{self.base_url().rstrip('/')}/idle.jpg"
        mime = "image/png" if url.lower().split("?")[0].endswith(".png") else "image/jpeg"
        req = MediaRequest(url=url, mime_type=mime, title="Chromecast Web", is_image=True)
        self._cancel_recovery(device_id)
        await self._release_restream(device_id)
        self._bump_epoch(device_id)
        self._meta[device_id] = _Meta(media_url=url, showing_idle=True, request=req)
        await self._load(device_id, req)
        self._push(device_id)
        return self.player(device_id)

    async def control(self, device_id: str, action: ControlAction, value: float | None) -> PlayerState:
        await self._ensure_connected(device_id, auto=False)
        meta = self._meta.get(device_id)
        if meta is not None and meta.recovering and action in (*PLAYBACK_ACTIONS, "play", "toggle"):
            # the user takes over: stop/next/previous/go_live replace the media as usual, and
            # play while reconnecting means "retry now" (the receiver has dropped the media)
            self._cancel_recovery(device_id)
            if action in ("play", "toggle"):
                async with self._play_lock(device_id):
                    if self._meta.get(device_id) is meta and meta.request is not None:
                        meta.load_failed = False
                        self._bump_epoch(device_id)
                        await self._load(device_id, meta.request)
                self._push(device_id)
                return self.player(device_id)
        if action in PLAYBACK_ACTIONS:
            async with self._play_lock(device_id):
                result = await self._control(device_id, action, value)
        else:  # volume/seek/pause never wait behind a slow LOAD
            result = await self._control(device_id, action, value)
        if result is not None:
            return result
        self._push(device_id)
        return self.player(device_id)

    async def _control(self, device_id: str, action: ControlAction, value: float | None) -> PlayerState | None:
        d = self.driver
        st = d.status(device_id)
        try:
            if action == "play":
                await d.play(device_id)
            elif action == "pause":
                await d.pause(device_id)
            elif action == "toggle":
                if st.player_state == "PLAYING":
                    await d.pause(device_id)
                else:
                    await d.play(device_id)
            elif action == "stop":
                self.queue.clear(device_id)
                if self.db.get_settings().show_idle_on_stop:
                    return await self._show_idle(device_id)
                self._bump_epoch(device_id)
                await self._release_restream(device_id)
                await d.stop_media(device_id)
                self._meta.pop(device_id, None)
            elif action == "seek":
                await d.seek(device_id, self._require_value(value))
            elif action == "seek_relative":
                await d.seek(device_id, max(0.0, st.position_now() + self._require_value(value)))
            elif action == "go_live":
                await self._go_live(device_id)
            elif action == "volume":
                await d.set_volume(device_id, max(0.0, min(1.0, self._require_value(value))))
            elif action == "volume_relative":
                await d.set_volume(device_id, max(0.0, min(1.0, st.volume_level + self._require_value(value))))
            elif action == "mute":
                await d.set_muted(device_id, True)
            elif action == "unmute":
                await d.set_muted(device_id, False)
            elif action == "next":
                if not await self._play_next(device_id):
                    raise AppError(409, "Queue is empty", "queue_empty")
            elif action == "previous":
                entry = self.queue.pop_previous(device_id)
                if entry is None:
                    await d.seek(device_id, 0.0)
                else:
                    await self._play_entry(device_id, entry)
        except CastError as exc:
            raise AppError(502, str(exc), "cast_error") from exc
        return None

    @staticmethod
    def _require_value(value: float | None) -> float:
        if value is None:
            raise AppError(422, "This action requires a numeric 'value'", "validation_error")
        return float(value)

    async def _go_live(self, device_id: str) -> None:
        st = self.driver.status(device_id)
        meta = self._meta.get(device_id)
        if st.stream_type == "LIVE" and meta and meta.request and not meta.showing_idle:
            # Reloading a live stream jumps to the live edge on every receiver. Same
            # epoch / load_failed handling as any LOAD: a rejected reload is the caller's
            # 502 only, its IDLE/ERROR broadcast must not toast again nor skip the queue.
            meta.load_failed = False
            self._bump_epoch(device_id)
            await self._load(device_id, meta.request)
        elif st.duration:
            await self.driver.seek(device_id, st.duration)

    async def set_tracks(self, device_id: str, track_ids: list[int]) -> PlayerState:
        await self._ensure_connected(device_id, auto=False)
        try:
            await self.driver.set_active_tracks(device_id, track_ids)
        except CastError as exc:
            raise AppError(502, str(exc), "cast_error") from exc
        self._push(device_id)
        return self.player(device_id)

    # ------------------------------------------------------------ queue
    async def enqueue(
        self,
        device_id: str,
        input: str,
        kind: SourceKind | None = None,
        title: str | None = None,
        media: ResolvedMedia | None = None,
        thumbnail: str | None = None,
        pinned: bool = False,
    ) -> PlayerState:
        """``pinned``: ``media`` is not derivable from ``input`` (remote-browser capture) and
        must be played as is; otherwise it is re-resolved when it gets old."""
        # Like play(): the device is connected on demand, otherwise the item would sit in
        # an invisible queue (players only lists connected devices) and never start.
        await self._ensure_connected(device_id, auto=True)
        if media is None and title is None:
            # resolve now: validates the input early and gives the item a real title
            media = await self.resolver.resolve_media(input, kind)
        async with self._play_lock(device_id):
            # under the lock: a queue advance (media finished) can't pop concurrently
            self._queue_add(device_id, input, kind, title, media, thumbnail, pinned)
            if not self._busy(device_id):
                await self._play_next(device_id)
        self._push_any(device_id)
        return self.player(device_id)

    def _queue_add(
        self,
        device_id: str,
        input: str,
        kind: SourceKind | None,
        title: str | None,
        media: ResolvedMedia | None,
        thumbnail: str | None,
        pinned: bool = False,
    ) -> None:
        self.queue.add(
            device_id,
            input,
            title or (media.title if media else None),
            thumbnail or (media.thumbnail if media else None),
            kind=kind or (media.source_kind if media else None),
            media=media,
            pinned=pinned and media is not None,
        )

    def _push_any(self, device_id: str) -> None:
        if self.driver.is_connected(device_id):
            self._push(device_id)
        else:
            self.hub.notify()

    def remove_from_queue(self, device_id: str, item_id: str) -> PlayerState:
        self.get_device(device_id)
        if not self.queue.remove(device_id, item_id):
            raise AppError(404, "Queue item not found", "queue_item_not_found")
        self._push_any(device_id)
        return self.player(device_id)

    def reorder_queue(self, device_id: str, item_ids: list[str]) -> PlayerState:
        self.get_device(device_id)
        self.queue.reorder(device_id, item_ids)
        self._push_any(device_id)
        return self.player(device_id)
