"use client";

import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ClipboardList,
  Edit3,
  FileSearch,
  GitBranch,
  History,
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
type DetailTab = "affected" | "trace" | "code" | "dependencies" | "rca";

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
  requirement_evidence: string[];
  code_evidence: string[];
  validation_level: string;
  missing_dependencies: string[];
  affected_files: string[];
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

type AffectedFile = {
  path: string;
  reason: string;
  confidence: "high" | "medium" | "low";
  related_requirement: string;
  suspected_module?: string;
  confidence_score?: number;
  matched_symbols?: string[];
  line_range?: string;
  evidence?: string[];
  evidence_snippets?: string[];
  expected_change?: string;
  status?: "to_be_modified" | "needs_investigation";
};

type MissingDependency = {
  name: string;
  reason: string;
  suggested_mock: string;
  db_validation_query: string;
};

type RcaHypothesis = {
  title: string;
  confidence: "high" | "medium" | "low";
  evidence: string[];
  likely_files: string[];
  suggested_checks: string[];
  suggested_fix_area: string;
  validation_level: string;
};

type CodeChangeSuggestion = {
  title: string;
  change_type: "modify" | "create" | "db" | "config" | "cross_repo" | "blocked";
  target_file: string;
  target_symbol: string;
  rationale: string;
  implementation_steps: string[];
  suggested_patch: string;
  safety_notes: string[];
  tests_to_add: string[];
  dependencies: string[];
  confidence: "high" | "medium" | "low";
  blocker_reason: string;
  validation_level: string;
};

type ImpactMetrics = {
  manual_analysis_estimate_minutes: number;
  tracefix_analysis_seconds: number;
  generated_test_cases: number;
  requirement_linked_cases: number;
  code_supported_cases: number;
  runtime_validated_cases: number;
};

type AgentStep = {
  step: string;
  status: "running" | "done" | "failed";
  message: string;
};

type AgentRunOutput = {
  analysis: Analysis;
  impact_analysis?: Record<string, unknown>;
  test_case_summary: string[];
  test_cases: TestCase[];
  affected_files: AffectedFile[];
  missing_dependencies: MissingDependency[];
  rca_hypotheses: RcaHypothesis[];
  code_change_suggestions: CodeChangeSuggestion[];
  impact_metrics: ImpactMetrics;
  suggested_agent_project_yml: string;
  steps: AgentStep[];
};

type AgentRun = {
  run_id: string;
  mode: string;
  ticket_id: string;
  repo_id: string;
  repo_name: string;
  branch: string;
  brd_source: string;
  files_used: string[];
  llm_model: string;
  status: "running" | "completed" | "failed";
  started_at: string;
  completed_at: string;
  output_json: AgentRunOutput | null;
  steps: AgentStep[];
  error: string;
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
          <span>Intelligent QA + RCA Agent</span>
        </div>
        <nav className="nav">
          <button
            className={activeTab === "workbench" ? "navItem active" : "navItem"}
            onClick={() => setActiveTab("workbench")}
          >
            <ClipboardList size={20} />
            BRD Analysis
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
  const [testCasesDirty, setTestCasesDirty] = useState(false);
  const [savingTestCases, setSavingTestCases] = useState(false);
  const [testCaseMeta, setTestCaseMeta] = useState<TestCaseMeta | null>(null);
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([]);
  const [selectedAgentRun, setSelectedAgentRun] = useState<AgentRun | null>(null);
  const [showGeneratedTc, setShowGeneratedTc] = useState(false);
  const [activeDetailTab, setActiveDetailTab] = useState<DetailTab>("affected");
  const [editingCaseId, setEditingCaseId] = useState("");
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState("");

  function clearBackendReachabilityError() {
    setError((current) => current.startsWith("QA + RCA backend is not reachable") ? "" : current);
  }

  useEffect(() => {
    loadTickets("").catch((err) => setError(err.message));
    loadRepos("").catch((err) => setError(err.message));
    loadAgentRuns().catch(() => undefined);
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

  useEffect(() => {
    if (selectedAgentRun?.status !== "running") {
      return;
    }
    const interval = window.setInterval(() => {
      refreshAgentRun(selectedAgentRun.run_id).catch((err) => setError(err.message));
    }, 2500);
    return () => window.clearInterval(interval);
  }, [selectedAgentRun?.run_id, selectedAgentRun?.status]);

  const hasBrdAttachment = Boolean(selectedTicket?.brd_attachments?.length);
  const brdUrl = useMemo(
    () => manualBrdUrl.trim() || (hasBrdAttachment ? "" : selectedTicket?.brd_links?.[0] || ""),
    [hasBrdAttachment, manualBrdUrl, selectedTicket]
  );

  async function loadTickets(query: string) {
    const response = await fetch(`${API_BASE}/api/tickets?query=${encodeURIComponent(query)}`);
    if (!response.ok) throw new Error("Unable to fetch tickets");
    setTickets(await response.json());
    clearBackendReachabilityError();
  }

  async function loadRepos(query: string) {
    const response = await fetch(`${API_BASE}/api/scm/repos?query=${encodeURIComponent(query)}`);
    if (!response.ok) throw new Error("Unable to fetch repositories");
    setRepos(await response.json());
    clearBackendReachabilityError();
  }

  async function loadBranches(repoId: string, query: string) {
    const response = await fetch(
      `${API_BASE}/api/scm/repos/${encodeURIComponent(repoId)}/branches?query=${encodeURIComponent(query)}`
    );
    if (!response.ok) throw new Error("Unable to fetch branches");
    const branchList: Branch[] = await response.json();
    setBranches(branchList);
    clearBackendReachabilityError();
    setSelectedBranch((current) => {
      if (current && branchList.some((branch) => branch.name === current)) {
        return current;
      }
      return pickDefaultBranch(branchList, selectedRepo?.default_branch || "");
    });
  }

  async function loadAgentRuns() {
    const response = await fetch(`${API_BASE}/api/agent-runs?limit=3`);
    if (!response.ok) throw new Error("Unable to fetch agent runs");
    setAgentRuns(await response.json());
    clearBackendReachabilityError();
  }

  async function refreshAgentRun(runId: string) {
    const response = await fetch(`${API_BASE}/api/agent-runs/${encodeURIComponent(runId)}`);
    if (!response.ok) throw new Error("Unable to fetch agent run status");
    const run: AgentRun = await response.json();
    applyRun(run);
    if (run.status !== "running") {
      await loadAgentRuns().catch(() => undefined);
    }
  }

  function applyRun(run: AgentRun) {
    setSelectedAgentRun(run);
    setAnalysis(run.output_json?.analysis || null);
    if (!testCasesDirty) {
      setTestCases(run.output_json?.test_cases || []);
    }
    setTestCaseMeta({ engine: "llm", model: run.llm_model });
    if (run.status === "failed") {
      setError(run.error || "BRD analysis failed");
    } else {
      setError("");
    }
  }

  async function selectTicket(ticket: Ticket) {
    setError("");
    setAnalysis(null);
    setTestCases([]);
    setTestCasesDirty(false);
    setTestCaseMeta(null);
    setShowGeneratedTc(false);
    setActiveDetailTab("affected");
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
    setTestCasesDirty(false);
    setTestCaseMeta(null);
    setSelectedAgentRun(null);
    setShowGeneratedTc(false);
    setActiveDetailTab("affected");
    setEditingCaseId("");
    setLoading("analysis");
    try {
      const response = await fetch(`${API_BASE}/api/agent-runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticket_id: selectedTicket?.id,
          brd_url: brdUrl,
          repo_id: selectedRepo?.id,
          repo_name: selectedRepo?.name || selectedRepo?.path || "",
          branch: selectedBranch
        })
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Unable to analyze BRD");
      }
      const run: AgentRun = await response.json();
      if (run.status === "failed") {
        throw new Error(run.error || "BRD analysis failed");
      }
      applyRun(run);
      setShowGeneratedTc(false);
      setActiveDetailTab("affected");
      await loadAgentRuns().catch(() => undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to analyze BRD");
    } finally {
      setLoading(null);
    }
  }

  function loadRunIntoWorkbench(run: AgentRun) {
    setTestCasesDirty(false);
    applyRun(run);
    setShowGeneratedTc(false);
    setActiveDetailTab("affected");
    setEditingCaseId("");
  }

  const runningRun = selectedAgentRun?.status === "running";

  function updateTestCases(cases: TestCase[]) {
    setTestCases(cases);
    setTestCasesDirty(true);
  }

  async function saveTestCases() {
    if (!selectedAgentRun?.run_id) return;
    setSavingTestCases(true);
    try {
      const response = await fetch(`${API_BASE}/api/agent-runs/${encodeURIComponent(selectedAgentRun.run_id)}/test-cases`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(testCases)
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Unable to save test cases");
      }
      const run: AgentRun = await response.json();
      setTestCasesDirty(false);
      setSelectedAgentRun(run);
      setTestCases(run.output_json?.test_cases || []);
      await loadAgentRuns().catch(() => undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save test cases");
    } finally {
      setSavingTestCases(false);
    }
  }

  return (
    <>
      <header className="pageHeader">
        <div>
          <h1>BRD Analysis</h1>
        </div>
        <button className="primaryAction" onClick={analyzeBrd} disabled={loading === "analysis" || runningRun}>
          {loading === "analysis" || runningRun ? <Loader2 className="spin" size={18} /> : <Bot size={18} />}
          {runningRun ? "Analyzing BRD" : "Analyze BRD"}
        </button>
      </header>

      {error && (
        <div className="errorBanner">
          <AlertTriangle size={18} />
          {error}
        </div>
      )}

      <div className="workbenchWithHistory">
        <div className="workbenchMain">
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

      {selectedAgentRun ? <AgentRunProgress run={selectedAgentRun} /> : null}

      {analysis && (
        <>
          <AnalysisPanel analysis={analysis} />
          <TcGenerationControl
            viewing={showGeneratedTc}
            hasCases={testCases.length > 0}
            onView={() => setShowGeneratedTc(true)}
            onClose={() => setShowGeneratedTc(false)}
          />
          {showGeneratedTc && testCases.length ? (
            <TestCasePanel
              testCases={testCases}
              editingCaseId={editingCaseId}
              onEdit={setEditingCaseId}
              onChange={updateTestCases}
              onSave={saveTestCases}
              dirty={testCasesDirty}
              saving={savingTestCases}
            />
          ) : null}
          {selectedAgentRun?.output_json ? (
            <TraceabilityPanels
              run={selectedAgentRun}
              output={selectedAgentRun.output_json}
              activeTab={activeDetailTab}
              onTabChange={setActiveDetailTab}
            />
          ) : null}
        </>
      )}
        </div>
        <TicketHistorySidebar
          runs={agentRuns}
          selectedRunId={selectedAgentRun?.run_id || ""}
          onSelect={loadRunIntoWorkbench}
        />
      </div>
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

function TicketHistorySidebar({
  runs,
  selectedRunId,
  onSelect
}: {
  runs: AgentRun[];
  selectedRunId: string;
  onSelect: (run: AgentRun) => void;
}) {
  return (
    <aside className="ticketHistorySidebar">
      <div className="ticketHistoryHeader">
        <div>
          <p className="eyebrow">OpenProject Account</p>
          <h2>Ticket History</h2>
        </div>
        <History size={19} />
      </div>
      <p className="historyNote">Showing the last 3 runs for the currently saved OpenProject API token.</p>
      <div className="ticketHistoryList">
        {runs.length ? (
          runs.slice(0, 3).map((run) => (
            <button
              key={run.run_id}
              className={selectedRunId === run.run_id ? "ticketHistoryItem selected" : "ticketHistoryItem"}
              onClick={() => onSelect(run)}
            >
              <span>
                <strong>{run.ticket_id}</strong>
                <small>{run.repo_name || run.repo_id || "repo"} · {run.branch || "branch"}</small>
                <small>{formatDate(run.started_at)}</small>
              </span>
              <Tag>{run.status}</Tag>
            </button>
          ))
        ) : (
          <EmptyState text="No ticket history for this OpenProject token yet." />
        )}
      </div>
    </aside>
  );
}

function AgentRunProgress({ run }: { run: AgentRun }) {
  const steps = run.output_json?.steps?.length ? run.output_json.steps : run.steps || [];
  return (
    <section className="panel runProgressPanel">
      <div className="panelTitle">
        {run.status === "running" ? <Loader2 className="spin" size={19} /> : <CheckCircle2 size={19} />}
        <h2>BRD Analysis Progress</h2>
      </div>
      <div className="progressMeta">
        <Tag>{run.repo_name || run.repo_id || "Selected repository"}</Tag>
        <Tag>{run.branch || "Selected branch"}</Tag>
        <Tag>{run.status}</Tag>
      </div>
      <div className="stepRail">
        {steps.length ? (
          steps.map((step) => (
            <div className={`stepPill ${step.status}`} key={`${step.step}-${step.message}`}>
              <CheckCircle2 size={15} />
              <span>{humanize(step.step)}</span>
            </div>
          ))
        ) : (
          <div className="stepPill running">
            <Loader2 className="spin" size={15} />
            <span>Starting run</span>
          </div>
        )}
      </div>
      {run.error ? <p className="docStatus">{run.error}</p> : null}
    </section>
  );
}

function AgentRunOverview({ run, output }: { run: AgentRun; output: AgentRunOutput }) {
  const metrics = output.impact_metrics;
  return (
    <section className="agentOverview">
      <div className="analysisHeader">
        <div>
          <p className="eyebrow">Traceability</p>
          <h2>Traceability Report</h2>
        </div>
        <ValidationBadge value={metrics.code_supported_cases ? "L2 Code-supported" : "L1 Requirement-derived"} />
      </div>
      <div className="stepRail">
        {output.steps.map((step) => (
          <div className={`stepPill ${step.status}`} key={`${step.step}-${step.message}`}>
            <CheckCircle2 size={15} />
            <span>{humanize(step.step)}</span>
          </div>
        ))}
      </div>
      <div className="tcMetrics impactMetrics">
        <Metric label="Manual baseline" value={metrics.manual_analysis_estimate_minutes} suffix="min" />
        <Metric label="Agent runtime" value={metrics.tracefix_analysis_seconds} suffix="sec" />
        <Metric label="Generated cases" value={metrics.generated_test_cases} />
        <Metric label="Requirement-linked" value={metrics.requirement_linked_cases} />
        <Metric label="Code-supported" value={metrics.code_supported_cases} />
        <Metric label="Runtime validated" value={metrics.runtime_validated_cases} />
      </div>
    </section>
  );
}

function TcGenerationControl({
  viewing,
  hasCases,
  onView,
  onClose
}: {
  viewing: boolean;
  hasCases: boolean;
  onView: () => void;
  onClose: () => void;
}) {
  return (
    <section className="panel tcGatePanel">
      <div>
        <p className="eyebrow">Quality Coverage</p>
        <h2>Generated Test Cases</h2>
      </div>
      <div className="tcGateActions">
        <span className="successNote">
          {hasCases ? "TC has been generated." : "No generated TC available."}
        </span>
        {viewing ? (
          <button className="secondaryAction" onClick={onClose}>
            Close
          </button>
        ) : (
          <button className="primaryAction" onClick={onView} disabled={!hasCases}>
            <Sparkles size={18} />
            View Generated TC
          </button>
        )}
      </div>
    </section>
  );
}

function TraceabilityPanels({
  run,
  output,
  activeTab,
  onTabChange
}: {
  run: AgentRun;
  output: AgentRunOutput;
  activeTab: DetailTab;
  onTabChange: (tab: DetailTab) => void;
}) {
  const tabs: Array<{ id: DetailTab; label: string; count?: number }> = [
    { id: "affected", label: "Affected Files", count: output.affected_files.length },
    { id: "trace", label: "Trace Report" },
    { id: "code", label: "Code Suggestions", count: output.code_change_suggestions?.length || 0 },
    { id: "dependencies", label: "Dependencies", count: output.missing_dependencies.length },
    { id: "rca", label: "RCA", count: output.rca_hypotheses.length }
  ];

  return (
    <section className="panel detailTabsPanel">
      <div className="panelTitle">
        <FileSearch size={19} />
        <h2>Implementation Details</h2>
      </div>
      <div className="detailTabs" role="tablist" aria-label="analysis details">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={activeTab === tab.id ? "detailTab active" : "detailTab"}
            onClick={() => onTabChange(tab.id)}
            type="button"
          >
            {tab.label}
            {typeof tab.count === "number" ? <span>{tab.count}</span> : null}
          </button>
        ))}
      </div>

      <div className="detailTabPanel">
        {activeTab === "affected" ? <AffectedFilesList files={output.affected_files} /> : null}
        {activeTab === "trace" ? <AgentRunOverview run={run} output={output} /> : null}
        {activeTab === "code" ? <CodeSuggestionList suggestions={output.code_change_suggestions || []} /> : null}
        {activeTab === "dependencies" ? <DependencyList dependencies={output.missing_dependencies} /> : null}
        {activeTab === "rca" ? <RcaList hypotheses={output.rca_hypotheses} /> : null}
      </div>
    </section>
  );
}

function AffectedFilesList({ files }: { files: AffectedFile[] }) {
  return (
    <div className="evidenceList">
      {files.length ? (
        files.map((file) => (
          <article className="evidenceCard" key={`${file.path}-${file.reason}`}>
            <div>
              <strong>{file.path}</strong>
              <p>{file.reason}</p>
              {file.expected_change ? <small>{file.expected_change}</small> : null}
            </div>
            <div className="evidenceTags">
              <Tag>{file.status || "needs_investigation"}</Tag>
              <Tag>{typeof file.confidence_score === "number" ? `${file.confidence_score}/100` : file.confidence}</Tag>
              <Tag>{file.related_requirement || "requirement"}</Tag>
            </div>
            {file.suspected_module || file.line_range || file.matched_symbols?.length ? (
              <div className="targetBox">
                {file.suspected_module ? <span><strong>Module:</strong> {file.suspected_module}</span> : null}
                {file.line_range ? <span><strong>Lines:</strong> {file.line_range}</span> : null}
                {file.matched_symbols?.length ? <span><strong>Symbols:</strong> {file.matched_symbols.join(", ")}</span> : null}
              </div>
            ) : null}
            <InfoList label="Evidence" items={file.evidence || []} />
            {file.evidence_snippets?.length ? (
              <div className="snippetList">
                {file.evidence_snippets.map((snippet, index) => (
                  <pre key={`${file.path}-snippet-${index}`}>{snippet}</pre>
                ))}
              </div>
            ) : null}
          </article>
        ))
      ) : (
        <EmptyState text="No code-supported affected files found." />
      )}
    </div>
  );
}

function DependencyList({ dependencies }: { dependencies: MissingDependency[] }) {
  return (
    <div className="evidenceList">
      {dependencies.length ? (
        dependencies.map((dependency) => (
          <article className="evidenceCard warning" key={dependency.name}>
            <div>
              <strong>{dependency.name}</strong>
              <p>{dependency.reason}</p>
              <small>{dependency.suggested_mock}</small>
              {dependency.db_validation_query ? <code>{dependency.db_validation_query}</code> : null}
            </div>
          </article>
        ))
      ) : (
        <EmptyState text="No missing dependency was detected from current context." />
      )}
    </div>
  );
}

function RcaList({ hypotheses }: { hypotheses: RcaHypothesis[] }) {
  return (
    <div className="rcaList">
      {hypotheses.map((hypothesis) => (
        <article className="rcaCard" key={hypothesis.title}>
          <div className="rcaTop">
            <h3>{hypothesis.title}</h3>
            <div className="evidenceTags">
              <Tag>{hypothesis.confidence}</Tag>
              <ValidationBadge value={hypothesis.validation_level} />
            </div>
          </div>
          <InfoList label="Evidence" items={hypothesis.evidence} />
          <InfoList label="Likely files" items={hypothesis.likely_files} />
          <InfoList label="Suggested checks" items={hypothesis.suggested_checks} />
          {hypothesis.suggested_fix_area ? (
            <p className="fixArea"><strong>Suggested fix area:</strong> {hypothesis.suggested_fix_area}</p>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function CodeSuggestionList({ suggestions }: { suggestions: CodeChangeSuggestion[] }) {
  return (
    <div className="codeSuggestionList">
      {suggestions.length ? (
        suggestions.map((suggestion) => (
          <article className={suggestion.change_type === "blocked" ? "codeSuggestion blocked" : "codeSuggestion"} key={suggestion.title}>
            <div className="rcaTop">
              <div>
                <h3>{suggestion.title}</h3>
                <p>{suggestion.rationale}</p>
              </div>
              <div className="evidenceTags">
                <Tag>{suggestion.change_type}</Tag>
                <Tag>{suggestion.confidence}</Tag>
                <ValidationBadge value={suggestion.validation_level} />
              </div>
            </div>
            {suggestion.target_file || suggestion.target_symbol ? (
              <div className="targetBox">
                {suggestion.target_file ? <span><strong>File:</strong> {suggestion.target_file}</span> : null}
                {suggestion.target_symbol ? <span><strong>Symbol:</strong> {suggestion.target_symbol}</span> : null}
              </div>
            ) : null}
            {suggestion.blocker_reason ? (
              <div className="blockerBox">
                <strong>Blocked:</strong> {suggestion.blocker_reason}
              </div>
            ) : null}
            <InfoList label="Implementation steps" items={suggestion.implementation_steps} />
            <InfoList label="Safety notes" items={suggestion.safety_notes} />
            <InfoList label="Tests to add" items={suggestion.tests_to_add} />
            <InfoList label="Cross-repo/dependency notes" items={suggestion.dependencies} />
            {suggestion.suggested_patch ? <pre className="suggestedPatch">{suggestion.suggested_patch}</pre> : null}
          </article>
        ))
      ) : (
        <EmptyState text="No code-change suggestion was generated for this run." />
      )}
    </div>
  );
}

function ValidationBadge({ value }: { value: string }) {
  const level = value.split(" ")[0] || "L1";
  return <span className={`validationBadge validation-${level.toLowerCase()}`}>{value}</span>;
}

function InfoList({ label, items }: { label: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="infoList">
      <span>{label}</span>
      <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
    </div>
  );
}

function humanize(value: string) {
  return value.replace(/_/g, " ");
}

function AnalysisPanel({ analysis }: { analysis: Analysis }) {
  return (
    <section className="analysis">
      <div className="analysisHeader">
        <div>
          <p className="eyebrow">BRD Intelligence</p>
          <h2>Requirement Summary</h2>
        </div>
      </div>
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
  editingCaseId,
  onEdit,
  onChange,
  onSave,
  dirty,
  saving
}: {
  testCases: TestCase[];
  editingCaseId: string;
  onEdit: (id: string) => void;
  onChange: (cases: TestCase[]) => void;
  onSave: () => void;
  dirty: boolean;
  saving: boolean;
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
    const nextNumber = Math.max(
      0,
      ...testCases.map((testCase) => Number(testCase.id.replace(/^TC-/, ""))).filter(Number.isFinite)
    ) + 1;
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
        coverage: "Manual addition",
        requirement_evidence: ["Manual test case added by reviewer"],
        code_evidence: [],
        validation_level: "L1 Requirement-derived",
        missing_dependencies: [],
        affected_files: []
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
        </div>
        <button className="secondaryAction" onClick={addCase}>
          <Plus size={17} />
          Add Test Case
        </button>
        <button className="primaryAction" onClick={onSave} disabled={!dirty || saving}>
          {saving ? <Loader2 className="spin" size={17} /> : <CheckCircle2 size={17} />}
          Save Test Cases
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

function Metric({ label, value, suffix = "" }: { label: string; value: number; suffix?: string }) {
  return (
    <div className="tcMetric">
      <strong>{value}{suffix ? ` ${suffix}` : ""}</strong>
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
            <ValidationBadge value={testCase.validation_level || "L1 Requirement-derived"} />
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
          <div className="tcEditActions" style={{ display: "flex", justifyContent: "flex-end", marginTop: "14px" }}>
            <button className="primaryAction" onClick={() => onEdit("")}>
              <CheckCircle2 size={16} />
              Save changes
            </button>
          </div>
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
          <div className="tcTraceability">
            <InfoList label="Requirement evidence" items={testCase.requirement_evidence || []} />
            <InfoList label="Code evidence" items={testCase.code_evidence || testCase.affected_files || []} />
            <InfoList label="Missing dependencies" items={testCase.missing_dependencies || []} />
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
