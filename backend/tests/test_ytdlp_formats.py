import json

import pytest

from app import ytdlp
from app.ytdlp import to_formats


def test_to_formats_exposes_only_standard_resolutions_without_duplicates():
    payload = {
        "formats": [
            {"format_id": "360-webm", "height": 360, "width": 640, "ext": "webm", "vcodec": "vp9", "acodec": "none", "tbr": 900, "url": "https://example.com/360-webm"},
            {"format_id": "360-mp4", "height": 360, "width": 640, "ext": "mp4", "vcodec": "avc1", "acodec": "aac", "tbr": 700, "url": "https://example.com/360-mp4"},
            {"format_id": "480", "height": 480, "width": 854, "ext": "mp4", "vcodec": "avc1", "tbr": 850, "url": "https://example.com/480"},
            {"format_id": "720", "height": 720, "width": 1280, "ext": "mp4", "vcodec": "avc1", "tbr": 1200, "url": "https://example.com/720"},
            {"format_id": "1080", "height": 1080, "width": 1920, "ext": "mp4", "vcodec": "avc1", "tbr": 2500, "url": "https://example.com/1080"},
            {"format_id": "1440", "height": 1440, "width": 2560, "ext": "mp4", "vcodec": "avc1", "url": "https://example.com/1440"},
            {"format_id": "audio", "ext": "m4a", "vcodec": "none", "url": "https://example.com/audio"},
        ]
    }

    formats, sources = to_formats(payload)

    assert [item.label for item in formats] == ["1080P", "720P", "480P", "360P"]
    assert [item.id for item in formats] == ["1080", "720", "480", "360-mp4"]
    assert set(sources) == {"1080", "720", "480", "360-mp4"}


@pytest.mark.asyncio
async def test_inspect_extracts_optional_video_metadata(monkeypatch):
    payload = {
        "title": "Video title",
        "thumbnail": "https://example.com/cover.jpg",
        "duration": "90",
        "uploader": "Creator",
        "description": "  Video description  ",
        "extractor_key": "Bilibili",
        "view_count": "6789",
        "formats": [
            {"format_id": "1080", "height": 1080, "width": 1920, "ext": "mp4", "vcodec": "avc1", "url": "https://example.com/video.mp4"},
        ],
    }

    async def run_command(*_):
        return json.dumps(payload), ""

    monkeypatch.setattr(ytdlp, "run_command", run_command)
    title, thumbnail, duration, author, description, platform, view_count, formats, sources = await ytdlp.inspect("https://example.com/video")

    assert (title, thumbnail, duration) == ("Video title", "https://example.com/cover.jpg", 90)
    assert (author, description, platform, view_count) == ("Creator", "Video description", "Bilibili", 6789)
    assert [item.id for item in formats] == ["1080"]
    assert set(sources) == {"1080"}


@pytest.mark.asyncio
async def test_inspect_uses_bilibili_public_metadata_when_extractor_omits_it(monkeypatch):
    payload = {
        "title": "Video title",
        "formats": [{"format_id": "1080", "height": 1080, "width": 1920, "ext": "mp4", "vcodec": "avc1", "url": "https://example.com/video.mp4"}],
    }

    async def run_command(*_):
        return json.dumps(payload), ""

    async def bilibili_metadata(url):
        assert url == "https://www.bilibili.com/video/BV1mAAmzqEfP"
        return {"author": "程序员鱼皮", "description": "公开视频简介", "view_count": 90756}

    monkeypatch.setattr(ytdlp, "run_command", run_command)
    monkeypatch.setattr(ytdlp, "_bilibili_metadata", bilibili_metadata)

    _, _, _, author, description, platform, view_count, _, _ = await ytdlp.inspect("https://www.bilibili.com/video/BV1mAAmzqEfP")

    assert (author, description, platform, view_count) == ("程序员鱼皮", "公开视频简介", "Bilibili", 90756)
