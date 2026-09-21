import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from .ai_models import AnswerResponse, SummaryResult, TaskStatus, TranscriptCue
from .store import now


@dataclass
class AiSummaryTask:
    id: str
    inspection_id: str
    subtitle_id: str
    source_language: str
    cues: list[TranscriptCue] = field(default_factory=list)
    status: TaskStatus = TaskStatus.queued
    progress: float = 0
    error: str | None = None
    result: SummaryResult | None = None
    stream_text: str = ""
    stream_done: bool = False
    questions: list[tuple[str, AnswerResponse]] = field(default_factory=list)
    created_at: object = field(default_factory=now)
    user_id: str | None = None


class AiMemoryStore:
    def __init__(self, ttl_seconds: int):
        self.ttl = timedelta(seconds=ttl_seconds)
        self.tasks: dict[str, AiSummaryTask] = {}
        self.lock = asyncio.Lock()

    @staticmethod
    def token() -> str:
        return secrets.token_urlsafe(24)

    async def cleanup(self) -> None:
        cutoff = now() - self.ttl
        async with self.lock:
            self.tasks = {key: value for key, value in self.tasks.items() if value.created_at > cutoff}
