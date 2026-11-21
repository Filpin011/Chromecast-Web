"""Demuxed HLS (separate audio/subtitle renditions): master structure, segment formats sniffed
from the bytes (also AES-128 encrypted), consistent audio language, LOAD logging."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import respx

from app.services.cast.base import MediaRequest
from app.services.cast.pychromecast_driver import PyChromecastDriver, load_summary, log_receiver_errors
from app.services.proxy import hls
from app.services.proxy.aes import cbc_decrypt_prefix
from app.services.proxy.restream import RestreamManager
from app.services.proxy.stream import ProxyService
from app.services.proxy.tokens import TokenRegistry
from app.services.resolver.service import Resolver
from tests.fakes import DEMUXED_MASTER, NOEXT_MEDIA

HOST = "cdn.example.com"
MASTER_URL = f"https://{HOST}/show/master.m3u8?tok=A"

TS = (b"\x47" + b"\x00" * 187) * 3
FTYP = b"\x00\x00\x00\x18ftypiso6" + b"\x00" * 100
ADTS = b"\xff\xf1\x50\x80" + bytes(range(60))
AC3 = b"\x0b\x77\x00\x00\x00\x40" + b"\x00" * 64  # bsid 8 → AC-3
# ADTS above, encrypted with `openssl enc -aes-128-cbc -K 0011..eeff -iv 00..ab`
AES_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
AES_IV = "0x000000000000000000000000000000ab"
ADTS_ENCRYPTED = bytes.fromhex(
    "92823fd3de2c6406846c87ef2056aa278be90020f6279211c574e9c78997a59b"
    "ca5bae659aa60b61997149e9969edef78a6701e4f82a8263b295aaeaf10c32ac"
    "9c1cf27a515e8ef01235086acc5e68c2"
)


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as c:
        yield c


def make(http: httpx.AsyncClient, tmp_path: Path, audio_language: str | None = None) -> Resolver:
    return Resolver(
        http,
        TokenRegistry(),
        RestreamManager(tmp_path / "rs"),
        media_root=None,
        browser=None,
        enable_playwright=False,
        base_url=lambda: "http://cast.test:8000",
        audio_language=audio_language,
    )


def serve(path: str, **kw) -> respx.Route:
    return respx.route(host=HOST, path=path).respond(200, **kw)


def demuxed(video: bytes, audio: bytes, audio_playlist: str = NOEXT_MEDIA) -> dict[str, respx.Route]:
    return {
        "master": serve("/show/master.m3u8", text=DEMUXED_MASTER),
        "video": serve("/show/video/720.m3u8", text=NOEXT_MEDIA),
        "vseg": serve("/show/video/chunk", content=video),
        "audio": serve("/show/audio/hi/ita.m3u8", text=audio_playlist),
        "aseg": serve("/show/audio/hi/chunk", content=audio),
    }


# ---------------------------------------------------------------- pure helpers


def test_child_playlist_urls_cover_variants_and_renditions():
    kids = hls.child_playlist_urls(DEMUXED_MASTER, MASTER_URL)
    base = f"https://{HOST}/show/"
    assert kids == [
        base + "audio/hi/ita.m3u8?tok=A",
        base + "audio/hi/eng.m3u8?tok=A",
        base + "audio/lo/ita.m3u8?tok=A",
        base + "audio/lo/eng.m3u8?tok=A",
        base + "subs/ita.m3u8?tok=A",
        base + "video/720.m3u8?tok=A",
        base + "video/480.m3u8?tok=A",
    ]
    assert hls.child_playlist_urls(NOEXT_MEDIA, MASTER_URL) == []


def test_media_playlist_kind():
    audio = NOEXT_MEDIA.replace("chunk?n=0", "seg0.aac")
    subs = NOEXT_MEDIA.replace("chunk?n=0", "seg0.webvtt")
    assert hls.media_playlist_kind(audio) == "audio"
    assert hls.media_playlist_kind(subs) == "subtitles"
    assert hls.media_playlist_kind(NOEXT_MEDIA) is None
    assert hls.media_playlist_kind(DEMUXED_MASTER) is None


def test_first_segment_key_iv_from_attribute_or_sequence():
    explicit = NOEXT_MEDIA.replace("#EXTINF", f'#EXT-X-KEY:METHOD=AES-128,URI="k",IV={AES_IV}\n#EXTINF', 1)
    assert hls.first_segment_key(explicit) == ("AES-128", "k", bytes.fromhex(AES_IV[2:]))
    implicit = NOEXT_MEDIA.replace("SEQUENCE:0", "SEQUENCE:7").replace(
        "#EXTINF", '#EXT-X-KEY:METHOD=AES-128,URI="k"\n#EXTINF', 1
    )
    assert hls.first_segment_key(implicit) == ("AES-128", "k", (7).to_bytes(16, "big"))
    assert hls.first_segment_key(NOEXT_MEDIA) is None
    assert hls.first_segment_key(NOEXT_MEDIA.replace("#EXTINF", "#EXT-X-KEY:METHOD=NONE\n#EXTINF", 1)) is None


def test_aes128_cbc_prefix():
    # FIPS-197 C.1 vector (one block, zero IV) and a multi-block openssl ciphertext
    assert cbc_decrypt_prefix(
        bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a"), bytes(range(16)), bytes(16)
    ) == bytes.fromhex("00112233445566778899aabbccddeeff")
    assert cbc_decrypt_prefix(ADTS_ENCRYPTED, AES_KEY, bytes.fromhex(AES_IV[2:]))[: len(ADTS)] == ADTS
    assert hls.sniff_segment(AC3) == "ac3"


def test_harmonize_audio_defaults_keeps_one_language_across_groups():
    out = hls.harmonize_audio_defaults(DEMUXED_MASTER)
    lines = [ln for ln in out.splitlines() if "TYPE=AUDIO" in ln]
    # the first variant's group default (ita) becomes the default of every group
    assert [("DEFAULT=YES" in ln, 'LANGUAGE="ita"' in ln) for ln in lines] == [
        (True, True), (False, False), (True, True), (False, False)
    ]
    assert "AUTOSELECT=YES" in lines[2]
    assert out.count("#EXT-X-STREAM-INF") == 2 and out.endswith("\n")
    # an explicit preference wins (it/ita/it-IT and en/eng match each other)
    eng = [ln for ln in hls.harmonize_audio_defaults(DEMUXED_MASTER, "en-US").splitlines() if "TYPE=AUDIO" in ln]
    assert [("DEFAULT=YES" in ln) for ln in eng] == [False, True, False, True]
    # unknown preference → the master's own default; single-rendition groups unchanged
    assert hls.harmonize_audio_defaults(DEMUXED_MASTER, "de") == out
    single = "\n".join(ln for ln in DEMUXED_MASTER.splitlines() if "eng.m3u8" not in ln)
    assert hls.harmonize_audio_defaults(single) == single


def test_proxy_serves_the_master_with_harmonized_audio_defaults():
    tokens = TokenRegistry()
    target = tokens.register(MASTER_URL, {})
    proxy = ProxyService(httpx.AsyncClient(), tokens, audio_language="it")
    body = proxy._playlist_response(DEMUXED_MASTER.encode(), MASTER_URL, target).body.decode()
    lo = [ln for ln in body.splitlines() if 'GROUP-ID="lo"' in ln]
    assert "DEFAULT=YES" in lo[0] and 'LANGUAGE="ita"' in lo[0] and "DEFAULT=NO" in lo[1]
    assert '/proxy/' in lo[0]


# ---------------------------------------------------------------- resolver probe


@respx.mock
async def test_ts_video_with_ts_audio_rendition_says_ts(http, tmp_path):
    routes = demuxed(TS, TS)
    info = await make(http, tmp_path).hls_info(MASTER_URL)
    assert routes["aseg"].called  # the DEFAULT=YES rendition of the first variant's group
    assert info.is_master and info.segment_format == "ts" and info.video_segment_format is None
    assert len(info.child_urls) == 7 and info.media_type is None
    assert (info.width, info.height) == (1280, 720)


@respx.mock
async def test_fmp4_video_with_ts_audio_rendition(http, tmp_path):
    demuxed(FTYP, TS)
    info = await make(http, tmp_path).hls_info(MASTER_URL)
    assert info.segment_format == "ts" and info.video_segment_format == "fmp4"
    media = PyChromecastDriver.build_play_kwargs(MediaRequest(
        url="u", mime_type="application/x-mpegURL",
        hls_segment_format=info.segment_format, hls_video_segment_format=info.video_segment_format,
    ))["media_info"]
    assert media == {"hlsSegmentFormat": "ts", "hlsVideoSegmentFormat": "fmp4"}


@respx.mock
async def test_ac3_audio_rendition_is_sniffed_without_extension(http, tmp_path):
    demuxed(TS, AC3)
    assert (await make(http, tmp_path).hls_info(MASTER_URL)).segment_format == "ac3"


@respx.mock
async def test_aes128_audio_rendition_is_decrypted_before_sniffing(http, tmp_path):
    keyed = NOEXT_MEDIA.replace("#EXTINF", f'#EXT-X-KEY:METHOD=AES-128,URI="/keys/k1?tok=Z",IV={AES_IV}\n#EXTINF', 1)
    routes = demuxed(TS, ADTS_ENCRYPTED, keyed)
    key = serve("/keys/k1", content=AES_KEY)
    info = await make(http, tmp_path).hls_info(MASTER_URL)
    assert key.called and routes["aseg"].called
    assert info.segment_format == "aac" and info.video_segment_format is None


@respx.mock
async def test_aes128_without_key_does_not_trust_ciphertext(http, tmp_path):
    keyed = NOEXT_MEDIA.replace("#EXTINF", f'#EXT-X-KEY:METHOD=AES-128,URI="/keys/k1",IV={AES_IV}\n#EXTINF', 1)
    demuxed(TS, TS, keyed)  # ciphertext that happens to look like TS must not be sniffed as such
    respx.route(host=HOST, path="/keys/k1").respond(403)
    info = await make(http, tmp_path).hls_info(MASTER_URL)
    assert info.segment_format is None  # unknown audio container: the TS video default stays


@respx.mock
async def test_audio_and_subtitle_media_playlists_are_flagged(http, tmp_path):
    serve("/radio/a.m3u8", text=NOEXT_MEDIA)
    serve("/radio/chunk", content=ADTS)
    serve("/radio/named.m3u8", text=NOEXT_MEDIA.replace("chunk?n=0", "seg0.aac"))
    serve("/radio/seg0.aac", content=ADTS)
    serve("/subs/s.m3u8", text=NOEXT_MEDIA.replace("chunk?n=0", "seg0.vtt"))
    serve("/subs/seg0.vtt", text="WEBVTT\n")
    serve("/tv/v.m3u8", text=NOEXT_MEDIA)
    serve("/tv/chunk", content=TS)
    r = make(http, tmp_path)
    assert (await r.hls_info(f"https://{HOST}/radio/a.m3u8")).media_type == "audio"
    assert (await r.hls_info(f"https://{HOST}/radio/named.m3u8")).media_type == "audio"
    assert (await r.hls_info(f"https://{HOST}/subs/s.m3u8")).media_type == "subtitles"
    tv = await r.hls_info(f"https://{HOST}/tv/v.m3u8")
    assert tv.media_type is None and tv.segment_format is None and tv.child_urls == []


# ---------------------------------------------------------------- driver diagnostics


def test_load_summary_and_receiver_error_logging(caplog):
    media = MediaRequest(url="http://cast.test:8000/proxy/" + "x" * 200, mime_type="application/x-mpegURL",
                         stream_type="LIVE", hls_segment_format="ts")
    summary = load_summary(media, PyChromecastDriver.build_play_kwargs(media))
    assert summary["hlsSegmentFormat"] == "ts" and summary["streamType"] == "LIVE"
    assert len(summary["contentId"]) <= 96 and summary["contentId"].endswith("…")
    assert summary["tracks"] == [] and summary["activeTrackIds"] is None

    class Controller:
        def __init__(self) -> None:
            self.got: list[dict] = []

        def receive_message(self, message, data):
            self.got.append(data)
            return True

    ctl = Controller()
    log_receiver_errors(ctl, "dev1")
    log_receiver_errors(ctl, "dev1")  # idempotent
    with caplog.at_level(logging.INFO, logger="app.services.cast.pychromecast_driver"):
        assert ctl.receive_message(None, {"type": "ERROR", "detailedErrorCode": 314, "reason": "INVALID"})
        ctl.receive_message(None, {"type": "MEDIA_STATUS"})
    assert len(ctl.got) == 2
    errors = [r.getMessage() for r in caplog.records if "detailedErrorCode" in r.getMessage()]
    assert errors == ["receiver ERROR on dev1: detailedErrorCode=314 HLS_NETWORK_KEY_LOAD reason=INVALID itemId=None"]
