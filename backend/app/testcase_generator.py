from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .schemas import AppSettings, BrdAnalyzeResponse, TestCase, TestCaseGenerateResponse


class TestCaseGenerator:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or AppSettings()

    async def generate(
        self,
        analysis: BrdAnalyzeResponse,
        ticket_id: str | None = None,
        repo_id: str | None = None,
        branch: str | None = None,
    ) -> TestCaseGenerateResponse:
        if self._llm_requested():
            if not self._llm_configured():
                raise ValueError("LLM Gateway is selected but TRACEFIX_LLM_API_KEY or TRACEFIX_LLM_MODEL is missing.")
            return await self._generate_with_llm(analysis, ticket_id, repo_id, branch)
        return self._generate_rule_based(analysis, ticket_id, repo_id, branch)

    def _generate_rule_based(
        self,
        analysis: BrdAnalyzeResponse,
        ticket_id: str | None,
        repo_id: str | None,
        branch: str | None,
    ) -> TestCaseGenerateResponse:
        current_flow = self._clean_flow(analysis.current_flow)
        expected_flow = self._clean_flow(analysis.expected_flow)
        cases: list[TestCase] = []

        cases.extend(self._existing_sanity_cases(current_flow))
        cases.extend(self._new_requirement_cases(expected_flow, analysis))
        cases.extend(self._edge_cases())

        for index, case in enumerate(cases, start=1):
            case.id = f"TC-{index:03d}"

        return TestCaseGenerateResponse(
            summary=[
                f"{len([case for case in cases if case.category == 'existing'])} sanity/regression cases for existing flow",
                f"{len([case for case in cases if case.category == 'new'])} cases for new BRD requirement",
                f"Context: {ticket_id or 'ticket'} on {repo_id or 'repo'} / {branch or 'branch'}",
            ],
            test_cases=cases,
            engine="rule_based",
            model="",
        )

    def _llm_requested(self) -> bool:
        return self.settings.llm_provider != "none" or bool(self.settings.llm_base_url or self.settings.llm_model)

    def _llm_configured(self) -> bool:
        return (
            self.settings.llm_provider != "none"
            and bool(self.settings.llm_api_key)
            and bool(self.settings.llm_model)
        )

    async def _generate_with_llm(
        self,
        analysis: BrdAnalyzeResponse,
        ticket_id: str | None,
        repo_id: str | None,
        branch: str | None,
    ) -> TestCaseGenerateResponse:
        prompt = f"""
You are TraceFix AI's senior QA test designer.

Generate exhaustive but non-duplicative test cases from the given BRD analysis and repo-derived flows.
Differentiate existing system sanity/regression cases from new requirement test cases.
Include functional, negative, edge, integration, and sanity coverage.

Return only valid JSON:
{{
  "summary": ["..."],
  "test_cases": [
    {{
      "id": "TC-001",
      "title": "...",
      "category": "existing" | "new",
      "priority": "P0" | "P1" | "P2",
      "test_type": "sanity" | "functional" | "negative" | "edge" | "regression" | "integration",
      "preconditions": ["..."],
      "steps": ["..."],
      "expected_result": "...",
      "coverage": "..."
    }}
  ]
}}

Ticket: {ticket_id or "not provided"}
Repository: {repo_id or "not provided"}
Branch: {branch or "not provided"}

Requirement summary:
{json.dumps(analysis.summary, ensure_ascii=False)}

Current behavior:
{json.dumps(analysis.current_behavior, ensure_ascii=False)}

Expected behavior:
{json.dumps(analysis.expected_behavior, ensure_ascii=False)}

Current repo-derived flow:
{json.dumps(analysis.current_flow, ensure_ascii=False)}

Expected BRD-derived flow:
{json.dumps(analysis.expected_flow, ensure_ascii=False)}
"""
        content = await self._call_llm(prompt, max_tokens=5000)
        try:
            payload = self._parse_json(content)
        except Exception:
            payload = self._parse_json(await self._repair_json(content))
        cases = [
            case
            for item in payload.get("test_cases", [])
            if (case := self._coerce_test_case(item)) is not None
        ]
        for index, case in enumerate(cases, start=1):
            case.id = f"TC-{index:03d}"
        if not cases:
            raise ValueError("LLM did not return test cases")
        return TestCaseGenerateResponse(
            summary=payload.get("summary") or [
                f"{len([case for case in cases if case.category == 'existing'])} existing-flow cases",
                f"{len([case for case in cases if case.category == 'new'])} new-requirement cases",
            ],
            test_cases=cases,
            engine="llm",
            model=self.settings.llm_model,
        )

    def _coerce_test_case(self, item: dict[str, Any]) -> TestCase | None:
        title = str(item.get("title") or "").strip()
        steps = item.get("steps") or []
        if isinstance(steps, str):
            steps = [line.strip() for line in steps.splitlines() if line.strip()]
        if not title or not steps:
            return None

        lowered = title.lower()
        category = item.get("category")
        if category not in {"existing", "new"}:
            category = "existing" if any(word in lowered for word in ("sanity", "regression", "existing")) else "new"

        priority = item.get("priority")
        if priority not in {"P0", "P1", "P2"}:
            priority = "P1"

        test_type = item.get("test_type")
        if test_type not in {"sanity", "functional", "negative", "edge", "regression", "integration"}:
            if "sanity" in lowered:
                test_type = "sanity"
            elif "regression" in lowered:
                test_type = "regression"
            elif any(word in lowered for word in ("missing", "invalid", "failure", "negative")):
                test_type = "negative"
            elif any(word in lowered for word in ("edge", "boundary", "special", "large", "expired")):
                test_type = "edge"
            else:
                test_type = "functional"

        preconditions = item.get("preconditions") or []
        if isinstance(preconditions, str):
            preconditions = [line.strip() for line in preconditions.splitlines() if line.strip()]

        return TestCase(
            id=str(item.get("id") or ""),
            title=title,
            category=category,
            priority=priority,
            test_type=test_type,
            preconditions=preconditions,
            steps=steps,
            expected_result=str(
                item.get("expected_result")
                or item.get("expected")
                or "System behavior matches the covered requirement without regression."
            ),
            coverage=str(item.get("coverage") or title),
        )

    async def _call_llm(self, prompt: str, max_tokens: int) -> str:
        base_url = (self.settings.llm_base_url or "https://imllm.intermesh.net/v1").rstrip("/")
        url = base_url + "/chat/completions"
        timeout = httpx.Timeout(180.0, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                    json={
                        "model": self.settings.llm_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": max_tokens,
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
Repair the following malformed JSON into valid JSON only.
Do not add markdown. Preserve all test case content and keys.

Malformed JSON:
{content[:20000]}
"""
        return await self._call_llm(prompt, max_tokens=5000)

    def _parse_json(self, content: str) -> dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def _existing_sanity_cases(self, current_flow: list[str]) -> list[TestCase]:
        return [
            TestCase(
                id="",
                title="Sanity: existing WhatsApp template still sends text-only message",
                category="existing",
                priority="P0",
                test_type="sanity",
                preconditions=["Existing buyer/enquiry event is available", "Valid WhatsApp template is configured"],
                steps=[
                    "Trigger the existing buyer/enquiry notification flow.",
                    "Allow ccs-consumers to consume the message trigger.",
                    "Verify template variables are resolved for seller and enquiry details.",
                    "Submit the WhatsApp provider request without product image input.",
                ],
                expected_result="Message is sent successfully with existing body content and no regression in text-only template flow.",
                coverage=" -> ".join(current_flow[:5]),
            ),
            TestCase(
                id="",
                title="Regression: ineligible template is skipped without provider call",
                category="existing",
                priority="P1",
                test_type="regression",
                preconditions=["Template eligibility rule can be made false"],
                steps=[
                    "Trigger a notification where WhatsApp template eligibility fails.",
                    "Track processing through the consumer/template resolution path.",
                    "Verify provider request is not created.",
                ],
                expected_result="System skips WhatsApp send and records the skip reason without affecting other notifications.",
                coverage="decision: Is WhatsApp template eligible?",
            ),
            TestCase(
                id="",
                title="Sanity: provider response and delivery logs are persisted",
                category="existing",
                priority="P1",
                test_type="sanity",
                preconditions=["WhatsApp provider returns a success or failure response"],
                steps=[
                    "Send an existing WhatsApp template message.",
                    "Capture provider response.",
                    "Verify delivery status/log records are created.",
                ],
                expected_result="Provider response, template type, and delivery status remain traceable after processing.",
                coverage="Existing logging/monitoring behavior",
            ),
        ]

    def _new_requirement_cases(self, expected_flow: list[str], analysis: BrdAnalyzeResponse) -> list[TestCase]:
        requirement_summary = "; ".join(analysis.summary[:3])
        return [
            TestCase(
                id="",
                title="New: product image is sent as WhatsApp media header",
                category="new",
                priority="P0",
                test_type="functional",
                preconditions=["Product-team API sends a valid public product image URL", "WhatsApp template supports media header"],
                steps=[
                    "Trigger buyer/enquiry notification with product image URL.",
                    "Verify ccs-consumers reads the product image URL from input.",
                    "Verify existing body variables remain unchanged.",
                    "Inspect WhatsApp provider payload.",
                ],
                expected_result="Payload contains product image as media/header image and existing message body remains unchanged.",
                coverage=requirement_summary,
            ),
            TestCase(
                id="",
                title="New: valid image URL with special characters is passed unchanged",
                category="new",
                priority="P1",
                test_type="edge",
                preconditions=["Image URL contains encoded spaces/query params/signed token"],
                steps=[
                    "Trigger notification with signed product image URL.",
                    "Inspect generated WhatsApp payload.",
                    "Verify provider accepts the URL.",
                ],
                expected_result="URL is not truncated, double-encoded, or stripped before provider call.",
                coverage="Image URL payload handling",
            ),
            TestCase(
                id="",
                title="New: missing image URL falls back to existing text-only payload",
                category="new",
                priority="P0",
                test_type="negative",
                preconditions=["Product-team API does not send image URL"],
                steps=[
                    "Trigger buyer/enquiry notification without image URL.",
                    "Verify template payload generation.",
                    "Send request to WhatsApp provider.",
                ],
                expected_result="System does not fail; message is sent with existing text/body behavior and no media header.",
                coverage="no: Continue with text-only template payload",
            ),
            TestCase(
                id="",
                title="New: inaccessible image URL is handled safely",
                category="new",
                priority="P1",
                test_type="edge",
                preconditions=["Image URL is private, expired, or returns non-200"],
                steps=[
                    "Trigger notification with inaccessible image URL.",
                    "Verify payload validation or provider failure handling.",
                    "Check logs for image URL and provider response.",
                ],
                expected_result="Failure is logged clearly and does not break consumer processing for subsequent messages.",
                coverage="Public accessibility requirement",
            ),
            TestCase(
                id="",
                title="New: unsupported image type or oversize image is rejected/logged",
                category="new",
                priority="P2",
                test_type="edge",
                preconditions=["Image URL points to unsupported format or oversize media"],
                steps=[
                    "Trigger notification with unsupported/oversize product image.",
                    "Observe provider request/response handling.",
                    "Verify error is logged with template type and image URL.",
                ],
                expected_result="System captures provider rejection and keeps processing stable.",
                coverage="Media validation/provider failure handling",
            ),
            TestCase(
                id="",
                title="New: image-template delivery tracking is separate from text template",
                category="new",
                priority="P1",
                test_type="integration",
                preconditions=["Delivery tracking table/dashboard is available"],
                steps=[
                    "Send one text-only template and one image-header template.",
                    "Compare delivery tracking records.",
                    "Verify template type is stored for both messages.",
                ],
                expected_result="Image-template delivery can be filtered or audited separately without changing existing text metrics.",
                coverage="Logging and monitoring requirement",
            ),
        ]

    def _edge_cases(self) -> list[TestCase]:
        return [
            TestCase(
                id="",
                title="New: retry or duplicate consumer event does not send duplicate image message",
                category="new",
                priority="P1",
                test_type="edge",
                preconditions=["Same buyer/enquiry event can be retried"],
                steps=[
                    "Trigger the same notification event twice or force consumer retry.",
                    "Verify idempotency/deduplication behavior.",
                    "Inspect provider requests and logs.",
                ],
                expected_result="System avoids duplicate sends or marks retries according to existing idempotency rules.",
                coverage="Consumer retry safety",
            ),
            TestCase(
                id="",
                title="New: high volume image-template events do not block existing templates",
                category="new",
                priority="P2",
                test_type="edge",
                preconditions=["Bulk buyer/enquiry events are available"],
                steps=[
                    "Trigger a batch with mixed image and text-only templates.",
                    "Monitor consumer processing latency and failures.",
                    "Verify existing text templates are still sent.",
                ],
                expected_result="Image handling does not degrade existing WhatsApp template processing.",
                coverage="Performance and regression safety",
            ),
        ]

    def _clean_flow(self, flow: list[str]) -> list[str]:
        cleaned = []
        for item in flow:
            if ":" in item:
                cleaned.append(item.split(":", 1)[1].strip())
            else:
                cleaned.append(item)
        return cleaned
