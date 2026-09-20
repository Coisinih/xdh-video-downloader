import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from .config import settings
from .models import DownloadMode, DownloadRequest, DownloadResponse, InspectionRequest, InspectionResponse, TaskResponse
from .security import normalize_video_url, safe_filename, validate_source_url
from .store import Delivery, Inspection, MemoryStore, Task, now
from . import ytdlp
from .ai_router import router as ai_router

store = MemoryStore(settings.ttl_seconds)
download_semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="VidNest API", version="1.0.0", lifespan=lifespan)
app.state.vidnest_store = store
app.include_router(ai_router)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/inspections", response_model=InspectionResponse)
async def create_inspection(payload: InspectionRequest):
    await store.cleanup()
    source_url = normalize_video_url(str(payload.url))
    validate_source_url(source_url)
    title, thumbnail, duration, author, description, platform, view_count, formats, direct_sources = await ytdlp.inspect(source_url)
    inspection = Inspection(
        store.token(), source_url, title, thumbnail, duration, formats,
        author=author, description=description, platform=platform, view_count=view_count,
        direct_sources=direct_sources,
    )
    store.inspections[inspection.id] = inspection
    return InspectionResponse(
        inspection_id=inspection.id, title=title, thumbnail=thumbnail, duration=duration,
        author=author, description=description, platform=platform, view_count=view_count,
        formats=formats, expires_at=inspection.created_at + store.ttl,
    )


def get_inspection(inspection_id: str) -> Inspection:
    inspection = store.inspections.get(inspection_id)
    if not inspection or inspection.created_at + store.ttl <= now():
        raise HTTPException(404, "解析结果已过期，请重新解析")
    return inspection


async def run_download(task: Task, inspection: Inspection) -> None:
    async with download_semaphore:
        task.status = "downloading"
        task.progress = 1
        directory = settings.download_dir / task.id
        try:
            async def progress(value: float):
                task.progress = value
            file_path = await ytdlp.download(inspection.source_url, task.format_id, directory, inspection.title, progress)
            if file_path.stat().st_size > settings.max_file_size_mb * 1024 * 1024:
                file_path.unlink(missing_ok=True)
                raise HTTPException(413, "文件超过服务端大小限制")
            delivery = Delivery(store.token(), file_path=file_path, filename=safe_filename(file_path.name))
            store.deliveries[delivery.token] = delivery
            task.status = "completed"
            task.progress = 100
            task.delivery_token = delivery.token
            task.filename = delivery.filename
        except HTTPException as exc:
            task.status = "failed"
            task.error = exc.detail
        except Exception:
            task.status = "failed"
            task.error = "下载失败，请稍后重试"


@app.get("/api/v1/thumbnails/{inspection_id}")
async def thumbnail(inspection_id: str):
    inspection = get_inspection(inspection_id)
    if not inspection.thumbnail:
        raise HTTPException(404, "Thumbnail is unavailable")
    validate_source_url(inspection.thumbnail)
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        response = await client.get(inspection.thumbnail, headers={"Referer": inspection.source_url})
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/jpeg").split(";", 1)[0]
        return Response(content=response.content, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})

@app.post("/api/v1/downloads", response_model=DownloadResponse)
async def create_download(payload: DownloadRequest):
    await store.cleanup()
    inspection = get_inspection(payload.inspection_id)
    selected = next((item for item in inspection.formats if item.id == payload.format_id), None)
    if not selected:
        raise HTTPException(422, "所选格式不属于本次解析结果")
    if payload.mode == DownloadMode.direct:
        source_url, source_headers = inspection.direct_sources[payload.format_id]
        validate_source_url(source_url)
        delivery = Delivery(store.token(), source_url=source_url, filename=f"{safe_filename(inspection.title)}.{selected.ext}", headers_required=bool(source_headers), source_headers=source_headers)
        store.deliveries[delivery.token] = delivery
        return DownloadResponse(mode=payload.mode, delivery_url=f"/api/v1/deliveries/{delivery.token}")
    task = Task(store.token(), inspection.id, payload.format_id)
    store.tasks[task.id] = task
    asyncio.create_task(run_download(task, inspection))
    return DownloadResponse(mode=payload.mode, task_id=task.id)


@app.get("/api/v1/downloads/{task_id}", response_model=TaskResponse)
async def get_download(task_id: str):
    task = store.tasks.get(task_id)
    if not task or task.created_at + store.ttl <= now():
        raise HTTPException(404, "下载任务不存在或已过期")
    return TaskResponse(id=task.id, status=task.status, progress=task.progress, error=task.error, filename=task.filename, delivery_url=f"/api/v1/deliveries/{task.delivery_token}" if task.delivery_token else None)


@app.get("/api/v1/deliveries/{token}")
async def deliver(token: str, request: Request):
    delivery = store.deliveries.get(token)
    if not delivery or delivery.created_at + store.ttl <= now():
        raise HTTPException(404, "下载链接已过期")
    if delivery.file_path:
        return FileResponse(delivery.file_path, filename=delivery.filename, media_type="application/octet-stream")
    if not delivery.headers_required:
        return RedirectResponse(delivery.source_url, status_code=302)

    headers = dict(delivery.source_headers)
    if request.headers.get("range"):
        headers["Range"] = request.headers["range"]
    client = httpx.AsyncClient(follow_redirects=True, timeout=settings.download_timeout_seconds)
    upstream = await client.send(client.build_request("GET", delivery.source_url, headers=headers), stream=True)
    try:
        upstream.raise_for_status()
    except httpx.HTTPStatusError as exc:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(502, "上游媒体服务拒绝下载请求") from exc

    async def body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    encoded_filename = quote(delivery.filename, safe="")
    response_headers = {"Content-Disposition": f"attachment; filename=\"video.mp4\"; filename*=UTF-8''{encoded_filename}", "Accept-Ranges": "bytes"}
    for name in ("content-length", "content-range"):
        if upstream.headers.get(name):
            response_headers["-".join(part.capitalize() for part in name.split("-"))] = upstream.headers[name]
    return StreamingResponse(body(), status_code=upstream.status_code, media_type=upstream.headers.get("content-type", "application/octet-stream"), headers=response_headers)
