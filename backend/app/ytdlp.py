import asyncio
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException

from .config import settings
from .models import FormatInfo
from .security import safe_filename

YTDLP_SOURCE = Path(__file__).resolve().parents[1] / "vendor" / "yt-dlp"
PUBLIC_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_youtube_url(url: str) -> bool:
    host = _host(url)
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def is_douyin_url(url: str) -> bool:
    host = _host(url)
    return host in {"douyin.com", "iesdouyin.com"} or host.endswith((".douyin.com", ".iesdouyin.com"))


def is_xiaohongshu_url(url: str) -> bool:
    host = _host(url)
    return host in {"xiaohongshu.com", "xhslink.com"} or host.endswith((".xiaohongshu.com", ".xhslink.com"))


def ytdlp_command(*arguments: str, youtube: bool = False) -> list[str]:
    """Build a hermetic yt-dlp command.

    YouTube now delegates parts of its public-player JavaScript challenge to
    yt-dlp-ejs.  The official remote component is loaded only for YouTube;
    other extractors keep the original, dependency-free command path.
    """
    extras = ["--js-runtimes", "node", "--remote-components", "ejs:npm"] if youtube else []
    return [sys.executable, "-m", "yt_dlp", *extras, *arguments]


def ytdlp_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(YTDLP_SOURCE) + os.pathsep + environment.get("PYTHONPATH", "")
    return environment


async def run_command(args: list[str], timeout: int, source_url: str = "") -> tuple[str, str]:
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=ytdlp_environment())
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise HTTPException(504, "Video processing timed out")
    if process.returncode != 0:
        detail = stderr.decode(errors="replace")
        if "Fresh cookies" in detail and "Douyin" in detail:
            raise HTTPException(403, "抖音当前拒绝服务器的公开访问，未使用 Cookie 或验证码绕过，暂时无法解析该视频。")
        if is_youtube_url(source_url) and ("not a bot" in detail.lower() or "sign in to confirm" in detail.lower()):
            raise HTTPException(403, "YouTube 要求确认非机器人。服务已启用官方 EJS 组件，但该公开视频仍被平台风控拦截。")
        if is_xiaohongshu_url(source_url) and "No video formats found" in detail:
            raise HTTPException(403, "小红书未向当前服务器返回公开视频流，未使用 Cookie 或验证码绕过，暂时无法解析该视频。")
        raise HTTPException(422, "无法解析该公开视频，请确认链接有效且平台允许公开访问。")
    return stdout.decode(errors="replace"), stderr.decode(errors="replace")


def to_formats(payload: dict) -> tuple[list[FormatInfo], dict[str, tuple[str, dict[str, str]]]]:
    """Return one dependable stream for each commonly used video resolution.

    Extractors commonly expose the same resolution many times for different
    codecs, protocols and bitrates.  Showing every raw stream makes the
    download choice needlessly confusing, so the public contract deliberately
    exposes one dependable choice per supported resolution. Entitlement
    filtering happens at the API boundary so the stored inspection can be
    reused if the user upgrades without trusting a client-provided format.
    """
    supported_heights = (4320, 2160, 1440, 1080, 720, 480, 360)
    candidates: dict[int, dict] = {}
    sources: dict[str, tuple[str, dict[str, str]]] = {}
    for item in payload.get("formats", []):
        if item.get("vcodec") == "none" or not item.get("url"):
            continue
        width = item.get("width")
        video_height = item.get("height")
        # Portrait videos report their long side as height, so 1080x1920 would
        # never match a landscape tier list. Classify on the shorter side, which
        # is the dimension viewers name resolutions by in either orientation.
        height = min(width, video_height) if width and video_height else video_height
        if height not in supported_heights:
            continue
        format_id = str(item.get("format_id", ""))
        if not format_id:
            continue
        previous = candidates.get(height)
        # Prefer MP4 and muxed streams, then choose the larger bitrate/file.
        # The final format-id comparison makes the result deterministic when
        # metadata is otherwise identical.
        def score(value: dict) -> tuple[int, int, float, int, str]:
            return (
                int(str(value.get("ext", "")).lower() == "mp4"),
                int(value.get("acodec") not in {None, "none"}),
                float(value.get("tbr") or 0),
                int(value.get("filesize") or value.get("filesize_approx") or 0),
                str(value.get("format_id", "")),
            )
        if previous is None or score(item) > score(previous):
            candidates[height] = item

    formats: list[FormatInfo] = []
    for height in supported_heights:
        item = candidates.get(height)
        if not item:
            continue
        format_id = str(item["format_id"])
        resolution = f"{item.get('width')}x{item.get('height')}" if item.get("width") else f"{height}P"
        ext = str(item.get("ext") or "mp4")
        has_audio = item.get("acodec") not in {None, "none"}
        formats.append(FormatInfo(id=format_id, label=f"{height}P", ext=ext, resolution=resolution, filesize=item.get("filesize") or item.get("filesize_approx"), codec=item.get("vcodec"), direct_available=has_audio))
        headers = {str(key): str(value) for key, value in (item.get("http_headers") or {}).items() if str(key).lower() in {"referer", "user-agent", "origin"}}
        # A browser redirect cannot merge adaptive video with its separate audio
        # track. Such choices are deliberately delivered by the server instead.
        if has_audio:
            sources[format_id] = (str(item["url"]), headers)
    return formats, sources


async def resolve_public_url(url: str) -> str:
    """Expand known public share links without accepting a client Cookie.

    Redirect targets are checked before every request so a public short URL
    cannot pivot the service into a private network request.
    """
    from .security import normalize_video_url, validate_source_url

    current = normalize_video_url(url)
    if _host(current) not in {"v.douyin.com", "xhslink.com", "www.xhslink.com"}:
        return current
    async with httpx.AsyncClient(headers=PUBLIC_BROWSER_HEADERS, follow_redirects=False, timeout=15) as client:
        for _ in range(5):
            validate_source_url(current)
            async with client.stream("GET", current) as response:
                if response.status_code not in {301, 302, 303, 307, 308}:
                    return normalize_video_url(current)
                location = response.headers.get("location")
            if not location:
                return normalize_video_url(current)
            current = urljoin(current, location)
    return normalize_video_url(current)


def _douyin_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    for value in (parsed.path, parsed.query):
        match = re.search(r"(?<!\d)(\d{15,24})(?!\d)", value)
        if match:
            return match.group(1)
    return None


def _douyin_result(item: dict, video_id: str) -> tuple[str, str | None, int | None, str | None, str | None, str | None, int | None, list[FormatInfo], dict[str, tuple[str, dict[str, str]]]] | None:
    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    play_urls = ((video.get("play_addr") or {}).get("url_list") or []) if isinstance(video, dict) else []
    if not play_urls or not isinstance(play_urls[0], str):
        return None
    height = _optional_int(video.get("height")) or 720
    width = _optional_int(video.get("width"))
    title = _optional_text(item.get("desc")) or f"抖音视频_{video_id}"
    author_data = item.get("author") if isinstance(item.get("author"), dict) else {}
    statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
    cover_urls = ((video.get("cover") or {}).get("url_list") or []) if isinstance(video, dict) else []
    duration_ms = _optional_int(video.get("duration"))
    duration = duration_ms // 1000 if duration_ms and duration_ms > 1000 else duration_ms
    format_id = f"douyin-{video_id}"
    media_url = play_urls[0].replace("playwm", "play")
    headers = {**PUBLIC_BROWSER_HEADERS, "Referer": "https://www.douyin.com/"}
    format_info = FormatInfo(
        id=format_id,
        label=f"{height}P",
        ext="mp4",
        resolution=f"{width}x{height}" if width else f"{height}P",
        filesize=None,
        codec="h264",
        direct_available=True,
    )
    return (
        title,
        cover_urls[0] if cover_urls and isinstance(cover_urls[0], str) else None,
        duration,
        _optional_text(author_data.get("nickname")),
        _optional_text(item.get("desc")),
        "Douyin",
        _optional_int(statistics.get("play_count") or statistics.get("digg_count")),
        [format_info],
        {format_id: (media_url, headers)},
    )


async def _douyin_public_inspect(url: str):
    """Try Douyin's public legacy metadata endpoint, without challenge solving.

    This is intentionally only an opportunistic public-data adapter. If
    Douyin asks for encrypted anti-bot parameters or a login session, the
    caller falls back to yt-dlp and returns an explicit availability error.
    """
    video_id = _douyin_video_id(url)
    if not video_id:
        return None
    headers = {**PUBLIC_BROWSER_HEADERS, "Referer": "https://www.douyin.com/"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=15) as client:
            response = await client.get("https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/", params={"item_ids": video_id})
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    items = payload.get("item_list") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    return _douyin_result(items[0], video_id)


async def inspect(url: str) -> tuple[str, str | None, int | None, str | None, str | None, str | None, int | None, list[FormatInfo], dict[str, tuple[str, dict[str, str]]]]:
    if is_douyin_url(url):
        public_result = await _douyin_public_inspect(url)
        if public_result:
            return public_result
    stdout, _ = await run_command(
        ytdlp_command("--no-playlist", "--skip-download", "--dump-single-json", url, youtube=is_youtube_url(url)),
        settings.inspection_timeout_seconds,
        url,
    )
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Invalid video metadata") from exc
    formats, sources = to_formats(data)
    if not formats:
        raise HTTPException(422, "No downloadable video formats found")
    duration = _optional_int(data.get("duration"))
    view_count = _optional_int(data.get("view_count"))
    author = _optional_text(data.get("uploader") or data.get("channel") or data.get("creator"))
    description = _optional_text(data.get("description"))
    platform = _optional_text(data.get("extractor_key") or data.get("extractor"))
    # Some Bilibili extractor responses contain the download formats but omit
    # creator, description and statistics. The public view endpoint carries
    # those display fields and does not require a user cookie.
    bilibili = await _bilibili_metadata(url)
    if bilibili:
        author = author or bilibili["author"]
        description = description or bilibili["description"]
        view_count = view_count if view_count is not None else bilibili["view_count"]
        platform = "Bilibili"
    return data.get("title") or "Untitled video", data.get("thumbnail"), duration, author, description, platform, view_count, formats, sources


async def _bilibili_metadata(url: str) -> dict[str, str | int | None] | None:
    host = (urlparse(url).hostname or "").lower()
    if host != "bilibili.com" and not host.endswith(".bilibili.com"):
        return None
    match = re.search(r"\b(BV[0-9A-Za-z]{10})\b", url, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": match.group(1)},
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
        return None
    data = payload["data"]
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
    stats = data.get("stat") if isinstance(data.get("stat"), dict) else {}
    return {
        "author": _optional_text(owner.get("name")),
        "description": _optional_text(data.get("desc")),
        "view_count": _optional_int(stats.get("view")),
    }


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def download(url: str, format_id: str, output_dir: Path, title: str, on_progress) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / f"{safe_filename(title)}.%(ext)s")
    selected_format = format_id if "+" in format_id else f"{format_id}+bestaudio/best"
    args = ytdlp_command("--no-playlist", "--no-warnings", "--newline", "-f", selected_format, "--merge-output-format", "mp4", "-o", output_template, url, youtube=is_youtube_url(url))
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=ytdlp_environment())
    percent = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
    try:
        while line := await asyncio.wait_for(process.stdout.readline(), settings.download_timeout_seconds):
            match = percent.search(line.decode(errors="ignore"))
            if match:
                await on_progress(float(match.group(1)))
        if await process.wait() != 0:
            raise HTTPException(422, "Video download failed")
    except TimeoutError:
        process.kill()
        await process.wait()
        raise HTTPException(504, "Video download timed out")
    files = [path for path in output_dir.iterdir() if path.is_file()]
    if not files:
        raise HTTPException(422, "Video download produced no file")
    return max(files, key=lambda path: path.stat().st_mtime)


async def download_public_media(source_url: str, headers: dict[str, str], output_dir: Path, title: str, on_progress) -> Path:
    """Save a previously inspected, muxed public media URL.

    The Douyin public adapter already supplies a video+audio MP4 URL. Running
    yt-dlp against the original share page again would discard that successful
    public result and can fail on a later anti-bot check, so server delivery
    streams the inspected source with its required public request headers.
    """
    from .security import validate_source_url

    validate_source_url(source_url)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{safe_filename(title)}.mp4"
    written = 0
    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=settings.download_timeout_seconds) as client:
            async with client.stream("GET", source_url) as response:
                response.raise_for_status()
                total = _optional_int(response.headers.get("content-length"))
                with destination.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        output.write(chunk)
                        written += len(chunk)
                        if total:
                            await on_progress(min(99.0, written / total * 100))
    except httpx.HTTPError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, "公开媒体源拒绝了服务端下载请求。") from exc
    if not written:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, "公开媒体源未返回可下载的视频数据。")
    await on_progress(100)
    return destination
