import asyncio
import re
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from .config import settings
from .models import BatchDownloadRequest, BatchDownloadResponse, BatchItemResponse, DownloadMode, DownloadRequest, DownloadResponse, InspectionRequest, InspectionResponse, TaskResponse
from .security import normalize_video_url, safe_filename, validate_source_url
from .store import BatchItem, BatchTask, Delivery, Inspection, MemoryStore, Task, now
from . import ytdlp
from .ai_router import router as ai_router
from .account_router import router as account_router
from .auth import CurrentUser, get_optional_user, require_csrf, require_user
from .billing import StripeGateway, router as billing_router
from .database import Database
from .entitlements import consume_anonymous_download, consume_download, membership_for, require_vip

store = MemoryStore(settings.ttl_seconds)
download_semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    app.state.database.migrate()
    yield


app = FastAPI(title="VidNest API", version="1.0.0", lifespan=lifespan)
app.state.vidnest_store = store
app.state.database = Database(settings.database_path)
app.state.database.migrate()
app.state.billing_gateway = StripeGateway()
app.include_router(ai_router)
app.include_router(account_router)
app.include_router(billing_router)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/inspections", response_model=InspectionResponse)
async def create_inspection(payload: InspectionRequest, request: Request, user: CurrentUser | None = Depends(get_optional_user)):
    await store.cleanup()
    source_url = await ytdlp.resolve_public_url(normalize_video_url(str(payload.url)))
    validate_source_url(source_url)
    title, thumbnail, duration, author, description, platform, view_count, formats, direct_sources = await ytdlp.inspect(source_url)
    inspection = Inspection(
        store.token(), source_url, title, thumbnail, duration, formats,
        author=author, description=description, platform=platform, view_count=view_count,
        direct_sources=direct_sources,
    )
    store.inspections[inspection.id] = inspection
    vip = bool(user and membership_for(request.app.state.database, user.id).is_vip)
    visible_formats = formats if vip else [item for item in formats if _format_height(item) <= settings.free_max_height]
    return InspectionResponse(
        inspection_id=inspection.id, title=title, thumbnail=thumbnail, duration=duration,
        author=author, description=description, platform=platform, view_count=view_count,
        formats=visible_formats, expires_at=inspection.created_at + store.ttl,
    )


def _format_height(item) -> int:
    for value in (item.resolution, item.label):
        if value:
            match = re.search(r"(4320|2160|1440|1080|720|480|360)", str(value))
            if match:
                return int(match.group(1))
    return 0


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
            source = inspection.direct_sources.get(task.format_id)
            if ytdlp.is_douyin_url(inspection.source_url) and source:
                file_path = await ytdlp.download_public_media(source[0], source[1], directory, inspection.title, progress)
            else:
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
async def create_download(
    payload: DownloadRequest,
    request: Request,
    user: CurrentUser | None = Depends(get_optional_user),
    request_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
):
    await store.cleanup()
    inspection = get_inspection(payload.inspection_id)
    selected = next((item for item in inspection.formats if item.id == payload.format_id), None)
    if not selected:
        raise HTTPException(422, "所选格式不属于本次解析结果")
    vip = bool(user and membership_for(request.app.state.database, user.id).is_vip)
    if not vip and _format_height(selected) > settings.free_max_height:
        raise HTTPException(403, "免费版最高支持 720P，开通 VIP 可下载 4K / 8K")
    safe_request_key = request_key if request_key and 16 <= len(request_key) <= 100 else store.token()
    if user:
        # 登录用户（含免费用户）不限次数下载
        consume_download(request.app.state.database, user.id, safe_request_key)
    else:
        # 未登录用户每天有免费额度（默认 5 次）
        client_address = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
        consume_anonymous_download(request.app.state.database, client_address, safe_request_key)
    if payload.mode == DownloadMode.direct and selected.direct_available:
        source = inspection.direct_sources.get(payload.format_id)
        if not source:
            raise HTTPException(422, "该视频格式不支持浏览器直连下载，请使用服务端合并下载。")
        source_url, source_headers = source
        validate_source_url(source_url)
        delivery = Delivery(store.token(), source_url=source_url, filename=f"{safe_filename(inspection.title)}.{selected.ext}", headers_required=bool(source_headers), source_headers=source_headers)
        store.deliveries[delivery.token] = delivery
        return DownloadResponse(mode=payload.mode, delivery_url=f"/api/v1/deliveries/{delivery.token}")
    task = Task(store.token(), inspection.id, payload.format_id)
    store.tasks[task.id] = task
    asyncio.create_task(run_download(task, inspection))
    # Adaptive streams have no embedded audio. The public request is upgraded
    # transparently to a server task, where yt-dlp and ffmpeg merge both tracks.
    return DownloadResponse(mode=DownloadMode.server, task_id=task.id)


@app.get("/api/v1/downloads/{task_id}", response_model=TaskResponse)
async def get_download(task_id: str):
    task = store.tasks.get(task_id)
    if not task or task.created_at + store.ttl <= now():
        raise HTTPException(404, "下载任务不存在或已过期")
    return TaskResponse(id=task.id, status=task.status, progress=task.progress, error=task.error, filename=task.filename, delivery_url=f"/api/v1/deliveries/{task.delivery_token}" if task.delivery_token else None)


async def run_batch(batch: BatchTask) -> None:
    for item in batch.items:
        item.status = "inspecting"
        try:
            source_url = await ytdlp.resolve_public_url(normalize_video_url(item.url))
            validate_source_url(source_url)
            title, thumbnail, duration, author, description, platform, view_count, formats, direct_sources = await ytdlp.inspect(source_url)
            if not formats:
                raise HTTPException(422, "没有可下载格式")
            inspection = Inspection(
                store.token(), source_url, title, thumbnail, duration, formats,
                author=author, description=description, platform=platform, view_count=view_count,
                direct_sources=direct_sources,
            )
            store.inspections[inspection.id] = inspection
            selected = formats[0]
            task = Task(store.token(), inspection.id, selected.id)
            store.tasks[task.id] = task
            item.title = title
            item.task_id = task.id
            item.status = "queued"
            asyncio.create_task(run_download(task, inspection))
        except HTTPException as exc:
            item.status = "failed"
            item.error = str(exc.detail)
        except Exception:
            item.status = "failed"
            item.error = "视频解析失败"


def batch_response(batch: BatchTask) -> BatchDownloadResponse:
    items: list[BatchItemResponse] = []
    for item in batch.items:
        task = store.tasks.get(item.task_id) if item.task_id else None
        status = str(task.status.value if hasattr(task.status, "value") else task.status) if task else item.status
        items.append(BatchItemResponse(
            url=item.url,
            title=item.title,
            status=status,
            progress=task.progress if task else 0,
            error=(task.error if task else None) or item.error,
            delivery_url=f"/api/v1/deliveries/{task.delivery_token}" if task and task.delivery_token else None,
        ))
    terminal = all(item.status in {"completed", "failed"} for item in items)
    return BatchDownloadResponse(id=batch.id, status="completed" if terminal else "processing", items=items)


@app.post("/api/v1/batch-downloads", response_model=BatchDownloadResponse)
async def create_batch_download(payload: BatchDownloadRequest, request: Request, user: CurrentUser = Depends(require_csrf)):
    require_vip(request.app.state.database, user.id)
    unique_urls = list(dict.fromkeys(str(url) for url in payload.urls))
    if len(unique_urls) > settings.batch_max_items:
        raise HTTPException(422, f"单次最多批量下载 {settings.batch_max_items} 个视频")
    batch = BatchTask(store.token(), user.id, [BatchItem(url) for url in unique_urls])
    store.batch_tasks[batch.id] = batch
    asyncio.create_task(run_batch(batch))
    return batch_response(batch)


@app.get("/api/v1/batch-downloads/{batch_id}", response_model=BatchDownloadResponse)
async def get_batch_download(batch_id: str, request: Request, user: CurrentUser = Depends(require_user)):
    batch = store.batch_tasks.get(batch_id)
    if not batch or batch.user_id != user.id or batch.created_at + store.ttl <= now():
        raise HTTPException(404, "批量下载任务不存在或已过期")
    return batch_response(batch)


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
