"""Werkzeug-Registry: Schemaableitung und Fehlerverhalten."""

from __future__ import annotations

import pytest

from hive.harness.tools import ToolError, ToolRegistry, tool_from_function


async def greet(name: str, times: int = 1) -> str:
    """Grüßt jemanden mehrfach."""
    return " ".join([f"Hallo {name}"] * times)


async def explodes(what: str) -> str:
    """Wirft immer."""
    raise ToolError(f"kann '{what}' nicht")


async def crashes(value: int) -> str:
    """Wirft einen unerwarteten Fehler."""
    return str(1 // value)


def test_schema_is_derived_from_annotations() -> None:
    spec = tool_from_function(greet)
    assert spec.name == "greet"
    assert spec.description == "Grüßt jemanden mehrfach."
    assert spec.parameters["properties"]["name"]["type"] == "string"
    assert spec.parameters["properties"]["times"]["default"] == 1
    assert spec.parameters["required"] == ["name"]


def test_titles_are_stripped_from_schema() -> None:
    """Pydantic-Titel tragen keine Information und kosten bei jedem Aufruf Kontext."""
    spec = tool_from_function(greet)
    assert "title" not in spec.parameters
    assert all("title" not in prop for prop in spec.parameters["properties"].values())


def test_missing_annotation_is_rejected() -> None:
    async def broken(x) -> str:  # type: ignore[no-untyped-def]
        """Kaputt."""
        return str(x)

    with pytest.raises(TypeError, match="ohne Typannotation"):
        tool_from_function(broken)


def test_missing_docstring_is_rejected() -> None:
    """Der Docstring landet wörtlich im Prompt — er fehlt zu lassen wäre ein stiller Bug."""

    async def undocumented(x: str) -> str:
        return x

    with pytest.raises(ValueError, match="Docstring"):
        tool_from_function(undocumented)


async def test_invoke_returns_result() -> None:
    registry = ToolRegistry([tool_from_function(greet)])
    result, ok = await registry.invoke("greet", {"name": "Welt", "times": 2})
    assert ok is True
    assert result == "Hallo Welt Hallo Welt"


async def test_unknown_tool_lists_alternatives() -> None:
    """Ein halluzinierter Name muss dem Modell die Korrektur ermöglichen."""
    registry = ToolRegistry([tool_from_function(greet)])
    result, ok = await registry.invoke("gruesse", {})
    assert ok is False
    assert "existiert nicht" in result
    assert "greet" in result


async def test_invalid_arguments_become_feedback() -> None:
    registry = ToolRegistry([tool_from_function(greet)])
    result, ok = await registry.invoke("greet", {"times": 2})
    assert ok is False
    assert "ungültige Argumente" in result


async def test_tool_error_is_reported_not_raised() -> None:
    registry = ToolRegistry([tool_from_function(explodes)])
    result, ok = await registry.invoke("explodes", {"what": "fliegen"})
    assert ok is False
    assert "kann 'fliegen' nicht" in result


async def test_unexpected_exception_does_not_escape() -> None:
    """Ein Werkzeugfehler darf nie den ganzen Lauf kippen."""
    registry = ToolRegistry([tool_from_function(crashes)])
    result, ok = await registry.invoke("crashes", {"value": 0})
    assert ok is False
    assert "ZeroDivisionError" in result


def test_subset_for_read_only_roles() -> None:
    registry = ToolRegistry([tool_from_function(greet), tool_from_function(explodes)])
    assert registry.subset(["greet"]).names == ["greet"]
    with pytest.raises(KeyError):
        registry.subset(["gibtsnicht"])


def test_duplicate_registration_is_rejected() -> None:
    registry = ToolRegistry([tool_from_function(greet)])
    with pytest.raises(ValueError, match="bereits registriert"):
        registry.register(tool_from_function(greet))


def test_openai_schema_shape() -> None:
    schema = ToolRegistry([tool_from_function(greet)]).as_openai_schema()
    assert schema[0]["type"] == "function"
    assert schema[0]["function"]["name"] == "greet"
    assert "parameters" in schema[0]["function"]
