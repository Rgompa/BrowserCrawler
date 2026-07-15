from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import AsyncExitStack
from typing import Any

from .models import BrowserAction, TestCase


class IntegrationError(RuntimeError):
    pass


def extract_json(text: str) -> Any:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else text
    first_object, first_array = candidate.find("{"), candidate.find("[")
    starts = [index for index in (first_object, first_array) if index >= 0]
    if not starts:
        raise IntegrationError("Copilot did not return JSON")
    start = min(starts)
    end = max(candidate.rfind("}"), candidate.rfind("]"))
    return json.loads(candidate[start:end + 1])


class PlaywrightMCPBrowser:
    SAFE_TOOLS = {
        "browser_navigate", "browser_snapshot", "browser_click", "browser_type",
        "browser_fill_form", "browser_select_option", "browser_navigate_back",
        "browser_wait_for", "browser_tabs", "browser_find",
    }

    def __init__(self, origin: str) -> None:
        self.origin = origin.rstrip("/")
        self.stack = AsyncExitStack()
        self.session = None
        self.schemas: dict[str, Any] = {}

    async def __aenter__(self) -> "PlaywrightMCPBrowser":
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise IntegrationError("Install the 'mcp' Python package before crawling") from exc
        params = StdioServerParameters(
            command="npx",
            args=["-y", "@playwright/mcp@latest", "--headless", "--isolated", "--image-responses", "omit"],
            env={**os.environ, "npm_config_cache": os.getenv("ATLAS_NPM_CACHE", "/tmp/atlas-npm-cache")},
        )
        read, write = await self.stack.enter_async_context(stdio_client(params))
        self.session = await self.stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        tools = await self.session.list_tools()
        self.schemas = {
            tool.name: tool.inputSchema for tool in tools.tools if tool.name in self.SAFE_TOOLS
        }
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        if not self.session or name not in self.schemas:
            raise IntegrationError(f"Unsupported Playwright MCP tool: {name}")
        result = await self.session.call_tool(name, arguments or {})
        text = "\n".join(getattr(item, "text", "") for item in result.content if getattr(item, "text", None))
        if getattr(result, "isError", False):
            raise IntegrationError(text or f"Playwright tool {name} failed")
        return text

    def tool_catalog(self) -> str:
        return json.dumps(self.schemas, separators=(",", ":"))


class CopilotAnalyzer:
    def __init__(self, model: str | None = None) -> None:
        self.model = model
        self.client = None
        self.session = None
        self._assistant_message_type = None
        self._idle_type = None

    async def __aenter__(self) -> "CopilotAnalyzer":
        try:
            from copilot import CopilotClient
            from copilot.session import AssistantMessageData, PermissionRequestResult, SessionIdleData
        except ImportError as exc:
            raise IntegrationError("Install github-copilot-sdk before starting analysis") from exc

        def reject_tools(_request: Any, _invocation: Any) -> Any:
            return PermissionRequestResult(kind="reject")

        self.client = CopilotClient()
        await self.client.start()
        self.session = await self.client.create_session(
            model=self.model,
            working_directory=os.path.abspath("."),
            on_permission_request=reject_tools,
            system_message={
                "mode": "append",
                "content": "You are a senior QA analyst. Return only valid JSON matching the requested schema. Never reveal secrets.",
            },
        )
        self._assistant_message_type = AssistantMessageData
        self._idle_type = SessionIdleData
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.session:
            await self.session.disconnect()
        if self.client:
            await self.client.stop()

    async def complete(self, prompt: str) -> str:
        if not self.session or not self._assistant_message_type or not self._idle_type:
            raise IntegrationError("CopilotAnalyzer must be used as an async context manager")
        messages: list[str] = []
        done = asyncio.Event()
        assistant_type = self._assistant_message_type
        idle_type = self._idle_type
        def on_event(event: Any) -> None:
            if isinstance(event.data, assistant_type):
                messages.append(event.data.content)
            if isinstance(event.data, idle_type):
                done.set()
        unsubscribe = self.session.on(on_event)
        try:
            await self.session.send(prompt)
            await asyncio.wait_for(done.wait(), timeout=180)
        finally:
            unsubscribe()
        if not messages:
            raise IntegrationError("Copilot returned no analysis")
        return messages[-1]

    async def next_action(self, *, snapshot: str, history: list[dict[str, Any]], tools: str, budget: int) -> BrowserAction:
        prompt = f"""Choose one safe action that maximizes business-flow discovery.
Never confirm purchases, payments, transfers, deletions, cancellations, messages, or other irreversible actions.
Credentials are represented as $USERNAME and $PASSWORD. You may place those exact tokens in tool arguments.
Stop when the useful interactive surface is exhausted or the remaining action budget is zero.

AVAILABLE PLAYWRIGHT MCP TOOLS AND INPUT SCHEMAS:
{tools}

RECENT HISTORY:
{json.dumps(history[-10:])}

CURRENT ACCESSIBILITY SNAPSHOT:
{snapshot[-30000:]}

REMAINING ACTION BUDGET: {budget}

Return: {{"stop":boolean,"tool":string|null,"arguments":object,"flow":string,"observation":string,"reason":string}}"""
        return BrowserAction.model_validate(extract_json(await self.complete(prompt)))

    async def generate_cases(self, evidence: list[dict[str, Any]]) -> list[TestCase]:
        prompt = f"""Create a risk-based regression suite from observed evidence. Cover every observed business flow with positive, negative, boundary, empty-state, authorization, validation, and recovery cases when supported. Do not invent inaccessible features. Mark inferred cases 'Needs review'. Prefer stable role/name locators in automation metadata.

EVIDENCE:
{json.dumps(evidence)[-90000:]}

Return a JSON array. Each item must match:
{{"id":"FLOW-001","title":"...","flow":"...","type":"Positive|Negative|Edge","priority":"P0|P1|P2","status":"Ready|Needs review","preconditions":["..."],"steps":[{{"action":"...","expected":"...","automation":{{"kind":"navigate|click|fill|select|press|assert_text|assert_url|assert_visible|wait","locator":null,"value":null,"role":null,"name":null}}}}],"evidence":["URL or observation"]}}"""
        raw = extract_json(await self.complete(prompt))
        if isinstance(raw, dict):
            raw = raw.get("items", raw.get("test_cases", []))
        return [TestCase.model_validate(item) for item in raw]
