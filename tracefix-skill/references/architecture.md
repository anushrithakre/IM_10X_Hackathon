# TraceFix Architecture

TraceFix is currently implemented as a synchronous read-only agent run:

Frontend UI -> FastAPI backend -> OpenProject/GitLab connectors -> LLM Gateway -> SQLite agent run store.

The hackathon version intentionally avoids autonomous writes. It focuses on reproducible analysis, traceability, and validation-level honesty.

Future production architecture:

- Backend API and orchestrator.
- Queue-backed worker pool.
- Business context index.
- Code indexer.
- QA/RCA agents.
- Sandbox validation runner.
- Human approval and GitLab MR publisher.
