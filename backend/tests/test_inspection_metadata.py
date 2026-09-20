import httpx
import pytest

from app.main import app, store
from app.models import FormatInfo
from app.store import Inspection


@pytest.mark.asyncio
async def test_inspection_returns_optional_video_metadata(monkeypatch):
    formats = [FormatInfo(id="1080", label="1080P", ext="mp4", resolution="1920x1080")]

    async def inspect(_: str):
        return (
            "A video", "https://example.com/cover.jpg", 120,
            "Video author", "Video description", "Bilibili", 12345,
            formats, {"1080": ("https://cdn.example.com/video.mp4", {})},
        )

    monkeypatch.setattr("app.main.ytdlp.inspect", inspect)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/inspections", json={"url": "https://example.com/video"})

    assert response.status_code == 200
    body = response.json()
    assert body["author"] == "Video author"
    assert body["description"] == "Video description"
    assert body["platform"] == "Bilibili"
    assert body["view_count"] == 12345
    assert body["title"] == "A video"
    store.inspections.pop(body["inspection_id"], None)


def test_inspection_keeps_legacy_constructor_compatible():
    inspection = Inspection("id", "https://example.com/video", "Title", None, 60, [])

    assert inspection.author is None
    assert inspection.description is None
    assert inspection.platform is None
    assert inspection.view_count is None
