from __future__ import annotations

import csv
import io
import json
import re
import zipfile

from .models import Project, TestCase


def cases_csv(cases: list[TestCase]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Test case ID", "Business flow", "Title", "Type", "Priority", "Status", "Preconditions", "Detailed steps", "Expected results", "Evidence"])
    for case in cases:
        writer.writerow([
            case.id, case.flow, case.title, case.type, case.priority, case.status,
            "\n".join(case.preconditions),
            "\n".join(f"{index}. {step.action}" for index, step in enumerate(case.steps, 1)),
            "\n".join(f"{index}. {step.expected}" for index, step in enumerate(case.steps, 1)),
            "\n".join(case.evidence),
        ])
    return output.getvalue()


def _identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "case"


def _q(value: str | None) -> str:
    return repr(value or "")


def _locator(step) -> str:
    auto = step.automation
    if auto and auto.role and auto.name:
        return f"page.get_by_role({_q(auto.role)}, name={_q(auto.name)})"
    if auto and auto.locator:
        return f"page.locator({_q(auto.locator)})"
    return "None"


def _step_code(step) -> list[str]:
    auto = step.automation
    if not auto:
        return [f"    # TODO: {step.action}", f"    # Expected: {step.expected}"]
    locator = _locator(step)
    kind = auto.kind
    if kind == "navigate": return [f"    page.goto(base_url + {_q(auto.value)})"]
    if kind == "click": return [f"    {locator}.click()"] if locator != "None" else [f"    # TODO click: {step.action}"]
    if kind == "fill": return [f"    {locator}.fill(resolve_value({_q(auto.value)}))"] if locator != "None" else [f"    # TODO fill: {step.action}"]
    if kind == "select": return [f"    {locator}.select_option(resolve_value({_q(auto.value)}))"] if locator != "None" else [f"    # TODO select: {step.action}"]
    if kind == "press": return [f"    {locator}.press({_q(auto.value or 'Enter')})"] if locator != "None" else [f"    # TODO press: {step.action}"]
    if kind == "assert_text": return [f"    expect(page.get_by_text({_q(auto.value)}, exact=False)).to_be_visible()"]
    if kind == "assert_url": return [f"    expect(page).to_have_url(re.compile({_q(auto.value)}))"]
    if kind == "assert_visible": return [f"    expect({locator}).to_be_visible()"] if locator != "None" else [f"    # TODO assert: {step.expected}"]
    if kind == "wait": return [f"    page.wait_for_timeout({int(float(auto.value or '1') * 1000)})"]
    return [f"    # TODO: {step.action}"]


def pytest_zip(project: Project, cases: list[TestCase]) -> bytes:
    buffer = io.BytesIO()
    approved = [case for case in cases if case.status == "Ready"]
    groups: dict[str, list[TestCase]] = {}
    for case in approved:
        groups.setdefault(_identifier(case.flow), []).append(case)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("requirements.txt", "pytest>=8.0\npytest-playwright>=0.7\n")
        archive.writestr("pytest.ini", "[pytest]\naddopts = --tracing=retain-on-failure --screenshot=only-on-failure\n")
        archive.writestr(".env.example", f"BASE_URL={project.base_url}\nTEST_USERNAME=\nTEST_PASSWORD=\n")
        archive.writestr("conftest.py", """import os\nimport pytest\n\n@pytest.fixture\ndef base_url():\n    return os.environ.get('BASE_URL', '').rstrip('/')\n\ndef resolve_value(value):\n    return value.replace('$USERNAME', os.environ.get('TEST_USERNAME', '')).replace('$PASSWORD', os.environ.get('TEST_PASSWORD', ''))\n""")
        for flow, flow_cases in groups.items():
            lines = ["import re", "from playwright.sync_api import Page, expect", "from conftest import resolve_value", ""]
            for case in flow_cases:
                lines.extend([
                    f"def test_{_identifier(case.id + '_' + case.title)}(page: Page, base_url: str):",
                    f"    \"\"\"{case.id}: {case.title}\"\"\"",
                ])
                if not case.steps:
                    lines.append("    pass")
                for step in case.steps:
                    lines.extend(_step_code(step))
                lines.append("")
            archive.writestr(f"tests/test_{flow}.py", "\n".join(lines))
        archive.writestr("test-cases.json", json.dumps([case.model_dump() for case in cases], indent=2))
        archive.writestr("README.md", f"# {project.name} regression suite\n\nGenerated from approved Atlas QA cases. Copy `.env.example` values into your CI secrets, install dependencies, run `playwright install chromium`, then run `pytest`. Cases marked Needs review remain in `test-cases.json` but are not emitted as executable tests.\n")
    return buffer.getvalue()
