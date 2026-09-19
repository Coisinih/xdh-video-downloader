from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.ai_models import AnswerResponse, MindMapNode, SummaryResult, TaskStatus, TranscriptCue
from app.ai_router import ai_store, ask_question, clear_questions
from app.ai_store import AiSummaryTask


@pytest.mark.asyncio
async def test_question_requires_completed_summary():
    task = AiSummaryTask("waiting", "inspection", "track", "zh")
    ai_store.tasks[task.id] = task
    try:
        with pytest.raises(HTTPException) as error:
            await ask_question(task.id, type("Payload", (), {"question": "测试"})())
        assert error.value.status_code == 409
    finally:
        ai_store.tasks.pop(task.id, None)


@pytest.mark.asyncio
async def test_clear_questions_removes_only_current_session():
    result = SummaryResult(
        overview="概览", outline=[{"title": "章节", "summary": "内容"}], key_points=[{"title": "要点", "detail": "细节"}],
        keywords=["关键词"], mindmap=MindMapNode(title="根"), source_language="zh",
    )
    task = AiSummaryTask("complete", "inspection", "track", "zh", cues=[TranscriptCue(start=0, end=1, text="内容")], status=TaskStatus.completed, result=result)
    task.questions.append(("问题", AnswerResponse(answer="回答", created_at=datetime.now(UTC))))
    ai_store.tasks[task.id] = task
    try:
        await clear_questions(task.id)
        assert task.questions == []
    finally:
        ai_store.tasks.pop(task.id, None)
