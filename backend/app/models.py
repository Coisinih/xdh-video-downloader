from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl


class DownloadMode(str, Enum):
    server = "server"
    direct = "direct"


class FormatInfo(BaseModel):
    id: str
    label: str
    ext: str
    resolution: str | None = None
    filesize: int | None = None
    codec: str | None = None
    direct_available: bool = False


class InspectionRequest(BaseModel):
    url: HttpUrl


class InspectionResponse(BaseModel):
    inspection_id: str
    title: str
    thumbnail: str | None = None
    duration: int | None = None
    author: str | None = None
    description: str | None = None
    platform: str | None = None
    view_count: int | None = None
    formats: list[FormatInfo]
    expires_at: datetime


class DownloadRequest(BaseModel):
    inspection_id: str = Field(min_length=1)
    format_id: str = Field(min_length=1)
    mode: DownloadMode = DownloadMode.direct


class DownloadResponse(BaseModel):
    mode: DownloadMode = DownloadMode.direct
    task_id: str | None = None
    delivery_url: str | None = None


class TaskStatus(str, Enum):
    queued = "queued"
    downloading = "downloading"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class TaskResponse(BaseModel):
    id: str
    status: TaskStatus
    progress: float = 0
    error: str | None = None
    delivery_url: str | None = None
    filename: str | None = None
