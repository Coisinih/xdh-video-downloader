import asyncio
import json
import os
import re
import sys
from pathlib import Path

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
    formats: list[FormatInfo] = []
    sources: dict[str, tuple[str, dict[str, str]]] = {}
    for item in payload.get("formats", []):
        if item.get("vcodec") == "none" or not item.get("url"):
            continue
        format_id = str(item.get("format_id", ""))
        if not format_id:
            continue
        resolution = f"{item.get('width')}x{item.get('height')}" if item.get("height") else None
        ext = item.get("ext", "mp4")
        formats.append(FormatInfo(id=format_id, label=item.get("format_note") or resolution or ext.upper(), ext=ext, resolution=resolution, filesize=item.get("filesize") or item.get("filesize_approx"), codec=item.get("vcodec"), direct_available=True))
        headers = {str(key): str(value) for key, value in (item.get("http_headers") or {}).items() if str(key).lower() in {"referer", "user-agent", "origin"}}
        sources[format_id] = (item["url"], headers)
    return formats[:20], sources


async def inspect(url: str) -> tuple[str, str | None, int | None, list[FormatInfo], dict[str, tuple[str, dict[str, str]]]]:
    stdout, _ = await run_command(ytdlp_command("--no-playlist", "--skip-download", "--dump-single-json", url), settings.inspection_timeout_seconds)
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Invalid video metadata") from exc
    formats, sources = to_formats(data)
    if not formats:
        raise HTTPException(422, "No downloadable video formats found")
    return data.get("title") or "Untitled video", data.get("thumbnail"), int(data["duration"]) if data.get("duration") is not None else None, formats, sources


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
