"""Template endpoints — the task list the run view starts from."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...templates.models import Template
from ...templates.store import TemplateError, TemplateStore
from ..deps import get_template_store

router = APIRouter(prefix="/templates", tags=["templates"])

StoreDep = Annotated[TemplateStore, Depends(get_template_store)]


class TemplateSummary(BaseModel):
    name: str
    version: int
    ref: str
    content_hash: str
    prompt: str
    checks: list[str] = Field(default_factory=list)
    network: str
    max_iterations: int
    #: Set when the template file cannot be loaded. Listing it broken is more useful than
    #: hiding it — a typo in the YAML should be visible, not silently reduce the list.
    error: str | None = None


def _summarise(template: Template) -> TemplateSummary:
    return TemplateSummary(
        name=template.name,
        version=template.version,
        ref=template.ref,
        content_hash=template.content_hash,
        prompt=template.prompt,
        checks=[c.name for c in template.checks],
        network=template.workspace.network,
        max_iterations=template.budget.max_iterations,
    )


@router.get("", response_model=list[TemplateSummary])
def list_templates(store: StoreDep) -> list[TemplateSummary]:
    summaries: list[TemplateSummary] = []
    for name in store.names():
        try:
            summaries.append(_summarise(store.load(name)))
        except TemplateError as exc:
            summaries.append(
                TemplateSummary(
                    name=name,
                    version=0,
                    ref=name,
                    content_hash="",
                    prompt="",
                    network="none",
                    max_iterations=0,
                    error=str(exc),
                )
            )
    return summaries


@router.get("/{name}", response_model=Template)
def get_template(name: str, store: StoreDep) -> Template:
    try:
        return store.load(name)
    except TemplateError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
