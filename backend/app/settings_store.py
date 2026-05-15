from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

from .schemas import AppSettings, ConnectionStatus, SettingsStatus

load_dotenv()

SENSITIVE_FIELDS = {
    "project_token",
    "scm_token",
    "google_token",
}


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
            return AppSettings()
        for key in SENSITIVE_FIELDS:
            payload[key] = self._unprotect(payload.get(key, ""))
        return AppSettings(**payload)

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
                configured=bool(settings.google_token),
                mode="token",
                token_saved=bool(settings.google_token),
            ),
            mock_fallback_enabled=self.mock_fallback_enabled,
        )

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
