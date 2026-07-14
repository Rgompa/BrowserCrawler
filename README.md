# Atlas QA

Atlas QA is a local-first discovery and regression-generation workbench for undocumented web applications. It explores a target through Playwright MCP, uses the GitHub Copilot SDK to infer business flows and risk conditions, lets a reviewer edit and approve the resulting cases, exports detailed CSV, and compiles approved cases into `pytest-playwright` tests.

## What is included

- A responsive review UI with target URL, optional credentials, crawl budget, progress, test-case filters, step editing, approval, CSV export, and pytest export.
- A FastAPI control plane with SQLite job/case persistence. Passwords never enter SQLite; the in-memory credential entry is deleted after the crawl.
- A Playwright MCP client using isolated, headless browser sessions and accessibility snapshots.
- A GitHub Copilot SDK adapter for next-action selection and structured test design.
- Same-origin navigation enforcement, a restricted browser-tool allowlist, secret redaction before LLM calls, crawl budgets, loop detection, and an irreversible-action denylist.
- Deterministic CSV and pytest ZIP generation. Only cases marked `Ready` become executable tests; all cases remain in the JSON evidence file.

## Prerequisites

- Node.js 22+
- Python 3.11+
- GitHub Copilot access with the Copilot CLI authenticated, or an authentication method supported by the Copilot SDK

## Run locally

Frontend:

```bash
npm install
npm run dev
```

Crawler API (a separate terminal):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m copilot download-runtime
cd backend
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:3000`. The UI expects the API at `http://localhost:8000`; override it with `NEXT_PUBLIC_API_BASE_URL`.

Playwright MCP is launched by the API through `npx @playwright/mcp@latest`. On a host without an installed compatible browser, run:

```bash
npx playwright install chromium
```

## Test

```bash
npm run build
cd backend && pytest
```

## Operating model

1. The user submits the application URL, a crawl budget, and optionally one test account.
2. The API launches an isolated Playwright MCP session and navigates to the allowed origin.
3. Copilot receives a redacted accessibility snapshot and chooses one action from the runtime MCP schemas.
4. The orchestrator validates the action, executes it, records grounded evidence, and repeats until the budget, page cap, loop detector, or agent stop condition is reached.
5. Copilot converts the evidence graph into positive, negative, and edge cases using a strict JSON schema.
6. A reviewer edits detailed steps and expected outcomes, then marks cases `Ready`.
7. CSV includes every case. The pytest ZIP includes executable code only for approved cases and retains the complete source suite as JSON.

## Production safety requirements

The MVP is deliberately local-first because it controls a browser and handles credentials. Before exposing it to other users:

- Put the API behind enterprise authentication and TLS; never deploy the crawler as an anonymous public endpoint.
- Add an application allowlist and outbound network policy. The current same-origin rule controls agent actions but the user-supplied starting URL can still target an internal host by design.
- Use a secret manager and short-lived test accounts. The in-memory vault is appropriate for a single-process MVP, not a distributed deployment.
- Run each crawl in an isolated container/VM with CPU, memory, duration, and network limits.
- Keep `allow_mutations=false` against production. Use a masked staging copy for creation, update, deletion, payment, messaging, or other state-changing paths.
- Add roles as separate projects or extend the schema with role-specific credential handles; do not give one crawl a privileged production administrator account.
- Treat inferred business meaning and negative/edge coverage as proposals. Human approval is required before execution.
- Pin and scan Playwright MCP, Copilot SDK, browsers, and Python/Node dependencies in CI instead of using floating packages in production.

## Known MVP boundaries

- One credential set and one browser context per project.
- No CAPTCHA/MFA automation; use storage-state bootstrap or a controlled human checkpoint when adding that capability.
- Uploaded files, cross-origin SSO, pop-up-heavy workflows, canvas-only controls, and destructive flows need purpose-built policy modules.
- Generated locators are only as strong as the observed accessibility contract. Add stable test IDs to the upgraded application where possible.
- Crawling alone cannot reveal server-only rules, inaccessible roles, dormant features, batch jobs, or unlinked routes; supplement it with logs, API specifications, database constraints, and SME review.

See [ARCHITECTURE.md](ARCHITECTURE.md) for component contracts and the phased rollout.
