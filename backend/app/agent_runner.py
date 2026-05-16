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
FIX_CONFIDENCE_THRESHOLD = 70


class AgentRunExecutor:
    def __init__(self, settings: AppSettings, store: SettingsStore) -> None:
        self.settings = settings
        self.store = store

    def create_run(self, request: AgentRunRequest) -> AgentRun:
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
        return run

    async def run(self, request: AgentRunRequest) -> AgentRun:
        run = self.create_run(request)
        return await self.continue_run(request, run)

    async def continue_run(self, request: AgentRunRequest, run: AgentRun) -> AgentRun:
        owner_key = self.store.project_owner_key(self.settings)
        started = datetime.fromisoformat(run.started_at)
        steps: list[AgentStep] = list(run.steps)

        def save_progress() -> None:
            run.steps = steps
            if run.output_json:
                run.output_json.steps = steps
            self.store.save_agent_run(run, owner_key)

        def mark(step: str, message: str = "") -> None:
            steps.append(AgentStep(step=step, status="done", message=message))
            save_progress()

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
            run.output_json = AgentRunOutput(analysis=analysis, steps=steps)
            save_progress()

            tc_response = await TestCaseGenerator(self.settings).generate(
                analysis=analysis,
                ticket_id=request.ticket_id,
                repo_id=request.repo_id,
                branch=request.branch,
            )
            mark("generate_test_cases", f"Generated {len(tc_response.test_cases)} test cases.")
            run.output_json.test_case_summary = tc_response.summary
            run.output_json.test_cases = tc_response.test_cases
            save_progress()

            impact_queries = await self._impact_search_queries(
                brd_text=brd_text,
                ticket_context=ticket_context,
                analysis=analysis,
                test_cases=tc_response.test_cases,
                repo_tree_context=repo_context,
            )
            mark("impact_query_generation", f"Generated {len(impact_queries)} repository search queries.")

            impact_context = await scm_client.fetch_impact_search_context(
                request.repo_id,
                request.branch,
                impact_queries,
            )
            if impact_context:
                repo_context = repo_context + "\n\nImpact search evidence:\n" + impact_context
                files_used = list(dict.fromkeys([*files_used, *self._files_from_context(impact_context)]))[:25]
                run.files_used = files_used
            mark(
                "impact_code_search",
                f"Collected cited search evidence for {len(self._files_from_context(impact_context))} files."
                if impact_context
                else "No cited search evidence returned from GitLab search.",
            )

            impact_analysis = await self._impact_analysis(
                analysis=analysis,
                test_cases=tc_response.test_cases,
                ticket_context=ticket_context,
                repo_context=repo_context,
                files_used=files_used,
                impact_queries=impact_queries,
            )
            affected_files = self._affected_files(impact_analysis, files_used, analysis)
            confirmed_files = [item for item in affected_files if item.status == "to_be_modified"]
            mark(
                "impact_analysis",
                f"Ranked {len(affected_files)} candidate files; {len(confirmed_files)} passed confidence >= {FIX_CONFIDENCE_THRESHOLD}.",
            )
            run.output_json.impact_analysis = impact_analysis
            run.output_json.affected_files = affected_files
            save_progress()

            insights = await self._llm_insights(
                analysis=analysis,
                test_cases=tc_response.test_cases,
                repo_context=repo_context,
                ticket_context=ticket_context,
                files_used=files_used,
                manifest=manifest,
                impact_analysis=impact_analysis,
            )
            mark("generate_rca_and_traceability", "Generated dependency gaps, RCA hypotheses, and gated code suggestions.")

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

            output = run.output_json or AgentRunOutput(analysis=analysis)
            output.impact_analysis = impact_analysis
            output.test_case_summary = tc_response.summary
            output.test_cases = test_cases
            output.affected_files = affected_files
            output.missing_dependencies = missing_dependencies
            output.rca_hypotheses = rca_hypotheses
            output.code_change_suggestions = code_change_suggestions
            output.impact_metrics = metrics
            output.suggested_agent_project_yml = self._suggest_manifest(
                repo_name=request.repo_name or request.repo_id or "selected-repo",
                branch=request.branch or "",
                manifest=manifest,
                repo_context=repo_context,
            )
            output.steps = steps
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc).isoformat()
            run.output_json = output
            save_progress()
            return run
        except Exception as exc:
            steps.append(AgentStep(step="agent_run", status="failed", message=str(exc)))
            run.status = "failed"
            run.completed_at = datetime.now(timezone.utc).isoformat()
            run.error = str(exc)
            save_progress()
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

    async def _impact_search_queries(
        self,
        brd_text: str,
        ticket_context: str,
        analysis: BrdAnalyzeResponse,
        test_cases: list[TestCase],
        repo_tree_context: str,
    ) -> list[str]:
        fallback = self._search_terms(
            "\n".join(
                [
                    brd_text,
                    ticket_context,
                    " ".join(analysis.summary),
                    " ".join(analysis.current_behavior),
                    " ".join(analysis.expected_behavior),
                    " ".join(step for case in test_cases[:8] for step in case.steps),
                ]
            )
        )
        if not self.settings.llm_api_key or not self.settings.llm_model or self.settings.llm_provider == "none":
            return fallback
        prompt = f"""
You are Agent 2, a repository search query generator. Return valid JSON only.

Create targeted GitLab code-search queries from these inputs:
- requirement keywords
- API names
- UI labels
- DB table names
- config keys
- error messages
- existing behavior terms
- generated test case steps

Return:
{{"queries": ["..."]}}

Rules:
- Use exact identifiers and phrases when available.
- Keep each query short enough for GitLab blob search.
- Do not return broad filler words.
- Include 12-24 queries.

Requirement summary:
{json.dumps(analysis.summary, ensure_ascii=False)}

Current behavior:
{json.dumps(analysis.current_behavior, ensure_ascii=False)}

Expected behavior:
{json.dumps(analysis.expected_behavior, ensure_ascii=False)}

Generated flow:
{json.dumps({"current": analysis.current_flow, "expected": analysis.expected_flow}, ensure_ascii=False)}

Generated test case steps:
{json.dumps([case.steps for case in test_cases[:10]], ensure_ascii=False)}

Ticket/BRD:
{(ticket_context + "\n" + brd_text)[:9000]}

Repo tree/context:
{repo_tree_context[:7000] or "Not available"}
"""
        payload = await self._llm_json(prompt, max_tokens=1500)
        queries = self._as_list(payload.get("queries"))
        merged = list(dict.fromkeys([*queries, *fallback]))
        return [query for query in merged if 2 <= len(query) <= 80][:24]

    async def _impact_analysis(
        self,
        analysis: BrdAnalyzeResponse,
        test_cases: list[TestCase],
        ticket_context: str,
        repo_context: str,
        files_used: list[str],
        impact_queries: list[str],
    ) -> dict[str, Any]:
        if not self.settings.llm_api_key or not self.settings.llm_model or self.settings.llm_provider == "none":
            return self._fallback_impact_analysis(repo_context, files_used)
        prompt = f"""
You are Agent 3, an impacted-file ranker. Return valid JSON only.

Output only:
{{
  "suspected_modules": ["..."],
  "candidate_files": [
    {{
      "path": "...",
      "suspected_module": "...",
      "status": "to_be_modified" | "needs_investigation",
      "confidence_score": 0,
      "confidence": "high" | "medium" | "low",
      "reason": "...",
      "related_requirement": "...",
      "matched_symbols": ["function/class/component names only"],
      "line_range": "start-end",
      "evidence": ["matched symbol + line range + matched query"],
      "why_current_behavior_controlled": "...",
      "expected_behavior_change": "..."
    }}
  ],
  "file_discovery_fallback": {{
    "more_search_queries": ["..."],
    "files_to_inspect_next": ["..."],
    "missing_repo_context": ["..."],
    "branch_or_repo_may_be_wrong": false,
    "reason": "..."
  }}
}}

Evidence rules:
- Mark a file "to_be_modified" only when you can cite a matched function/class/component, exact line range, why that code controls current behavior, and what expected behavior changes there.
- If any citation is missing, mark the file "needs_investigation".
- Do not invent files. Candidate paths must come from Files used.
- Use code search/RAG evidence below, not full-repo guessing.
- Exact symbols/functions/classes matched must be listed in matched_symbols.
- Do not claim a directory was unscanned just because its raw contents were not included below. The repository tree context lists recursively discovered paths/directories; raw snippets are intentionally limited to selected candidates and GitLab search hits.
- If the relevant directory exists in the tree but no raw snippet is available, mark it as needs_investigation and name the exact files/search queries needed next.

Ranking:
- Direct keyword/symbol match: +40
- Called by relevant API/controller: +30
- Existing tests reference it: +20
- Recently modified in related ticket: +10
- Only semantic similarity: max +20
- Cap confidence_score at 100. Files below {FIX_CONFIDENCE_THRESHOLD} must be needs_investigation.

Files used with fetched snippets/search evidence:
{json.dumps(files_used, ensure_ascii=False)}

Search queries:
{json.dumps(impact_queries, ensure_ascii=False)}

Requirement summary:
{json.dumps(analysis.summary, ensure_ascii=False)}

Current/expected flow:
{json.dumps({"current": analysis.current_flow, "expected": analysis.expected_flow}, ensure_ascii=False)}

Generated test cases:
{json.dumps([case.model_dump() for case in test_cases[:12]], ensure_ascii=False)}

Ticket context:
{ticket_context[:5000]}

Code search evidence:
{repo_context[:16000] or "Not available"}
"""
        payload = await self._llm_json(prompt, max_tokens=4500)
        if not isinstance(payload.get("candidate_files"), list):
            return self._fallback_impact_analysis(repo_context, files_used)
        return payload

    async def _llm_json(self, prompt: str, max_tokens: int) -> dict[str, Any]:
        base_url = (self.settings.llm_base_url or "https://imllm.intermesh.net/v1").rstrip("/")
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
            response = await client.post(
                base_url + "/chat/completions",
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
        return self._parse_json(response.json()["choices"][0]["message"]["content"])

    async def _llm_insights(
        self,
        analysis: BrdAnalyzeResponse,
        test_cases: list[TestCase],
        repo_context: str,
        ticket_context: str,
        files_used: list[str],
        manifest: str,
        impact_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.settings.llm_api_key or not self.settings.llm_model or self.settings.llm_provider == "none":
            return {}
        prompt = f"""
Return valid JSON only for TraceFix reviewer and code-fix agents.

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
For affected_files and code_change_suggestions.target_file, choose paths ONLY from the confirmed impact files.
If no confirmed impact file has confidence_score >= {FIX_CONFIDENCE_THRESHOLD}, return only blocked code_change_suggestions.
If the exact file is not present in confirmed impact files, do not invent one.
Repository tree discovery may include more directories than the raw snippets. Do not call directories "unscanned" unless the tree context itself says the GitLab page cap was reached or the repository context is unavailable.
RCA hypotheses are requirement/code-supported hypotheses, not production-validated facts.
For code_change_suggestions:
- Behave like a senior full-stack/backend/frontend/database engineer.
- Identify exactly which existing file and symbol should change from impact_analysis evidence only.
- Suggest creating a new file only when the requirement cannot fit an existing file cleanly.
- If another repository/service owns the change, use change_type "cross_repo" and name the dependency.
- If the repo context is insufficient, use change_type "blocked" and explain blocker_reason.
- Do not invent exact code APIs that are not visible in context; provide safe pseudocode or targeted steps instead.
- Include regression safety notes and tests required to avoid breaking existing behavior.
- Keep suggested_patch detailed; provide the correct code fixes and show reference code snippets for evidence. Use a clear diff format to show what changes.
- Deep dive into the discovered likely files. For example, if a consumer sends data to a queue (like whatsapp_sent_queue), ensure you trace the flow and suggest changes for the consumer of that queue as well.
- Pay close attention to existing code structures and parameters (e.g., if an image_url param is already present in a struct, do not say it is missing; instead, show how to populate and pass it correctly).
- Reviewer/critic rule: remove any suggestion whose target file lacks cited function/class/component and line range evidence.
- Output fixes only for top confirmed files; files marked needs_investigation are blockers, not modification targets.

Requirement summary:
{json.dumps(analysis.summary, ensure_ascii=False)}

Requirements:
{analysis.model_dump_json()[:9000]}

Generated test cases:
{json.dumps([case.model_dump() for case in test_cases[:14]], ensure_ascii=False)}

Files used:
{json.dumps(files_used, ensure_ascii=False)}

Impact analysis:
{json.dumps(impact_analysis, ensure_ascii=False)[:9000]}

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
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            
            # Attempt naive repairs for truncated JSON
            for tail in ["", "}", "]}", "}]}", "]}]}", '"}', '"]}', '"]}]}']:
                try:
                    return json.loads(content + tail)
                except Exception:
                    continue
                    
            return {}

    def _files_from_context(self, repo_context: str) -> list[str]:
        paths = []
        for line in repo_context.splitlines():
            if line.startswith("FILE: "):
                paths.append(line.split("FILE: ", 1)[1].strip())
        return list(dict.fromkeys(path for path in paths if path))[:25]

    def _fallback_impact_analysis(self, repo_context: str, files_used: list[str]) -> dict[str, Any]:
        candidates = []
        for path in files_used[:8]:
            snippets = self._snippets_for_path(repo_context, path)
            symbols = []
            line_range = ""
            evidence = []
            score = 0
            for snippet in snippets:
                symbols.extend(self._symbols_from_numbered_text(snippet))
                if match := re.search(r"LINES:\s*(\d+-\d+)", snippet):
                    line_range = line_range or match.group(1)
                if "QUERY:" in snippet:
                    score += 40
                    evidence.append(next((line for line in snippet.splitlines() if line.startswith("QUERY:")), "query match"))
            symbols = list(dict.fromkeys(symbols))[:6]
            if symbols and line_range:
                score = min(max(score, 40), 60)
            candidates.append(
                {
                    "path": path,
                    "suspected_module": path.rsplit("/", 1)[0] if "/" in path else path,
                    "status": "needs_investigation",
                    "confidence_score": score,
                    "confidence": "medium" if score >= 40 else "low",
                    "reason": "Repository search found possible evidence, but no LLM-ranked citation confirmed modification ownership.",
                    "related_requirement": "",
                    "matched_symbols": symbols,
                    "line_range": line_range,
                    "evidence": evidence[:3],
                    "why_current_behavior_controlled": "",
                    "expected_behavior_change": "",
                }
            )
        return {
            "suspected_modules": list(dict.fromkeys(item["suspected_module"] for item in candidates if item["suspected_module"]))[:8],
            "candidate_files": candidates,
            "file_discovery_fallback": {
                "more_search_queries": [],
                "files_to_inspect_next": files_used[:8],
                "missing_repo_context": ["LLM impact ranker did not return cited confirmed files."],
                "branch_or_repo_may_be_wrong": not bool(repo_context),
                "reason": "Fix generation remains blocked until files have symbol and line-range citations with confidence >= 70.",
            },
        }

    def _snippets_for_path(self, repo_context: str, path: str) -> list[str]:
        chunks = re.split(r"\n(?=FILE:\s)", repo_context)
        return [chunk for chunk in chunks if chunk.startswith(f"FILE: {path}\n")]

    def _symbols_from_numbered_text(self, text: str) -> list[str]:
        symbols = []
        for pattern in (
            r"\b(?:def|class|function|const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"\b(?:public|private|protected|internal)\s+(?:static\s+)?(?:async\s+)?[A-Za-z0-9_<>,\[\]?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            r"\bfunc\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        ):
            for match in re.finditer(pattern, text):
                if match.group(1) not in symbols:
                    symbols.append(match.group(1))
        return symbols

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
        impact_analysis: dict[str, Any],
        files_used: list[str],
        analysis: BrdAnalyzeResponse,
    ) -> list[AffectedFile]:
        items = []
        allowed_paths = set(files_used)
        candidates = impact_analysis.get("candidate_files", []) if isinstance(impact_analysis, dict) else []
        for item in candidates:
            if isinstance(item, dict) and item.get("path"):
                path = str(item.get("path"))
                if path not in allowed_paths:
                    continue
                score = self._as_int(item.get("confidence_score"))
                matched_symbols = self._as_list(item.get("matched_symbols"))
                line_range = str(item.get("line_range") or "")
                status = item.get("status") if item.get("status") in {"to_be_modified", "needs_investigation"} else "needs_investigation"
                if score < FIX_CONFIDENCE_THRESHOLD or not matched_symbols or not line_range:
                    status = "needs_investigation"
                items.append(AffectedFile(**{
                    "path": path,
                    "reason": str(item.get("reason") or "Relevant to selected requirement/code flow."),
                    "confidence": item.get("confidence") if item.get("confidence") in {"high", "medium", "low"} else self._confidence_from_score(score),
                    "related_requirement": str(item.get("related_requirement") or analysis.requirements[0].id if analysis.requirements else ""),
                    "suspected_module": str(item.get("suspected_module") or path.rsplit("/", 1)[0]),
                    "confidence_score": score,
                    "matched_symbols": matched_symbols,
                    "line_range": line_range,
                    "evidence": self._as_list(item.get("evidence")),
                    "expected_change": str(item.get("expected_behavior_change") or ""),
                    "status": status,
                }))
        if items:
            return sorted(items, key=lambda item: item.confidence_score, reverse=True)[:8]
        return [
            AffectedFile(
                path=path,
                reason="Selected by repository scan as relevant code context, but no symbol/line citation confirmed modification ownership.",
                confidence="low",
                related_requirement=analysis.requirements[0].id if analysis.requirements else "REQ-001",
                suspected_module=path.rsplit("/", 1)[0] if "/" in path else path,
                status="needs_investigation",
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
        allowed_paths = {
            item.path
            for item in affected_files
            if item.status == "to_be_modified" and item.confidence_score >= FIX_CONFIDENCE_THRESHOLD
        }
        if repo_context and not allowed_paths:
            fallback = self._impact_blocked_suggestion(affected_files, missing_dependencies)
            if isinstance(insights, dict) and insights.get("code_change_suggestions"):
                return [fallback]
        for item in insights.get("code_change_suggestions", []) if isinstance(insights, dict) else []:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            change_type = item.get("change_type") if item.get("change_type") in valid_types else "modify"
            target_file = str(item.get("target_file") or "")
            if target_file and target_file not in allowed_paths:
                change_type = "blocked"
                blocker_reason = (
                    f"Model suggested '{target_file}', but that file did not pass impact confidence >= "
                    f"{FIX_CONFIDENCE_THRESHOLD} with symbol and line-range evidence."
                )
                target_file = ""
            elif change_type == "modify" and not target_file:
                change_type = "blocked"
                blocker_reason = "No confirmed impact file was cited for this code change."
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
        if primary_file not in allowed_paths:
            return [self._impact_blocked_suggestion(affected_files, missing_dependencies)]
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

    def _impact_blocked_suggestion(
        self,
        affected_files: list[AffectedFile],
        missing_dependencies: list[MissingDependency],
    ) -> CodeChangeSuggestion:
        investigation_files = [
            f"{item.path} ({item.confidence_score}/100, {item.status})"
            for item in affected_files[:5]
        ]
        return CodeChangeSuggestion(
            title="Code fix blocked until impact analysis has cited confirmed files",
            change_type="blocked",
            rationale=(
                f"No candidate file passed confidence >= {FIX_CONFIDENCE_THRESHOLD} with a matched symbol and line range citation."
            ),
            implementation_steps=[
                "Run additional GitLab searches from the file discovery fallback.",
                "Inspect candidate files until a controlling function/class/component and line range are confirmed.",
                "Generate code changes only for confirmed files.",
            ],
            safety_notes=["Do not generate implementation patches from semantic similarity alone."],
            dependencies=[dependency.name for dependency in missing_dependencies],
            confidence="high",
            blocker_reason=(
                "Impact candidates need investigation: " + "; ".join(investigation_files)
                if investigation_files
                else "No impact candidates were found in the selected repository/branch."
            ),
            validation_level=VALIDATION_L1,
        )

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

    def _as_int(self, value: Any) -> int:
        try:
            return max(0, min(int(value), 100))
        except (TypeError, ValueError):
            return 0

    def _confidence_from_score(self, score: int) -> str:
        if score >= 80:
            return "high"
        if score >= 40:
            return "medium"
        return "low"
