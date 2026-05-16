from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    project_base_url: str = "https://project.intermesh.net"
    project_token: str = ""
    scm_base_url: str = "https://scm.intermesh.net"
    scm_token: str = ""
    google_auth_mode: Literal["oauth", "token", "service_account", "none"] = "oauth"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_token: str = ""
    google_refresh_token: str = ""
    google_oauth_state: str = ""
    google_redirect_uri: str = ""
    google_service_json: str = ""
    llm_provider: Literal["gemini", "openai", "custom", "none"] = "none"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    system_prompt: str = (
        "You are TraceFix AI, an intelligent QA and RCA agent. Analyze BRDs "
        "into concise requirements, current behavior, expected behavior, "
        "acceptance criteria, and open questions."
    )


class ConnectionStatus(BaseModel):
    configured: bool
    base_url: str = ""
    token_saved: bool = False
    mode: str = ""
    provider: str = ""
    model: str = ""
    redirect_uri: str = ""


class SettingsStatus(BaseModel):
    project: ConnectionStatus
    scm: ConnectionStatus
    google: ConnectionStatus
    llm: ConnectionStatus
    mock_fallback_enabled: bool


class Bucket(BaseModel):
    id: str
    name: str
    identifier: str = ""
    status: str = "active"
    source: Literal["live", "mock"] = "mock"


class Ticket(BaseModel):
    id: str
    title: str
    status: str = "Open"
    assignee: str = "Unassigned"
    bucket_id: str = ""
    updated_at: str = ""
    description: str = ""
    comments: list[str] = Field(default_factory=list)
    brd_links: list[str] = Field(default_factory=list)
    brd_attachments: list[dict[str, str]] = Field(default_factory=list)
    source: Literal["live", "mock"] = "mock"


class Repository(BaseModel):
    id: str
    name: str
    path: str
    default_branch: str = "main"
    web_url: str = ""
    source: Literal["live", "mock"] = "mock"


class Branch(BaseModel):
    name: str
    protected: bool = False
    default: bool = False
    source: Literal["live", "mock"] = "mock"


class Requirement(BaseModel):
    id: str
    title: str
    summary: str
    current_behavior: str = "Not specified"
    expected_behavior: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class BrdAnalyzeRequest(BaseModel):
    ticket_id: str | None = None
    brd_url: str = ""
    repo_id: str | None = None
    branch: str | None = None


class BrdAnalyzeResponse(BaseModel):
    source: Literal["live", "mock"]
    brd_url: str
    brd_text_status: str
    summary: list[str]
    requirements: list[Requirement]
    current_behavior: list[str]
    expected_behavior: list[str]
    current_flow: list[str] = Field(default_factory=list)
    expected_flow: list[str] = Field(default_factory=list)
    open_questions: list[str]
    acceptance_criteria: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestCase(BaseModel):
    id: str
    title: str
    category: Literal["existing", "new"]
    priority: Literal["P0", "P1", "P2"] = "P1"
    test_type: Literal["sanity", "functional", "negative", "edge", "regression", "integration"] = "functional"
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    expected_result: str
    coverage: str = ""
    requirement_evidence: list[str] = Field(default_factory=list)
    code_evidence: list[str] = Field(default_factory=list)
    validation_level: str = "L1 Requirement-derived"
    missing_dependencies: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)


class TestCaseGenerateRequest(BaseModel):
    ticket_id: str | None = None
    repo_id: str | None = None
    branch: str | None = None
    analysis: BrdAnalyzeResponse


class TestCaseGenerateResponse(BaseModel):
    summary: list[str]
    test_cases: list[TestCase]
    engine: Literal["llm", "rule_based"] = "rule_based"
    model: str = ""


class AffectedFile(BaseModel):
    path: str
    reason: str
    confidence: Literal["high", "medium", "low"] = "medium"
    related_requirement: str = ""
    suspected_module: str = ""
    confidence_score: int = 0
    matched_symbols: list[str] = Field(default_factory=list)
    line_range: str = ""
    evidence: list[str] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)
    expected_change: str = ""
    status: Literal["to_be_modified", "needs_investigation"] = "needs_investigation"


class MissingDependency(BaseModel):
    name: str
    reason: str
    suggested_mock: str
    db_validation_query: str = ""


class RcaHypothesis(BaseModel):
    title: str
    confidence: Literal["high", "medium", "low"] = "medium"
    evidence: list[str] = Field(default_factory=list)
    likely_files: list[str] = Field(default_factory=list)
    suggested_checks: list[str] = Field(default_factory=list)
    suggested_fix_area: str = ""
    validation_level: str = "L2 Code-supported"


class CodeChangeSuggestion(BaseModel):
    title: str
    change_type: Literal["modify", "create", "db", "config", "cross_repo", "blocked"] = "modify"
    target_file: str = ""
    target_symbol: str = ""
    rationale: str
    implementation_steps: list[str] = Field(default_factory=list)
    suggested_patch: str = ""
    safety_notes: list[str] = Field(default_factory=list)
    tests_to_add: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    blocker_reason: str = ""
    validation_level: str = "L2 Code-supported"


class ImpactMetrics(BaseModel):
    manual_analysis_estimate_minutes: int = 25
    tracefix_analysis_seconds: float = 0
    generated_test_cases: int = 0
    requirement_linked_cases: int = 0
    code_supported_cases: int = 0
    runtime_validated_cases: int = 0


class AgentStep(BaseModel):
    step: str
    status: Literal["running", "done", "failed"] = "done"
    message: str = ""


class AgentRunRequest(BaseModel):
    ticket_id: str
    brd_url: str = ""
    repo_id: str | None = None
    repo_name: str = ""
    branch: str | None = None


class AgentRunOutput(BaseModel):
    analysis: BrdAnalyzeResponse
    impact_analysis: dict[str, Any] = Field(default_factory=dict)
    test_case_summary: list[str] = Field(default_factory=list)
    test_cases: list[TestCase] = Field(default_factory=list)
    affected_files: list[AffectedFile] = Field(default_factory=list)
    missing_dependencies: list[MissingDependency] = Field(default_factory=list)
    rca_hypotheses: list[RcaHypothesis] = Field(default_factory=list)
    code_change_suggestions: list[CodeChangeSuggestion] = Field(default_factory=list)
    impact_metrics: ImpactMetrics = Field(default_factory=ImpactMetrics)
    suggested_agent_project_yml: str = ""
    steps: list[AgentStep] = Field(default_factory=list)


class AgentRun(BaseModel):
    run_id: str
    mode: str = "qa_analysis"
    ticket_id: str
    repo_id: str = ""
    repo_name: str = ""
    branch: str = ""
    brd_source: str = ""
    files_used: list[str] = Field(default_factory=list)
    llm_model: str = ""
    status: Literal["running", "completed", "failed"] = "running"
    started_at: str
    completed_at: str = ""
    output_json: AgentRunOutput | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    error: str = ""
