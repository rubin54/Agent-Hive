"""Loading and validating task templates from the filesystem.

Layout of a template:

```
templates/minecraft-clone/
    template.yaml        task definition, checks, rubric
    checks/app.spec.ts   Playwright specification (optional)
    starter/             files placed in the workspace before the run (optional)
```
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import PlaywrightCheck, Template

TEMPLATE_FILE = "template.yaml"


class TemplateError(RuntimeError):
    """A template is unloadable or internally inconsistent."""


class TemplateStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def names(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            entry.name for entry in self.root.iterdir() if (entry / TEMPLATE_FILE).is_file()
        )

    def directory(self, name: str) -> Path:
        return self.root / name

    def load(self, name: str) -> Template:
        path = self.root / name / TEMPLATE_FILE
        if not path.is_file():
            available = ", ".join(self.names()) or "none"
            raise TemplateError(f"Template '{name}' not found. Available: {available}")

        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise TemplateError(f"{path}: YAML not readable — {exc}") from exc

        if not isinstance(raw, dict):
            raise TemplateError(f"{path}: a YAML object is expected")

        # The directory name is the source of truth. A diverging `name:` in the file would be
        # a silent trap on lookup.
        raw.setdefault("name", name)
        if raw["name"] != name:
            raise TemplateError(f"{path}: name '{raw['name']}' does not match directory '{name}'")

        try:
            template = Template.model_validate(raw).with_hash()
        except ValidationError as exc:
            raise TemplateError(f"{path}: invalid template\n{exc}") from exc

        self._verify_referenced_files(template)
        return template

    def load_all(self) -> list[Template]:
        return [self.load(name) for name in self.names()]

    def _verify_referenced_files(self, template: Template) -> None:
        """Check referenced files at load time, not halfway through a run.

        Noticing a missing spec file only after ten minutes of agent work costs real money —
        hence here.
        """
        base = self.directory(template.name)

        for check in template.checks:
            if isinstance(check, PlaywrightCheck) and not (base / check.spec).is_file():
                raise TemplateError(
                    f"{template.ref}: check '{check.name}' references {check.spec}, "
                    "but the file is missing"
                )

        starter = template.workspace.starter_dir
        if starter is not None and not (base / starter).is_dir():
            raise TemplateError(f"{template.ref}: starter_dir '{starter}' does not exist")

    def starter_files(self, template: Template) -> list[tuple[str, str]]:
        """Starter files as ``(target path in the workspace, content)``."""
        starter = template.workspace.starter_dir
        if starter is None:
            return []

        base = self.directory(template.name) / starter
        files: list[tuple[str, str]] = []
        for path in sorted(base.rglob("*")):
            if path.is_file():
                relative = path.relative_to(base).as_posix()
                files.append((relative, path.read_text(encoding="utf-8")))
        return files

    def spec_source(self, template: Template, check: PlaywrightCheck) -> str:
        return (self.directory(template.name) / check.spec).read_text(encoding="utf-8")
