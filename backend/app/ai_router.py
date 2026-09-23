import asyncio
import json
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from .ai_config import ai_settings
from .ai_deepseek import answer_question, generate_summary, stream_summary_markdown, translate_cues
from .ai_models import AnswerResponse, QuestionRequest, SubtitleTracksResponse, SummaryRequest, SummaryTaskResponse, TaskStatus, TranscriptCue, TranscriptResponse, TranslationRequest, TranslationResponse
from .ai_store import AiMemoryStore, AiSummaryTask
from .ai_subtitles import ResolvedTrack, discover_tracks, fetch_transcript, subtitles_to_srt, subtitles_to_txt
from .security import safe_filename
from .store import now
from .auth import CurrentUser, require_csrf, require_user
from .entitlements import consume_ai_summary, require_ai_summary_quota, require_vip

router = APIRouter(prefix="/api/v1/ai", tags=["ai-learning"])
ai_store = AiMemoryStore(ai_settings.ai_ttl_seconds)
ai_semaphore = asyncio.Semaphore(ai_settings.ai_max_concurrent_tasks)
_tracks: dict[str, list[ResolvedTrack]] = {}
# 已完成总结的复用缓存：key = "视频地址|字幕轨道"，值 = (写入时间, 已完成任务)
# 命中时直接复用结果（不再转写、不再调大模型），但业务上仍然扣一次额度。
_summary_cache: dict[str, tuple[object, AiSummaryTask]] = {}
# 字幕/转录内容缓存：避免同一视频反复触发语音转写（转写最耗时）
_transcript_cache: dict[str, tuple[object, list[TranscriptCue]]] = {}


def _content_key(source_url: str, subtitle_id: str) -> str:
    return f"{source_url}|{subtitle_id}"


def _cache_fresh(stamp: object) -> bool:
    return now() - stamp < ai_store.ttl


async def _cues_for(source_url: str, track: ResolvedTrack) -> list[TranscriptCue]:
    """取字幕/转录内容，命中缓存就直接复用（语音转写很贵，尽量只做一次）。"""
    key = _content_key(source_url, track.public.id)
    cached = _transcript_cache.get(key)
    if cached and _cache_fresh(cached[0]):
        return cached[1]
    cues = await fetch_transcript(track)
    _transcript_cache[key] = (now(), cues)
    return cues


def _vip(request: Request, user: CurrentUser) -> None:
    require_vip(request.app.state.database, user.id)


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


async def _run_summary(task: AiSummaryTask, title: str, database, source_url: str) -> None:
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
            # 生成成功后写入复用缓存，下次解析同一个视频可直接取用
            _summary_cache[_content_key(source_url, task.subtitle_id)] = (now(), task)
            # 生成成功后才扣配额；失败分支不会走到这里，所以"失败不扣次数"
            try:
                consume_ai_summary(database, task.user_id)
            except Exception:
                logging.getLogger(__name__).warning("AI 总结配额扣减失败", exc_info=True)
        except HTTPException as exc:
            task.error = exc.detail
            task.status = TaskStatus.failed
        except Exception:
            task.error = "AI 总结生成失败，请稍后重试"
            task.status = TaskStatus.failed
        finally:
            task.stream_done = True


@router.get("/inspections/{inspection_id}/subtitle-tracks", response_model=SubtitleTracksResponse)
async def subtitle_tracks(request: Request, inspection_id: str, user: CurrentUser = Depends(require_user)):
    await ai_store.cleanup()
    tracks = await _get_tracks(request, inspection_id)
    return SubtitleTracksResponse(tracks=[item.public for item in tracks])


@router.get("/inspections/{inspection_id}/subtitle-tracks/{subtitle_id}", response_model=TranscriptResponse)
async def transcript(request: Request, inspection_id: str, subtitle_id: str, user: CurrentUser = Depends(require_user)):
    inspection = _inspection(request, inspection_id)
    tracks = await _get_tracks(request, inspection_id)
    track = next((item for item in tracks if item.public.id == subtitle_id), None)
    if not track:
        raise HTTPException(404, "字幕轨道不存在")
    return TranscriptResponse(track=track.public, cues=await _cues_for(inspection.source_url, track))


@router.get("/inspections/{inspection_id}/subtitle-tracks/{subtitle_id}/download")
async def download_subtitle(request: Request, inspection_id: str, subtitle_id: str, format: str = Query(default="srt", pattern="^(srt|txt)$"), user: CurrentUser = Depends(require_user)):
    _vip(request, user)
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
            "Content-Disposition": f"attachment; filename=\"subtitles.{extension}\"; filename*=UTF-8''{encoded_filename}",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/summaries", response_model=SummaryTaskResponse)
async def create_summary(request: Request, payload: SummaryRequest, user: CurrentUser = Depends(require_csrf)):
    await ai_store.cleanup()
    # 顺手清理过期缓存，避免长时间运行后内存无限增长
    for cache in (_summary_cache, _transcript_cache):
        for key in [item for item, value in cache.items() if not _cache_fresh(value[0])]:
            cache.pop(key, None)
    inspection = _inspection(request, payload.inspection_id)
    # 命中复用缓存：跳过字幕获取与大模型生成，直接返回已有结果；
    # 但按业务规则仍然扣一次额度（每次解析都算一次使用）。
    cached = _summary_cache.get(_content_key(inspection.source_url, payload.subtitle_id))
    if cached and _cache_fresh(cached[0]) and cached[1].result:
        require_ai_summary_quota(request.app.state.database, user.id)
        consume_ai_summary(request.app.state.database, user.id)
        reused = AiSummaryTask(
            ai_store.token(), inspection.id, payload.subtitle_id, cached[1].source_language,
            cues=cached[1].cues, user_id=user.id,
        )
        reused.status = TaskStatus.completed
        reused.progress = 100
        reused.result = cached[1].result
        reused.stream_text = cached[1].stream_text
        reused.stream_done = True
        ai_store.tasks[reused.id] = reused
        return _task_response(reused)
    tracks = await _get_tracks(request, payload.inspection_id)
    track = next((item for item in tracks if item.public.id == payload.subtitle_id), None)
    if not track:
        raise HTTPException(404, "字幕轨道不存在")
    cues = await _cues_for(inspection.source_url, track)
    # 2026-09 业务规则：这里只"检查"配额有没有用完（免费用户每日 3 次，VIP 不限次）；
    # 真正的扣减发生在总结生成成功之后，失败不扣次数。
    require_ai_summary_quota(request.app.state.database, user.id)
    task = AiSummaryTask(ai_store.token(), inspection.id, track.public.id, track.public.language, cues=cues, user_id=user.id)
    ai_store.tasks[task.id] = task
    asyncio.create_task(_run_summary(task, inspection.title, request.app.state.database, inspection.source_url))
    return _task_response(task)


@router.get("/summaries/{summary_id}", response_model=SummaryTaskResponse)
async def get_summary(summary_id: str, request: Request, user: CurrentUser = Depends(require_user)):
    await ai_store.cleanup()
    task = ai_store.tasks.get(summary_id)
    if not task:
        raise HTTPException(404, "AI 总结任务不存在或已过期")
    if task.user_id != user.id:
        raise HTTPException(404, "AI 总结任务不存在或已过期")
    return _task_response(task)


@router.get("/summaries/{summary_id}/stream")
async def stream_summary(summary_id: str, request: Request, user: CurrentUser = Depends(require_user)):
    task = ai_store.tasks.get(summary_id)
    if not task:
        raise HTTPException(404, "AI summary task does not exist or has expired")
    if task.user_id != user.id:
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
async def ask_question(summary_id: str, payload: QuestionRequest, request: Request, user: CurrentUser = Depends(require_csrf)):
    _vip(request, user)
    await ai_store.cleanup()
    task = ai_store.tasks.get(summary_id)
    if not task:
        raise HTTPException(404, "AI 总结任务不存在或已过期")
    if task.user_id != user.id:
        raise HTTPException(404, "AI 总结任务不存在或已过期")
    if task.status != TaskStatus.completed or not task.result:
        raise HTTPException(409, "请在 AI 总结完成后再提问")
    answer = await answer_question(payload.question, task.result, task.cues)
    task.questions.append((payload.question, answer))
    return answer


@router.delete("/summaries/{summary_id}/questions", status_code=204)
async def clear_questions(summary_id: str, request: Request, user: CurrentUser = Depends(require_csrf)):
    _vip(request, user)
    task = ai_store.tasks.get(summary_id)
    if not task:
        raise HTTPException(404, "AI 总结任务不存在或已过期")
    if task.user_id != user.id:
        raise HTTPException(404, "AI 总结任务不存在或已过期")
    task.questions.clear()


@router.post("/inspections/{inspection_id}/subtitle-tracks/{subtitle_id}/translations", response_model=TranslationResponse)
async def translate_subtitle(
    request: Request,
    inspection_id: str,
    subtitle_id: str,
    payload: TranslationRequest,
    user: CurrentUser = Depends(require_csrf),
):
    _vip(request, user)
    tracks = await _get_tracks(request, inspection_id)
    track = next((item for item in tracks if item.public.id == subtitle_id), None)
    if not track:
        raise HTTPException(404, "字幕轨道不存在")
    cues = await fetch_transcript(track)
    translated = await translate_cues(cues, payload.target_language)
    return TranslationResponse(source_language=track.public.language, target_language=payload.target_language, cues=translated)
