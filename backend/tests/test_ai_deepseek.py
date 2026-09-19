import pytest
from fastapi import HTTPException

from app.ai_config import ai_settings
from app.ai_deepseek import DeepSeekClient, answer_question, build_mermaid, generate_summary
from app.ai_models import MindMapNode, SummaryResult, TranscriptCue


@pytest.mark.asyncio
async def test_model_validation_accepts_configured_flash(monkeypatch):
    monkeypatch.setattr(ai_settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(ai_settings, "deepseek_model", "deepseek-flash")

    async def request(self, method, path, payload=None):
        assert method == "GET"
        assert path == "models"
        return {"data": [{"id": "deepseek-flash"}]}

    monkeypatch.setattr(DeepSeekClient, "_request", request)
    await DeepSeekClient().validate_model()


def test_ai_client_reports_missing_key_without_affecting_app_startup(monkeypatch):
    monkeypatch.setattr(ai_settings, "deepseek_api_key", "")
    with pytest.raises(HTTPException) as error:
        DeepSeekClient()
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_model_validation_rejects_unavailable_model(monkeypatch):
    monkeypatch.setattr(ai_settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(ai_settings, "deepseek_model", "deepseek-flash")

    async def request(self, method, path, payload=None):
        return {"data": []}

    monkeypatch.setattr(DeepSeekClient, "_request", request)
    with pytest.raises(HTTPException, match="deepseek-flash"):
        await DeepSeekClient().validate_model()


@pytest.mark.asyncio
async def test_json_completion_retries_once_after_invalid_json(monkeypatch):
    monkeypatch.setattr(ai_settings, "deepseek_api_key", "test-key")
    calls = []

    async def request(self, method, path, payload=None):
        calls.append(payload)
        content = "not json" if len(calls) == 1 else '{"summary":"ok"}'
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(DeepSeekClient, "_request", request)
    assert await DeepSeekClient().json_completion("system", "user") == {"summary": "ok"}
    assert len(calls) == 2
    assert "合法 JSON" in calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_summary_adds_source_language_after_model_validation(monkeypatch):
    monkeypatch.setattr(ai_settings, "deepseek_api_key", "test-key")

    async def validate(self):
        return None

    async def completion(self, system, user):
        return {"overview": "概览", "outline": [{"title": "章节", "summary": "内容"}], "key_points": [{"title": "要点", "detail": "细节"}], "keywords": ["关键词"], "mindmap": {"title": "根", "children": []}}

    monkeypatch.setattr(DeepSeekClient, "validate_model", validate)
    monkeypatch.setattr(DeepSeekClient, "json_completion", completion)
    result = await generate_summary("视频", "zh-CN", [TranscriptCue(start=0, end=1, text="字幕")])
    assert result.source_language == "zh-CN"
    assert result.mermaid.startswith("mindmap")


@pytest.mark.asyncio
async def test_question_adds_relevant_citation_when_model_returns_none(monkeypatch):
    monkeypatch.setattr(ai_settings, "deepseek_api_key", "test-key")
    summary = SummaryResult(overview="概览", outline=[{"title": "章节", "summary": "内容"}], key_points=[{"title": "要点", "detail": "细节"}], keywords=["关键词"], mindmap=MindMapNode(title="根"))

    async def validate(self):
        return None

    async def completion(self, system, user):
        return {"answer": "答案", "citations": []}

    monkeypatch.setattr(DeepSeekClient, "validate_model", validate)
    monkeypatch.setattr(DeepSeekClient, "json_completion", completion)
    answer = await answer_question("问题", summary, [TranscriptCue(start=3, end=5, text="字幕证据")])
    assert [citation.model_dump() for citation in answer.citations] == [{"start": 3.0, "end": 5.0}]


def test_mermaid_escapes_untrusted_node_text():
    graph = build_mermaid(MindMapNode(title='根[节点]', children=[MindMapNode(title='子"节点')]))
    assert "[" not in graph
    assert '"' not in graph
    assert "mindmap" in graph
