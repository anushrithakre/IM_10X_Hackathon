from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from .analyzer import RequirementAnalyzer
from .clients import GoogleDocClient, ProjectClient, ScmClient
from .schemas import (
    AffectedFile,
    AgentRun,
    AgentRunOutput,
    AgentRunRequest,
    AgentStep,
    AppSettings,
    BrdAnalyzeResponse,
    CodeChangeSuggestion,
    ImpactMetrics,
    MissingDependency,
    RcaHypothesis,
    TestCase,
)
from .settings_store import SettingsStore
from .testcase_generator import TestCaseGenerator


VALIDATION_L1 = "L1 Requirement-derived"
VALIDATION_L2 = "L2 Code-supported"


class AgentRunExecutor:
    def __init__(self, settings: AppSettings, store: SettingsStore) -> None:
        self.settings = settings
        self.store = store

    async def run(self, request: AgentRunRequest) -> AgentRun:
        started = datetime.now(timezone.utc)
        started_at = started.isoformat()
        owner_key = self.store.project_owner_key(self.settings)
        run = AgentRun(
            run_id=f"run-{uuid.uuid4().hex[:10]}",
            ticket_id=request.ticket_id,
            repo_id=request.repo_id or "",
            repo_name=request.repo_name,
            branch=request.branch or "",
            llm_model=self.settings.llm_model,
            started_at=started_at,
        )
        self.store.save_agent_run(run, owner_key)
        steps: list[AgentStep] = []

        def mark(step: str, message: str = "") -> None:
            steps.append(AgentStep(step=step, status="done", message=message))

        try:
            project_client = ProjectClient(self.settings, self.store.mock_fallback_enabled)
            scm_client = ScmClient(self.settings, self.store.mock_fallback_enabled)

            ticket = await project_client.get_ticket(request.ticket_id)
            comments = await project_client.fetch_ticket_comments_text(request.ticket_id)
            ticket_context = (
                f"{ticket.id}: {ticket.title}\n"
                f"Status: {ticket.status}\n"
                f"Description:\n{ticket.description}\n\n"
                f"Comments:\n{comments or 'No comments returned.'}"
            )
            mark("fetch_openproject_context", f"Loaded {ticket.id} with ticket description/comments.")

            brd_text, brd_status, source, brd_reference = await self._fetch_brd(
                project_client, request, ticket_context
            )
            run.brd_source = brd_reference
            mark("fetch_brd_source", brd_status)

            search_terms = self._search_terms(brd_text + "\n" + ticket_context)
            repo_context = await scm_client.fetch_repository_context(request.repo_id, request.branch, search_terms)
            manifest = await scm_client.fetch_agent_project_manifest(request.repo_id, request.branch)
            files_used = self._files_from_context(repo_context)
            run.files_used = files_used
            repo_message = (
                f"Found {len(files_used)} relevant files."
                if repo_context
                else "Repository context unavailable."
            )
            if manifest:
                repo_context = repo_context + "\n\nagent.project.yml:\n" + manifest
                repo_message += " agent.project.yml loaded."
            mark("read_repository_context", repo_message)

            analysis = await RequirementAnalyzer(self.settings).analyze(
                brd_text=brd_text,
                brd_url=brd_reference,
                brd_text_status=brd_status,
                source=source,
                ticket_context=ticket_context,
                repo_id=request.repo_id,
                branch=request.branch,
                repo_context=repo_context,
            )
            mark("map_requirement_to_code", "LLM generated requirement and current/expected flow analysis.")

            tc_response = await TestCaseGenerator(self.settings).generate(
                analysis=analysis,
                ticket_id=request.ticket_id,
                repo_id=request.repo_id,
                branch=request.branch,
            )
            mark("generate_test_cases", f"Generated {len(tc_response.test_cases)} test cases.")

            insights = await self._llm_insights(
                analysis=analysis,
                test_cases=tc_response.test_cases,
                repo_context=repo_context,
                ticket_context=ticket_context,
                files_used=files_used,
                manifest=manifest,
            )
            mark("generate_rca_and_traceability", "Generated affected files, dependency gaps, RCA hypotheses, and code suggestions.")

            affected_files = self._affected_files(insights, files_used, analysis)
            missing_dependencies = self._missing_dependencies(insights, repo_context, analysis)
            rca_hypotheses = self._rca_hypotheses(insights, affected_files, analysis)
            code_change_suggestions = self._code_change_suggestions(
                insights, affected_files, missing_dependencies, repo_context, analysis
            )
            test_cases = self._enrich_test_cases(
                tc_response.test_cases,
                analysis,
                affected_files,
                missing_dependencies,
                bool(repo_context),
            )
            metrics = self._metrics(started, test_cases)
            mark("produce_traceability_report", "Traceability report is ready.")

            output = AgentRunOutput(
                analysis=analysis,
                test_case_summary=tc_response.summary,
                test_cases=test_cases,
                affected_files=affected_files,
                missing_dependencies=missing_dependencies,
                rca_hypotheses=rca_hypotheses,
                code_change_suggestions=code_change_suggestions,
                impact_metrics=metrics,
                suggested_agent_project_yml=self._suggest_manifest(
                    repo_name=request.repo_name or request.repo_id or "selected-repo",
                    branch=request.branch or "",
                    manifest=manifest,
                    repo_context=repo_context,
                ),
                steps=steps,
            )
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc).isoformat()
            run.output_json = output
            self.store.save_agent_run(run, owner_key)
            return run
        except Exception as exc:
            steps.append(AgentStep(step="agent_run", status="failed", message=str(exc)))
            run.status = "failed"
            run.completed_at = datetime.now(timezone.utc).isoformat()
            run.error = str(exc)
            self.store.save_agent_run(run, owner_key)
            return run

    async def _fetch_brd(
        self,
        project_client: ProjectClient,
        request: AgentRunRequest,
        ticket_context: str,
    ) -> tuple[str, str, str, str]:
        try:
            brd_text, brd_status, source = await project_client.fetch_brd_attachment_text(request.ticket_id)
            ticket = await project_client.get_ticket(request.ticket_id)
            reference = ticket.brd_attachments[0]["filename"] if ticket.brd_attachments else f"{request.ticket_id} attachment"
            return brd_text, brd_status, source, reference
        except Exception:
            if ticket_context.strip():
                return (
                    ticket_context,
                    "BRD attachment had no extractable text; using selected ticket description/comments.",
                    "live",
                    f"{request.ticket_id} ticket description/comments",
                )
            if request.brd_url:
                brd_text, brd_status, source = await GoogleDocClient(
                    self.settings, self.store.mock_fallback_enabled
                ).fetch_text(request.brd_url)
                return brd_text, brd_status, source, request.brd_url
            raise

    async def _llm_insights(
        self,
        analysis: BrdAnalyzeResponse,
        test_cases: list[TestCase],
        repo_context: str,
        ticket_context: str,
        files_used: list[str],
        manifest: str,
    ) -> dict[str, Any]:
        if not self.settings.llm_api_key or not self.settings.llm_model or self.settings.llm_provider == "none":
            return {}
        prompt = f"""
Return valid JSON only for a TraceFix read-only senior engineering report.

Keys:
affected_files: array of {{path, reason, confidence, related_requirement}}
missing_dependencies: array of {{name, reason, suggested_mock, db_validation_query}}
rca_hypotheses: array of {{title, confidence, evidence, likely_files, suggested_checks, suggested_fix_area}}
code_change_suggestions: array of {{
  title,
  change_type: "modify" | "create" | "db" | "config" | "cross_repo" | "blocked",
  target_file,
  target_symbol,
  rationale,
  implementation_steps,
  suggested_patch,
  safety_notes,
  tests_to_add,
  dependencies,
  confidence,
  blocker_reason,
  validation_level
}}

Use only the given BRD/ticket/repo context. Confidence must be high, medium, or low.
For affected_files and code_change_suggestions.target_file, choose paths ONLY from the Files used list.
If the exact file is not present in Files used, do not invent one. Return a blocked code_change_suggestion explaining what extra repo/module/context is needed.
RCA hypotheses are requirement/code-supported hypotheses, not production-validated facts.
For code_change_suggestions:
- Behave like a senior full-stack/backend/frontend/database engineer.
- Identify exactly which existing file and symbol should change when evidence exists.
- Suggest creating a new file only when the requirement cannot fit an existing file cleanly.
- If another repository/service owns the change, use change_type "cross_repo" and name the dependency.
- If the repo context is insufficient, use change_type "blocked" and explain blocker_reason.
- Do not invent exact code APIs that are not visible in context; provide safe pseudocode or targeted steps instead.
- Include regression safety notes and tests required to avoid breaking existing behavior.
- Keep suggested_patch concise; use a minimal illustrative diff only when the target code is clear.

Requirement summary:
{json.dumps(analysis.summary, ensure_ascii=False)}

Requirements:
{analysis.model_dump_json()[:9000]}

Generated test cases:
{json.dumps([case.model_dump() for case in test_cases[:14]], ensure_ascii=False)}

Files used:
{json.dumps(files_used, ensure_ascii=False)}

agent.project.yml:
{manifest or "Not found"}

Ticket context:
{ticket_context[:5000]}

Repository context:
{repo_context[:10000] or "Not available"}
"""
        base_url = (self.settings.llm_base_url or "https://imllm.intermesh.net/v1").rstrip("/")
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
            response = await client.post(
                base_url + "/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json={
                    "model": self.settings.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 3500,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
        return self._parse_json(response.json()["choices"][0]["message"]["content"])

    def _parse_json(self, content: str) -> dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            return json.loads(match.group(0)) if match else {}

    def _files_from_context(self, repo_context: str) -> list[str]:
        paths = []
        for line in repo_context.splitlines():
            if line.startswith("FILE: "):
                paths.append(line.split("FILE: ", 1)[1].strip())
        return list(dict.fromkeys(path for path in paths if path))[:25]

    def _search_terms(self, text: str) -> list[str]:
        preferred = []
        lowered = text.lower()
        domain_terms = [
            "whatsapp",
            "template",
            "notification",
            "message",
            "media",
            "image",
            "nach",
            "lotuspay",
            "razorpay",
            "ingenico",
            "receipt",
            "gateway",
            "payment",
            "mandate",
            "pan",
            "cashback",
            "invoice",
        ]
        for term in domain_terms:
            if term in lowered:
                preferred.append(term)
        words = re.findall(r"[A-Za-z][A-Za-z0-9_]{3,}", text)
        stop = {"currently", "should", "would", "requirement", "business", "expected", "behavior", "description", "comments"}
        for word in words:
            clean = word.lower()
            if clean not in stop and clean not in preferred:
                preferred.append(clean)
            if len(preferred) >= 12:
                break
        return preferred[:12]

    def _affected_files(
        self,
        insights: dict[str, Any],
        files_used: list[str],
        analysis: BrdAnalyzeResponse,
    ) -> list[AffectedFile]:
        items = []
        allowed_paths = set(files_used)
        for item in insights.get("affected_files", []) if isinstance(insights, dict) else []:
            if isinstance(item, dict) and item.get("path"):
                path = str(item.get("path"))
                if path not in allowed_paths:
                    continue
                items.append(AffectedFile(**{
                    "path": path,
                    "reason": str(item.get("reason") or "Relevant to selected requirement/code flow."),
                    "confidence": item.get("confidence") if item.get("confidence") in {"high", "medium", "low"} else "medium",
                    "related_requirement": str(item.get("related_requirement") or analysis.requirements[0].id if analysis.requirements else ""),
                }))
        if items:
            return items[:8]
        return [
            AffectedFile(
                path=path,
                reason="Selected by repository scan as relevant code context.",
                confidence="medium",
                related_requirement=analysis.requirements[0].id if analysis.requirements else "REQ-001",
            )
            for path in files_used[:6]
        ]

    def _missing_dependencies(
        self,
        insights: dict[str, Any],
        repo_context: str,
        analysis: BrdAnalyzeResponse,
    ) -> list[MissingDependency]:
        items = []
        for item in insights.get("missing_dependencies", []) if isinstance(insights, dict) else []:
            if isinstance(item, dict) and item.get("name"):
                items.append(MissingDependency(**{
                    "name": str(item.get("name")),
                    "reason": str(item.get("reason") or "Needed for runtime validation."),
                    "suggested_mock": str(item.get("suggested_mock") or "Create a fake service response for positive, negative, and timeout cases."),
                    "db_validation_query": str(item.get("db_validation_query") or ""),
                }))
        if items:
            return items[:6]
        text = " ".join(analysis.summary + analysis.expected_behavior).lower()
        if any(term in text for term in ("api", "service", "payment", "gateway", "provider")):
            return [
                MissingDependency(
                    name="External service/API sandbox",
                    reason="Runtime validation depends on a live or fake downstream service response.",
                    suggested_mock="Provide fake success, validation failure, timeout, and HTTP 500 responses.",
                    db_validation_query="-- Add module-specific DB assertions after table mapping is confirmed.",
                )
            ]
        if not repo_context:
            return [
                MissingDependency(
                    name="Repository context",
                    reason="Code-supported validation could not be performed without selected repo snippets.",
                    suggested_mock="Select a repo and branch with readable source files.",
                )
            ]
        return []

    def _rca_hypotheses(
        self,
        insights: dict[str, Any],
        affected_files: list[AffectedFile],
        analysis: BrdAnalyzeResponse,
    ) -> list[RcaHypothesis]:
        items = []
        for item in insights.get("rca_hypotheses", []) if isinstance(insights, dict) else []:
            if isinstance(item, dict) and item.get("title"):
                confidence = item.get("confidence") if item.get("confidence") in {"high", "medium", "low"} else "medium"
                items.append(
                    RcaHypothesis(
                        title=str(item.get("title")),
                        confidence=confidence,
                        evidence=self._as_list(item.get("evidence")),
                        likely_files=self._as_list(item.get("likely_files")),
                        suggested_checks=self._as_list(item.get("suggested_checks")),
                        suggested_fix_area=str(item.get("suggested_fix_area") or ""),
                        validation_level=VALIDATION_L2 if affected_files else VALIDATION_L1,
                    )
                )
        if items:
            return items[:5]
        return [
            RcaHypothesis(
                title="Requirement/code-supported implementation gap",
                confidence="medium",
                evidence=analysis.summary[:3],
                likely_files=[item.path for item in affected_files[:3]],
                suggested_checks=[
                    "Verify selected files implement the expected behavior.",
                    "Confirm generated edge cases are covered by existing or new tests.",
                ],
                suggested_fix_area="Review affected modules before implementation.",
                validation_level=VALIDATION_L2 if affected_files else VALIDATION_L1,
            )
        ]

    def _code_change_suggestions(
        self,
        insights: dict[str, Any],
        affected_files: list[AffectedFile],
        missing_dependencies: list[MissingDependency],
        repo_context: str,
        analysis: BrdAnalyzeResponse,
    ) -> list[CodeChangeSuggestion]:
        suggestions = []
        valid_types = {"modify", "create", "db", "config", "cross_repo", "blocked"}
        allowed_paths = {item.path for item in affected_files}
        for item in insights.get("code_change_suggestions", []) if isinstance(insights, dict) else []:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            change_type = item.get("change_type") if item.get("change_type") in valid_types else "modify"
            target_file = str(item.get("target_file") or "")
            if target_file and target_file not in allowed_paths:
                change_type = "blocked"
                blocker_reason = (
                    f"Model suggested '{target_file}', but that file was not present in the fetched repository context. "
                    "Re-run with a more specific repo/module or add agent.project.yml entrypoints."
                )
                target_file = ""
            else:
                blocker_reason = str(item.get("blocker_reason") or "")
            confidence = item.get("confidence") if item.get("confidence") in {"high", "medium", "low"} else "medium"
            suggestions.append(
                CodeChangeSuggestion(
                    title=str(item.get("title")),
                    change_type=change_type,
                    target_file=target_file,
                    target_symbol=str(item.get("target_symbol") or ""),
                    rationale=str(item.get("rationale") or "Suggested from requirement and selected repository context."),
                    implementation_steps=self._as_list(item.get("implementation_steps")),
                    suggested_patch=str(item.get("suggested_patch") or ""),
                    safety_notes=self._as_list(item.get("safety_notes")),
                    tests_to_add=self._as_list(item.get("tests_to_add")),
                    dependencies=self._as_list(item.get("dependencies")),
                    confidence=confidence,
                    blocker_reason=blocker_reason,
                    validation_level=str(
                        item.get("validation_level")
                        or (VALIDATION_L2 if repo_context and change_type != "blocked" else VALIDATION_L1)
                    ),
                )
            )
        if suggestions:
            return suggestions[:8]

        if not repo_context:
            return [
                CodeChangeSuggestion(
                    title="Code change suggestion blocked by missing repository context",
                    change_type="blocked",
                    rationale="TraceFix could not inspect selected repository files, so file-level changes would be unsafe.",
                    implementation_steps=[
                        "Select a repository and branch with readable source files.",
                        "Re-run TraceFix analysis to map the requirement to concrete files and symbols.",
                    ],
                    safety_notes=["Do not implement code changes without repository evidence."],
                    dependencies=[dependency.name for dependency in missing_dependencies],
                    confidence="high",
                    blocker_reason="Repository context unavailable.",
                    validation_level=VALIDATION_L1,
                )
            ]

        primary_file = affected_files[0].path if affected_files else ""
        return [
            CodeChangeSuggestion(
                title="Review and update the primary affected implementation path",
                change_type="modify" if primary_file else "blocked",
                target_file=primary_file,
                rationale="The requirement changes expected behavior and this file was selected as the highest-confidence code context.",
                implementation_steps=[
                    "Confirm the existing branch logic that implements the current behavior.",
                    "Add the new requirement behavior behind the same validation and error-handling conventions.",
                    "Preserve existing behavior for legacy/negative paths.",
                    "Add regression tests for unchanged existing behavior and new requirement edge cases.",
                ],
                safety_notes=[
                    "Avoid changing shared contracts unless all callers are reviewed.",
                    "Keep fallback behavior explicit for missing downstream dependencies.",
                ],
                tests_to_add=[requirement.title for requirement in analysis.requirements[:3]],
                dependencies=[dependency.name for dependency in missing_dependencies],
                confidence="medium",
                blocker_reason="" if primary_file else "No affected file could be identified from repository context.",
                validation_level=VALIDATION_L2 if primary_file else VALIDATION_L1,
            )
        ]

    def _enrich_test_cases(
        self,
        test_cases: list[TestCase],
        analysis: BrdAnalyzeResponse,
        affected_files: list[AffectedFile],
        missing_dependencies: list[MissingDependency],
        repo_context_available: bool,
    ) -> list[TestCase]:
        requirement = analysis.requirements[0] if analysis.requirements else None
        evidence = []
        if requirement:
            evidence.append(f"{requirement.id}: {requirement.summary or requirement.title}")
        evidence.extend(analysis.summary[:2])
        files = [item.path for item in affected_files[:4]]
        deps = [item.name for item in missing_dependencies[:3]]
        level = VALIDATION_L2 if repo_context_available and files else VALIDATION_L1
        enriched = []
        for case in test_cases:
            case.requirement_evidence = case.requirement_evidence or evidence[:3]
            case.code_evidence = case.code_evidence or files[:3]
            case.validation_level = case.validation_level or level
            if case.validation_level == VALIDATION_L1 and level == VALIDATION_L2:
                case.validation_level = level
            case.missing_dependencies = case.missing_dependencies or deps
            case.affected_files = case.affected_files or files
            enriched.append(case)
        return enriched

    def _metrics(self, started: datetime, test_cases: list[TestCase]) -> ImpactMetrics:
        elapsed = max(time.time() - started.timestamp(), 0)
        return ImpactMetrics(
            tracefix_analysis_seconds=round(elapsed, 1),
            generated_test_cases=len(test_cases),
            requirement_linked_cases=sum(1 for case in test_cases if case.requirement_evidence),
            code_supported_cases=sum(1 for case in test_cases if case.validation_level.startswith("L2")),
            runtime_validated_cases=sum(
                1 for case in test_cases if case.validation_level.startswith(("L3", "L4", "L5"))
            ),
        )

    def _suggest_manifest(self, repo_name: str, branch: str, manifest: str, repo_context: str) -> str:
        if manifest:
            return ""
        lowered = (repo_name + "\n" + repo_context).lower()
        language = "dotnet" if any(term in lowered for term in (".cs", "dotnet", "csproj")) else "go" if ".go" in lowered else "unknown"
        build = "dotnet build" if language == "dotnet" else "go build ./..." if language == "go" else ""
        test = "dotnet test" if language == "dotnet" else "go test ./..." if language == "go" else ""
        return f"""name: {repo_name}
language: {language}
type: cron-or-service

commands:
  build: "{build}"
  test: "{test}"

entrypoints:
  - name: primary-flow
    path: "TODO: add entrypoint path"
    schedule: "TODO: add cron schedule if applicable"

dependencies:
  database: "TODO"
  external_apis:
    - "TODO"

business_mapping:
  openproject_project: "TODO"
  module: "TODO"
branch: "{branch}"
"""

    def _as_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if str(value).strip() else []
