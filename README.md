# Intelligent QA + RCA Agent

Milestone 1 implementation for the Intelligent QA + RCA agent:

- Settings dashboard for OpenProject/SCM tokens and Google OAuth.
- Workbench to search/select open tickets assigned to the token user.
- BRD link extraction from selected ticket.
- Repository and branch selection.
- BRD fetch and requirement analysis.
- Persisted TraceFix agent runs with run history, impact metrics, validation levels, affected files, missing dependency suggestions, RCA hypotheses, and traceable test cases.
- Live API adapters with mock fallback data for demos.

## Run Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```
## Run Backend for Windows

```bash
& "C:\Program Files\Python312\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```
## Run Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Notes

- Secrets are submitted to the FastAPI backend and stored in SQLite using a local app-secret protected format.
- Blank secret fields on the settings screen keep the previously saved value.
- The frontend calls its own `/api/...` routes, which proxy to FastAPI at `http://127.0.0.1:8000` by default. Override with `BACKEND_API_BASE_URL` if needed.
- If Project, SCM, or Google Docs calls fail, the backend returns mock/demo data unless `TRACEFIX_ALLOW_MOCK_FALLBACK=false`.
- The SCM adapter uses GitLab-compatible APIs under `/api/v4`.
- The Project adapter uses OpenProject-compatible work package APIs under `/api/v3`.
- Project and SCM base URLs are fixed by default to `https://project.intermesh.net` and `https://scm.intermesh.net`.
- For Google OAuth, add the exact redirect URI shown on the Settings page to Google Cloud Console.
- Save Google Client ID and Client Secret in Settings, then click `Connect Google`.
- For LLM Gateway, set `TRACEFIX_LLM_PROVIDER=custom`, `TRACEFIX_LLM_BASE_URL=https://imllm.intermesh.net/v1`,
  `TRACEFIX_LLM_MODEL=openrouter/anthropic/claude-opus-4.6`, and `TRACEFIX_LLM_API_KEY=<access-key>` in `backend/.env`.
- Repository context is fetched by the backend through GitLab-compatible SCM APIs using the saved SCM token. The LLM
  does not access GitLab directly; it receives BRD/ticket context plus selected repository snippets prepared by the backend.
- The hackathon skill deliverable is available under `tracefix-skill/`.
