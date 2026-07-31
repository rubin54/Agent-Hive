from __future__ import annotations

from typing import Any

import pytest

from hive.catalog import OpenRouterModel


def make_model(
    model_id: str = "acme/test-model",
    *,
    name: str | None = None,
    prompt: str | None = "0.000001",
    completion: str | None = "0.000003",
    tools: bool = True,
    vision: bool = False,
    context_length: int | None = 128_000,
    created: int | None = 1_700_000_000,
    description: str = "Ein Testmodell.",
) -> OpenRouterModel:
    """Baut ein Modell in der Form, wie OpenRouter es ausliefert."""
    supported: list[str] = ["temperature", "max_tokens"]
    if tools:
        supported += ["tools", "tool_choice"]

    pricing: dict[str, Any] = {}
    if prompt is not None:
        pricing["prompt"] = prompt
    if completion is not None:
        pricing["completion"] = completion

    return OpenRouterModel.model_validate(
        {
            "id": model_id,
            "name": name or model_id,
            "description": description,
            "created": created,
            "context_length": context_length,
            "architecture": {
                "modality": "text+image->text" if vision else "text->text",
                "input_modalities": ["text", "image"] if vision else ["text"],
                "output_modalities": ["text"],
            },
            "pricing": pricing,
            "top_provider": {"context_length": context_length, "max_completion_tokens": 8192},
            "supported_parameters": supported,
        }
    )


@pytest.fixture
def sample_models() -> list[OpenRouterModel]:
    return [
        make_model(
            "anthropic/claude-sonnet", prompt="0.000003", completion="0.000015", vision=True
        ),
        make_model("openai/gpt-mini", prompt="0.0000004", completion="0.0000016", vision=True),
        make_model("mistralai/mistral-small", prompt="0.0000002", completion="0.0000006"),
        make_model("meta/llama-text", prompt="0", completion="0", tools=False),
        make_model("obscure/no-price", prompt=None, completion=None, tools=False),
    ]
