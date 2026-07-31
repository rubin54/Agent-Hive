"""Template model and loading. No Docker required."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.templates.models import CommandCheck, PlaywrightCheck, ServeCheck, Template
from hive.templates.store import TemplateError, TemplateStore

MINIMAL = """
version: 1
prompt: Build something.
checks:
  - kind: command
    name: build
    command: "echo ok"
"""


def write_template(root: Path, name: str, body: str) -> TemplateStore:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "template.yaml").write_text(body, encoding="utf-8")
    return TemplateStore(root)


# ----------------------------------------------------------------------- model


def test_ref_identifies_name_and_version() -> None:
    template = Template(name="a", version=3, prompt="x")
    assert template.ref == "a@3"


def test_hash_changes_with_content_but_not_with_itself() -> None:
    """The hash exposes edits where someone forgot to bump the version."""
    one = Template(name="a", version=1, prompt="x").with_hash()
    same = Template(name="a", version=1, prompt="x").with_hash()
    other = Template(name="a", version=1, prompt="y").with_hash()

    assert one.content_hash == same.content_hash
    assert one.content_hash != other.content_hash
    # The hash itself is not part of the computation.
    assert one.with_hash().content_hash == one.content_hash


def test_templates_are_immutable() -> None:
    template = Template(name="a", version=1, prompt="x")
    with pytest.raises(ValueError, match=r"frozen|immutable"):
        template.version = 2  # type: ignore[misc]


def test_duplicate_check_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate check names"):
        Template(
            name="a",
            version=1,
            prompt="x",
            checks=[
                CommandCheck(name="same", command="a"),
                CommandCheck(name="same", command="b"),
            ],
        )


def test_playwright_without_matching_serve_is_rejected() -> None:
    """Otherwise it only fails inside the container — after the expensive agent phase."""
    with pytest.raises(ValueError, match="no serve check"):
        Template(
            name="a",
            version=1,
            prompt="x",
            checks=[
                ServeCheck(command="node serve.js", port=5173),
                PlaywrightCheck(spec="checks/a.spec.ts", port=4173),
            ],
        )


def test_unknown_field_is_rejected() -> None:
    """extra=forbid: a typo in the YAML must not be ignored silently."""
    with pytest.raises(ValueError):
        Template.model_validate({"name": "a", "version": 1, "prompt": "x", "tempo": 5})


# --------------------------------------------------------------------- loading


def test_load_minimal_template(tmp_path: Path) -> None:
    store = write_template(tmp_path, "simple", MINIMAL)
    template = store.load("simple")

    assert template.ref == "simple@1"
    assert template.content_hash != ""
    assert template.checks[0].name == "build"


def test_directory_name_wins_over_file(tmp_path: Path) -> None:
    """A diverging name in the file would be a silent trap on lookup."""
    store = write_template(tmp_path, "real", "version: 1\nname: different\nprompt: x\n")
    with pytest.raises(TemplateError, match="does not match directory"):
        store.load("real")


def test_missing_template_lists_alternatives(tmp_path: Path) -> None:
    store = write_template(tmp_path, "one", MINIMAL)
    with pytest.raises(TemplateError, match="Available: one"):
        store.load("two")


def test_broken_yaml_is_reported(tmp_path: Path) -> None:
    store = write_template(tmp_path, "broken", "version: 1\n  prompt: [unbalanced\n")
    with pytest.raises(TemplateError, match="YAML not readable"):
        store.load("broken")


def test_missing_spec_file_is_caught_at_load_time(tmp_path: Path) -> None:
    """Noticing a missing spec file after ten minutes of agent work costs money."""
    store = write_template(
        tmp_path,
        "spec",
        """
version: 1
prompt: x
checks:
  - kind: serve
    name: serve
    command: node serve.js
    port: 5173
  - kind: playwright
    name: behaviour
    spec: checks/missing.spec.ts
    port: 5173
""",
    )
    with pytest.raises(TemplateError, match="the file is missing"):
        store.load("spec")


def test_missing_starter_dir_is_caught(tmp_path: Path) -> None:
    store = write_template(
        tmp_path, "s", "version: 1\nprompt: x\nworkspace:\n  starter_dir: starter\n"
    )
    with pytest.raises(TemplateError, match="starter_dir"):
        store.load("s")


def test_starter_files_are_read_recursively(tmp_path: Path) -> None:
    store = write_template(
        tmp_path, "s", "version: 1\nprompt: x\nworkspace:\n  starter_dir: starter\n"
    )
    starter = tmp_path / "s" / "starter"
    (starter / "sub").mkdir(parents=True)
    (starter / "serve.js").write_text("// server\n", encoding="utf-8")
    (starter / "sub" / "util.js").write_text("// util\n", encoding="utf-8")

    files = dict(store.starter_files(store.load("s")))
    assert files == {"serve.js": "// server\n", "sub/util.js": "// util\n"}


def test_names_ignores_directories_without_template(tmp_path: Path) -> None:
    store = write_template(tmp_path, "real", MINIMAL)
    (tmp_path / "not-a-template").mkdir()
    assert store.names() == ["real"]


# ------------------------------------------------------------ shipped templates


def repo_templates() -> TemplateStore:
    return TemplateStore(Path(__file__).resolve().parents[2] / "templates")


def test_shipped_templates_all_load() -> None:
    """A broken shipped template should surface in CI, not at a user."""
    store = repo_templates()
    assert set(store.names()) >= {"counter-page", "minecraft-clone"}
    for template in store.load_all():
        assert template.prompt.strip()
        assert template.checks


def test_minecraft_template_declares_its_network_needs() -> None:
    template = repo_templates().load("minecraft-clone")
    assert template.workspace.network == "internal"
    # The model installs packages itself; the check phase must see no open network.
    assert template.workspace.agent_internet is True
    install = next(c for c in template.checks if c.name == "install")
    assert isinstance(install, CommandCheck)
    assert install.needs_network is True
