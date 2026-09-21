from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SubtitleTrack(BaseModel):
    id: str
    language: str
    label: str
    automatic: bool


class TranscriptCue(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=4000)


class SubtitleTracksResponse(BaseModel):
    tracks: list[SubtitleTrack]


class TranscriptResponse(BaseModel):
    track: SubtitleTrack
    cues: list[TranscriptCue]


class TaskStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class OutlineSection(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=2000)


class KeyPoint(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    detail: str = Field(min_length=1, max_length=2000)


class MindMapNode(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    children: list["MindMapNode"] = Field(default_factory=list, max_length=12)


class SummaryResult(BaseModel):
    overview: str = Field(min_length=1, max_length=3000)
    outline: list[OutlineSection] = Field(min_length=1, max_length=16)
    key_points: list[KeyPoint] = Field(min_length=1, max_length=20)
    keywords: list[str] = Field(min_length=1, max_length=20)
    mindmap: MindMapNode
    mermaid: str = ""
    mindmap_markdown: str = ""
    source_language: str = ""


class SummaryRequest(BaseModel):
    inspection_id: str = Field(min_length=1)
    subtitle_id: str = Field(min_length=1)


class SummaryTaskResponse(BaseModel):
    id: str
    status: TaskStatus
    progress: float = Field(ge=0, le=100)
    error: str | None = None
    result: SummaryResult | None = None
    # The streamed Markdown is the canonical video-outline text. Returning it
    # also lets the client retain the exact final content after a refresh.
    stream_text: str = ""
    created_at: datetime


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class Citation(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class AnswerResponse(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)
    citations: list[Citation] = Field(default_factory=list, max_length=8)
    created_at: datetime


class TranslationRequest(BaseModel):
    target_language: str = Field(pattern="^(zh-CN|zh-TW|en|ja|ko|es|fr|de)$")


class TranslationResponse(BaseModel):
    source_language: str
    target_language: str
    cues: list[TranscriptCue]


MindMapNode.model_rebuild()
