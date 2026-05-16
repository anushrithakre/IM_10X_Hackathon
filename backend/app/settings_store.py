from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

from .schemas import AgentRun, AppSettings, ConnectionStatus, SettingsStatus

load_dotenv()

SENSITIVE_FIELDS = {
    "project_token",
    "scm_token",
    "google_client_secret",
    "google_token",
    "google_refresh_token",
    "google_oauth_state",
    "llm_api_key",
}

PRESERVE_EMPTY_FIELDS = {"google_client_id"}


class SettingsStore:
    def __init__(self) -> None:
        self.db_path = Path(os.getenv("TRACEFIX_DB_PATH", "./tracefix.db"))
        self.secret = os.getenv("TRACEFIX_SECRET", "tracefix-local-dev-secret")
        self.mock_fallback_enabled = (
            os.getenv("TRACEFIX_ALLOW_MOCK_FALLBACK", "true").lower() != "false"
        )
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(agent_runs)").fetchall()
            }
            if "owner_key" not in columns:
                conn.execute("ALTER TABLE agent_runs ADD COLUMN owner_key TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_runs_owner_created ON agent_runs(owner_key, created_at DESC)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def save(self, settings: AppSettings) -> None:
        payload = settings.model_dump()
        existing = self._raw_payload()
        for key in PRESERVE_EMPTY_FIELDS:
            if not payload.get(key) and existing.get(key):
                payload[key] = existing[key]
        for key in SENSITIVE_FIELDS:
            if not payload.get(key) and existing.get(key):
                payload[key] = existing[key]
            else:
                payload[key] = self._protect(payload.get(key, ""))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (id, payload)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload
                """,
                (json.dumps(payload),),
            )

    def load(self) -> AppSettings:
        payload = self._raw_payload()
        if not payload:
            return AppSettings(**self._with_env_defaults({}))
        for key in SENSITIVE_FIELDS:
            payload[key] = self._unprotect(payload.get(key, ""))
        return AppSettings(**self._with_env_defaults(payload))

    def _with_env_defaults(self, values: dict) -> dict:
        env_defaults = {
            "llm_provider": os.getenv("TRACEFIX_LLM_PROVIDER", ""),
            "llm_api_key": os.getenv("TRACEFIX_LLM_API_KEY", ""),
            "llm_model": os.getenv("TRACEFIX_LLM_MODEL", ""),
            "llm_base_url": os.getenv("TRACEFIX_LLM_BASE_URL", ""),
        }
        if values.get("llm_provider") not in {"gemini", "openai", "custom", "none", None, ""}:
            values["llm_provider"] = "none"
        for key, value in env_defaults.items():
            if value:
                values[key] = value
        return values

    def _raw_payload(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM app_settings WHERE id = 1"
            ).fetchone()
        if not row:
            return {}
        return json.loads(row[0])

    def status(self) -> SettingsStatus:
        settings = self.load()
        return SettingsStatus(
            project=ConnectionStatus(
                configured=bool(settings.project_base_url and settings.project_token),
                base_url=settings.project_base_url,
                token_saved=bool(settings.project_token),
            ),
            scm=ConnectionStatus(
                configured=bool(settings.scm_base_url and settings.scm_token),
                base_url=settings.scm_base_url,
                token_saved=bool(settings.scm_token),
            ),
            google=ConnectionStatus(
                configured=bool(settings.google_refresh_token or settings.google_token),
                mode=(
                    "oauth"
                    if settings.google_client_id or settings.google_refresh_token
                    else "token"
                ),
                token_saved=bool(settings.google_client_id and settings.google_client_secret),
                redirect_uri=settings.google_redirect_uri,
            ),
            llm=ConnectionStatus(
                configured=bool(settings.llm_provider != "none" and settings.llm_api_key and settings.llm_model),
                base_url=settings.llm_base_url,
                token_saved=bool(settings.llm_api_key),
                provider=settings.llm_provider,
                model=settings.llm_model,
            ),
            mock_fallback_enabled=self.mock_fallback_enabled,
        )

    def project_owner_key(self, settings: AppSettings | None = None) -> str:
        settings = settings or self.load()
        token = settings.project_token or ""
        if not token:
            return "no-project-token"
        digest = hashlib.sha256((self.secret + ":" + token).encode("utf-8")).hexdigest()
        return digest

    def save_agent_run(self, run: AgentRun, owner_key: str | None = None) -> None:
        owner_key = owner_key or self.project_owner_key()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (id, owner_key, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    owner_key = excluded.owner_key,
                    payload = excluded.payload
                """,
                (run.run_id, owner_key, run.model_dump_json()),
            )

    def list_agent_runs(self, limit: int = 20) -> list[AgentRun]:
        owner_key = self.project_owner_key()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_runs
                WHERE owner_key = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (owner_key, limit),
            ).fetchall()
        return [AgentRun.model_validate_json(row[0]) for row in rows]

    def get_agent_run(self, run_id: str) -> AgentRun | None:
        owner_key = self.project_owner_key()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM agent_runs WHERE id = ? AND owner_key = ?",
                (run_id, owner_key),
            ).fetchone()
        return AgentRun.model_validate_json(row[0]) if row else None

    def _protect(self, value: str) -> str:
        if not value:
            return ""
        nonce = os.urandom(16)
        raw = value.encode("utf-8")
        protected = self._xor(raw, nonce)
        return "v1:" + base64.urlsafe_b64encode(nonce).decode() + ":" + base64.urlsafe_b64encode(protected).decode()

    def _unprotect(self, value: str) -> str:
        if not value:
            return ""
        if not value.startswith("v1:"):
            return value
        try:
            _, nonce_b64, protected_b64 = value.split(":", 2)
            nonce = base64.urlsafe_b64decode(nonce_b64.encode())
            protected = base64.urlsafe_b64decode(protected_b64.encode())
            return self._xor(protected, nonce).decode("utf-8")
        except Exception:
            return ""

    def _xor(self, data: bytes, nonce: bytes) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < len(data):
            digest = hashlib.sha256(
                self.secret.encode("utf-8") + nonce + counter.to_bytes(4, "big")
            ).digest()
            out.extend(digest)
            counter += 1
        return bytes(a ^ b for a, b in zip(data, out))
