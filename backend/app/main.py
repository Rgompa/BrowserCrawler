from __future__ import annotations

import asyncio
import hashlib
import os
from collections import Counter
from typing import Any
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .generator import cases_csv, pytest_zip
from .integrations import CopilotAnalyzer, IntegrationError, PlaywrightMCPBrowser
from .models import CreateProject, Project, TestCase
from .store import Store

app = FastAPI(title="Atlas QA API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ATLAS_UI_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)

store = Store(os.getenv("ATLAS_DB_PATH", "data/atlas.db"))
credential_vault: dict[str, dict[str, str]] = {}
project_options: dict[str, CreateProject] = {}

IRREVERSIBLE_WORDS = {
    "delete", "remove", "purchase", "buy now", "pay", "transfer", "send message",
    "cancel order", "close account", "confirm order", "place order", "book now",
}


def _resolve_secrets(value: Any, secrets: dict[str, str]) -> Any:
    if isinstance(value, str):
        return value.replace("$USERNAME", secrets.get("username", "")).replace("$PASSWORD", secrets.get("password", ""))
    if isinstance(value, list):
        return [_resolve_secrets(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_secrets(item, secrets) for key, item in value.items()}
    return value


def _redact(text: str, secrets: dict[str, str]) -> str:
    redacted = text
    for label, value in secrets.items():
        if value:
            redacted = redacted.replace(value, f"${label.upper()}")
    return redacted


def _action_is_safe(tool: str, arguments: dict[str, Any], base_url: str, allow_mutations: bool) -> bool:
    if tool == "browser_navigate":
        target = urlparse(str(arguments.get("url", "")))
        base = urlparse(base_url)
        return target.scheme in {"http", "https"} and target.netloc == base.netloc
    if allow_mutations:
        return True
    haystack = str(arguments).lower()
    return not any(word in haystack for word in IRREVERSIBLE_WORDS)


async def _run_discovery(project_id: str) -> None:
    project = store.get_project(project_id)
    options = project_options.get(project_id)
    if not project or not options:
        return
    secrets = credential_vault.get(project_id, {})
    evidence: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    snapshots_seen: Counter[str] = Counter()
    urls: set[str] = set()
    flows: set[str] = set()
    try:
        project.status = "crawling"
        project.progress = 3
        project.message = "Starting an isolated Playwright MCP browser"
        store.save_project(project)

        async with CopilotAnalyzer(os.getenv("COPILOT_MODEL")) as analyzer:
            async with PlaywrightMCPBrowser(project.base_url) as browser:
                await browser.call("browser_navigate", {"url": project.base_url})
                for index in range(options.max_actions):
                    snapshot = _redact(await browser.call("browser_snapshot", {"depth": 12}), secrets)
                    digest = hashlib.sha256(snapshot.encode()).hexdigest()[:16]
                    snapshots_seen[digest] += 1
                    for token in snapshot.split():
                        if token.startswith("http://") or token.startswith("https://"):
                            urls.add(token.rstrip("'\"),]"))

                    if len(urls) >= options.max_pages or snapshots_seen[digest] >= 3:
                        break

                    action = await analyzer.next_action(
                        snapshot=snapshot,
                        history=history,
                        tools=browser.tool_catalog(),
                        budget=options.max_actions - index,
                    )
                    if action.stop or not action.tool:
                        break
                    arguments = _resolve_secrets(action.arguments, secrets)
                    if not _action_is_safe(action.tool, arguments, project.base_url, options.allow_mutations):
                        history.append({"tool": action.tool, "flow": action.flow, "result": "blocked by safety policy"})
                        continue

                    result = _redact(await browser.call(action.tool, arguments), secrets)
                    flows.add(action.flow)
                    event = {
                        "sequence": index + 1,
                        "flow": action.flow,
                        "tool": action.tool,
                        "arguments": action.arguments,
                        "observation": action.observation,
                        "result": result[-8000:],
                        "snapshot_hash": digest,
                    }
                    history.append(event)
                    evidence.append(event)
                    project.pages_discovered = max(1, len(urls))
                    project.flows_discovered = len(flows)
                    project.progress = min(72, 8 + int((index + 1) / options.max_actions * 64))
                    project.message = f"Exploring {action.flow}: {action.reason}"
                    store.save_project(project)

            project.status = "analyzing"
            project.progress = 78
            project.message = "Copilot is deriving positive, negative, and edge cases"
            store.save_project(project)
            cases = await analyzer.generate_cases(evidence)
        if not cases:
            raise IntegrationError("No test cases could be grounded in the crawl evidence")
        store.save_cases(project_id, cases)
        project.status = "ready"
        project.progress = 100
        project.test_case_count = len(cases)
        project.flows_discovered = len({case.flow for case in cases})
        project.message = "Regression suite ready for human review"
        store.save_project(project)
    except Exception as exc:
        project.status = "failed"
        project.message = str(exc)[:500]
        store.save_project(project)
    finally:
        credential_vault.pop(project_id, None)
        project_options.pop(project_id, None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/projects", response_model=Project, status_code=202)
async def create_project(payload: CreateProject, background_tasks: BackgroundTasks) -> Project:
    project = Project(name=payload.name, base_url=str(payload.base_url).rstrip("/"))
    store.save_project(project)
    credential_vault[project.id] = {
        "username": payload.username,
        "password": payload.password.get_secret_value() if payload.password else "",
    }
    project_options[project.id] = payload
    background_tasks.add_task(_run_discovery, project.id)
    return project


@app.get("/api/projects/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@app.get("/api/projects/{project_id}/test-cases")
def get_test_cases(project_id: str) -> dict[str, list[TestCase]]:
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    return {"items": store.get_cases(project_id)}


@app.patch("/api/projects/{project_id}/test-cases/{case_id}", response_model=TestCase)
def update_test_case(project_id: str, case_id: str, payload: dict[str, Any]) -> TestCase:
    allowed = {"title", "flow", "type", "priority", "status", "preconditions", "steps"}
    update = {key: value for key, value in payload.items() if key in allowed}
    current = store.get_cases(project_id)
    item = next((case for case in current if case.id == case_id), None)
    if not item:
        raise HTTPException(404, "Test case not found")
    try:
        validated = TestCase.model_validate({**item.model_dump(), **update})
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    saved = store.update_case(project_id, case_id, validated.model_dump())
    return saved or validated


@app.get("/api/projects/{project_id}/test-cases.csv")
def download_csv(project_id: str) -> Response:
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return Response(
        cases_csv(store.get_cases(project_id)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{project.name}-test-cases.csv"'},
    )


@app.post("/api/projects/{project_id}/pytest.zip")
def download_pytest(project_id: str) -> Response:
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return Response(
        pytest_zip(project, store.get_cases(project_id)),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{project.name}-pytest.zip"'},
    )
