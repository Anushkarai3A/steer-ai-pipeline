from __future__ import annotations

"""Minimal OpenAI-compatible chat client.

Configuration comes from environment variables only (LLM_PROVIDER, LLM_API_KEY,
LLM_MODEL, LLM_BASE_URL). Credentials are never logged. Failures raise LLMError
with a human-readable message so pipeline stages can fail honestly instead of
producing fake output.
"""

import json
from typing import Any

import httpx

from app.core.config import settings


class LLMError(Exception):
    pass


def provider_label() -> str:
    if not settings.ai_enabled:
        return "none (deterministic mode)"
    return f"{settings.llm_provider}:{settings.llm_model}"


def chat_json(system: str, user: str, *, schema_hint: str | None = None, max_tokens: int = 4096) -> dict[str, Any]:
    if not settings.ai_enabled:
        raise LLMError(
            "No AI provider configured (LLM_PROVIDER=none or LLM_API_KEY missing). "
            "Set LLM_PROVIDER=openai and LLM_API_KEY to enable model-assisted generation."
        )

    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=settings.llm_timeout_seconds)
    except httpx.TimeoutException as exc:
        raise LLMError(f"The AI provider timed out after {settings.llm_timeout_seconds}s.") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach the AI provider: {exc}") from exc

    if resp.status_code in (401, 403):
        raise LLMError("The AI provider rejected the configured credentials (HTTP %d)." % resp.status_code)
    if resp.status_code == 429:
        raise LLMError("The AI provider rate-limited the request (HTTP 429). Retry later.")
    if resp.status_code >= 500:
        raise LLMError(f"The AI provider returned a server error (HTTP {resp.status_code}).")
    if resp.status_code >= 400:
        raise LLMError(f"The AI provider rejected the request (HTTP {resp.status_code}).")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise LLMError("The AI provider returned a response that was not valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise LLMError("The AI provider returned JSON that is not an object.")
    return parsed
