import httpx
import pytest

from app.ai_subtitles import _bilibili_dm_tracks


@pytest.mark.asyncio
async def test_bilibili_dm_fallback_discovers_cc_and_ai_subtitles(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params):
            if url.endswith("/web-interface/view"):
                return httpx.Response(200, json={"data": {"aid": 1, "cid": 2}})
            return httpx.Response(200, json={"data": {"subtitle": {"subtitles": [
                {"id": 10, "lan": "zh", "lan_doc": "Chinese", "type": 0, "subtitle_url": "//aisubtitle.hdslb.com/a.json"},
                {"id": 11, "lan": "ai-zh", "lan_doc": "Chinese auto", "type": 1, "subtitle_url": "http://aisubtitle.hdslb.com/b.json"},
            ]}}})

    monkeypatch.setattr("app.ai_subtitles.httpx.AsyncClient", Client)
    monkeypatch.setattr("app.ai_subtitles.validate_source_url", lambda url: None)

    tracks = await _bilibili_dm_tracks("https://www.bilibili.com/video/BV1mAAmzqEfP", {"id": "BV1mAAmzqEfP"})

    assert [(track.public.language, track.public.automatic, track.url) for track in tracks] == [
        ("zh", False, "https://aisubtitle.hdslb.com/a.json"),
        ("zh", True, "https://aisubtitle.hdslb.com/b.json"),
    ]
