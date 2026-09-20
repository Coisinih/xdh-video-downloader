import asyncio
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from .config import settings
from .models import FormatInfo
from .security import safe_filename

YTDLP_SOURCE = Path(__file__).resolve().parents[1] / "vendor" / "yt-dlp"


def ytdlp_command(*arguments: str) -> list[str]:
    return [sys.executable, "-m", "yt_dlp", *arguments]


def ytdlp_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(YTDLP_SOURCE) + os.pathsep + environment.get("PYTHONPATH", "")
    return environment


async def run_command(args: list[str], timeout: int) -> tuple[str, str]:
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
            raise HTTPException(403, "抖音当前拒绝该服务器访问，需要用户自己的新鲜浏览器会话后才能解析。")
        raise HTTPException(422, "无法解析该公开视频，请确认链接有效且平台允许公开访问。")
    return stdout.decode(errors="replace"), stderr.decode(errors="replace")


def to_formats(payload: dict) -> tuple[list[FormatInfo], dict[str, tuple[str, dict[str, str]]]]:
    """Return one dependable stream for each commonly used video resolution.

    Extractors commonly expose the same resolution many times for different
    codecs, protocols and bitrates.  Showing every raw stream makes the
    download choice needlessly confusing, so the public contract deliberately
    exposes only the four resolutions supported by the product.
    """
    supported_heights = (1080, 720, 480, 360)
    candidates: dict[int, dict] = {}
    sources: dict[str, tuple[str, dict[str, str]]] = {}
    for item in payload.get("formats", []):
        if item.get("vcodec") == "none" or not item.get("url"):
            continue
        height = item.get("height")
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
        resolution = f"{item.get('width')}x{height}" if item.get("width") else f"{height}P"
        ext = str(item.get("ext") or "mp4")
        formats.append(FormatInfo(id=format_id, label=f"{height}P", ext=ext, resolution=resolution, filesize=item.get("filesize") or item.get("filesize_approx"), codec=item.get("vcodec"), direct_available=True))
        headers = {str(key): str(value) for key, value in (item.get("http_headers") or {}).items() if str(key).lower() in {"referer", "user-agent", "origin"}}
        sources[format_id] = (str(item["url"]), headers)
    return formats, sources


async def inspect(url: str) -> tuple[str, str | None, int | None, str | None, str | None, str | None, int | None, list[FormatInfo], dict[str, tuple[str, dict[str, str]]]]:
    stdout, _ = await run_command(ytdlp_command("--no-playlist", "--skip-download", "--dump-single-json", url), settings.inspection_timeout_seconds)
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
    args = ytdlp_command("--no-playlist", "--no-warnings", "--newline", "-f", selected_format, "--merge-output-format", "mp4", "-o", output_template, url)
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
