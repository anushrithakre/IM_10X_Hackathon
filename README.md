# TraceFix AI

Milestone 1 implementation for the Intelligent QA + RCA agent:

- Settings dashboard for OpenProject, SCM, and Google tokens only.
- Workbench to search/select open tickets assigned to the token user.
- BRD link extraction from selected ticket.
- Repository and branch selection.
- BRD fetch and requirement analysis.
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
