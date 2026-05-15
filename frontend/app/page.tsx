"use client";

import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ClipboardList,
  Edit3,
  GitBranch,
  KeyRound,
  Loader2,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Trash2,
  TicketCheck
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";

type Tab = "workbench" | "settings";

type Ticket = {
  id: string;
  title: string;
  status: string;
  assignee: string;
  updated_at: string;
  description: string;
  comments: string[];
  brd_links: string[];
  brd_attachments: Array<{ filename: string; href: string; download_url: string }>;
  source: "live" | "mock";
};

type Repository = {
  id: string;
  name: string;
  path: string;
  default_branch: string;
  web_url: string;
  source: "live" | "mock";
};

type Branch = {
  name: string;
  protected: boolean;
  default: boolean;
  source: "live" | "mock";
};

type Requirement = {
  id: string;
  title: string;
  summary: string;
  current_behavior: string;
  expected_behavior: string;
  acceptance_criteria: string[];
  open_questions: string[];
};

type Analysis = {
  source: "live" | "mock";
  brd_url: string;
  brd_text_status: string;
  summary: string[];
  requirements: Requirement[];
  current_behavior: string[];
  expected_behavior: string[];
  current_flow: string[];
  expected_flow: string[];
  open_questions: string[];
  acceptance_criteria: string[];
  metadata: Record<string, string | boolean | null>;
};

type TestCase = {
  id: string;
  title: string;
  category: "existing" | "new";
  priority: "P0" | "P1" | "P2";
  test_type: "sanity" | "functional" | "negative" | "edge" | "regression" | "integration";
  preconditions: string[];
  steps: string[];
  expected_result: string;
  coverage: string;
};

type TestCaseMeta = {
  engine: "llm" | "rule_based";
  model: string;
};

type SettingsStatus = {
  project: StatusBlock;
  scm: StatusBlock;
  google: StatusBlock;
  llm: StatusBlock;
  mock_fallback_enabled: boolean;
};

type StatusBlock = {
  configured: boolean;
  base_url?: string;
  token_saved: boolean;
  mode?: string;
  provider?: string;
  model?: string;
  redirect_uri?: string;
};

type SettingsForm = {
  project_token: string;
  scm_token: string;
  google_client_id: string;
  google_client_secret: string;
};

const defaultSettings: SettingsForm = {
  project_token: "",
  scm_token: "",
  google_client_id: "",
  google_client_secret: ""
};

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("workbench");
  const [status, setStatus] = useState<SettingsStatus | null>(null);

  async function refreshStatus() {
    const response = await fetch(`${API_BASE}/api/settings/status`);
    setStatus(await response.json());
  }

  useEffect(() => {
    refreshStatus().catch(() => setStatus(null));
  }, []);

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandIcon">
            <ShieldCheck size={28} />
          </span>
          <span>TraceFix AI</span>
        </div>
        <nav className="nav">
          <button
            className={activeTab === "workbench" ? "navItem active" : "navItem"}
            onClick={() => setActiveTab("workbench")}
          >
            <ClipboardList size={20} />
            Workbench
          </button>
          <button
            className={activeTab === "settings" ? "navItem active" : "navItem"}
            onClick={() => setActiveTab("settings")}
          >
            <Settings size={20} />
            Settings
          </button>
        </nav>
        <ConnectionRail status={status} />
      </aside>
      <section className="content">
        {activeTab === "workbench" ? (
          <Workbench />
        ) : (
          <SettingsPanel onSaved={refreshStatus} status={status} />
        )}
      </section>
    </main>
  );
}

function ConnectionRail({ status }: { status: SettingsStatus | null }) {
  const connected = status
    ? [status.project, status.scm, status.google].filter((item) => item.configured).length
    : 0;
  return (
    <div className="railStatus">
      <p>Connections</p>
      <strong>{connected}/3 configured</strong>
      <span>{status?.mock_fallback_enabled ? "Mock fallback on" : "Live only"}</span>
    </div>
  );
}

function Workbench() {
  const [ticketQuery, setTicketQuery] = useState("");
  const [repoQuery, setRepoQuery] = useState("");
  const [branchQuery, setBranchQuery] = useState("");
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);
  const [selectedRepo, setSelectedRepo] = useState<Repository | null>(null);
  const [selectedBranch, setSelectedBranch] = useState("");
  const [manualBrdUrl, setManualBrdUrl] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [testCaseMeta, setTestCaseMeta] = useState<TestCaseMeta | null>(null);
  const [editingCaseId, setEditingCaseId] = useState("");
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    loadTickets("").catch((err) => setError(err.message));
    loadRepos("").catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      loadTickets(ticketQuery).catch((err) => setError(err.message));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [ticketQuery]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      loadRepos(repoQuery).catch((err) => setError(err.message));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [repoQuery]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      if (selectedRepo) {
        loadBranches(selectedRepo.id, branchQuery).catch((err) => setError(err.message));
      }
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [selectedRepo, branchQuery]);

  const hasBrdAttachment = Boolean(selectedTicket?.brd_attachments?.length);
  const brdUrl = useMemo(
    () => manualBrdUrl.trim() || (hasBrdAttachment ? "" : selectedTicket?.brd_links?.[0] || ""),
    [hasBrdAttachment, manualBrdUrl, selectedTicket]
  );

  async function loadTickets(query: string) {
    const response = await fetch(`${API_BASE}/api/tickets?query=${encodeURIComponent(query)}`);
    if (!response.ok) throw new Error("Unable to fetch tickets");
    setTickets(await response.json());
  }

  async function loadRepos(query: string) {
    const response = await fetch(`${API_BASE}/api/scm/repos?query=${encodeURIComponent(query)}`);
    if (!response.ok) throw new Error("Unable to fetch repositories");
    setRepos(await response.json());
  }

  async function loadBranches(repoId: string, query: string) {
    const response = await fetch(
      `${API_BASE}/api/scm/repos/${encodeURIComponent(repoId)}/branches?query=${encodeURIComponent(query)}`
    );
    if (!response.ok) throw new Error("Unable to fetch branches");
    const branchList: Branch[] = await response.json();
    setBranches(branchList);
    setSelectedBranch((current) => {
      if (current && branchList.some((branch) => branch.name === current)) {
        return current;
      }
      return pickDefaultBranch(branchList, selectedRepo?.default_branch || "");
    });
  }

  async function selectTicket(ticket: Ticket) {
    setError("");
    setAnalysis(null);
    setTestCases([]);
    setTestCaseMeta(null);
    setEditingCaseId("");
    setLoading("ticket");
    try {
      const response = await fetch(`${API_BASE}/api/tickets/${encodeURIComponent(ticket.id)}`);
      if (!response.ok) throw new Error("Unable to fetch ticket details");
      const detail = await response.json();
      setSelectedTicket(detail);
      setManualBrdUrl(detail.brd_attachments?.length ? "" : detail.brd_links?.[0] || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to fetch ticket details");
    } finally {
      setLoading(null);
    }
  }

  async function selectRepo(repo: Repository) {
    setError("");
    setSelectedRepo(repo);
    setSelectedBranch("");
    setBranchQuery("");
    setBranches([]);
    setLoading("branches");
    try {
      const response = await fetch(`${API_BASE}/api/scm/repos/${encodeURIComponent(repo.id)}/branches`);
      if (!response.ok) throw new Error("Unable to fetch branches");
      const branchList: Branch[] = await response.json();
      setBranches(branchList);
      setSelectedBranch(pickDefaultBranch(branchList, repo.default_branch));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to fetch branches");
    } finally {
      setLoading(null);
    }
  }

  async function analyzeBrd() {
    if (!brdUrl) {
      if (!selectedTicket?.brd_attachments?.length) {
        setError("Select a ticket with a BRD link, BRD attachment, or enter a BRD URL manually.");
        return;
      }
    }
    if (!selectedTicket?.id && !brdUrl) {
      setError("Select a ticket or enter a BRD URL manually.");
      return;
    }
    setError("");
    setAnalysis(null);
    setTestCases([]);
    setTestCaseMeta(null);
    setEditingCaseId("");
    setLoading("analysis");
    try {
      const response = await fetch(`${API_BASE}/api/brd/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticket_id: selectedTicket?.id,
          brd_url: brdUrl,
          repo_id: selectedRepo?.id,
          branch: selectedBranch
        })
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Unable to analyze BRD");
      }
      setAnalysis(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to analyze BRD");
    } finally {
      setLoading(null);
    }
  }

  async function generateTestCases() {
    if (!analysis) {
      setError("Run BRD analysis before generating test cases.");
      return;
    }
    setError("");
    setLoading("testcases");
    try {
      const response = await fetch(`${API_BASE}/api/test-cases/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticket_id: selectedTicket?.id,
          repo_id: selectedRepo?.id,
          branch: selectedBranch,
          analysis
        })
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Unable to generate test cases");
      }
      const payload: { test_cases: TestCase[]; engine: "llm" | "rule_based"; model: string } = await response.json();
      setTestCases(payload.test_cases);
      setTestCaseMeta({ engine: payload.engine, model: payload.model });
      setEditingCaseId("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to generate test cases");
    } finally {
      setLoading(null);
    }
  }

  return (
    <>
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Milestone 1</p>
          <h1>Workbench</h1>
        </div>
        <button className="primaryAction" onClick={analyzeBrd} disabled={loading === "analysis"}>
          {loading === "analysis" ? <Loader2 className="spin" size={18} /> : <Bot size={18} />}
          Analyze BRD
        </button>
      </header>

      {error && (
        <div className="errorBanner">
          <AlertTriangle size={18} />
          {error}
        </div>
      )}

      <div className="workbenchGrid">
        <section className="panel">
          <div className="panelTitle">
            <TicketCheck size={19} />
            <h2>Assigned Tickets</h2>
          </div>
          <SearchBox
            value={ticketQuery}
            onChange={setTicketQuery}
            placeholder="Search by ticket ID or title"
          />
          <div className="listBox">
            {tickets.map((ticket) => (
              <button
                className={selectedTicket?.id === ticket.id ? "listItem selected" : "listItem"}
                key={ticket.id}
                onClick={() => selectTicket(ticket)}
              >
                <span>
                  <strong>{ticket.id}</strong>
                  <small>{ticket.title}</small>
                </span>
                <Tag>{ticket.source}</Tag>
              </button>
            ))}
            {!tickets.length && <EmptyState text="No open tickets assigned to you." />}
          </div>
        </section>

        <section className="panel repoPanel">
          <div className="panelTitle">
            <GitBranch size={19} />
            <h2>Select Repository & Branch</h2>
          </div>
          <SearchBox
            value={repoQuery}
            onChange={setRepoQuery}
            placeholder="Search repository"
          />
          <div className="listBox repoList">
            {repos.map((repo) => (
              <button
                className={selectedRepo?.id === repo.id ? "listItem selected" : "listItem"}
                key={repo.id}
                onClick={() => selectRepo(repo)}
              >
                <span>
                  <strong>{repo.name}</strong>
                  <small>{repo.path}</small>
                </span>
                <Tag>{repo.source}</Tag>
              </button>
            ))}
            {!repos.length && <EmptyState text="No repositories found." />}
          </div>
          <div className="field compact">
            <span>Target branch</span>
            <SearchBox
              value={branchQuery}
              onChange={setBranchQuery}
              placeholder="Search branch, e.g. production"
            />
            <select
              value={selectedBranch}
              onChange={(event) => setSelectedBranch(event.target.value)}
              disabled={!selectedRepo || loading === "branches"}
            >
              <option value="">
                {loading === "branches" ? "Loading branches..." : "Select branch"}
              </option>
              {branches.map((branch) => (
                <option key={branch.name} value={branch.name}>
                  {branch.name}
                  {branch.default ? " (default)" : ""}
                </option>
              ))}
            </select>
          </div>
        </section>
      </div>

      <section className="panel detailPanel">
        <div className="panelTitle">
          <ClipboardList size={19} />
          <h2>Ticket & BRD Source</h2>
        </div>
        {selectedTicket ? (
          <div className="ticketDetailWrap">
            <div className="ticketDetail">
              <div>
                <p className="detailLabel">Selected ticket</p>
                <h3>
                  {selectedTicket.id} · {selectedTicket.title}
                </h3>
                <div className="ticketMetaLine">
                  <span>Assignee: {selectedTicket.assignee || "Unassigned"}</span>
                  {selectedTicket.updated_at ? <span>Updated: {formatDate(selectedTicket.updated_at)}</span> : null}
                </div>
              </div>
              <div className="detailMeta">
                <Tag>{selectedTicket.status}</Tag>
                {loading === "ticket" && <Tag>loading</Tag>}
              </div>
            </div>

            <div className="ticketDataGrid">
              <section className="ticketDataBlock ticketDescriptionBlock">
                <div className="ticketDataHeader">
                  <span>Ticket description</span>
                  <Tag>{selectedTicket.description?.trim() ? "loaded" : "empty"}</Tag>
                </div>
                <p className="ticketText">
                  {selectedTicket.description?.trim() || "No description returned for this ticket."}
                </p>
              </section>

              <section className="ticketDataBlock">
                <div className="ticketDataHeader">
                  <span>Ticket files & links</span>
                  <Tag>{selectedTicket.brd_attachments?.length || selectedTicket.brd_links?.length ? "found" : "none"}</Tag>
                </div>
                {selectedTicket.brd_attachments?.length ? (
                  <ul className="compactList">
                    {selectedTicket.brd_attachments.map((attachment) => (
                      <li key={`${attachment.filename}-${attachment.href}`}>{attachment.filename}</li>
                    ))}
                  </ul>
                ) : selectedTicket.brd_links?.length ? (
                  <ul className="compactList">
                    {selectedTicket.brd_links.map((link) => (
                      <li key={link}>{link}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="ticketText mutedText">No BRD attachment or link returned.</p>
                )}
              </section>

              <section className="ticketDataBlock ticketCommentsBlock">
                <div className="ticketDataHeader">
                  <span>Comments</span>
                  <Tag>{selectedTicket.comments?.length || 0}</Tag>
                </div>
                {selectedTicket.comments?.length ? (
                  <ul className="commentList">
                    {selectedTicket.comments.slice(0, 6).map((comment, index) => (
                      <li key={`${index}-${comment.slice(0, 24)}`}>{comment}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="ticketText mutedText">No comments returned for this ticket.</p>
                )}
              </section>
            </div>
          </div>
        ) : (
          <EmptyState text="Select a ticket to inspect its BRD link." />
        )}
        <label className="field">
          <span>{hasBrdAttachment ? "Manual BRD URL fallback" : "Detected or manual BRD URL"}</span>
          <input
            value={manualBrdUrl}
            onChange={(event) => setManualBrdUrl(event.target.value)}
            placeholder="https://docs.google.com/document/d/..."
          />
        </label>
        {selectedTicket?.brd_attachments?.length ? (
          <div className="attachmentNotice">
            <strong>Primary BRD source:</strong>{" "}
            {selectedTicket.brd_attachments[0].filename} from the ticket files section will be analyzed first.
          </div>
        ) : null}
      </section>

      {analysis && (
        <>
          <AnalysisPanel analysis={analysis} />
          <div className="tcActionBar">
            <button className="primaryAction" onClick={generateTestCases} disabled={loading === "testcases"}>
              {loading === "testcases" ? <Loader2 className="spin" size={18} /> : <Sparkles size={18} />}
              Generate TC
            </button>
          </div>
        </>
      )}
      {testCases.length ? (
        <TestCasePanel
          testCases={testCases}
          meta={testCaseMeta}
          editingCaseId={editingCaseId}
          onEdit={setEditingCaseId}
          onChange={setTestCases}
        />
      ) : null}
    </>
  );
}

function pickDefaultBranch(branches: Branch[], repoDefault: string) {
  return (
    branches.find((branch) => branch.name.toLowerCase() === "production")?.name ||
    branches.find((branch) => branch.default)?.name ||
    branches.find((branch) => branch.name === repoDefault)?.name ||
    repoDefault ||
    branches[0]?.name ||
    ""
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function SettingsPanel({
  onSaved,
  status
}: {
  onSaved: () => Promise<void>;
  status: SettingsStatus | null;
}) {
  const [form, setForm] = useState<SettingsForm>(defaultSettings);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [redirectUri, setRedirectUri] = useState("");

  useEffect(() => {
    setRedirectUri(`${window.location.origin}/api/google/oauth/callback`);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form)
      });
      if (!response.ok) throw new Error("Unable to save settings");
      await onSaved();
      setMessage("Settings saved. Blank secret fields kept existing saved values.");
      setForm((current) => ({
        ...current,
        project_token: "",
        scm_token: "",
        google_client_secret: ""
      }));
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Unable to save settings");
    } finally {
      setSaving(false);
    }
  }

  function update<K extends keyof SettingsForm>(key: K, value: SettingsForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  return (
    <>
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Application</p>
          <h1>Settings</h1>
        </div>
      </header>
      <div className="settingsGrid">
        <form className="settingsForm" onSubmit={submit}>
          <section className="panel">
            <div className="panelTitle">
              <KeyRound size={19} />
              <h2>Connection Tokens</h2>
            </div>
            <div className="formGrid">
              <label className="field">
                <span>OpenProject API token</span>
                <input
                  type="password"
                  value={form.project_token}
                  onChange={(event) => update("project_token", event.target.value)}
                  placeholder={status?.project.token_saved ? "Saved token kept if blank" : ""}
                />
              </label>
              <label className="field">
                <span>scm.intermesh.net API token</span>
                <input
                  type="password"
                  value={form.scm_token}
                  onChange={(event) => update("scm_token", event.target.value)}
                  placeholder={status?.scm.token_saved ? "Saved token kept if blank" : ""}
                />
              </label>
              <label className="field">
                <span>Google OAuth Client ID</span>
                <input
                  value={form.google_client_id}
                  onChange={(event) => update("google_client_id", event.target.value)}
                  placeholder="...apps.googleusercontent.com"
                />
              </label>
              <label className="field">
                <span>Google OAuth Client Secret</span>
                <input
                  type="password"
                  value={form.google_client_secret}
                  onChange={(event) => update("google_client_secret", event.target.value)}
                  placeholder={status?.google.token_saved ? "Saved secret kept if blank" : ""}
                />
              </label>
            </div>
            <p className="statusNote tokenNote">
              Project and SCM hosts are fixed to project.intermesh.net and scm.intermesh.net.
              Add this exact redirect URI in Google Cloud:
            </p>
            <code className="redirectUri">
              {status?.google.redirect_uri || redirectUri || "http://localhost:3000/api/google/oauth/callback"}
            </code>
            <p className="statusNote tokenNote">
              If you open this app from a different host or port, Google must allow that exact URI.
            </p>
            <div className="formActions">
              <button className="primaryAction" disabled={saving}>
                {saving ? <Loader2 className="spin" size={18} /> : <CheckCircle2 size={18} />}
                Save Settings
              </button>
              <a className="secondaryAction" href={`${API_BASE}/api/google/oauth/start`}>
                Connect Google
              </a>
              {message && <span className="formMessage">{message}</span>}
            </div>
          </section>
        </form>

        <section className="panel statusPanel">
          <div className="panelTitle">
            <ShieldCheck size={19} />
            <h2>Connection Status</h2>
          </div>
          <StatusRow label="Project" item={status?.project} />
          <StatusRow label="SCM" item={status?.scm} />
          <StatusRow label="Google" item={status?.google} />
          <StatusRow label="LLM Gateway" item={status?.llm} />
          <p className="statusNote">
            Tokens are submitted to the backend settings API and are not stored in browser
            localStorage.
          </p>
        </section>
      </div>
    </>
  );
}

function StatusRow({ label, item }: { label: string; item?: StatusBlock }) {
  return (
    <div className="statusRow">
      <span>{label}</span>
      <strong className={item?.configured ? "ok" : "pending"}>
        {item?.configured ? "Configured" : "Fallback / missing"}
      </strong>
    </div>
  );
}

function SearchBox({
  value,
  onChange,
  placeholder
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <label className="searchBox">
      <Search size={18} />
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return <span className="tag">{children}</span>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="emptyState">{text}</div>;
}

function AnalysisPanel({ analysis }: { analysis: Analysis }) {
  return (
    <section className="analysis">
      <div className="analysisHeader">
        <div>
          <p className="eyebrow">BRD Analysis</p>
          <h2>Requirement Summary</h2>
        </div>
        <Tag>{analysis.source}</Tag>
      </div>
      <p className="docStatus">{analysis.brd_text_status}</p>
      <div className="analysisGrid">
        <div className="panel summaryPanel">
          <h3>Summary</h3>
          <ul>
            {analysis.summary.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="flowGrid">
          <div className="panel flowPanel">
            <h3>Current Behavior</h3>
            <FlowDiagram items={analysis.current_flow.length ? analysis.current_flow : analysis.current_behavior} />
          </div>
          <div className="panel flowPanel">
            <h3>Expected Behavior</h3>
            <FlowDiagram items={analysis.expected_flow.length ? analysis.expected_flow : analysis.expected_behavior} />
          </div>
        </div>
      </div>
    </section>
  );
}

function TestCasePanel({
  testCases,
  meta,
  editingCaseId,
  onEdit,
  onChange
}: {
  testCases: TestCase[];
  meta: TestCaseMeta | null;
  editingCaseId: string;
  onEdit: (id: string) => void;
  onChange: (cases: TestCase[]) => void;
}) {
  const existingCases = testCases.filter((testCase) => testCase.category === "existing");
  const newCases = testCases.filter((testCase) => testCase.category === "new");

  function updateCase(id: string, patch: Partial<TestCase>) {
    onChange(testCases.map((testCase) => (testCase.id === id ? { ...testCase, ...patch } : testCase)));
  }

  function deleteCase(id: string) {
    onChange(testCases.filter((testCase) => testCase.id !== id));
    if (editingCaseId === id) onEdit("");
  }

  function addCase() {
    const nextNumber = testCases.length + 1;
    const id = `TC-${String(nextNumber).padStart(3, "0")}`;
    onChange([
      ...testCases,
      {
        id,
        title: "New custom test case",
        category: "new",
        priority: "P1",
        test_type: "functional",
        preconditions: ["Add precondition"],
        steps: ["Add test step"],
        expected_result: "Add expected result",
        coverage: "Manual addition"
      }
    ]);
    onEdit(id);
  }

  return (
    <section className="tcPanel">
      <div className="tcHeader">
        <div>
          <p className="eyebrow">TC Generation</p>
          <h2>Generated Test Coverage</h2>
          {meta ? (
            <p className="tcEngine">
              Generated by {meta.engine === "llm" ? "LLM Gateway" : "rule-based fallback"}
              {meta.model ? ` · ${meta.model}` : ""}
            </p>
          ) : null}
        </div>
        <button className="secondaryAction" onClick={addCase}>
          <Plus size={17} />
          Add Test Case
        </button>
      </div>
      <div className="tcMetrics">
        <Metric label="Existing sanity/regression" value={existingCases.length} />
        <Metric label="New requirement coverage" value={newCases.length} />
        <Metric label="Total test cases" value={testCases.length} />
      </div>
      <div className="tcColumns">
        <TcGroup
          title="Existing System Sanity"
          subtitle="Keeps current template flow from breaking"
          testCases={existingCases}
          editingCaseId={editingCaseId}
          onEdit={onEdit}
          onUpdate={updateCase}
          onDelete={deleteCase}
        />
        <TcGroup
          title="New Requirement TC"
          subtitle="Covers product image media-header behavior and edge cases"
          testCases={newCases}
          editingCaseId={editingCaseId}
          onEdit={onEdit}
          onUpdate={updateCase}
          onDelete={deleteCase}
        />
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="tcMetric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function TcGroup({
  title,
  subtitle,
  testCases,
  editingCaseId,
  onEdit,
  onUpdate,
  onDelete
}: {
  title: string;
  subtitle: string;
  testCases: TestCase[];
  editingCaseId: string;
  onEdit: (id: string) => void;
  onUpdate: (id: string, patch: Partial<TestCase>) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="tcGroup">
      <div className="tcGroupHeader">
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
        <Tag>{testCases.length}</Tag>
      </div>
      <div className="tcList">
        {testCases.map((testCase) => (
          <TcCard
            key={testCase.id}
            testCase={testCase}
            editing={editingCaseId === testCase.id}
            onEdit={onEdit}
            onUpdate={onUpdate}
            onDelete={onDelete}
          />
        ))}
      </div>
    </div>
  );
}

function TcCard({
  testCase,
  editing,
  onEdit,
  onUpdate,
  onDelete
}: {
  testCase: TestCase;
  editing: boolean;
  onEdit: (id: string) => void;
  onUpdate: (id: string, patch: Partial<TestCase>) => void;
  onDelete: (id: string) => void;
}) {
  const stepsText = testCase.steps.join("\n");
  const preconditionsText = testCase.preconditions.join("\n");

  return (
    <article className={testCase.category === "new" ? "tcCard tcCardNew" : "tcCard"}>
      <div className="tcCardTop">
        <div>
          <div className="tcBadges">
            <Tag>{testCase.id}</Tag>
            <Tag>{testCase.priority}</Tag>
            <Tag>{testCase.test_type}</Tag>
          </div>
          {editing ? (
            <input
              className="tcTitleInput"
              value={testCase.title}
              onChange={(event) => onUpdate(testCase.id, { title: event.target.value })}
            />
          ) : (
            <h4>{testCase.title}</h4>
          )}
        </div>
        <div className="tcActions">
          <button className="iconAction" onClick={() => onEdit(editing ? "" : testCase.id)} title="Modify test case">
            <Edit3 size={16} />
          </button>
          <button className="iconAction danger" onClick={() => onDelete(testCase.id)} title="Delete test case">
            <Trash2 size={16} />
          </button>
        </div>
      </div>
      {editing ? (
        <div className="tcEditGrid">
          <label>
            Preconditions
            <textarea
              value={preconditionsText}
              onChange={(event) =>
                onUpdate(testCase.id, {
                  preconditions: event.target.value.split("\n").filter(Boolean)
                })
              }
            />
          </label>
          <label>
            Steps
            <textarea
              value={stepsText}
              onChange={(event) =>
                onUpdate(testCase.id, {
                  steps: event.target.value.split("\n").filter(Boolean)
                })
              }
            />
          </label>
          <label>
            Expected Result
            <textarea
              value={testCase.expected_result}
              onChange={(event) => onUpdate(testCase.id, { expected_result: event.target.value })}
            />
          </label>
        </div>
      ) : (
        <>
          <div className="tcSection">
            <span>Preconditions</span>
            <ul>{testCase.preconditions.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
          <div className="tcSection">
            <span>Steps</span>
            <ol>{testCase.steps.map((item) => <li key={item}>{item}</li>)}</ol>
          </div>
          <div className="tcExpected">
            <span>Expected</span>
            <p>{testCase.expected_result}</p>
          </div>
        </>
      )}
    </article>
  );
}

function FlowDiagram({ items }: { items: string[] }) {
  const nodes = items.map(parseFlowStep);
  const root = nodes.find((node) => node.type === "start") || nodes[0] || { type: "start", text: "Flow start" };
  const rest = nodes.filter((node) => node !== root);
  const firstDecisionIndex = rest.findIndex((node) => node.type === "decision");
  const beforeDecision = firstDecisionIndex >= 0 ? rest.slice(0, firstDecisionIndex) : rest;
  const decision = firstDecisionIndex >= 0 ? rest[firstDecisionIndex] : null;
  const afterDecision = firstDecisionIndex >= 0 ? rest.slice(firstDecisionIndex + 1) : [];
  const yesBranch = afterDecision.filter((node) => node.type === "yes" || node.type === "decision").slice(0, 5);
  const noBranch = afterDecision.filter((node) => node.type === "no").slice(0, 3);
  const sharedTail = afterDecision.filter((node) => node.type === "process" || node.type === "end").slice(0, 4);

  return (
    <div className="flowDiagram" aria-label="behavior flow diagram">
      <FlowNode node={root} />
      {beforeDecision.map((node, index) => (
        <FlowNode node={node} key={`pre-${node.text}-${index}`} />
      ))}
      {decision ? <FlowNode node={decision} /> : null}
      {decision ? (
        <div className="flowSplit">
          <div className="flowLane">
            <span className="laneLabel">No</span>
            {(noBranch.length ? noBranch : [{ type: "no", text: "Skip / keep existing behavior" }]).map((node, index) => (
              <FlowNode node={node} key={`no-${node.text}-${index}`} />
            ))}
          </div>
          <div className="flowLane">
            <span className="laneLabel">Yes</span>
            {yesBranch.map((node, index) => (
              <FlowNode node={node} key={`yes-${node.text}-${index}`} />
            ))}
          </div>
        </div>
      ) : null}
      {sharedTail.map((node, index) => (
        <FlowNode node={node} key={`tail-${node.text}-${index}`} />
      ))}
    </div>
  );
}

type FlowStep = {
  type: string;
  text: string;
};

function parseFlowStep(value: string): FlowStep {
  const match = value.match(/^(start|process|decision|yes|no|end):\s*(.+)$/i);
  if (!match) {
    return { type: value.includes("?") ? "decision" : "process", text: value };
  }
  return { type: match[1].toLowerCase(), text: match[2] };
}

function FlowNode({ node }: { node: FlowStep }) {
  return (
    <div className={`flowNode flowNode-${node.type}`}>
      <p>{node.text}</p>
    </div>
  );
}
