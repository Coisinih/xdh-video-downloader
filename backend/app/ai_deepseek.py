import json
import re
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from .ai_config import ai_settings
from .ai_models import AnswerResponse, Citation, MindMapNode, SummaryResult, TranscriptCue


class ChunkResult(BaseModel):
    summary: str = Field(min_length=1, max_length=6000)


class AnswerPayload(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)
    citations: list[Citation] = Field(default_factory=list, max_length=8)


def _url(path: str) -> str:
    return f"{ai_settings.deepseek_base_url.rstrip('/')}/{path.lstrip('/')}"


def _transcript_text(cues: list[TranscriptCue]) -> str:
    def timestamp(seconds: float) -> str:
        value = int(seconds)
        return f"{value // 3600:02}:{(value % 3600) // 60:02}:{value % 60:02}"
    return "\n".join(f"[{timestamp(cue.start)}-{timestamp(cue.end)}] {cue.text}" for cue in cues)


def _split_text(value: str) -> list[str]:
    if len(value) <= ai_settings.ai_chunk_chars:
        return [value]
    return [value[index:index + ai_settings.ai_chunk_chars] for index in range(0, len(value), ai_settings.ai_chunk_chars)]


def _escape_mermaid(value: str) -> str:
    return re.sub(r"[\[\]{}()\"`\\]", " ", value).replace("\n", " ").strip()[:120] or "未命名节点"


def build_mermaid(root: MindMapNode) -> str:
    lines = ["mindmap"]
    def visit(node: MindMapNode, depth: int) -> None:
        lines.append(f"{'  ' * depth}{_escape_mermaid(node.title)}")
        for child in node.children:
            visit(child, depth + 1)
    visit(root, 1)
    return "\n".join(lines)


def build_markmap(root: MindMapNode) -> str:
    lines = [f"# {root.title}"]

    def visit(node: MindMapNode, depth: int) -> None:
        lines.append(f"{'#' * depth} {node.title}")
        for child in node.children:
            visit(child, depth + 1)

    for child in root.children:
        visit(child, 2)
    return "\n".join(lines)


def _limit_summary_collections(payload: dict) -> dict:
    """Keep otherwise valid model output within the public response contract."""
    result = dict(payload)
    for field, limit in (("outline", 16), ("key_points", 20), ("keywords", 20)):
        if isinstance(result.get(field), list):
            result[field] = result[field][:limit]

    def limit_node(node: object) -> None:
        if not isinstance(node, dict) or not isinstance(node.get("children"), list):
            return
        node["children"] = node["children"][:12]
        for child in node["children"]:
            limit_node(child)

    limit_node(result.get("mindmap"))
    return result


class DeepSeekClient:
    def __init__(self) -> None:
        if not ai_settings.deepseek_api_key:
            raise HTTPException(503, "AI 服务尚未配置 DeepSeek API Key")
        self.headers = {"Authorization": f"Bearer {ai_settings.deepseek_api_key}", "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=ai_settings.deepseek_timeout_seconds) as client:
                response = await client.request(method, _url(path), headers=self.headers, json=payload)
        except httpx.TimeoutException as exc:
            raise HTTPException(504, "DeepSeek 响应超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, "无法连接 DeepSeek 服务") from exc
        if response.status_code in {401, 403}:
            raise HTTPException(503, "DeepSeek API Key 无效或无访问权限")
        if response.status_code == 429:
            raise HTTPException(429, "AI 服务繁忙，请稍后重试")
        if response.status_code >= 400:
            raise HTTPException(502, "DeepSeek 服务请求失败")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(502, "DeepSeek 返回了无效响应") from exc

    async def validate_model(self) -> None:
        data = await self._request("GET", "models")
        ids = {str(item.get("id")) for item in data.get("data", [])}
        if ai_settings.deepseek_model not in ids:
            raise HTTPException(503, f"配置的 DeepSeek 模型不可用：{ai_settings.deepseek_model}")

    async def json_completion(self, system: str, user: str) -> dict:
        async def completion(extra_instruction: str = "") -> str:
            data = await self._request("POST", "chat/completions", {
            "model": ai_settings.deepseek_model,
            "messages": [{"role": "system", "content": system + extra_instruction}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": ai_settings.deepseek_max_tokens,
            # Structured extraction does not benefit from chain-of-thought.
            # Disabling it preserves the response budget for valid JSON.
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "stream": False,
        })
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise HTTPException(502, "DeepSeek 未返回有效 JSON 结果") from exc
        try:
            return json.loads(await completion())
        except json.JSONDecodeError:
            try:
                return json.loads(await completion(" 输出必须是单个合法 JSON 对象，不得包含 Markdown、说明文字或代码围栏。"))
            except json.JSONDecodeError as exc:
                raise HTTPException(502, "DeepSeek 未返回有效 JSON 结果") from exc
        except HTTPException:
            raise
        except (KeyError, IndexError, TypeError) as exc:
            raise HTTPException(502, "DeepSeek 未返回有效 JSON 结果") from exc


    async def text_completion_stream(self, system: str, user: str) -> AsyncIterator[str]:
        payload = {
            "model": ai_settings.deepseek_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.4,
            "max_tokens": ai_settings.deepseek_max_tokens,
            "thinking": {"type": "disabled"},
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=ai_settings.deepseek_timeout_seconds) as client:
                async with client.stream("POST", _url("chat/completions"), headers=self.headers, json=payload) as response:
                    if response.status_code in {401, 403}:
                        raise HTTPException(503, "DeepSeek API Key is invalid or unauthorized")
                    if response.status_code == 429:
                        raise HTTPException(429, "DeepSeek service is busy")
                    if response.status_code >= 400:
                        raise HTTPException(502, "DeepSeek request failed")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        value = line[5:].strip()
                        if value == "[DONE]":
                            return
                        try:
                            event = json.loads(value)
                            content = event["choices"][0]["delta"].get("content")
                        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                            continue
                        if content:
                            yield str(content)
        except httpx.TimeoutException as exc:
            raise HTTPException(504, "DeepSeek response timed out") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Unable to connect to DeepSeek") from exc


SUMMARY_SYSTEM = "你是严谨的视频学习助手。仅根据用户提供的字幕生成中文总结，不得补充字幕中没有的事实。必须只返回 JSON。"
SUMMARY_PROMPT = """根据下列视频字幕生成 JSON，字段必须为 overview、outline、key_points、keywords、mindmap。outline 的元素含 title、summary；key_points 的元素含 title、detail；mindmap 是含 title、children 的树。所有字段必须有内容。\n\n视频标题：{title}\n字幕语言：{language}\n字幕：\n{transcript}"""
CHUNK_PROMPT = "请仅根据下列字幕片段返回 JSON：{\"summary\": \"片段核心内容\"}。\n\n{transcript}"
STREAM_SUMMARY_SYSTEM = "You summarize only the supplied video transcript. Write in Chinese, do not add facts, and return readable Markdown only."
STREAM_SUMMARY_PROMPT = """Create a concise learning summary in Chinese Markdown. Include headings for overview, outline, key points, and conclusion.

Title: {title}
Transcript language: {language}
Transcript:
{transcript}"""
ANSWER_SYSTEM = "你是视频字幕问答助手。只能依据提供的摘要和字幕证据回答；找不到依据时明确说明。必须只返回 JSON。"
ANSWER_PROMPT = """视频摘要：{overview}\n\n字幕证据：\n{evidence}\n\n问题：{question}\n\n返回 JSON：{{\"answer\":\"...\",\"citations\":[{{\"start\":0,\"end\":0}}]}}。citations 只能使用字幕证据内的时间。"""


async def generate_summary(title: str, language: str, cues: list[TranscriptCue]) -> SummaryResult:
    client = DeepSeekClient()
    await client.validate_model()
    transcript = _transcript_text(cues)
    if len(transcript) > ai_settings.ai_max_transcript_chars:
        transcript = transcript[:ai_settings.ai_max_transcript_chars]
    chunks = _split_text(transcript)
    if len(chunks) > 1:
        partials = []
        for chunk in chunks:
            try:
                partials.append(ChunkResult.model_validate(await client.json_completion(SUMMARY_SYSTEM, CHUNK_PROMPT.format(transcript=chunk))).summary)
            except ValidationError as exc:
                raise HTTPException(502, "DeepSeek 返回的片段摘要格式无效") from exc
        transcript = "\n\n".join(f"片段摘要 {index + 1}：{value}" for index, value in enumerate(partials))
    try:
        payload = await client.json_completion(
            SUMMARY_SYSTEM,
            SUMMARY_PROMPT.format(title=title, language=language, transcript=transcript),
        )
        result = SummaryResult.model_validate(_limit_summary_collections(payload))
    except ValidationError as exc:
        raise HTTPException(502, "DeepSeek 返回的总结格式无效") from exc
    result.source_language = language
    result.mermaid = build_mermaid(result.mindmap)
    result.mindmap_markdown = build_markmap(result.mindmap)
    return result


async def stream_summary_markdown(title: str, language: str, cues: list[TranscriptCue]) -> AsyncIterator[str]:
    client = DeepSeekClient()
    await client.validate_model()
    transcript = _transcript_text(cues)[:ai_settings.ai_max_transcript_chars]
    async for delta in client.text_completion_stream(
        STREAM_SUMMARY_SYSTEM,
        STREAM_SUMMARY_PROMPT.format(title=title, language=language, transcript=transcript),
    ):
        yield delta


def _relevant_cues(question: str, cues: list[TranscriptCue]) -> list[TranscriptCue]:
    tokens = {char for char in question.lower() if not char.isspace()}
    ranked = sorted(cues, key=lambda cue: sum(char in cue.text.lower() for char in tokens), reverse=True)
    return ranked[:12] if tokens else cues[:12]


async def answer_question(question: str, summary: SummaryResult, cues: list[TranscriptCue]) -> AnswerResponse:
    client = DeepSeekClient()
    await client.validate_model()
    evidence_cues = _relevant_cues(question, cues)
    try:
        raw_payload = await client.json_completion(
            ANSWER_SYSTEM,
            ANSWER_PROMPT.format(overview=summary.overview, evidence=_transcript_text(evidence_cues), question=question),
        )
        normalized_payload = dict(raw_payload)
        if isinstance(normalized_payload.get("answer"), str):
            normalized_payload["answer"] = normalized_payload["answer"].strip()[:4000]
        citations = normalized_payload.get("citations")
        normalized_payload["citations"] = citations[:8] if isinstance(citations, list) else []
        payload = AnswerPayload.model_validate(normalized_payload)
    except ValidationError as exc:
        raise HTTPException(502, "DeepSeek 返回的问答格式无效") from exc
    allowed = {(cue.start, cue.end) for cue in evidence_cues}
    citations = [citation for citation in payload.citations if (citation.start, citation.end) in allowed]
    if not citations and evidence_cues:
        # A response without a source range is not auditable. Keep the answer
        # grounded by citing the highest-ranked subtitle evidence as fallback.
        citations = [Citation(start=evidence_cues[0].start, end=evidence_cues[0].end)]
    return AnswerResponse(answer=payload.answer, citations=citations, created_at=datetime.now().astimezone())
