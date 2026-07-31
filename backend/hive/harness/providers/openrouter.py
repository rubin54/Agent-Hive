"""OpenRouter provider (OpenAI-compatible chat completions format)."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from ..messages import Completion, FinishReason, Message, Role, ToolCall, Usage
from .base import ProviderError

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

# 429 and 5xx are transient, other 4xx are not — retrying a 400 only burns time and, worse,
# budget.
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})


def _to_wire(message: Message) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": message.role.value}
    if message.role is Role.TOOL:
        wire["tool_call_id"] = message.tool_call_id
        wire["content"] = message.content or ""
        return wire

    wire["content"] = message.content
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
    return wire


def _parse_tool_calls(raw: list[dict[str, Any]] | None) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for index, entry in enumerate(raw or []):
        function = entry.get("function") or {}
        name = function.get("name")
        if not name:
            continue
        # Arguments arrive as a JSON string. Weaker models regularly emit broken JSON here —
        # that must not take down the run. It becomes empty arguments, which schema
        # validation then reports back as feedback.
        arguments: dict[str, Any] = {}
        raw_args = function.get("arguments")
        if isinstance(raw_args, dict):
            arguments = raw_args
        elif isinstance(raw_args, str) and raw_args.strip():
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    arguments = parsed
            except json.JSONDecodeError:
                arguments = {}
        calls.append(
            ToolCall(id=str(entry.get("id") or f"call_{index}"), name=name, arguments=arguments)
        )
    return calls


def _parse_finish_reason(value: str | None) -> FinishReason:
    try:
        return FinishReason(value or "stop")
    except ValueError:
        return FinishReason.OTHER


class OpenRouterProvider:
    """Calls a model through OpenRouter.

    The API key is only passed through and never stored — the public demo runs on recorded
    runs anyway, not on live calls.
    """

    def __init__(
        self,
        model_id: str,
        *,
        api_key: str,
        url: str = OPENROUTER_CHAT_URL,
        timeout: float = 180.0,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
        referer: str = "https://github.com/agent-hive",
        title: str = "Agent Hive",
    ) -> None:
        if not api_key:
            raise ProviderError("No OpenRouter API key set (HIVE_OPENROUTER_API_KEY)")
        self.model_id = model_id
        self._url = url
        self._max_retries = max_retries
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # OpenRouter uses these two fields for attribution in its statistics.
            "HTTP-Referer": referer,
            "X-Title": title,
        }

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        body: dict[str, Any] = {
            "model": self.model_id,
            "messages": [_to_wire(m) for m in messages],
            # Enables the cost field in the response. Reported cost beats our own arithmetic
            # because it accounts for discounts and cache hits.
            "usage": {"include": True},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        payload = await self._post_with_retry(body)
        return self._to_completion(payload)

    async def _post_with_retry(self, body: dict[str, Any]) -> dict[str, Any]:
        last_error = "unknown"
        for attempt in range(self._max_retries):
            try:
                response = await self._client.post(self._url, json=body, headers=self._headers)
            except httpx.HTTPError as exc:
                last_error = f"Network error: {exc}"
            else:
                if response.status_code < 400:
                    try:
                        return dict(response.json())
                    except ValueError as exc:
                        raise ProviderError(f"Response is not JSON: {exc}") from exc
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code not in RETRYABLE_STATUS:
                    raise ProviderError(last_error)

            if attempt < self._max_retries - 1:
                await asyncio.sleep(2**attempt)

        raise ProviderError(f"Failed after {self._max_retries} attempts — {last_error}")

    def _to_completion(self, payload: dict[str, Any]) -> Completion:
        # OpenRouter sometimes reports errors with HTTP 200 and an "error" object in the body.
        if "error" in payload and not payload.get("choices"):
            error = payload["error"]
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise ProviderError(f"OpenRouter: {detail}")

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("Response without 'choices'")

        choice = choices[0]
        raw_message = choice.get("message") or {}
        tool_calls = _parse_tool_calls(raw_message.get("tool_calls"))
        content = raw_message.get("content")

        raw_usage = payload.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
            completion_tokens=int(raw_usage.get("completion_tokens") or 0),
            reasoning_tokens=int(
                (raw_usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
            ),
        )

        reported_cost: Decimal | None = None
        if (raw_cost := raw_usage.get("cost")) is not None:
            try:
                reported_cost = Decimal(str(raw_cost))
            except (InvalidOperation, ValueError):
                reported_cost = None

        return Completion(
            message=Message.assistant(
                content if isinstance(content, str) else None, tool_calls=tool_calls
            ),
            usage=usage,
            finish_reason=_parse_finish_reason(choice.get("finish_reason")),
            model_id=str(payload.get("model") or self.model_id),
            reported_cost_usd=reported_cost,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
