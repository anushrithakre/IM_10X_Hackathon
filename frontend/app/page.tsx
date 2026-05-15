"use client";

import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ClipboardList,
  GitBranch,
  KeyRound,
  Loader2,
  Search,
  Settings,
  ShieldCheck,
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
  brd_links: string[];
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
  open_questions: string[];
  acceptance_criteria: string[];
  metadata: Record<string, string | boolean | null>;
};

type SettingsStatus = {
  project: StatusBlock;
  scm: StatusBlock;
  google: StatusBlock;
  mock_fallback_enabled: boolean;
};

type StatusBlock = {
  configured: boolean;
  base_url?: string;
  token_saved: boolean;
  mode?: string;
  provider?: string;
  model?: string;
};

type SettingsForm = {
  project_token: string;
  scm_token: string;
  google_token: string;
};

const defaultSettings: SettingsForm = {
  project_token: "",
  scm_token: "",
  google_token: ""
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

  const brdUrl = useMemo(
    () => manualBrdUrl || selectedTicket?.brd_links?.[0] || "",
    [manualBrdUrl, selectedTicket]
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
    setLoading("ticket");
    try {
      const response = await fetch(`${API_BASE}/api/tickets/${encodeURIComponent(ticket.id)}`);
      if (!response.ok) throw new Error("Unable to fetch ticket details");
      const detail = await response.json();
      setSelectedTicket(detail);
      setManualBrdUrl(detail.brd_links?.[0] || "");
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
      setError("Select a ticket with a BRD link or enter a BRD URL manually.");
      return;
    }
    setError("");
    setAnalysis(null);
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
          <div className="ticketDetail">
            <div>
              <p className="detailLabel">Selected ticket</p>
              <h3>
                {selectedTicket.id} · {selectedTicket.title}
              </h3>
              <p>{selectedTicket.description || "No description returned from ticket API."}</p>
            </div>
            <div className="detailMeta">
              <Tag>{selectedTicket.status}</Tag>
              <Tag>{selectedTicket.assignee}</Tag>
              {loading === "ticket" && <Tag>loading</Tag>}
            </div>
          </div>
        ) : (
          <EmptyState text="Select a ticket to inspect its BRD link." />
        )}
        <label className="field">
          <span>Detected or manual BRD URL</span>
          <input
            value={manualBrdUrl}
            onChange={(event) => setManualBrdUrl(event.target.value)}
            placeholder="https://docs.google.com/document/d/..."
          />
        </label>
      </section>

      {analysis && <AnalysisPanel analysis={analysis} />}
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
        google_token: ""
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
                <span>Google Docs token</span>
                <input
                  type="password"
                  value={form.google_token}
                  onChange={(event) => update("google_token", event.target.value)}
                  placeholder={status?.google.token_saved ? "Saved credential kept if blank" : ""}
                />
              </label>
            </div>
            <p className="statusNote tokenNote">
              Project and SCM hosts are fixed to project.intermesh.net and scm.intermesh.net.
              Google token is only needed for private BRD docs.
            </p>
            <div className="formActions">
              <button className="primaryAction" disabled={saving}>
                {saving ? <Loader2 className="spin" size={18} /> : <CheckCircle2 size={18} />}
                Save Settings
              </button>
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
        <div className="panel">
          <h3>Summary</h3>
          <ul>
            {analysis.summary.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="panel">
          <h3>Current Behavior</h3>
          <ul>
            {analysis.current_behavior.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="panel">
          <h3>Expected Behavior</h3>
          <ul>
            {analysis.expected_behavior.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>
      <div className="requirements">
        {analysis.requirements.map((requirement) => (
          <article className="requirement" key={requirement.id}>
            <div>
              <Tag>{requirement.id}</Tag>
              <h3>{requirement.title}</h3>
            </div>
            <p>{requirement.summary}</p>
            <dl>
              <dt>Current</dt>
              <dd>{requirement.current_behavior}</dd>
              <dt>Expected</dt>
              <dd>{requirement.expected_behavior}</dd>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}
