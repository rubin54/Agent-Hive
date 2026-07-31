"""Tool registry: schema derivation and failure behaviour."""

from __future__ import annotations

import pytest

from hive.harness.tools import ToolError, ToolRegistry, tool_from_function


async def greet(name: str, times: int = 1) -> str:
    """Greet someone repeatedly."""
    return " ".join([f"Hello {name}"] * times)


async def explodes(what: str) -> str:
    """Always raises."""
    raise ToolError(f"cannot '{what}'")


async def crashes(value: int) -> str:
    """Raises an unexpected error."""
    return str(1 // value)


def test_schema_is_derived_from_annotations() -> None:
    spec = tool_from_function(greet)
    assert spec.name == "greet"
    assert spec.description == "Greet someone repeatedly."
    assert spec.parameters["properties"]["name"]["type"] == "string"
    assert spec.parameters["properties"]["times"]["default"] == 1
    assert spec.parameters["required"] == ["name"]


def test_titles_are_stripped_from_schema() -> None:
    """Pydantic titles carry no information and cost context on every call."""
    spec = tool_from_function(greet)
    assert "title" not in spec.parameters
    assert all("title" not in prop for prop in spec.parameters["properties"].values())


def test_missing_annotation_is_rejected() -> None:
    async def broken(x) -> str:  # type: ignore[no-untyped-def]
        """Broken."""
        return str(x)

    with pytest.raises(TypeError, match="no type annotation"):
        tool_from_function(broken)


def test_missing_docstring_is_rejected() -> None:
    """The docstring ends up verbatim in the prompt — leaving it out would be a silent bug."""

    async def undocumented(x: str) -> str:
        return x

    with pytest.raises(ValueError, match="docstring"):
        tool_from_function(undocumented)


async def test_invoke_returns_result() -> None:
    registry = ToolRegistry([tool_from_function(greet)])
    result, ok = await registry.invoke("greet", {"name": "world", "times": 2})
    assert ok is True
    assert result == "Hello world Hello world"


async def test_unknown_tool_lists_alternatives() -> None:
    """A hallucinated name must let the model correct itself."""
    registry = ToolRegistry([tool_from_function(greet)])
    result, ok = await registry.invoke("greetings", {})
    assert ok is False
    assert "does not exist" in result
    assert "greet" in result


async def test_invalid_arguments_become_feedback() -> None:
    registry = ToolRegistry([tool_from_function(greet)])
    result, ok = await registry.invoke("greet", {"times": 2})
    assert ok is False
    assert "invalid arguments" in result


async def test_tool_error_is_reported_not_raised() -> None:
    registry = ToolRegistry([tool_from_function(explodes)])
    result, ok = await registry.invoke("explodes", {"what": "fly"})
    assert ok is False
    assert "cannot 'fly'" in result


async def test_unexpected_exception_does_not_escape() -> None:
    """A tool failure must never take down the whole run."""
    registry = ToolRegistry([tool_from_function(crashes)])
    result, ok = await registry.invoke("crashes", {"value": 0})
    assert ok is False
    assert "ZeroDivisionError" in result


def test_subset_for_read_only_roles() -> None:
    registry = ToolRegistry([tool_from_function(greet), tool_from_function(explodes)])
    assert registry.subset(["greet"]).names == ["greet"]
    with pytest.raises(KeyError):
        registry.subset(["nonexistent"])


def test_duplicate_registration_is_rejected() -> None:
    registry = ToolRegistry([tool_from_function(greet)])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool_from_function(greet))


def test_openai_schema_shape() -> None:
    schema = ToolRegistry([tool_from_function(greet)]).as_openai_schema()
    assert schema[0]["type"] == "function"
    assert schema[0]["function"]["name"] == "greet"
    assert "parameters" in schema[0]["function"]
