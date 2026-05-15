from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .analyzer import RequirementAnalyzer
from .clients import GoogleDocClient, ProjectClient, ScmClient
from .schemas import AppSettings, BrdAnalyzeRequest
from .settings_store import SettingsStore

app = FastAPI(title="TraceFix AI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = SettingsStore()


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


@app.post("/api/brd/analyze")
async def analyze_brd(request: BrdAnalyzeRequest):
    if not request.brd_url:
        raise HTTPException(status_code=400, detail="BRD URL is required")

    settings = store.load()
    ticket_context = ""
    if request.ticket_id:
        try:
            ticket = await ProjectClient(settings, store.mock_fallback_enabled).get_ticket(
                request.ticket_id
            )
            ticket_context = f"{ticket.id}: {ticket.title}\n{ticket.description}"
        except Exception:
            ticket_context = ""

    brd_text, brd_status, source = await GoogleDocClient(
        settings, store.mock_fallback_enabled
    ).fetch_text(request.brd_url)
    return await RequirementAnalyzer(settings).analyze(
        brd_text=brd_text,
        brd_url=request.brd_url,
        brd_text_status=brd_status,
        source=source,
        ticket_context=ticket_context,
        repo_id=request.repo_id,
        branch=request.branch,
    )
