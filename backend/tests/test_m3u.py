from app.services.resolver.m3u import looks_like_m3u_list, parse_attributes, parse_m3u, to_channels
from tests.fakes import LIVE_MEDIA, MASTER

IPTV = """﻿#EXTM3U x-tvg-url="https://epg.example.com/guide.xml.gz" url-tvg="https://epg.example.com/alt.xml"
#EXTINF:-1 tvg-id="Rai1.it" tvg-name="Rai 1 HD" tvg-logo="https://logo.example.com/rai1.png" group-title="Generalisti",Rai 1 HD
https://streams.example.com/rai1/index.m3u8
#EXTINF:-1 tvg-id="" tvg-logo="https://logo.example.com/a,b.png" group-title="Sport, Calcio",Sky Sport 24, Live
#EXTVLCOPT:http-referrer=https://sky.example.com/
#EXTVLCOPT:http-user-agent=Mozilla/5.0
http://streams.example.com/sky24.ts
#EXTINF:0 tvg-name='Single Quoted' group-title='Musica',Radio Italia
https://radio.example.com/live.aac

#EXTINF:-1,No Attributes Channel
#EXTGRP:Altro
rtmp://live.example.com/app/stream
# random comment
http://bare.example.com/bare.mp4
"""


def test_parse_attributes_quotes_and_commas():
    attrs, rest = parse_attributes(' tvg-logo="http://x/a,b.png" group-title="A, B" foo=bar,Name, with comma')
    assert attrs == {"tvg-logo": "http://x/a,b.png", "group-title": "A, B", "foo": "bar"}
    assert rest == "Name, with comma"


def test_parse_iptv_playlist_entries():
    pl = parse_m3u(IPTV)
    assert pl.attrs["x-tvg-url"] == "https://epg.example.com/guide.xml.gz"
    assert len(pl.entries) == 5
    rai, sky, radio, plain, bare = pl.entries
    assert rai.name == "Rai 1 HD"
    assert rai.attrs["tvg-logo"] == "https://logo.example.com/rai1.png"
    assert rai.group == "Generalisti"
    assert rai.duration == "-1"
    assert sky.name == "Sky Sport 24, Live"
    assert sky.group == "Sport, Calcio"
    assert sky.attrs["tvg-logo"] == "https://logo.example.com/a,b.png"
    assert sky.vlc_opts == {"http-referrer": "https://sky.example.com/", "http-user-agent": "Mozilla/5.0"}
    assert radio.attrs["tvg-name"] == "Single Quoted"
    assert radio.group == "Musica"
    assert plain.name == "No Attributes Channel"
    assert plain.group == "Altro"
    assert plain.url.startswith("rtmp://")
    assert bare.name == "bare.mp4"
    assert bare.vlc_opts == {}


def test_to_channels_maps_fields():
    chans = to_channels(parse_m3u(IPTV), playlist_id="p1")
    assert chans[0].tvg_id == "Rai1.it"
    assert chans[0].logo == "https://logo.example.com/rai1.png"
    assert chans[0].playlist_id == "p1"
    assert chans[1].tvg_id is None  # empty attribute → None
    assert len({c.id for c in chans}) == len(chans)


def test_looks_like_m3u_list_vs_hls():
    assert looks_like_m3u_list(IPTV)
    assert not looks_like_m3u_list(MASTER)
    assert not looks_like_m3u_list(LIVE_MEDIA)
    assert not looks_like_m3u_list("<html></html>")


def test_parse_crlf_and_empty():
    pl = parse_m3u("#EXTM3U\r\n#EXTINF:-1,A\r\nhttp://a/1.ts\r\n")
    assert [(e.name, e.url) for e in pl.entries] == [("A", "http://a/1.ts")]
    assert parse_m3u("").entries == []


def test_channel_headers_from_every_convention():
    text = """#EXTM3U
#EXTINF:-1 user-agent="UA-attr" group-title="X",Attr
https://a.example/1.m3u8
#EXTINF:-1,Vlc
#EXTVLCOPT:http-referrer=https://ref.example/
#EXTVLCOPT:http-user-agent=Mozilla/5.0
#EXTVLCOPT:network-caching=1000
https://a.example/2.m3u8
#EXTINF:-1,Kodi
https://a.example/3.m3u8|Referer=https%3A%2F%2Fk.example%2F&User-Agent=Kodi%2F20
#EXTINF:-1,ExtHttp
#EXTHTTP:{"cookie":"s=1","referer":"https://h.example/"}
https://a.example/4.m3u8
#EXTINF:-1,Plain
https://a.example/5.m3u8
"""
    attr, vlc, kodi, exthttp, plain = to_channels(parse_m3u(text))
    assert attr.headers == {"User-Agent": "UA-attr"}
    assert vlc.headers == {"Referer": "https://ref.example/", "User-Agent": "Mozilla/5.0"}
    assert kodi.url == "https://a.example/3.m3u8"  # the pipe never stays in the URL
    assert kodi.headers == {"Referer": "https://k.example/", "User-Agent": "Kodi/20"}
    assert exthttp.headers == {"Cookie": "s=1", "Referer": "https://h.example/"}
    assert plain.headers == {}


def test_split_and_join_input_round_trip():
    from app.services.resolver.inputs import join_input, split_input

    joined = join_input("https://a.example/x.m3u8", {"http-referrer": "https://r.example/?a=1&b=2"})
    assert joined == "https://a.example/x.m3u8|Referer=https%3A%2F%2Fr.example%2F%3Fa%3D1%26b%3D2"
    assert split_input(joined) == ("https://a.example/x.m3u8", {"Referer": "https://r.example/?a=1&b=2"})
    assert join_input(joined, {"User-Agent": "VLC"}).endswith("&User-Agent=VLC")
    assert join_input("https://a.example/x.m3u8", None) == "https://a.example/x.m3u8"
    assert split_input("Movies/a|b.mp4") == ("Movies/a|b.mp4", {})
