from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .schemas import AppSettings, BrdAnalyzeResponse, Requirement


class RequirementAnalyzer:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    async def analyze(
        self,
        brd_text: str,
        brd_url: str,
        brd_text_status: str,
        source: str,
        ticket_context: str = "",
        repo_id: str | None = None,
        branch: str | None = None,
    ) -> BrdAnalyzeResponse:
        if self._llm_configured():
            try:
                return await self._llm_analyze(
                    brd_text, brd_url, brd_text_status, source, ticket_context, repo_id, branch
                )
            except Exception:
                pass
        return self._heuristic_analyze(
            brd_text, brd_url, brd_text_status, source, ticket_context, repo_id, branch
        )

    def _llm_configured(self) -> bool:
        return (
            self.settings.llm_provider != "none"
            and bool(self.settings.llm_api_key)
            and bool(self.settings.llm_model)
        )

    async def _llm_analyze(
        self,
        brd_text: str,
        brd_url: str,
        brd_text_status: str,
        source: str,
        ticket_context: str,
        repo_id: str | None,
        branch: str | None,
    ) -> BrdAnalyzeResponse:
        prompt = f"""
{self.settings.system_prompt}

Return only valid JSON with these keys:
summary: string[]
requirements: array of objects with id, title, summary, current_behavior, expected_behavior, acceptance_criteria, open_questions
current_behavior: string[]
expected_behavior: string[]
open_questions: string[]
acceptance_criteria: string[]

Ticket context:
{ticket_context or "Not provided"}

Repository: {repo_id or "Not selected"}
Branch: {branch or "Not selected"}

BRD:
{brd_text[:12000]}
"""
        if self.settings.llm_provider == "gemini":
            content = await self._call_gemini(prompt)
        else:
            content = await self._call_openai_compatible(prompt)
        payload = self._parse_json(content)
        requirements = [
            Requirement(
                id=item.get("id") or f"REQ-{idx:03d}",
                title=item.get("title") or f"Requirement {idx}",
                summary=item.get("summary") or "",
                current_behavior=item.get("current_behavior") or "Not specified",
                expected_behavior=item.get("expected_behavior") or item.get("summary") or "",
                acceptance_criteria=item.get("acceptance_criteria") or [],
                open_questions=item.get("open_questions") or [],
            )
            for idx, item in enumerate(payload.get("requirements", []), start=1)
        ]
        return BrdAnalyzeResponse(
            source=source,  # type: ignore[arg-type]
            brd_url=brd_url,
            brd_text_status=brd_text_status,
            summary=payload.get("summary") or [],
            requirements=requirements,
            current_behavior=payload.get("current_behavior") or [],
            expected_behavior=payload.get("expected_behavior") or [],
            open_questions=payload.get("open_questions") or [],
            acceptance_criteria=payload.get("acceptance_criteria") or [],
            metadata={"analysis_engine": self.settings.llm_provider},
        )

    async def _call_gemini(self, prompt: str) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.llm_model}:generateContent"
        )
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                url,
                params={"key": self.settings.llm_api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    async def _call_openai_compatible(self, prompt: str) -> str:
        base_url = self.settings.llm_base_url or "https://api.openai.com/v1"
        url = base_url.rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json={
                    "model": self.settings.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
            )
            response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _parse_json(self, content: str) -> dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def _heuristic_analyze(
        self,
        brd_text: str,
        brd_url: str,
        brd_text_status: str,
        source: str,
        ticket_context: str,
        repo_id: str | None,
        branch: str | None,
    ) -> BrdAnalyzeResponse:
        sections = self._sections(brd_text)
        current = self._bullets(sections.get("current behavior", "Not specified"))
        expected = self._bullets(sections.get("expected behavior", ""))
        acceptance = self._bullets(sections.get("acceptance criteria", ""))
        questions = self._bullets(sections.get("open questions", ""))

        expected_source = expected or acceptance or self._sentences(brd_text, 4)
        requirements = []
        for idx, item in enumerate(expected_source[:6], start=1):
            requirements.append(
                Requirement(
                    id=f"REQ-{idx:03d}",
                    title=self._title(item),
                    summary=item,
                    current_behavior=current[0] if current else "Not specified",
                    expected_behavior=item,
                    acceptance_criteria=acceptance[:6],
                    open_questions=questions,
                )
            )

        if not requirements:
            requirements.append(
                Requirement(
                    id="REQ-001",
                    title="Analyze BRD requirement",
                    summary="BRD text was fetched, but no explicit requirement section was detected.",
                    current_behavior=current[0] if current else "Not specified",
                    expected_behavior="Review the BRD and confirm expected behavior.",
                    acceptance_criteria=acceptance,
                    open_questions=questions or ["BRD needs clearer acceptance criteria."],
                )
            )

        summary = self._summary(sections, brd_text)
        return BrdAnalyzeResponse(
            source=source,  # type: ignore[arg-type]
            brd_url=brd_url,
            brd_text_status=brd_text_status,
            summary=summary,
            requirements=requirements,
            current_behavior=current or ["Not specified"],
            expected_behavior=expected or [req.expected_behavior for req in requirements],
            open_questions=questions,
            acceptance_criteria=acceptance,
            metadata={
                "analysis_engine": "heuristic",
                "ticket_context_available": bool(ticket_context),
                "repo_id": repo_id,
                "branch": branch,
            },
        )

    def _sections(self, text: str) -> dict[str, str]:
        sections: dict[str, list[str]] = {}
        current = "overview"
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            header = line.rstrip(":").lower()
            if header in {
                "background",
                "overview",
                "current behavior",
                "expected behavior",
                "acceptance criteria",
                "open questions",
            }:
                current = header
                sections.setdefault(current, [])
                continue
            sections.setdefault(current, []).append(line)
        return {key: "\n".join(value) for key, value in sections.items()}

    def _summary(self, sections: dict[str, str], text: str) -> list[str]:
        overview = sections.get("background") or sections.get("overview") or text
        bullets = self._sentences(overview, 3)
        expected = self._bullets(sections.get("expected behavior", ""))
        if expected:
            bullets.append(f"Expected workflow: {expected[0]}")
        return bullets[:4]

    def _bullets(self, text: str) -> list[str]:
        if not text or text == "Not specified":
            return []
        items = []
        for line in text.splitlines():
            clean = re.sub(r"^[-*•\d.\s]+", "", line).strip()
            if clean:
                items.append(clean)
        if len(items) <= 1:
            items = self._sentences(text, 6)
        return items

    def _sentences(self, text: str, limit: int) -> list[str]:
        parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
        return [part.strip() for part in parts if part.strip()][:limit]

    def _title(self, text: str) -> str:
        words = re.sub(r"[^A-Za-z0-9 ]", "", text).split()
        return " ".join(words[:8]) or "Requirement"
