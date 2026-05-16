from __future__ import annotations

import asyncio
import os
import secrets
from urllib.parse import quote, urlencode

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from .agent_runner import AgentRunExecutor
from .analyzer import RequirementAnalyzer
from .clients import GoogleDocClient, ProjectClient, ScmClient
from .schemas import AgentRunRequest, AppSettings, BrdAnalyzeRequest, TestCase, TestCaseGenerateRequest
from .settings_store import SettingsStore
from .testcase_generator import TestCaseGenerator

app = FastAPI(title="Intelligent QA + RCA Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = SettingsStore()

GOOGLE_SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/documents.readonly",
    ]
)
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:3000/api/google/oauth/callback",
)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


def _oauth_origin(request: Request) -> str:
    origin = request.headers.get("x-tracefix-origin") or FRONTEND_URL
    return origin.rstrip("/")


def _google_redirect_uri(request: Request) -> str:
    if os.getenv("GOOGLE_REDIRECT_URI"):
        return GOOGLE_REDIRECT_URI
    return f"{_oauth_origin(request)}/api/google/oauth/callback"


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/settings")
async def save_settings(settings: AppSettings) -> dict[str, str]:
    store.save(settings)
    return {"status": "saved"}


@app.get("/api/settings/status")
async def settings_status():
    return store.status()


@app.get("/api/google/oauth/start")
async def google_oauth_start(request: Request):
    settings = store.load()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=400,
            detail="Save Google Client ID and Client Secret before connecting Google.",
        )
    state = secrets.token_urlsafe(24)
    redirect_uri = _google_redirect_uri(request)
    settings.google_oauth_state = state
    settings.google_redirect_uri = redirect_uri
    store.save(settings)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return RedirectResponse(
        "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    )


@app.get("/api/google/oauth/callback")
async def google_oauth_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
):
    if error:
        return RedirectResponse(f"{_oauth_origin(request)}/?google_error={quote(error)}")
    settings = store.load()
    if not code or not state or state != settings.google_oauth_state:
        raise HTTPException(status_code=400, detail="Invalid Google OAuth callback state.")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri or _google_redirect_uri(request),
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
    payload = response.json()
    settings.google_auth_mode = "oauth"
    settings.google_token = payload.get("access_token", "")
    settings.google_refresh_token = payload.get("refresh_token") or settings.google_refresh_token
    settings.google_oauth_state = ""
    store.save(settings)
    return RedirectResponse(f"{_oauth_origin(request)}/?google=connected")


@app.get("/api/buckets")
async def list_buckets(query: str = Query(default="")):
    settings = store.load()
    client = ProjectClient(settings, store.mock_fallback_enabled)
    return await client.list_buckets(query)


@app.get("/api/tickets")
async def list_tickets(query: str = Query(default="")):
    settings = store.load()
    client = ProjectClient(settings, store.mock_fallback_enabled)
    return await client.list_open_tickets(query)


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: str):
    settings = store.load()
    client = ProjectClient(settings, store.mock_fallback_enabled)
    return await client.get_ticket(ticket_id)


@app.get("/api/scm/repos")
async def list_repos(query: str = Query(default="")):
    settings = store.load()
    client = ScmClient(settings, store.mock_fallback_enabled)
    return await client.list_repos(query)


@app.get("/api/scm/repos/{repo_id:path}/branches")
async def list_branches(repo_id: str, query: str = Query(default="")):
    settings = store.load()
    client = ScmClient(settings, store.mock_fallback_enabled)
    return await client.list_branches(repo_id, query)


@app.post("/api/agent-runs")
async def create_agent_run(request: AgentRunRequest):
    settings = store.load()
    executor = AgentRunExecutor(settings, store)
    run = executor.create_run(request)
    asyncio.create_task(executor.continue_run(request, run))
    return run


@app.get("/api/agent-runs")
async def list_agent_runs(limit: int = Query(default=20, ge=1, le=50)):
    return store.list_agent_runs(limit)


@app.get("/api/agent-runs/{run_id}")
async def get_agent_run(run_id: str):
    run = store.get_agent_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


@app.patch("/api/agent-runs/{run_id}/test-cases")
async def update_agent_run_test_cases(run_id: str, test_cases: list[TestCase]):
    run = store.get_agent_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if not run.output_json:
        raise HTTPException(status_code=400, detail="Agent run has no generated output yet")
    run.output_json.test_cases = test_cases
    run.output_json.impact_metrics.generated_test_cases = len(test_cases)
    run.output_json.impact_metrics.requirement_linked_cases = sum(1 for case in test_cases if case.requirement_evidence)
    run.output_json.impact_metrics.code_supported_cases = sum(
        1 for case in test_cases if case.validation_level.startswith("L2")
    )
    run.output_json.impact_metrics.runtime_validated_cases = sum(
        1 for case in test_cases if case.validation_level.startswith(("L3", "L4", "L5"))
    )
    store.save_agent_run(run)
    return run


@app.post("/api/brd/analyze")
async def analyze_brd(request: BrdAnalyzeRequest):
    if not request.brd_url and not request.ticket_id:
        raise HTTPException(status_code=400, detail="BRD URL or ticket ID is required")

    settings = store.load()
    project_client = ProjectClient(settings, store.mock_fallback_enabled)
    ticket_context = ""
    ticket = None
    if request.ticket_id:
        try:
            ticket = await project_client.get_ticket(request.ticket_id)
            comments = await project_client.fetch_ticket_comments_text(request.ticket_id)
            ticket_context = (
                f"{ticket.id}: {ticket.title}\n"
                f"Status: {ticket.status}\n"
                f"Description:\n{ticket.description}\n\n"
                f"Comments:\n{comments or 'No comments returned.'}"
            )
        except Exception:
            ticket_context = ""

    brd_text = ""
    brd_status = ""
    source = "mock"
    brd_reference = request.brd_url

    # Ticket files are the source of truth for selected tickets. Do not fall
    # back to Google mock content when a ticket file cannot be read.
    if request.ticket_id:
        try:
            brd_text, brd_status, source = await project_client.fetch_brd_attachment_text(request.ticket_id)
            if ticket and ticket.brd_attachments:
                brd_reference = ticket.brd_attachments[0]["filename"]
            else:
                brd_reference = f"{request.ticket_id} attachment"
        except Exception as exc:
            if ticket_context.strip():
                brd_text = ticket_context
                brd_status = (
                    "BRD attachment had no extractable text; using selected ticket description/comments."
                )
                source = "live"
                brd_reference = f"{request.ticket_id} ticket description/comments"
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unable to fetch BRD from ticket files section: {exc}",
                ) from exc

    if not brd_text and request.brd_url:
        try:
            brd_text, brd_status, source = await GoogleDocClient(
                settings, store.mock_fallback_enabled
            ).fetch_text(request.brd_url)
        except Exception:
            if not request.ticket_id:
                raise
    try:
        return await RequirementAnalyzer(settings).analyze(
            brd_text=brd_text,
            brd_url=brd_reference,
            brd_text_status=brd_status,
            source=source,
            ticket_context=ticket_context,
            repo_id=request.repo_id,
            branch=request.branch,
            repo_context=await ScmClient(settings, store.mock_fallback_enabled).fetch_repository_context(
                request.repo_id, request.branch
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to analyze BRD through LLM Gateway: {exc}") from exc


@app.post("/api/test-cases/generate")
async def generate_test_cases(request: TestCaseGenerateRequest):
    settings = store.load()
    try:
        return await TestCaseGenerator(settings).generate(
            analysis=request.analysis,
            ticket_id=request.ticket_id,
            repo_id=request.repo_id,
            branch=request.branch,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to generate test cases through LLM Gateway: {exc}") from exc
