import pytest

from app.ai_config import ai_settings
from app.ai_deepseek import DeepSeekClient


@pytest.mark.asyncio
async def test_json_completion_disables_thinking_for_structured_output(monkeypatch):
    monkeypatch.setattr(ai_settings, "deepseek_api_key", "test-key")
    payloads = []

    async def request(self, method, path, payload=None):
        payloads.append(payload)
        return {"choices": [{"message": {"content": '{"summary":"ok"}'}}]}

    monkeypatch.setattr(DeepSeekClient, "_request", request)

    assert await DeepSeekClient().json_completion("system", "user") == {"summary": "ok"}
    assert payloads[0]["thinking"] == {"type": "disabled"}
