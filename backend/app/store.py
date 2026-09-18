import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from .models import FormatInfo, TaskStatus


def now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Inspection:
    id: str
    source_url: str
    title: str
    thumbnail: str | None
    duration: int | None
    formats: list[FormatInfo]
    created_at: datetime = field(default_factory=now)
    direct_sources: dict[str, tuple[str, dict[str, str]]] = field(default_factory=dict)


@dataclass
class Delivery:
    token: str
    source_url: str | None = None
    file_path: Path | None = None
    filename: str = "video"
    headers_required: bool = False
    source_headers: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=now)


@dataclass
class Task:
    id: str
    inspection_id: str
    format_id: str
    status: TaskStatus = TaskStatus.queued
    progress: float = 0
    error: str | None = None
    delivery_token: str | None = None
    filename: str | None = None
    created_at: datetime = field(default_factory=now)


class MemoryStore:
    def __init__(self, ttl_seconds: int):
        self.ttl = timedelta(seconds=ttl_seconds)
        self.inspections: dict[str, Inspection] = {}
        self.deliveries: dict[str, Delivery] = {}
        self.tasks: dict[str, Task] = {}
        self.lock = asyncio.Lock()

    @staticmethod
    def token() -> str:
        return secrets.token_urlsafe(24)

    async def cleanup(self) -> None:
        cutoff = now() - self.ttl
        async with self.lock:
            self.inspections = {key: value for key, value in self.inspections.items() if value.created_at > cutoff}
            self.tasks = {key: value for key, value in self.tasks.items() if value.created_at > cutoff}
            expired = [key for key, value in self.deliveries.items() if value.created_at <= cutoff]
            for key in expired:
                delivery = self.deliveries.pop(key)
                if delivery.file_path:
                    delivery.file_path.unlink(missing_ok=True)
