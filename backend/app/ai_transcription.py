"""On-demand audio transcription for videos without a platform subtitle track."""

import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import HTTPException

from .ai_config import ai_settings
from .ai_models import TranscriptCue
from . import ytdlp


_model = None
_model_lock = asyncio.Lock()
_transcription_semaphore = asyncio.Semaphore(1)
_MODEL_REPOSITORIES = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v1": "Systran/faster-whisper-large-v1",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "distil-large-v2": "Systran/faster-distil-whisper-large-v2",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
}


async def _download_audio(source_url: str, work_dir: Path) -> Path:
    # Bilibili 的视频页面在机房 IP 上会被 412 拒绝（yt-dlp 取不到音频），
    # 所以优先走公开接口的 dash 音轨；其他平台或接口不可用时回落到 yt-dlp。
    public_audio = await ytdlp.fetch_bilibili_audio(source_url, work_dir)
    if public_audio:
        return public_audio
    output_template = str(work_dir / "audio.%(ext)s")
    await ytdlp.run_command(
        ytdlp.ytdlp_command(
            "--no-playlist", "--no-warnings", "--format", "bestaudio/best",
            "--max-filesize", str(ai_settings.ai_max_audio_bytes),
            "--output", output_template, source_url,
            youtube=ytdlp.is_youtube_url(source_url),
        ),
        ai_settings.ai_asr_timeout_seconds,
        source_url,
    )
    files = [path for path in work_dir.iterdir() if path.is_file()]
    if not files:
        raise HTTPException(422, "未能获取可用于转录的公开视频音频。")
    audio_file = max(files, key=lambda path: path.stat().st_size)
    if audio_file.stat().st_size > ai_settings.ai_max_audio_bytes:
        raise HTTPException(413, "音频文件超过转录大小限制。")
    return audio_file


def _load_model():
    try:
        from faster_whisper import WhisperModel
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise HTTPException(503, "音频转录组件尚未安装，请更新服务后重试。") from exc
    model_dir = ai_settings.ai_work_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_name = ai_settings.ai_asr_model.lower()
    repository = _MODEL_REPOSITORIES.get(model_name)
    if not repository:
        raise HTTPException(422, f"不支持的转录模型：{ai_settings.ai_asr_model}")
    local_model_dir = model_dir / model_name
    try:
        # download_root makes huggingface-hub create cache symlinks on Windows.
        # local_dir stores ordinary files, so it works without Developer Mode
        # or administrator privileges and is also portable in Docker volumes.
        if not (local_model_dir / "model.bin").is_file():
            snapshot_download(repository, local_dir=str(local_model_dir))
        # int8 is the dependable CPU configuration for the product's Docker image.
        return WhisperModel(str(local_model_dir), device="cpu", compute_type="int8")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "音频转录模型下载或加载失败，请检查服务器网络后重试。") from exc


async def _get_model():
    global _model
    if _model is not None:
        return _model
    async with _model_lock:
        if _model is None:
            _model = await asyncio.to_thread(_load_model)
    return _model


def _run_transcription(model, audio_file: Path) -> list[TranscriptCue]:
    segments, _info = model.transcribe(
        str(audio_file),
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=True,
    )
    cues: list[TranscriptCue] = []
    for segment in segments:
        text = str(segment.text).strip()
        start, end = max(0.0, float(segment.start)), max(0.0, float(segment.end))
        if text and end >= start:
            cues.append(TranscriptCue(start=start, end=end, text=text))
    return cues


async def transcribe_audio(source_url: str) -> list[TranscriptCue]:
    """Return an in-memory transcript and remove the temporary public audio."""
    if not ai_settings.ai_enable_audio_transcription:
        raise HTTPException(422, "该视频没有可下载的自带字幕，且音频转录未启用。")
    ai_settings.ai_work_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="transcript-", dir=ai_settings.ai_work_dir))
    try:
        async with _transcription_semaphore:
            audio_file = await _download_audio(source_url, work_dir)
            model = await _get_model()
            try:
                cues = await asyncio.wait_for(
                    asyncio.to_thread(_run_transcription, model, audio_file),
                    timeout=ai_settings.ai_asr_timeout_seconds,
                )
            except TimeoutError as exc:
                raise HTTPException(504, "音频转录超时，请稍后重试。") from exc
        if not cues:
            raise HTTPException(422, "未能从视频音频识别出可用文本。")
        return cues
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
