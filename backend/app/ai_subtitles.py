import asyncio
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from .ai_config import ai_settings
from .ai_models import SubtitleTrack, TranscriptCue
from .security import validate_source_url

YTDLP_SOURCE = Path(__file__).resolve().parents[1] / "vendor" / "yt-dlp"
TIMESTAMP = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2}(?:[.,]\d+)?)")
TAG = re.compile(r"<[^>]+>")


@dataclass
class ResolvedTrack:
    public: SubtitleTrack
    url: str
    headers: dict[str, str]


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(YTDLP_SOURCE) + os.pathsep + environment.get("PYTHONPATH", "")
    return environment


async def _metadata(source_url: str) -> dict:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "yt_dlp", "--no-playlist", "--skip-download", "--dump-single-json", source_url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=_environment(),
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), ai_settings.ai_subtitle_timeout_seconds)
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise HTTPException(504, "获取字幕信息超时") from exc
    if process.returncode != 0:
        raise HTTPException(422, "无法获取该视频的字幕信息")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "字幕信息格式无效") from exc


def _priority(language: str, automatic: bool) -> tuple[int, int, str]:
    normalized = language.lower().replace("_", "-")
    chinese = normalized == "zh" or normalized.startswith("zh-") or normalized.startswith("chi")
    return (0 if chinese else 1, 1 if automatic else 0, normalized)


def _pick_format(formats: list[dict]) -> dict | None:
    ordered = sorted(formats, key=lambda item: {"vtt": 0, "srt": 1}.get(str(item.get("ext", "")).lower(), 2))
    return next((item for item in ordered if item.get("url")), None)


async def _bilibili_tracks(source_url: str, payload: dict) -> list[ResolvedTrack]:
    """Use Bilibili's public player metadata when yt-dlp has no subtitle list."""
    host = (urlparse(source_url).hostname or "").lower()
    bvid = str(payload.get("id") or "")
    if not host.endswith("bilibili.com") or not bvid.startswith("BV"):
        return []
    headers = {"Referer": "https://www.bilibili.com/", "User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=ai_settings.ai_subtitle_timeout_seconds) as client:
            view = await client.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid})
            cid = (view.json().get("data") or {}).get("cid")
            if not cid:
                return []
            player = await client.get("https://api.bilibili.com/x/player/wbi/v2", params={"bvid": bvid, "cid": cid})
            subtitles = (((player.json().get("data") or {}).get("subtitle") or {}).get("subtitles") or [])
    except (httpx.HTTPError, ValueError):
        return []
    tracks: list[ResolvedTrack] = []
    for item in subtitles:
        subtitle_url = str(item.get("subtitle_url") or "")
        if subtitle_url.startswith("//"):
            subtitle_url = f"https:{subtitle_url}"
        if not subtitle_url:
            continue
        try:
            validate_source_url(subtitle_url)
        except HTTPException:
            continue
        language = str(item.get("lan") or "und")
        label = str(item.get("lan_doc") or language)
        tracks.append(ResolvedTrack(SubtitleTrack(id=f"bilibili:manual:{language}", language=language, label=f"{label}（B站字幕）", automatic=False), subtitle_url, headers))
    return tracks


async def _bilibili_dm_tracks(source_url: str, payload: dict) -> list[ResolvedTrack]:
    """Fallback to the public danmaku metadata endpoint for CC/AI subtitles.

    Bilibili currently exposes some subtitle records through ``x/v2/dm/view``
    while hiding the same records from ``x/player/wbi/v2`` behind
    ``need_login_subtitle``.  This is a public metadata endpoint and does not
    require forwarding cookies or a login session.
    """
    host = (urlparse(source_url).hostname or "").lower()
    bvid = str(payload.get("id") or "")
    if not host.endswith("bilibili.com") or not bvid.startswith("BV"):
        return []
    headers = {"Referer": f"https://www.bilibili.com/video/{bvid}", "User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=ai_settings.ai_subtitle_timeout_seconds) as client:
            view = await client.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid})
            view_payload = view.json().get("data") or {}
            aid, cid = view_payload.get("aid"), view_payload.get("cid")
            if not aid or not cid:
                return []
            response = await client.get(
                "https://api.bilibili.com/x/v2/dm/view",
                params={"aid": aid, "oid": cid, "type": 1},
            )
            subtitles = ((response.json().get("data") or {}).get("subtitle") or {}).get("subtitles") or []
    except (httpx.HTTPError, ValueError, TypeError):
        return []
    tracks: list[ResolvedTrack] = []
    for item in subtitles:
        subtitle_url = str(item.get("subtitle_url") or "")
        if subtitle_url.startswith("//"):
            subtitle_url = f"https:{subtitle_url}"
        elif subtitle_url.startswith("http://"):
            subtitle_url = f"https://{subtitle_url[7:]}"
        if not subtitle_url:
            continue
        try:
            validate_source_url(subtitle_url)
        except HTTPException:
            continue
        language = str(item.get("lan") or "und")
        automatic = bool(item.get("type") == 1 or language.startswith("ai-"))
        label = str(item.get("lan_doc") or language)
        subtitle_id = str(item.get("id_str") or item.get("id") or language)
        tracks.append(ResolvedTrack(
            SubtitleTrack(
                id=f"bilibili:{'auto' if automatic else 'manual'}:{subtitle_id}",
                language=language.removeprefix("ai-"),
                label=f"{label}（B站字幕）",
                automatic=automatic,
            ),
            subtitle_url,
            headers,
        ))
    return tracks


async def discover_tracks(source_url: str) -> list[ResolvedTrack]:
    payload = await _metadata(source_url)
    tracks: list[ResolvedTrack] = []
    for automatic, key in ((False, "subtitles"), (True, "automatic_captions")):
        for language, formats in (payload.get(key) or {}).items():
            selected = _pick_format(formats if isinstance(formats, list) else [])
            if not selected:
                continue
            url = str(selected["url"])
            validate_source_url(url)
            safe_language = str(language)
            track_id = f"{'auto' if automatic else 'manual'}:{safe_language}"
            headers = {str(name): str(value) for name, value in (selected.get("http_headers") or {}).items() if str(name).lower() in {"referer", "user-agent", "origin"}}
            tracks.append(ResolvedTrack(SubtitleTrack(id=track_id, language=safe_language, label=f"{safe_language}{'（自动字幕）' if automatic else '（字幕）'}", automatic=automatic), url, headers))
    bili_tracks = await _bilibili_tracks(source_url, payload)
    tracks.extend(bili_tracks)
    if not bili_tracks:
        tracks.extend(await _bilibili_dm_tracks(source_url, payload))
    return sorted(tracks, key=lambda item: _priority(item.public.language, item.public.automatic))


def _seconds(value: str) -> float:
    match = TIMESTAMP.fullmatch(value.strip())
    if not match:
        raise ValueError(value)
    hour, minute, second = match.groups()
    return int(hour or 0) * 3600 + int(minute) * 60 + float(second.replace(",", "."))


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG.sub("", value))).strip()


def parse_subtitles(content: str) -> list[TranscriptCue]:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if content.lstrip().startswith(("{", "[")):
        try:
            payload = json.loads(content)
            body = payload.get("body", []) if isinstance(payload, dict) else payload
            cues = [
                TranscriptCue(start=float(item["from"]), end=float(item["to"]), text=_clean_text(str(item["content"])))
                for item in body
                if isinstance(item, dict) and item.get("content") and float(item["to"]) >= float(item["from"])
            ]
            return [cue for index, cue in enumerate(cues) if index == 0 or cue != cues[index - 1]]
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return []
    cues: list[TranscriptCue] = []
    for block in re.split(r"\n\s*\n", content):
        lines = [line.strip() for line in block.split("\n") if line.strip() and not line.startswith("WEBVTT") and not line.startswith("NOTE")]
        time_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if time_index is None:
            continue
        start_raw, end_raw = [part.strip().split(" ", 1)[0] for part in lines[time_index].split("-->", 1)]
        try:
            start, end = _seconds(start_raw), _seconds(end_raw)
        except ValueError:
            continue
        text = _clean_text(" ".join(lines[time_index + 1:]))
        if text and end >= start and (not cues or cues[-1].text != text or cues[-1].start != start):
            cues.append(TranscriptCue(start=start, end=end, text=text))
    return cues


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def subtitles_to_srt(cues: list[TranscriptCue]) -> str:
    """Produce a portable UTF-8 SRT document from validated transcript cues."""
    return "\n\n".join(
        f"{index}\n{_srt_timestamp(cue.start)} --> {_srt_timestamp(cue.end)}\n{cue.text}"
        for index, cue in enumerate(cues, start=1)
    ) + ("\n" if cues else "")

def subtitles_to_txt(cues: list[TranscriptCue]) -> str:
    """Produce a plain UTF-8 transcript for note-taking and summarisation."""
    return "\n".join(cue.text for cue in cues) + ("\n" if cues else "")


async def fetch_transcript(track: ResolvedTrack) -> list[TranscriptCue]:
    validate_source_url(track.url)
    async with httpx.AsyncClient(follow_redirects=True, timeout=ai_settings.ai_subtitle_timeout_seconds) as client:
        response = await client.get(track.url, headers=track.headers)
        response.raise_for_status()
        content = response.content
    if len(content) > ai_settings.ai_max_subtitle_bytes:
        raise HTTPException(413, "字幕文件超过大小限制")
    cues = parse_subtitles(content.decode("utf-8", errors="replace"))
    if not cues:
        raise HTTPException(422, "未能解析出可用字幕文本")
    return cues
