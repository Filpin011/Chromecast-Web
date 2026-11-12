import asyncio
import json
import stat
import sys
from pathlib import Path

import pytest

from app.services.proxy.restream import UNKNOWN, RestreamManager, build_ffmpeg_cmd, build_ffprobe_cmd

FAKE_FFMPEG = """#!{py}
import json, sys, time, pathlib
args = sys.argv[1:]
with open({log!r}, "a") as fh:
    fh.write(json.dumps(args) + "\\n")
out = pathlib.Path(args[-1])
mode = "copy" if "copy" in args else "transcode"
if mode == "copy" and "{fail_copy}" == "1":
    sys.exit(1)
end = "#EXT-X-ENDLIST\\n" if "{finish}" == "1" and "-hls_playlist_type" in args else ""
out.write_text("#EXTM3U\\n#EXT-X-TARGETDURATION:4\\n#EXTINF:4,\\nseg_00000.ts\\n" + end)
(out.parent / "seg_00000.ts").write_bytes(b"TS" + mode.encode())
if "{finish}" != "1":
    time.sleep(30)
"""

FAKE_FFPROBE = """#!{py}
import sys
print({codec!r})
"""


def fake_ffmpeg(tmp_path: Path, fail_copy: bool, finish: bool = False) -> str:
    p = tmp_path / "ffmpeg"
    p.write_text(FAKE_FFMPEG.format(py=sys.executable, fail_copy="1" if fail_copy else "0",
                                    finish="1" if finish else "0", log=str(tmp_path / "ffmpeg.log")))
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def fake_ffprobe(tmp_path: Path, codec: str) -> str:
    p = tmp_path / "ffprobe"
    p.write_text(FAKE_FFPROBE.format(py=sys.executable, codec=codec))
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def ffmpeg_calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "ffmpeg.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_build_cmd_headers_and_modes(tmp_path):
    m = RestreamManager(tmp_path)
    job = m.register("http://iptv/x.ts", {"User-Agent": "VLC", "Referer": "http://r/"})
    copy = build_ffmpeg_cmd("ffmpeg", job, "copy")
    assert copy[copy.index("-user_agent") + 1] == "VLC"
    assert copy[copy.index("-headers") + 1] == "Referer: http://r/\r\n"
    assert "copy" in copy and copy[-1].endswith("index.m3u8")
    tr = build_ffmpeg_cmd("ffmpeg", job, "transcode")
    assert "libx264" in tr and "-reconnect" in tr
    local = build_ffmpeg_cmd("ffmpeg", m.register("/media/a.avi"), "copy")
    assert "-reconnect" not in local
    assert m.register("http://iptv/x.ts", {"Referer": "http://r/", "User-Agent": "VLC"}) is job
    # no captured UA: a browser one, never Lavf (403 on many IPTV panels)
    bare = build_ffmpeg_cmd("ffmpeg", m.register("http://iptv/y.ts"), "copy")
    assert bare[bare.index("-user_agent") + 1].startswith("Mozilla/") and "-headers" not in bare
    probe = build_ffprobe_cmd("ffprobe", m.register("http://iptv/y.ts"))
    assert probe[probe.index("-user_agent") + 1].startswith("Mozilla/")


def test_live_vs_file_output_shapes(tmp_path):
    m = RestreamManager(tmp_path)
    live = build_ffmpeg_cmd("ffmpeg", m.register("http://iptv/x.ts"), "copy")
    flags = live[live.index("-hls_flags") + 1]
    assert "delete_segments" in flags and "omit_endlist" in flags and "append_list" not in flags
    assert "-re" not in live and "-hls_playlist_type" not in live
    resumed = build_ffmpeg_cmd("ffmpeg", m.register("http://iptv/x.ts"), "copy", append=True)
    assert "append_list" in resumed[resumed.index("-hls_flags") + 1]
    # a local file must keep every segment and get an ENDLIST, read at native speed
    vod = build_ffmpeg_cmd("ffmpeg", m.register("/media/film.avi", live=False), "transcode")
    assert "-re" in vod and vod.index("-re") < vod.index("-i")
    assert vod[vod.index("-hls_playlist_type") + 1] == "event"
    assert vod[vod.index("-hls_list_size") + 1] == "0"
    assert "delete_segments" not in " ".join(vod) and "omit_endlist" not in " ".join(vod)
    assert "zerolatency" not in vod
    assert m.register("/media/film.avi", live=False) is not m.register("/media/film.avi", live=True)
    probe = build_ffprobe_cmd("ffprobe", m.register("http://iptv/x.ts", {"Referer": "http://r/"}))
    assert probe[probe.index("-headers") + 1] == "Referer: http://r/\r\n" and probe[-1] == "http://iptv/x.ts"


@pytest.mark.parametrize(("codec", "mode"), [("h264", "copy"), ("mpeg4", "transcode"), ("mpeg2video", "transcode"),
                                             ("wmv3", "transcode"), ("flv1", "transcode")])
async def test_only_h264_is_copied(tmp_path, codec, mode):
    m = RestreamManager(tmp_path / "rs", ffmpeg=fake_ffmpeg(tmp_path, False),
                        ffprobe=fake_ffprobe(tmp_path, codec))
    job = m.register(str(tmp_path / "film.avi"), live=False)
    await m.ensure_running(job)
    assert job.video_codec == codec and job.mode == mode
    assert ["copy" in c for c in ffmpeg_calls(tmp_path)] == [mode == "copy"]  # no failed copy attempt first
    await m.shutdown()


async def test_finished_vod_is_served_not_restarted(tmp_path):
    m = RestreamManager(tmp_path / "rs", ffmpeg=fake_ffmpeg(tmp_path, False, finish=True),
                        ffprobe=fake_ffprobe(tmp_path, "h264"))
    job = m.register(str(tmp_path / "film.ts"), live=False)
    await m.ensure_running(job)
    for _ in range(100):
        if job.finished:
            break
        await asyncio.sleep(0.05)
    assert job.finished
    await m.ensure_running(job)
    assert len(ffmpeg_calls(tmp_path)) == 1 and "#EXT-X-ENDLIST" in job.playlist.read_text()
    await m.shutdown()


async def test_live_restart_resumes_media_sequence(tmp_path):
    m = RestreamManager(tmp_path / "rs", ffmpeg=fake_ffmpeg(tmp_path, False),
                        ffprobe=fake_ffprobe(tmp_path, "h264"))
    job = m.register("http://iptv/x.ts")
    await m.ensure_running(job)
    job.proc.kill()  # the upstream dropped
    await job.proc.wait()
    await m.ensure_running(job)
    calls = ffmpeg_calls(tmp_path)
    assert len(calls) == 2
    assert "append_list" in calls[1][calls[1].index("-hls_flags") + 1]
    await m.shutdown()


async def test_unknown_codec_tries_copy_then_transcode(tmp_path):
    m = RestreamManager(tmp_path / "rs", ffmpeg=fake_ffmpeg(tmp_path, True), ffprobe=str(tmp_path / "missing"))
    job = m.register("http://iptv/x.ts")
    await m.ensure_running(job)
    assert job.video_codec == UNKNOWN and job.mode == "transcode"
    await m.shutdown()


async def test_reaper_stops_idle_jobs(tmp_path):
    m = RestreamManager(tmp_path / "rs", ffmpeg=fake_ffmpeg(tmp_path, False),
                        ffprobe=fake_ffprobe(tmp_path, "h264"), idle_timeout=60)
    job = m.register("http://iptv/x.ts")
    await m.ensure_running(job)
    job.last_access -= 120
    await m.reap()
    assert not job.running and not job.out_dir.exists()


async def test_reaper_keeps_paused_vod_loaded_on_a_device(tmp_path):
    """A paused receiver stops fetching: a VOD it still has loaded keeps ffmpeg and its
    segments (resume requests seg_000NN.ts directly); once unloaded it is cleaned up."""
    m = RestreamManager(tmp_path / "rs", ffmpeg=fake_ffmpeg(tmp_path, False),
                        ffprobe=fake_ffprobe(tmp_path, "h264"), idle_timeout=60)
    loaded: set[str] = set()
    m.in_use = lambda j: j.token in loaded
    job = m.register(str(tmp_path / "film.avi"), live=False)
    loaded.add(job.token)
    await m.ensure_running(job)
    job.last_access -= 600
    await m.reap()
    assert job.running and m.file_path(job, "seg_00000.ts") is not None
    loaded.clear()
    job.last_access -= 600
    await m.reap()
    assert not job.running and not job.out_dir.exists()
    await m.shutdown()


async def test_reaper_keeps_loaded_live_output_so_restart_appends(tmp_path):
    m = RestreamManager(tmp_path / "rs", ffmpeg=fake_ffmpeg(tmp_path, False),
                        ffprobe=fake_ffprobe(tmp_path, "h264"), idle_timeout=60)
    m.in_use = lambda j: True
    job = m.register("http://iptv/x.ts")
    await m.ensure_running(job)
    job.last_access -= 120
    await m.reap()
    # upstream no longer pulled, but the window is kept...
    assert not job.running and job.playlist.exists()
    # ...so the next playlist request continues the media sequence
    await m.ensure_running(job)
    calls = ffmpeg_calls(tmp_path)
    assert len(calls) == 2 and "append_list" in calls[1][calls[1].index("-hls_flags") + 1]
    await m.shutdown()


@pytest.mark.parametrize("fail_copy", [False, True])
async def test_ensure_running_falls_back_and_cleans_up(tmp_path, fail_copy):
    m = RestreamManager(tmp_path / "rs", ffmpeg=fake_ffmpeg(tmp_path, fail_copy), idle_timeout=60,
                        ffprobe=fake_ffprobe(tmp_path, "h264"))
    job = m.register("http://iptv/x.ts")
    await m.ensure_running(job)
    assert job.running and job.mode == ("transcode" if fail_copy else "copy")
    seg = m.file_path(job, "seg_00000.ts")
    assert seg is not None and seg.read_bytes().startswith(b"TS")
    assert m.file_path(job, "../etc") is None
    await m.shutdown()
    assert not job.running and not job.out_dir.exists()


async def test_missing_ffmpeg(tmp_path):
    m = RestreamManager(tmp_path, ffmpeg=str(tmp_path / "nope"))
    with pytest.raises(RuntimeError):
        await m.ensure_running(m.register("http://x/a.ts"))
    await asyncio.sleep(0)


def test_restream_endpoint(client, tmp_path):
    svc = client.app.state.services
    svc.restream.ffmpeg = fake_ffmpeg(tmp_path, False)
    svc.restream.ffprobe = fake_ffprobe(tmp_path, "h264")
    job = svc.restream.register("http://iptv/x.ts")
    r = client.get(f"/restream/{job.token}/index.m3u8")
    assert r.status_code == 200 and r.text.startswith("#EXTM3U")
    assert r.headers["access-control-allow-origin"] == "*"
    assert client.get(f"/restream/{job.token}/seg_00000.ts").content == b"TScopy"
    assert client.get(f"/restream/{job.token}/missing.ts").status_code == 404
    assert client.get("/restream/nope/index.m3u8").status_code == 404
