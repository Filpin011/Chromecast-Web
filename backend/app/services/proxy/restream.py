"""ffmpeg restream to HLS for sources the Chromecast can't play directly.

Two output shapes:

- **live** inputs (IPTV raw TS, RTMP/RTSP/UDP, ...): a sliding window
  (``delete_segments``, no ENDLIST). If ffmpeg dies it is restarted with
  ``append_list`` so the media sequence keeps growing (players never see it go back).
- **VOD/file** inputs (local .avi/.ts/.flv/.wmv/.m2ts, HTTP files with a length):
  read at native speed (``-re``) into an ``event`` playlist that keeps every segment
  and gets ``#EXT-X-ENDLIST`` when done. A job that ended normally is served as is,
  never wiped and restarted.

Codecs: the source is probed with ffprobe first; video is copied only when it is
H.264 (what a Chromecast decodes inside HLS-TS), everything else (MPEG-4 Part 2/Xvid,
MPEG-2, VC-1/WMV, FLV1, ...) is transcoded to H.264. When the probe fails we fall
back to "copy, then transcode if ffmpeg can't produce a playlist".
Processes are reaped when idle and on shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.services.net import DESKTOP_UA
from app.services.proxy.tokens import clean_headers

log = logging.getLogger(__name__)

STARTUP_TIMEOUT = 25.0
PROBE_TIMEOUT = 15.0
# Worst case for the first playlist: probe, then copy and transcode attempts. A LOAD of
# a restreamed URL must wait at least this long (plus the receiver's own round trip).
WORST_STARTUP = PROBE_TIMEOUT + 2 * STARTUP_TIMEOUT
RESTREAM_PATH_RE = re.compile(r"/restream/([0-9a-f]+)/index\.m3u8(?:$|\?)")
# video codecs the Chromecast (incl. Ultra) decodes from HLS MPEG-TS segments
COPYABLE_VIDEO = ("h264",)
UNKNOWN = "?"  # probe not possible / failed


@dataclass
class RestreamJob:
    token: str
    source: str
    headers: dict[str, str]
    out_dir: Path
    live: bool = True
    proc: asyncio.subprocess.Process | None = None
    mode: str = "copy"
    video_codec: str | None = None  # None = not probed yet, UNKNOWN = probe failed
    last_access: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    failed: str | None = None

    @property
    def playlist(self) -> Path:
        return self.out_dir / "index.m3u8"

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    @property
    def finished(self) -> bool:
        """A VOD job whose ffmpeg completed: the playlist is final (has ENDLIST)."""
        if self.live or self.running or not self.playlist.exists():
            return False
        try:
            return "#EXT-X-ENDLIST" in self.playlist.read_text(errors="replace")
        except OSError:  # pragma: no cover
            return False


def _input_args(job: RestreamJob) -> list[str]:
    args: list[str] = []
    src = job.source
    if src.startswith(("http://", "https://")):
        hdrs = {k: v for k, v in job.headers.items() if k.lower() != "user-agent"}
        ua = next((v for k, v in job.headers.items() if k.lower() == "user-agent"), DESKTOP_UA)
        args += ["-user_agent", ua]
        if hdrs:
            args += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())]
    return args


def build_ffprobe_cmd(ffprobe: str, job: RestreamJob) -> list[str]:
    cmd = [ffprobe, "-v", "error", *_input_args(job)]
    if job.source.startswith(("http://", "https://")):
        cmd += ["-rw_timeout", "10000000"]
    cmd += [
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        "-i", job.source,
    ]
    return cmd


def build_ffmpeg_cmd(ffmpeg: str, job: RestreamJob, mode: str, append: bool = False) -> list[str]:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin"]
    cmd += _input_args(job)
    if job.source.startswith(("http://", "https://")):
        cmd += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]
    if not job.live:
        # files are remuxed much faster than real time: pace them like a live feed
        cmd += ["-re"]
    cmd += ["-fflags", "+genpts", "-i", job.source, "-map", "0:v:0?", "-map", "0:a:0?"]
    if mode == "copy":
        cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast"]
        if job.live:
            cmd += ["-tune", "zerolatency"]
        cmd += [
            "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
            "-g", "48", "-c:a", "aac", "-b:a", "160k", "-ac", "2",
        ]
    cmd += ["-f", "hls", "-hls_time", "4"]
    if job.live:
        flags = "delete_segments+omit_endlist+independent_segments"
        if append:
            flags += "+append_list"  # continue the media sequence after a restart
        cmd += ["-hls_list_size", "8", "-hls_flags", flags]
    else:
        # keep every segment, write ENDLIST at the end → seekable once complete
        cmd += ["-hls_playlist_type", "event", "-hls_list_size", "0", "-hls_flags", "independent_segments"]
    cmd += ["-hls_segment_filename", str(job.out_dir / "seg_%05d.ts"), str(job.playlist)]
    return cmd


def _default_ffprobe(ffmpeg: str) -> str:
    p = Path(ffmpeg)
    if p.parent != Path("."):
        return str(p.with_name("ffprobe"))
    return "ffprobe"


def _executable(path: str) -> bool:
    return bool(shutil.which(path)) or Path(path).is_file()


class RestreamManager:
    def __init__(
        self,
        base_dir: Path,
        ffmpeg: str = "ffmpeg",
        idle_timeout: float = 60.0,
        ffprobe: str | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe or _default_ffprobe(ffmpeg)
        self.idle_timeout = idle_timeout
        # "Is this job's playlist the media loaded on a device?" (wired to CastService).
        # A paused receiver stops fetching; its job must survive that.
        self.in_use: Callable[[RestreamJob], bool] = lambda _job: False
        self.jobs: dict[str, RestreamJob] = {}
        self._reaper: asyncio.Task[None] | None = None
        self._warming: set[asyncio.Task[None]] = set()

    def register(self, source: str, headers: dict[str, str] | None = None, live: bool = True) -> RestreamJob:
        hdrs = clean_headers(headers)
        token = hashlib.sha256(f"{source}|{sorted(hdrs.items())}|{live}".encode()).hexdigest()[:24]
        job = self.jobs.get(token)
        if job is None:
            job = RestreamJob(token=token, source=source, headers=hdrs, out_dir=self.base_dir / token, live=live)
            self.jobs[token] = job
        return job

    def get(self, token: str) -> RestreamJob | None:
        return self.jobs.get(token)

    def job_for_url(self, url: str) -> RestreamJob | None:
        """The job behind a ``.../restream/{token}/index.m3u8`` cast URL, if any."""
        mt = RESTREAM_PATH_RE.search(url)
        return self.jobs.get(mt.group(1)) if mt else None

    def warm(self, job: RestreamJob) -> None:
        """Start ffmpeg in the background now, so probing/startup overlaps with the cast
        LOAD round trip instead of starting on the receiver's first playlist request."""
        if job.running or job.finished:
            return

        async def _run() -> None:
            try:
                await self.ensure_running(job)
            except Exception as exc:  # the receiver's own request will report it
                log.info("restream %s warm-up failed: %s", job.token, exc)

        task = asyncio.create_task(_run(), name=f"restream-warm-{job.token}")
        self._warming.add(task)
        task.add_done_callback(self._warming.discard)

    def start_reaper(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_loop(), name="restream-reaper")

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(max(5.0, self.idle_timeout / 4))
            await self.reap()

    async def reap(self) -> None:
        """Clean up idle jobs.

        - not loaded on any device: stop ffmpeg and delete the output;
        - loaded (e.g. paused) **VOD**: untouched, ffmpeg finishes the file, so resuming
          (segments requested directly) and seeking keep working;
        - loaded **live**: stop pulling the source but keep the directory, so the next
          playlist request restarts with ``append_list`` and a continuous media sequence.
        """
        now = time.time()
        for job in list(self.jobs.values()):
            if now - job.last_access <= self.idle_timeout:
                continue
            if not job.running and not job.out_dir.exists():
                continue
            in_use = self._in_use(job)
            if in_use and (not job.live or not job.running):
                continue
            async with job.lock:
                if time.time() - job.last_access <= self.idle_timeout:
                    continue  # requested again while we waited for the lock
                await self._kill(job)
                if in_use:
                    log.info("restream %s idle but still loaded, ffmpeg stopped (output kept)", job.token)
                else:
                    log.info("restream %s idle, stopping", job.token)
                    shutil.rmtree(job.out_dir, ignore_errors=True)

    def _in_use(self, job: RestreamJob) -> bool:
        try:
            return bool(self.in_use(job))
        except Exception:  # pragma: no cover - never let the reaper die
            log.exception("restream in_use check failed")
            return True

    # ------------------------------------------------------------ codec probe
    async def probe_video_codec(self, job: RestreamJob) -> str:
        if not _executable(self.ffprobe):
            return UNKNOWN
        try:
            proc = await asyncio.create_subprocess_exec(
                *build_ffprobe_cmd(self.ffprobe, job),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            return UNKNOWN
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), PROBE_TIMEOUT)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            return UNKNOWN
        if proc.returncode != 0:
            return UNKNOWN
        lines = [ln.strip().lower() for ln in out.decode(errors="replace").splitlines() if ln.strip()]
        # no video stream at all (audio-only): nothing to transcode, copy is fine
        return lines[0] if lines else "none"

    @staticmethod
    def modes_for(codec: str | None) -> tuple[str, ...]:
        if codec in (None, UNKNOWN):
            return ("copy", "transcode")
        if codec in COPYABLE_VIDEO or codec == "none":
            return ("copy", "transcode")
        return ("transcode",)

    # ------------------------------------------------------------ lifecycle
    async def ensure_running(self, job: RestreamJob) -> None:
        job.last_access = time.time()
        async with job.lock:
            if job.running and job.playlist.exists():
                return
            if job.finished:
                return  # VOD fully written: serve it, never wipe and restart
            if not _executable(self.ffmpeg):
                raise RuntimeError("ffmpeg not found")
            if job.live and job.playlist.exists() and job.failed is None:
                # live source dropped: resume the same window with a continuous media sequence
                mtime = job.playlist.stat().st_mtime_ns
                await self._spawn(job, job.mode, append=True)
                if await self._wait_playlist(job, after_mtime=mtime):
                    return
                await self._kill(job)
            if job.video_codec is None:
                job.video_codec = await self.probe_video_codec(job)
                log.info("restream %s video codec: %s", job.token, job.video_codec)
            for mode in self.modes_for(job.video_codec):
                await self._spawn(job, mode, append=False)
                if await self._wait_playlist(job):
                    job.failed = None
                    return
                await self._kill(job)
            job.failed = "ffmpeg could not produce a stream"
            raise RuntimeError(job.failed)

    async def _spawn(self, job: RestreamJob, mode: str, append: bool) -> None:
        await self._kill(job)
        if not append and job.out_dir.exists():
            shutil.rmtree(job.out_dir, ignore_errors=True)
        job.out_dir.mkdir(parents=True, exist_ok=True)
        job.mode = mode
        cmd = build_ffmpeg_cmd(self.ffmpeg, job, mode, append=append)
        log.info("restream %s starting (%s, %s%s)", job.token, mode, "live" if job.live else "vod",
                 ", resume" if append else "")
        job.proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )

    async def _wait_playlist(self, job: RestreamJob, after_mtime: int | None = None) -> bool:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if job.playlist.exists():
                st = job.playlist.stat()
                if st.st_size > 0 and (after_mtime is None or st.st_mtime_ns > after_mtime):
                    return True
            if job.proc is None or job.proc.returncode is not None:
                return False
            await asyncio.sleep(0.25)
        return False

    async def _kill(self, job: RestreamJob) -> None:
        proc = job.proc
        if proc is None or proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()

    def file_path(self, job: RestreamJob, name: str) -> Path | None:
        job.last_access = time.time()
        if "/" in name or "\\" in name or name.startswith("."):
            return None
        p = job.out_dir / name
        return p if p.exists() else None

    async def shutdown(self) -> None:
        for task in list(self._warming):
            task.cancel()
        for task in list(self._warming):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self._reaper:
            self._reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper
            self._reaper = None
        for job in list(self.jobs.values()):
            await self._kill(job)
            shutil.rmtree(job.out_dir, ignore_errors=True)
