import asyncio

import httpx
import pytest

from app import ytdlp
from app import main
from app.main import app, store
from app.models import FormatInfo
from app.store import Inspection


def test_douyin_public_item_is_converted_to_a_muxed_direct_format():
    result = ytdlp._douyin_result({
        "desc": "Public Douyin video",
        "author": {"nickname": "Creator"},
        "statistics": {"play_count": 42},
        "video": {
            "width": 1080,
            "height": 1920,
            "duration": 15300,
            "play_addr": {"url_list": ["https://cdn.example.com/aweme/v1/playwm/?video_id=1"]},
            "cover": {"url_list": ["https://cdn.example.com/cover.jpg"]},
        },
    }, "1234567890123456789")

    assert result is not None
    title, thumbnail, duration, author, _, platform, views, formats, sources = result
    assert (title, thumbnail, duration, author, platform, views) == ("Public Douyin video", "https://cdn.example.com/cover.jpg", 15, "Creator", "Douyin", 42)
    assert formats[0].direct_available is True
    assert "playwm" not in sources[formats[0].id][0]
    assert sources[formats[0].id][1]["Referer"] == "https://www.douyin.com/"


@pytest.mark.asyncio
async def test_adaptive_format_creates_server_task_when_browser_requests_direct(monkeypatch):
    inspection = Inspection(
        "adaptive-inspection", "https://www.youtube.com/watch?v=video", "Video", None, 30,
        [FormatInfo(id="137", label="720P", ext="mp4", direct_available=False)],
    )
    store.inspections[inspection.id] = inspection

    async def no_download(*_):
        return None

    monkeypatch.setattr("app.main.run_download", no_download)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/downloads", headers={"X-Real-IP": "198.51.100.72", "X-Idempotency-Key": "adaptive-test-request-0001"}, json={"inspection_id": inspection.id, "format_id": "137", "mode": "direct"})

    assert response.status_code == 200
    assert response.json()["mode"] == "server"
    assert response.json()["task_id"]
    await asyncio.sleep(0)
    store.inspections.pop(inspection.id, None)


@pytest.mark.asyncio
async def test_muxed_format_keeps_browser_delivery(monkeypatch):
    inspection = Inspection(
        "muxed-inspection", "https://example.com/video", "Video", None, 30,
        [FormatInfo(id="muxed", label="720P", ext="mp4", direct_available=True)],
        direct_sources={"muxed": ("https://cdn.example.com/video.mp4", {})},
    )
    store.inspections[inspection.id] = inspection
    monkeypatch.setattr("app.main.validate_source_url", lambda _: None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/downloads", headers={"X-Real-IP": "198.51.100.71", "X-Idempotency-Key": "muxed-test-request-0001"}, json={"inspection_id": inspection.id, "format_id": "muxed", "mode": "direct"})

    assert response.status_code == 200
    assert response.json()["mode"] == "direct"
    assert response.json()["delivery_url"]
    store.inspections.pop(inspection.id, None)


@pytest.mark.asyncio
async def test_douyin_server_delivery_uses_the_successfully_inspected_public_media(monkeypatch, tmp_path):
    inspection = Inspection(
        "douyin-inspection", "https://www.douyin.com/video/1234567890123456789", "Public video", None, 30,
        [FormatInfo(id="douyin-1234567890123456789", label="720P", ext="mp4", direct_available=True)],
        direct_sources={"douyin-1234567890123456789": ("https://cdn.example.com/video.mp4", {"Referer": "https://www.douyin.com/"})},
    )
    task = main.Task("task", inspection.id, "douyin-1234567890123456789")
    monkeypatch.setattr(main.settings, "download_dir", tmp_path)

    async def public_download(url, headers, directory, title, progress):
        assert (url, headers["Referer"], title) == ("https://cdn.example.com/video.mp4", "https://www.douyin.com/", "Public video")
        directory.mkdir(parents=True)
        file_path = directory / "Public video.mp4"
        file_path.write_bytes(b"video")
        await progress(100)
        return file_path

    async def unexpected_ytdlp(*_):
        raise AssertionError("Douyin server delivery must use the inspected public media URL")

    monkeypatch.setattr("app.main.ytdlp.download_public_media", public_download)
    monkeypatch.setattr("app.main.ytdlp.download", unexpected_ytdlp)
    await main.run_download(task, inspection)

    assert task.status == "completed"
    assert task.delivery_token
