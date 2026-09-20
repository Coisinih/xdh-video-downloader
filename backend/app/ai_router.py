import asyncio
import json
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from .ai_config import ai_settings
from .ai_deepseek import answer_question, generate_summary, stream_summary_markdown
from .ai_models import AnswerResponse, QuestionRequest, SubtitleTracksResponse, SummaryRequest, SummaryTaskResponse, TaskStatus, TranscriptResponse
from .ai_store import AiMemoryStore, AiSummaryTask
from .ai_subtitles import ResolvedTrack, discover_tracks, fetch_transcript, subtitles_to_srt, subtitles_to_txt
from .security import safe_filename
from .store import now

router = APIRouter(prefix="/api/v1/ai", tags=["ai-learning"])
ai_store = AiMemoryStore(ai_settings.ai_ttl_seconds)
ai_semaphore = asyncio.Semaphore(ai_settings.ai_max_concurrent_tasks)
_tracks: dict[str, list[ResolvedTrack]] = {}


def _inspection(request: Request, inspection_id: str):
    inspection = request.app.state.vidnest_store.inspections.get(inspection_id)
    if not inspection or inspection.created_at + request.app.state.vidnest_store.ttl <= now():
        raise HTTPException(404, "解析结果已过期，请重新解析视频")
    return inspection


async def _get_tracks(request: Request, inspection_id: str) -> list[ResolvedTrack]:
    _inspection(request, inspection_id)
    if inspection_id not in _tracks:
        _tracks[inspection_id] = await discover_tracks(_inspection(request, inspection_id).source_url)
    return _tracks[inspection_id]


def _task_response(task: AiSummaryTask) -> SummaryTaskResponse:
    return SummaryTaskResponse(
        id=task.id,
        status=task.status,
        progress=task.progress,
        error=task.error,
        result=task.result,
        stream_text=task.stream_text,
        created_at=task.created_at,
    )


async def _run_summary(task: AiSummaryTask, title: str) -> None:
    async with ai_semaphore:
        task.status = TaskStatus.processing
        task.progress = 25
        try:
            async for delta in stream_summary_markdown(title, task.source_language, task.cues):
                task.stream_text += delta
            task.progress = 75
            task.result = await generate_summary(title, task.source_language, task.cues)
            task.progress = 100
            task.status = TaskStatus.completed
        except HTTPException as exc:
            task.error = exc.detail
            task.status = TaskStatus.failed
        except Exception:
            task.error = "AI 总结生成失败，请稍后重试"
            task.status = TaskStatus.failed
        finally:
            task.stream_done = True


@router.get("/inspections/{inspection_id}/subtitle-tracks", response_model=SubtitleTracksResponse)
async def subtitle_tracks(request: Request, inspection_id: str):
    await ai_store.cleanup()
    tracks = await _get_tracks(request, inspection_id)
    return SubtitleTracksResponse(tracks=[item.public for item in tracks])


@router.get("/inspections/{inspection_id}/subtitle-tracks/{subtitle_id}", response_model=TranscriptResponse)
async def transcript(request: Request, inspection_id: str, subtitle_id: str):
    tracks = await _get_tracks(request, inspection_id)
    track = next((item for item in tracks if item.public.id == subtitle_id), None)
    if not track:
        raise HTTPException(404, "字幕轨道不存在")
    return TranscriptResponse(track=track.public, cues=await fetch_transcript(track))


@router.get("/inspections/{inspection_id}/subtitle-tracks/{subtitle_id}/download")
async def download_subtitle(request: Request, inspection_id: str, subtitle_id: str, format: str = Query(default="srt", pattern="^(srt|txt)$")):
    inspection = _inspection(request, inspection_id)
    tracks = await _get_tracks(request, inspection_id)
    track = next((item for item in tracks if item.public.id == subtitle_id), None)
    if not track:
        raise HTTPException(404, "字幕轨道不存在")
    extension = format.lower()
    filename = safe_filename(f"{inspection.title}.{track.public.language}.{extension}")
    encoded_filename = quote(filename, safe="")
    cues = await fetch_transcript(track)
    if extension == "txt":
        content = subtitles_to_txt(cues)
        media_type = "text/plain; charset=utf-8"
    else:
        content = subtitles_to_srt(cues)
        media_type = "application/x-subrip; charset=utf-8"
    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"subtitles.srt\"; filename*=UTF-8''{encoded_filename}",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/summaries", response_model=SummaryTaskResponse)
async def create_summary(request: Request, payload: SummaryRequest):
    await ai_store.cleanup()
    inspection = _inspection(request, payload.inspection_id)
    tracks = await _get_tracks(request, payload.inspection_id)
    track = next((item for item in tracks if item.public.id == payload.subtitle_id), None)
    if not track:
        raise HTTPException(404, "字幕轨道不存在")
    cues = await fetch_transcript(track)
    task = AiSummaryTask(ai_store.token(), inspection.id, track.public.id, track.public.language, cues=cues)
    ai_store.tasks[task.id] = task
    asyncio.create_task(_run_summary(task, inspection.title))
    return _task_response(task)


@router.get("/summaries/{summary_id}", response_model=SummaryTaskResponse)
async def get_summary(summary_id: str):
    await ai_store.cleanup()
    task = ai_store.tasks.get(summary_id)
    if not task:
        raise HTTPException(404, "AI 总结任务不存在或已过期")
    return _task_response(task)


@router.get("/summaries/{summary_id}/stream")
async def stream_summary(summary_id: str):
    task = ai_store.tasks.get(summary_id)
    if not task:
        raise HTTPException(404, "AI summary task does not exist or has expired")

    async def events():
        cursor = 0
        while True:
            if len(task.stream_text) > cursor:
                delta = task.stream_text[cursor:]
                cursor = len(task.stream_text)
                yield f"event: delta\ndata: {json.dumps({'text': delta}, ensure_ascii=False)}\n\n"
            if task.stream_done:
                if task.status == TaskStatus.completed:
                    yield "event: done\ndata: [DONE]\n\n"
                else:
                    yield f"event: error\ndata: {json.dumps({'message': task.error or 'Summary generation failed'}, ensure_ascii=False)}\n\n"
                return
            await asyncio.sleep(0.15)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/summaries/{summary_id}/questions", response_model=AnswerResponse)
async def ask_question(summary_id: str, payload: QuestionRequest):
    await ai_store.cleanup()
    task = ai_store.tasks.get(summary_id)
    if not task:
        raise HTTPException(404, "AI 总结任务不存在或已过期")
    if task.status != TaskStatus.completed or not task.result:
        raise HTTPException(409, "请在 AI 总结完成后再提问")
    answer = await answer_question(payload.question, task.result, task.cues)
    task.questions.append((payload.question, answer))
    return answer


@router.delete("/summaries/{summary_id}/questions", status_code=204)
async def clear_questions(summary_id: str):
    task = ai_store.tasks.get(summary_id)
    if not task:
        raise HTTPException(404, "AI 总结任务不存在或已过期")
    task.questions.clear()
