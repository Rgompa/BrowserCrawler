# Atlas QA architecture

## System boundary

```text
Browser UI (review only)
        |
        v
FastAPI control plane ---- SQLite (projects + test cases, no passwords)
        |
        +---- ephemeral credential vault (process memory)
        |
        +---- crawl orchestrator
                  |                         |
                  v                         v
        Playwright MCP session       GitHub Copilot SDK
        isolated browser             JSON decisions + cases
                  |                         ^
                  +-- redacted evidence ---+
        |
        +---- CSV exporter
        +---- deterministic pytest compiler --> ZIP
```

The LLM never receives the plaintext credential payload. It uses `$USERNAME` and `$PASSWORD` placeholders; the orchestrator resolves them immediately before a browser tool call and redacts matching values from browser output before analysis or persistence.

## Core contracts

### Browser action

Copilot returns exactly one action at a time:

```json
{
  "stop": false,
  "tool": "browser_click",
  "arguments": { "element": "Orders link", "target": "ref-42" },
  "flow": "Order management",
  "observation": "Orders are available from the account navigation",
  "reason": "Explore the primary post-login flow"
}
```

The service validates the tool name, same-origin navigation, action budget, and mutation policy before execution. Raw JavaScript/browser-code tools are never exposed.

### Test case

Each case keeps business-readable steps plus optional automation metadata. This separation lets reviewers improve the specification without forcing generated Python code into the database.

```json
{
  "id": "ORD-012",
  "title": "Reject a quantity above the allowed maximum",
  "flow": "Order management",
  "type": "Edge",
  "priority": "P1",
  "status": "Needs review",
  "preconditions": ["User is signed in"],
  "steps": [{
    "action": "Enter one above the maximum quantity",
    "expected": "The field is invalid and submission is blocked",
    "automation": { "kind": "fill", "role": "spinbutton", "name": "Quantity", "value": "101" }
  }],
  "evidence": ["Observed quantity control on /orders/new"]
}
```

## Coverage strategy

For every grounded flow, Copilot is asked to consider:

- Happy path and alternate valid path
- Required/optional fields, format validation, empty values, min/max, just-inside and just-outside boundaries
- Invalid credentials, authorization and direct URL access
- Duplicate submit, refresh/back behavior, session expiry, retry/recovery, and empty states
- Cross-field rules and persisted-state verification

Cases unsupported by direct evidence must be marked `Needs review`. Coverage counts are not a proof of completeness.

## Recommended rollout

### Phase 1 — Discovery pilot

Run read-only against a non-production clone with one low-privilege account. Compare the generated flow map to SME knowledge and web access logs. Establish a coverage baseline and tune prompts/policies.

### Phase 2 — Regression specification

Add role-specific projects, reviewer identity/audit history, deduplication across crawls, and links from every case to snapshots and routes. Export approved CSV into the test-management system.

### Phase 3 — Automation

Execute generated pytest only in CI against controlled test data. Add deterministic fixtures, database/API setup and cleanup, test IDs, trace retention, quarantine, retries only for known infrastructure faults, and migration comparison runs against old and new backends.

### Phase 4 — Change intelligence

Schedule paired crawls, diff accessibility/page/flow graphs, classify breaking changes, and selectively regenerate affected tests. Keep approved historical cases immutable and version generated automation.

## Deployment recommendation

Host the static UI separately from the crawler workers. Run the FastAPI API and each browser session inside a private, authenticated worker environment with restricted outbound access. Use a durable queue, Postgres, encrypted object storage for optional traces, and a secret manager. A serverless edge worker is not an appropriate runtime for the Python Copilot SDK plus Chromium browser processes.
