"""OpenRouter provider — wire format, error handling, retries."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from hive.harness.messages import FinishReason, Message, Role, ToolCall
from hive.harness.providers.base import ProviderError
from hive.harness.providers.openrouter import OpenRouterProvider

URL = "https://openrouter.ai/api/v1/chat/completions"


def provider(**kwargs: object) -> OpenRouterProvider:
    return OpenRouterProvider("acme/model", api_key="test-key", url=URL, **kwargs)  # type: ignore[arg-type]


def text_response(content: str = "done", **usage: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "acme/model",
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, **usage},
        },
    )


def test_missing_api_key_is_rejected_early() -> None:
    with pytest.raises(ProviderError, match="API key"):
        OpenRouterProvider("acme/model", api_key="")


@respx.mock
async def test_simple_completion() -> None:
    route = respx.post(URL).mock(return_value=text_response())
    result = await provider().complete([Message.user("hi")])

    assert result.message.content == "done"
    assert result.finish_reason is FinishReason.STOP
    assert result.usage.total_tokens == 15
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-key"


@respx.mock
async def test_tool_messages_use_the_expected_wire_format() -> None:
    import json

    route = respx.post(URL).mock(return_value=text_response())
    await provider().complete(
        [
            Message.system("sys"),
            Message.assistant(None, [ToolCall(id="c1", name="read", arguments={"path": "a.txt"})]),
            Message.tool_result("c1", "Inhalt"),
        ],
        tools=[{"type": "function", "function": {"name": "read", "parameters": {}}}],
    )

    body = json.loads(route.calls[0].request.content)
    assistant = body["messages"][1]
    assert assistant["tool_calls"][0]["function"]["name"] == "read"
    # Arguments must be sent as a JSON string, not as an object.
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"path": "a.txt"}

    tool_message = body["messages"][2]
    assert tool_message["role"] == Role.TOOL.value
    assert tool_message["tool_call_id"] == "c1"
    assert body["tool_choice"] == "auto"


@respx.mock
async def test_tool_calls_are_parsed() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "write_file",
                                        "arguments": '{"path": "a.js", "content": "x"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            },
        )
    )
    result = await provider().complete([Message.user("go")])

    assert result.finish_reason is FinishReason.TOOL_CALLS
    assert result.message.tool_calls[0].name == "write_file"
    assert result.message.tool_calls[0].arguments == {"path": "a.js", "content": "x"}


@respx.mock
async def test_broken_argument_json_does_not_crash() -> None:
    """Weak models regularly emit broken JSON.

    That must not take down the run: the garbage becomes empty arguments, schema validation
    reports them, and the model can correct itself.
    """
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "c",
                                    "function": {
                                        "name": "write_file",
                                        "arguments": '{"path": "a.js"',
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )
    )
    result = await provider().complete([Message.user("go")])
    assert result.message.tool_calls[0].arguments == {}


@respx.mock
async def test_reported_cost_is_parsed() -> None:
    respx.post(URL).mock(return_value=text_response(cost=0.00123))
    result = await provider().complete([Message.user("hi")])
    assert result.reported_cost_usd == Decimal("0.00123")


@respx.mock
async def test_reasoning_tokens_are_read() -> None:
    respx.post(URL).mock(
        return_value=text_response(completion_tokens_details={"reasoning_tokens": 42})
    )
    result = await provider().complete([Message.user("hi")])
    assert result.usage.reasoning_tokens == 42


@respx.mock
async def test_rate_limit_is_retried() -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(429, text="slow down"), text_response()]
    )
    result = await provider(max_retries=2).complete([Message.user("hi")])

    assert result.message.content == "done"
    assert route.call_count == 2


@respx.mock
async def test_client_error_is_not_retried() -> None:
    """Retrying a 400 only burns time and budget."""
    route = respx.post(URL).mock(return_value=httpx.Response(400, text="bad model"))
    with pytest.raises(ProviderError, match="400"):
        await provider(max_retries=3).complete([Message.user("hi")])
    assert route.call_count == 1


@respx.mock
async def test_error_inside_a_200_response_is_detected() -> None:
    """OpenRouter sometimes reports provider errors with HTTP 200 and an error object."""
    respx.post(URL).mock(
        return_value=httpx.Response(200, json={"error": {"message": "no provider available"}})
    )
    with pytest.raises(ProviderError, match="no provider available"):
        await provider().complete([Message.user("hi")])


@respx.mock
async def test_unknown_finish_reason_falls_back() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "x"}, "finish_reason": "something-else"}]},
        )
    )
    result = await provider().complete([Message.user("hi")])
    assert result.finish_reason is FinishReason.OTHER
