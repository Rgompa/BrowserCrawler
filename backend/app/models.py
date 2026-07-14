from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, SecretStr


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreateProject(BaseModel):
    name: str = Field(default="Legacy application", min_length=1, max_length=120)
    base_url: HttpUrl
    username: str = Field(default="", max_length=500)
    password: SecretStr | None = None
    max_pages: int = Field(default=25, ge=1, le=100)
    max_actions: int = Field(default=80, ge=1, le=300)
    allow_mutations: bool = False


class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    base_url: str
    status: Literal["queued", "crawling", "analyzing", "ready", "failed"] = "queued"
    progress: int = 0
    pages_discovered: int = 0
    flows_discovered: int = 0
    test_case_count: int = 0
    message: str = "Waiting for an available browser session"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class AutomationStep(BaseModel):
    kind: Literal["navigate", "click", "fill", "select", "press", "assert_text", "assert_url", "assert_visible", "wait"]
    locator: str | None = None
    value: str | None = None
    role: str | None = None
    name: str | None = None


class TestStep(BaseModel):
    action: str
    expected: str
    automation: AutomationStep | None = None


class TestCase(BaseModel):
    id: str
    title: str
    flow: str
    type: Literal["Positive", "Negative", "Edge"]
    priority: Literal["P0", "P1", "P2"] = "P2"
    status: Literal["Ready", "Needs review"] = "Needs review"
    preconditions: list[str] = Field(default_factory=list)
    steps: list[TestStep]
    evidence: list[str] = Field(default_factory=list)


class BrowserAction(BaseModel):
    stop: bool = False
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    flow: str = "Unclassified"
    observation: str = ""
    reason: str = ""
