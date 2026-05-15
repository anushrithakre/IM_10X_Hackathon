from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    project_base_url: str = "https://project.intermesh.net"
    project_token: str = ""
    scm_base_url: str = "https://scm.intermesh.net"
    scm_token: str = ""
    google_auth_mode: Literal["token", "service_account", "none"] = "token"
    google_token: str = ""
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


class SettingsStatus(BaseModel):
    project: ConnectionStatus
    scm: ConnectionStatus
    google: ConnectionStatus
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
    brd_links: list[str] = Field(default_factory=list)
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
    brd_url: str
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
    open_questions: list[str]
    acceptance_criteria: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)
