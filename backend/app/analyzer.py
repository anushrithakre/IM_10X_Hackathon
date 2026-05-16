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
        repo_context: str = "",
    ) -> BrdAnalyzeResponse:
        if self._llm_requested():
            if not self._llm_configured():
                raise ValueError("LLM Gateway is selected but TRACEFIX_LLM_API_KEY or TRACEFIX_LLM_MODEL is missing.")
            return await self._llm_analyze(
                brd_text, brd_url, brd_text_status, source, ticket_context, repo_id, branch, repo_context
            )
        return self._heuristic_analyze(
            brd_text, brd_url, brd_text_status, source, ticket_context, repo_id, branch, repo_context
        )

    def _llm_requested(self) -> bool:
        return self.settings.llm_provider != "none" or bool(self.settings.llm_base_url or self.settings.llm_model)

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
        repo_context: str,
    ) -> BrdAnalyzeResponse:
        prompt = f"""
Analyze the selected BRD as TraceFix AI's requirement-analysis agent.

Return only valid JSON with these keys:
summary: string[] (3-5 short crisp bullet points, each under 14 words)
requirements: array of objects with id, title, summary, current_behavior, expected_behavior, acceptance_criteria, open_questions
current_behavior: string[]
expected_behavior: string[]
current_flow: string[] (detailed flow nodes prefixed with start:, process:, decision:, yes:, no:, end:)
expected_flow: string[] (derive from current_flow, then apply BRD changes; use same prefixes)
open_questions: string[]
acceptance_criteria: string[]

Ticket context:
{ticket_context or "Not provided"}

Repository: {repo_id or "Not selected"}
Branch: {branch or "Not selected"}
Repository context:
{repo_context[:12000] or "Not available"}

BRD:
{brd_text[:12000]}
"""
        if self.settings.llm_provider == "gemini":
            content = await self._call_gemini(prompt)
        else:
            content = await self._call_openai_compatible(prompt)
        try:
            payload = self._parse_json(content)
        except Exception:
            payload = self._parse_json(await self._repair_json(content))
        requirements = [
            Requirement(
                id=self._as_text(item.get("id")) or f"REQ-{idx:03d}",
                title=self._as_text(item.get("title")) or f"Requirement {idx}",
                summary=self._as_text(item.get("summary")),
                current_behavior=self._as_text(item.get("current_behavior")) or "Not specified",
                expected_behavior=self._as_text(item.get("expected_behavior")) or self._as_text(item.get("summary")),
                acceptance_criteria=self._as_list(item.get("acceptance_criteria")),
                open_questions=self._as_list(item.get("open_questions")),
            )
            for idx, item in enumerate(payload.get("requirements", []), start=1)
            if isinstance(item, dict)
        ]
        return BrdAnalyzeResponse(
            source=source,  # type: ignore[arg-type]
            brd_url=brd_url,
            brd_text_status=brd_text_status,
            summary=self._as_list(payload.get("summary")),
            requirements=requirements,
            current_behavior=self._as_list(payload.get("current_behavior")),
            expected_behavior=self._as_list(payload.get("expected_behavior")),
            current_flow=self._as_list(payload.get("current_flow")),
            expected_flow=self._as_list(payload.get("expected_flow")),
            open_questions=self._as_list(payload.get("open_questions")),
            acceptance_criteria=self._as_list(payload.get("acceptance_criteria")),
            metadata={
                "analysis_engine": "llm",
                "llm_provider": self.settings.llm_provider,
                "llm_model": self.settings.llm_model,
                "ticket_context_available": bool(ticket_context),
                "repo_context_available": bool(repo_context),
                "repo_id": repo_id,
                "branch": branch,
            },
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
        base_url = self.settings.llm_base_url or "https://imllm.intermesh.net/v1"
        url = base_url.rstrip("/") + "/chat/completions"
        timeout = httpx.Timeout(180.0, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                    json={
                        "model": self.settings.llm_model,
                        "messages": [
                            {"role": "system", "content": self.settings.system_prompt},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 5000,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:500] if exc.response is not None else ""
                raise ValueError(
                    f"Gateway returned HTTP {exc.response.status_code} for model {self.settings.llm_model}: {body}"
                ) from exc
            except httpx.TimeoutException as exc:
                raise ValueError(f"Gateway timed out for model {self.settings.llm_model}") from exc
            except httpx.RequestError as exc:
                raise ValueError(f"Gateway request failed for model {self.settings.llm_model}: {exc}") from exc
        return response.json()["choices"][0]["message"]["content"]

    async def _repair_json(self, content: str) -> str:
        prompt = f"""
Convert this response into valid JSON only. Keep the same schema and data.

Response:
{content[:12000]}
"""
        if self.settings.llm_provider == "gemini":
            return await self._call_gemini(prompt)
        return await self._call_openai_compatible(prompt)

    def _parse_json(self, content: str) -> dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            for tail in ["", "}", "]}", "}]}", "]}]}", '"}', '"]}', '"]}]}']:
                try:
                    return json.loads(content + tail)
                except Exception:
                    continue
            return {}

    def _as_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return " ".join(self._as_text(item) for item in value if self._as_text(item)).strip()
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip()

    def _as_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [text for item in value if (text := self._as_text(item))]
        text = self._as_text(value)
        return [text] if text else []

    def _heuristic_analyze(
        self,
        brd_text: str,
        brd_url: str,
        brd_text_status: str,
        source: str,
        ticket_context: str,
        repo_id: str | None,
        branch: str | None,
        repo_context: str,
    ) -> BrdAnalyzeResponse:
        sections = self._sections(brd_text)
        current = self._current_behavior(repo_context, sections)
        expected = self._expected_behavior(sections, brd_text, ticket_context)
        acceptance = self._bullets(sections.get("acceptance criteria", ""))
        questions = self._bullets(sections.get("open questions", ""))
        current_flow = self._current_flow(repo_context, current)
        expected_flow = self._expected_flow(sections, brd_text, ticket_context, current_flow)

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
            current_flow=current_flow,
            expected_flow=expected_flow,
            open_questions=questions,
            acceptance_criteria=acceptance,
            metadata={
                "analysis_engine": "heuristic",
                "ticket_context_available": bool(ticket_context),
                "repo_context_available": bool(repo_context),
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
            header = re.sub(r"^[#\s*]+|[*:\s]+$", "", line).lower()
            if header in {
                "background",
                "overview",
                "objective",
                "user story",
                "scope",
                "functional requirements",
                "template changes",
                "image selection logic",
                "api/backend changes",
                "logging & monitoring",
                "technical notes",
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
        source = "\n".join(
            value
            for key, value in sections.items()
            if key
            in {
                "objective",
                "scope",
                "functional requirements",
                "template changes",
                "image selection logic",
                "api/backend changes",
                "logging & monitoring",
                "expected behavior",
            }
        ) or text
        bullets = []
        for item in self._bullets(source) or self._sentences(source, 6):
            if not self._meaningful(item):
                continue
            crisp = self._crisp(item)
            if crisp and crisp not in bullets:
                bullets.append(crisp)
            if len(bullets) == 5:
                break
        return bullets or ["Analyze selected BRD and ticket context."]

    def _bullets(self, text: str) -> list[str]:
        if not text or text == "Not specified":
            return []
        items = []
        for line in text.splitlines():
            for part in re.split(r"\s*[•●○]\s*", line):
                clean = re.sub(r"^[-*•●○\d.\s]+", "", part).strip()
                clean = re.sub(r"[*#`]+", "", clean).strip()
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

    def _crisp(self, text: str) -> str:
        words = re.sub(r"[•●○]", " ", text)
        words = re.sub(r"\s+", " ", words).strip(" .")
        if not words:
            return ""
        return " ".join(words.split()[:14])

    def _current_behavior(self, repo_context: str, sections: dict[str, str]) -> list[str]:
        repo_lower = repo_context.lower()
        brd_context = "\n".join(sections.values()).lower()
        brd_current = []
        if "only text" in brd_context or "text-based" in brd_context:
            brd_current.append("WhatsApp templates currently send text-based seller/enquiry information.")
        if "product image" in brd_context and ("currently" in brd_context or "background" in sections):
            brd_current.append("Product image is not currently attached as a media header.")
        if repo_context:
            behavior = []
            behavior.extend(brd_current)
            if "whatsapp" in repo_lower:
                behavior.append("Repository contains WhatsApp messaging flow.")
            if "template" in repo_lower:
                behavior.append("Template payload is built before provider call.")
            if "image" not in repo_lower and "media" not in repo_lower:
                behavior.append("Scanned template flow shows no obvious media-header handling.")
            return list(dict.fromkeys(behavior))[:4]
        current = self._bullets(sections.get("current behavior", ""))
        return brd_current or current or ["Repository context unavailable for current-flow analysis."]

    def _expected_behavior(self, sections: dict[str, str], brd_text: str, ticket_context: str) -> list[str]:
        candidates = []
        for key in ("objective", "scope", "functional requirements", "api/backend changes", "expected behavior"):
            candidates.extend(self._bullets(sections.get(key, "")))
        if not candidates:
            candidates = self._bullets(brd_text) or self._sentences(brd_text + "\n" + ticket_context, 8)
        meaningful = [self._crisp(item) for item in candidates if self._meaningful(item)]
        return list(dict.fromkeys(meaningful))[:6]

    def _current_flow(self, repo_context: str, current: list[str]) -> list[str]:
        if not repo_context:
            return [
                "start: Selected branch",
                "process: Repository scan unavailable",
                "end: Current flow needs code context",
            ]
        lowered = repo_context.lower()
        flow = ["start: Buyer/enquiry event"]
        if any(term in lowered for term in ("consumer", "queue", "worker", "cron", "job")):
            flow.append("process: ccs-consumers receives message/notification trigger")
        elif any(term in lowered for term in ("controller", "route", "api")):
            flow.append("process: API/controller receives message trigger")
        else:
            flow.append("process: Selected branch entrypoint receives trigger")

        if any(term in lowered for term in ("buyer", "enquiry", "seller", "product")):
            flow.append("process: Fetch buyer, seller, enquiry, and product context")
        if any(term in lowered for term in ("template", "message", "notification", "sms", "whatsapp")):
            flow.append("process: Resolve WhatsApp template and map body variables")

        flow.append("decision: Is WhatsApp template eligible?")
        if any("text-based" in item.lower() for item in current):
            flow.append("yes: Build text-only seller/enquiry template body")
        else:
            flow.append("yes: Build existing template payload")

        if any("text-based" in item.lower() or "not currently attached" in item.lower() for item in current):
            flow.append("yes: Send payload without product image media header")
        elif "image" not in lowered and "media" not in lowered:
            flow.append("yes: Send payload without product image media header")
        else:
            flow.append("yes: Send payload through existing media/template path")
        flow.append("no: Skip WhatsApp template send")

        if "whatsapp" in lowered:
            flow.append("process: Call WhatsApp/provider API")
        else:
            flow.append("process: Dispatch notification provider request")
        if any(term in lowered for term in ("log", "logger", "monitor", "response", "status")):
            flow.append("process: Persist provider response and delivery logs")
        flow.append("end: Template processing complete")
        return flow[:10]

    def _expected_flow(
        self,
        sections: dict[str, str],
        brd_text: str,
        ticket_context: str,
        current_flow: list[str],
    ) -> list[str]:
        text = (brd_text + "\n" + ticket_context).lower()
        flow = []
        for node in current_flow:
            lowered = node.lower()
            if "text-only" in lowered or "seller/enquiry text" in lowered or "without product image" in lowered:
                continue
            if "call whatsapp" in lowered or "provider api" in lowered or "dispatch notification" in lowered:
                if "image" in text or "media" in text:
                    flow.extend(
                        [
                            "decision: Is product image URL present and publicly accessible?",
                            "yes: Attach product image as WhatsApp media header",
                            "no: Continue with text-only template payload",
                        ]
                    )
                flow.append("process: Send template payload through WhatsApp provider")
                continue
            if lowered.startswith("decision:") and "template eligible" in lowered:
                flow.append(node)
                flow.append("yes: Build existing body content unchanged")
                continue
            if "template message payload" in lowered or "template and map" in lowered:
                flow.append(node)
                continue
            flow.append(node)

        if "product" in text:
            insert_after = self._find_flow_index(flow, "receives message/notification trigger")
            flow.insert(insert_after + 1, "process: Read product image URL from product-team API input")
        if "log" in text or "monitor" in text:
            if not any("image url" in item.lower() for item in flow):
                flow.insert(max(len(flow) - 1, 0), "process: Log image URL, template type, and provider response")
        if not flow or not flow[-1].lower().startswith("end:"):
            flow.append("end: Track image-template delivery separately if required")
        return list(dict.fromkeys(flow))[:14]

    def _find_flow_index(self, flow: list[str], needle: str) -> int:
        for idx, item in enumerate(flow):
            if needle.lower() in item.lower():
                return idx
        return 0

    def _meaningful(self, text: str) -> bool:
        clean = re.sub(r"[*#`]+", "", text).strip(" .:")
        lowered = clean.lower()
        if lowered in {
            "background",
            "objective",
            "user story",
            "scope",
            "functional requirements",
            "template changes",
            "api/backend changes",
            "logging & monitoring",
            "technical notes",
        }:
            return False
        words = re.findall(r"[A-Za-z0-9]+", clean)
        if len(words) < 4:
            return False
        return True
