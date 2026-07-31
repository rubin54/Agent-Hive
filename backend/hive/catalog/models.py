"""Pydantic models for the OpenRouter model catalog.

Field names follow the live response of ``GET https://openrouter.ai/api/v1/models``.
Everything is modelled leniently on purpose: OpenRouter adds fields regularly and returns
different subsets per model. ``extra="ignore"`` keeps a new field from breaking the sync.

Prices are ``Decimal``. They arrive as strings like ``"0.00000014"`` and are never computed
as ``float`` internally — at that magnitude, binary rounding errors accumulate into visible
drift across tens of thousands of calls.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

TOKENS_PER_MTOK = Decimal(1_000_000)

# Weighting for the blended price. A 3:1 input-to-output ratio is the usual convention for
# comparison tables and roughly matches agentic runs, where long contexts meet short tool calls.
BLEND_PROMPT_WEIGHT = Decimal("0.75")
BLEND_COMPLETION_WEIGHT = Decimal("0.25")


def _to_decimal(value: Any) -> Decimal | None:
    """Convert an OpenRouter price value into ``Decimal``.

    Unknown or negative prices (OpenRouter uses ``"-1"`` for variable rates) yield ``None`` —
    more honest than an invented zero, and surfaced in the UI.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return None if parsed < 0 else parsed


class Pricing(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt: Decimal | None = None
    completion: Decimal | None = None
    request: Decimal | None = None
    image: Decimal | None = None
    web_search: Decimal | None = None
    internal_reasoning: Decimal | None = None
    input_cache_read: Decimal | None = None
    input_cache_write: Decimal | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _parse_price(cls, value: Any) -> Decimal | None:
        return _to_decimal(value)

    @property
    def prompt_per_mtok(self) -> Decimal | None:
        return None if self.prompt is None else self.prompt * TOKENS_PER_MTOK

    @property
    def completion_per_mtok(self) -> Decimal | None:
        return None if self.completion is None else self.completion * TOKENS_PER_MTOK

    @property
    def blended_per_mtok(self) -> Decimal | None:
        """Blended price per million tokens at a 3:1 input/output ratio."""
        if self.prompt is None or self.completion is None:
            return None
        blended = self.prompt * BLEND_PROMPT_WEIGHT + self.completion * BLEND_COMPLETION_WEIGHT
        return blended * TOKENS_PER_MTOK

    @property
    def is_free(self) -> bool:
        return self.prompt == 0 and self.completion == 0


class Architecture(BaseModel):
    model_config = ConfigDict(extra="ignore")

    modality: str | None = None
    input_modalities: list[str] = []
    output_modalities: list[str] = []
    tokenizer: str | None = None
    instruct_type: str | None = None


class TopProvider(BaseModel):
    model_config = ConfigDict(extra="ignore")

    context_length: int | None = None
    max_completion_tokens: int | None = None
    is_moderated: bool | None = None


class ReasoningInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mandatory: bool | None = None
    default_enabled: bool | None = None
    supported_efforts: list[str] = []
    default_effort: str | None = None
    supports_max_tokens: bool | None = None


class OpenRouterModel(BaseModel):
    """A model exactly as OpenRouter delivers it."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    name: str
    canonical_slug: str | None = None
    description: str | None = None
    created: int | None = None
    context_length: int | None = None
    knowledge_cutoff: str | None = None
    architecture: Architecture = Architecture()
    pricing: Pricing = Pricing()
    top_provider: TopProvider = TopProvider()
    supported_parameters: list[str] = []
    reasoning: ReasoningInfo | None = None

    @field_validator("architecture", "pricing", "top_provider", mode="before")
    @classmethod
    def _null_to_default(cls, value: Any) -> Any:
        return {} if value is None else value

    @field_validator("supported_parameters", mode="before")
    @classmethod
    def _null_to_empty_list(cls, value: Any) -> Any:
        return [] if value is None else value

    @property
    def provider(self) -> str:
        """The provider prefix, e.g. ``anthropic`` from ``anthropic/claude-sonnet``."""
        return self.id.split("/", 1)[0] if "/" in self.id else self.id

    @property
    def effective_context_length(self) -> int | None:
        return self.context_length or self.top_provider.context_length
