import asyncio

import httpx
import pytest

from app.ai_models import AnswerResponse, MindMapNode, SubtitleTrack, SummaryResult, TranscriptCue
from app.ai_router import _tracks, ai_store
from app.ai_subtitles import ResolvedTrack
from app.main import app
from app.store import Inspection, now


@pytest.mark.asyncio
async def test_ai_learning_api_flow_with_mocked_external_services(monkeypatch):
    inspection = Inspection("ai-flow", "https://example.com/video", "学习视频", None, 60, [])
    app.state.vidnest_store.inspections[inspection.id] = inspection
    track = ResolvedTrack(SubtitleTrack(id="manual:zh-CN", language="zh-CN", label="zh-CN（字幕）", automatic=False), "https://example.com/subtitle.vtt", {})
    cues = [TranscriptCue(start=0, end=5, text="这是第一个知识点"), TranscriptCue(start=6, end=10, text="这是第二个知识点")]
    result = SummaryResult(
        overview="视频介绍了两个知识点。",
        outline=[{"title": "开场", "summary": "介绍主题"}],
        key_points=[{"title": "知识点", "detail": "需要掌握"}],
        keywords=["学习"],
        mindmap=MindMapNode(title="学习视频", children=[MindMapNode(title="知识点")]),
        mermaid="mindmap\n  学习视频\n    知识点",
        source_language="zh-CN",
    )

    async def discover(source_url):
        assert source_url == inspection.source_url
        return [track]

    async def transcript(resolved_track):
        assert resolved_track.public.id == track.public.id
        return cues

    async def summary(title, language, transcript_cues):
        assert title == inspection.title
        assert language == "zh-CN"
        assert transcript_cues == cues
        return result

    async def stream_summary(title, language, transcript_cues):
        yield "# 实时摘要\n"

    async def answer(question, summary_result, transcript_cues):
        assert question == "核心是什么？"
        assert summary_result is result
        return AnswerResponse(answer="两个知识点。", citations=[{"start": 0, "end": 5}], created_at=now())

    monkeypatch.setattr("app.ai_router.discover_tracks", discover)
    monkeypatch.setattr("app.ai_router.fetch_transcript", transcript)
    monkeypatch.setattr("app.ai_router.generate_summary", summary)
    monkeypatch.setattr("app.ai_router.stream_summary_markdown", stream_summary)
    monkeypatch.setattr("app.ai_router.answer_question", answer)
    _tracks.pop(inspection.id, None)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            tracks = await client.get(f"/api/v1/ai/inspections/{inspection.id}/subtitle-tracks")
            assert tracks.status_code == 200
            assert tracks.json()["tracks"][0]["id"] == track.public.id

            transcript_response = await client.get(f"/api/v1/ai/inspections/{inspection.id}/subtitle-tracks/manual:zh-CN")
            assert transcript_response.status_code == 200
            assert transcript_response.json()["cues"][0]["text"] == cues[0].text

            downloaded_subtitle = await client.get(f"/api/v1/ai/inspections/{inspection.id}/subtitle-tracks/manual:zh-CN/download")
            assert downloaded_subtitle.status_code == 200
            assert downloaded_subtitle.headers["content-type"].startswith("application/x-subrip")
            assert "attachment" in downloaded_subtitle.headers["content-disposition"]
            assert "00:00:00,000 --> 00:00:05,000" in downloaded_subtitle.text
            downloaded_text = await client.get(f"/api/v1/ai/inspections/{inspection.id}/subtitle-tracks/manual:zh-CN/download?format=txt")
            assert downloaded_text.status_code == 200
            assert downloaded_text.headers["content-type"].startswith("text/plain")
            assert downloaded_text.text == "这是第一个知识点\n这是第二个知识点\n"

            created = await client.post("/api/v1/ai/summaries", json={"inspection_id": inspection.id, "subtitle_id": track.public.id})
            assert created.status_code == 200
            summary_id = created.json()["id"]
            await asyncio.sleep(0)
            completed = await client.get(f"/api/v1/ai/summaries/{summary_id}")
            assert completed.status_code == 200
            assert completed.json()["status"] == "completed"
            assert completed.json()["result"]["mermaid"].startswith("mindmap")
            assert completed.json()["stream_text"] == "# 实时摘要\n"

            asked = await client.post(f"/api/v1/ai/summaries/{summary_id}/questions", json={"question": "核心是什么？"})
            assert asked.status_code == 200
            assert asked.json()["citations"] == [{"start": 0, "end": 5}]

            cleared = await client.delete(f"/api/v1/ai/summaries/{summary_id}/questions")
            assert cleared.status_code == 204
            assert ai_store.tasks[summary_id].questions == []
    finally:
        app.state.vidnest_store.inspections.pop(inspection.id, None)
        _tracks.pop(inspection.id, None)
        for task_id, task in list(ai_store.tasks.items()):
            if task.inspection_id == inspection.id:
                ai_store.tasks.pop(task_id, None)
