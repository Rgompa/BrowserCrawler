"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type CaseType = "Positive" | "Negative" | "Edge";
type CaseStatus = "Ready" | "Needs review";

type TestCase = {
  id: string;
  title: string;
  flow: string;
  type: CaseType;
  priority: "P0" | "P1" | "P2";
  status: CaseStatus;
  preconditions: string[];
  steps: Array<{ action: string; expected: string }>;
};

type Project = {
  id: string;
  name: string;
  base_url: string;
  status: "queued" | "crawling" | "analyzing" | "ready" | "failed";
  progress: number;
  pages_discovered: number;
  flows_discovered: number;
  test_case_count: number;
  message?: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const sampleCases: TestCase[] = [
  {
    id: "AUTH-001",
    title: "Sign in with a valid account",
    flow: "Authentication",
    type: "Positive",
    priority: "P0",
    status: "Ready",
    preconditions: ["Active user account exists", "User is signed out"],
    steps: [
      { action: "Open the sign-in page", expected: "Username and password fields are visible" },
      { action: "Enter valid credentials and submit", expected: "The account dashboard opens" },
      { action: "Refresh the page", expected: "The authenticated session remains active" },
    ],
  },
  {
    id: "AUTH-004",
    title: "Reject an incorrect password",
    flow: "Authentication",
    type: "Negative",
    priority: "P0",
    status: "Ready",
    preconditions: ["Active user account exists"],
    steps: [
      { action: "Enter a valid username and incorrect password", expected: "No account data is displayed" },
      { action: "Submit the sign-in form", expected: "A safe validation message is shown" },
    ],
  },
  {
    id: "ORD-012",
    title: "Submit an order at the maximum allowed quantity",
    flow: "Order management",
    type: "Edge",
    priority: "P1",
    status: "Needs review",
    preconditions: ["User is signed in", "A purchasable item exists"],
    steps: [
      { action: "Open an item and enter the maximum quantity", expected: "The value is accepted" },
      { action: "Submit the order", expected: "A single order is created with the correct total" },
    ],
  },
  {
    id: "ORD-015",
    title: "Prevent submission with a quantity above the limit",
    flow: "Order management",
    type: "Negative",
    priority: "P1",
    status: "Ready",
    preconditions: ["User is signed in"],
    steps: [
      { action: "Enter a quantity one above the allowed maximum", expected: "The field is marked invalid" },
      { action: "Attempt to submit", expected: "No order is created" },
    ],
  },
  {
    id: "PRF-003",
    title: "Update account contact details",
    flow: "Profile",
    type: "Positive",
    priority: "P2",
    status: "Needs review",
    preconditions: ["User is signed in"],
    steps: [
      { action: "Open Profile and change the phone number", expected: "The value passes validation" },
      { action: "Save and reopen Profile", expected: "The new phone number persists" },
    ],
  },
];

function caseFromApi(raw: Record<string, unknown>): TestCase {
  const steps = Array.isArray(raw.steps) ? raw.steps : [];
  return {
    id: String(raw.id ?? "CASE"),
    title: String(raw.title ?? "Untitled test"),
    flow: String(raw.flow ?? "Unclassified"),
    type: (raw.type as CaseType) ?? "Positive",
    priority: (raw.priority as TestCase["priority"]) ?? "P2",
    status: (raw.status as CaseStatus) ?? "Needs review",
    preconditions: Array.isArray(raw.preconditions) ? raw.preconditions.map(String) : [],
    steps: steps.map((step) => {
      const value = step as Record<string, unknown>;
      return { action: String(value.action ?? ""), expected: String(value.expected ?? "") };
    }),
  };
}

export default function Home() {
  const [project, setProject] = useState<Project | null>(null);
  const [cases, setCases] = useState<TestCase[]>(sampleCases);
  const [selectedId, setSelectedId] = useState(sampleCases[0].id);
  const [filter, setFilter] = useState<"All" | CaseType>("All");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("Sample review set — start a discovery run to replace it.");
  const [submitting, setSubmitting] = useState(false);

  const filtered = useMemo(() => cases.filter((item) => {
    const matchesType = filter === "All" || item.type === filter;
    const text = `${item.id} ${item.title} ${item.flow}`.toLowerCase();
    return matchesType && text.includes(query.toLowerCase());
  }), [cases, filter, query]);

  const selected = cases.find((item) => item.id === selectedId) ?? cases[0];
  const counts = useMemo(() => ({
    Positive: cases.filter((item) => item.type === "Positive").length,
    Negative: cases.filter((item) => item.type === "Negative").length,
    Edge: cases.filter((item) => item.type === "Edge").length,
  }), [cases]);

  useEffect(() => {
    if (!project || project.status === "ready" || project.status === "failed") return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/api/projects/${project.id}`);
        if (!response.ok) return;
        const next: Project = await response.json();
        setProject(next);
        setNotice(next.message ?? `Discovery ${next.progress}% complete`);
        if (next.status === "ready") {
          const casesResponse = await fetch(`${API_BASE}/api/projects/${project.id}/test-cases`);
          const data = await casesResponse.json();
          const normalized = (data.items ?? []).map(caseFromApi);
          setCases(normalized);
          if (normalized[0]) setSelectedId(normalized[0].id);
          setNotice(`${normalized.length} regression cases are ready for review.`);
        }
      } catch {
        setNotice("The crawler service is not reachable. Start the local API and try again.");
      }
    }, 2200);
    return () => window.clearInterval(timer);
  }, [project]);

  async function startDiscovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    const form = new FormData(event.currentTarget);
    const body = {
      name: String(form.get("name") || "Legacy application"),
      base_url: String(form.get("url") || ""),
      username: String(form.get("username") || ""),
      password: String(form.get("password") || ""),
      max_pages: Number(form.get("max_pages") || 25),
    };
    try {
      const response = await fetch(`${API_BASE}/api/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await response.text());
      const next = await response.json();
      setProject(next);
      setCases([]);
      setNotice("Secure browser session queued. Credentials are held in memory only.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not start discovery.");
    } finally {
      setSubmitting(false);
    }
  }

  function updateSelected(patch: Partial<TestCase>) {
    if (!selected) return;
    setCases((items) => items.map((item) => item.id === selected.id ? { ...item, ...patch } : item));
  }

  async function saveReview() {
    if (!selected) return;
    if (!project || project.status !== "ready") {
      setNotice("Sample review saved in this browser session.");
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/api/projects/${project.id}/test-cases/${selected.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(selected),
      });
      if (!response.ok) throw new Error(await response.text());
      const saved = caseFromApi(await response.json());
      setCases((items) => items.map((item) => item.id === saved.id ? saved : item));
      setNotice(`${saved.id} review saved. The pytest export will use this version.`);
    } catch {
      setNotice("Review could not be saved. The local edit is still visible.");
    }
  }

  function downloadCsv() {
    if (project?.status === "ready") {
      window.location.href = `${API_BASE}/api/projects/${project.id}/test-cases.csv`;
      return;
    }
    const rows = [["Test case ID", "Business flow", "Title", "Type", "Priority", "Preconditions", "Detailed steps", "Expected results"]];
    cases.forEach((item) => rows.push([
      item.id, item.flow, item.title, item.type, item.priority,
      item.preconditions.join("\n"),
      item.steps.map((step, index) => `${index + 1}. ${step.action}`).join("\n"),
      item.steps.map((step, index) => `${index + 1}. ${step.expected}`).join("\n"),
    ]));
    const csv = rows.map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(",")).join("\n");
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    anchor.download = "regression-test-cases.csv";
    anchor.click();
    URL.revokeObjectURL(anchor.href);
  }

  async function downloadPytest() {
    if (!project || project.status !== "ready") {
      setNotice("Complete a live discovery run before generating pytest automation.");
      return;
    }
    const response = await fetch(`${API_BASE}/api/projects/${project.id}/pytest.zip`, { method: "POST" });
    if (!response.ok) {
      setNotice("Automation generation failed. Review cases and try again.");
      return;
    }
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(await response.blob());
    anchor.download = `${project.name.toLowerCase().replaceAll(" ", "-")}-pytest.zip`;
    anchor.click();
    URL.revokeObjectURL(anchor.href);
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">A</span><span>Atlas QA</span><em>Flow discovery</em></div>
        <div className="top-actions"><span className="secure"><i /> Local credential vault</span><button className="avatar" aria-label="Account menu">QA</button></div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">Regression intelligence workspace</p>
          <h1>Turn an undocumented app into a testable map.</h1>
          <p className="hero-copy">Explore real screens with Playwright MCP, let Copilot infer business flows, then review every positive, negative, and edge case before generating pytest.</p>
        </div>
        <form className="launch-card" onSubmit={startDiscovery}>
          <div className="form-heading"><span>01</span><div><strong>Start discovery</strong><small>Credentials never persist to the project database.</small></div></div>
          <label>Application name<input name="name" placeholder="Claims portal" /></label>
          <label className="wide">Application URL<input name="url" type="url" placeholder="https://legacy.example.com" required /></label>
          <label>Username<input name="username" autoComplete="username" placeholder="Optional" /></label>
          <label>Password<input name="password" type="password" autoComplete="current-password" placeholder="Optional" /></label>
          <label>Page budget<select name="max_pages" defaultValue="25"><option value="10">10 pages</option><option value="25">25 pages</option><option value="50">50 pages</option></select></label>
          <button className="primary" disabled={submitting}>{submitting ? "Starting…" : "Discover business flows →"}</button>
        </form>
      </section>

      <section className="status-rail" aria-live="polite">
        <div className="run-state"><span className={project && project.status !== "failed" ? "pulse active" : "pulse"} /><div><small>Current run</small><strong>{project ? project.name : "Reviewing sample output"}</strong></div></div>
        <div className="progress-wrap"><div className="progress-label"><span>{notice}</span><b>{project?.progress ?? 100}%</b></div><div className="track"><i style={{ width: `${project?.progress ?? 100}%` }} /></div></div>
        <div className="metrics"><div><strong>{project?.pages_discovered ?? 14}</strong><span>Pages</span></div><div><strong>{project?.flows_discovered ?? 3}</strong><span>Flows</span></div><div><strong>{project?.test_case_count ?? cases.length}</strong><span>Cases</span></div></div>
      </section>

      <section className="workspace">
        <div className="workspace-head">
          <div><p className="eyebrow">02 · Review coverage</p><h2>Generated regression suite</h2></div>
          <div className="export-actions"><button className="secondary" onClick={downloadCsv}>↓ Export CSV</button><button className="dark" onClick={downloadPytest}>Generate pytest</button></div>
        </div>

        <div className="coverage-strip">
          {(["Positive", "Negative", "Edge"] as CaseType[]).map((type) => <div key={type}><span className={`legend ${type.toLowerCase()}`} /> <strong>{counts[type]}</strong> {type}</div>)}
          <div className="coverage-note">Coverage is proposed by Copilot and remains human-approved.</div>
        </div>

        <div className="review-grid">
          <aside className="case-list">
            <div className="list-tools"><input aria-label="Search test cases" placeholder="Search cases or flows" value={query} onChange={(event) => setQuery(event.target.value)} /><div className="filters">{(["All", "Positive", "Negative", "Edge"] as const).map((item) => <button key={item} className={filter === item ? "selected" : ""} onClick={() => setFilter(item)}>{item}</button>)}</div></div>
            <div className="rows">
              {filtered.map((item) => <button key={item.id} className={`case-row ${selected?.id === item.id ? "chosen" : ""}`} onClick={() => setSelectedId(item.id)}>
                <span className={`case-type ${item.type.toLowerCase()}`}>{item.type.slice(0, 1)}</span>
                <span className="case-copy"><small>{item.id} · {item.flow}</small><strong>{item.title}</strong><em>{item.steps.length} steps · {item.priority}</em></span>
                <span className="chevron">›</span>
              </button>)}
              {!filtered.length && <p className="empty">No cases match this view.</p>}
            </div>
          </aside>

          <article className="case-detail">
            {selected ? <>
              <div className="detail-head"><div><span className={`type-pill ${selected.type.toLowerCase()}`}>{selected.type}</span><span className="priority">{selected.priority}</span><h3>{selected.title}</h3><p>{selected.id} · {selected.flow}</p></div><label className="approval"><input type="checkbox" checked={selected.status === "Ready"} onChange={(event) => updateSelected({ status: event.target.checked ? "Ready" : "Needs review" })} /><span>Approved for automation</span></label></div>
              <div className="preconditions"><h4>Preconditions</h4>{selected.preconditions.map((item) => <p key={item}><span>✓</span>{item}</p>)}</div>
              <div className="step-table"><div className="step-header"><span>Step</span><span>Action</span><span>Expected result</span></div>{selected.steps.map((step, index) => <div className="step" key={`${step.action}-${index}`}><b>{String(index + 1).padStart(2, "0")}</b><textarea aria-label={`Action ${index + 1}`} value={step.action} onChange={(event) => updateSelected({ steps: selected.steps.map((item, i) => i === index ? { ...item, action: event.target.value } : item) })} /><textarea aria-label={`Expected result ${index + 1}`} value={step.expected} onChange={(event) => updateSelected({ steps: selected.steps.map((item, i) => i === index ? { ...item, expected: event.target.value } : item) })} /></div>)}</div>
              <footer className="detail-foot"><span><i /> Source: observed browser path</span><button onClick={saveReview}>Save review</button></footer>
            </> : <div className="no-selection"><strong>Waiting for discovery</strong><p>Test cases will appear here as the crawler completes business flows.</p></div>}
          </article>
        </div>
      </section>

      <section className="pipeline">
        <p className="eyebrow">How evidence becomes automation</p>
        <div className="pipeline-grid"><div><b>1</b><strong>Observe</strong><span>Accessibility snapshots, URLs, forms, and network-safe interactions.</span></div><div><b>2</b><strong>Infer</strong><span>Copilot groups paths into flows and proposes boundary conditions.</span></div><div><b>3</b><strong>Approve</strong><span>A reviewer edits steps, expected results, priority, and status.</span></div><div><b>4</b><strong>Generate</strong><span>Stable locators and approved cases compile into pytest-playwright.</span></div></div>
      </section>
    </main>
  );
}
