# TraceFix Skill

## Problem

Enterprise QA and RCA work is slowed down because business requirements live in OpenProject and BRDs, implementation lives in GitLab, cron/API behavior is often under-documented, and validation environments are incomplete. TraceFix links these sources into one requirement-to-code-to-test traceability report.

## When To Use

Use this skill when a team needs to analyze an OpenProject ticket or BRD against a selected GitLab repository and branch, then generate QA coverage, dependency gaps, and RCA hypotheses without giving the agent write access.

## Required Inputs

- OpenProject ticket ID with description, comments, or attached BRD.
- GitLab-compatible repository and branch.
- LLM Gateway credentials.
- Optional `agent.project.yml` for repo entrypoints, build/test commands, cron schedules, DB dependencies, and external APIs.

## Context Gathering

TraceFix fetches the selected ticket, BRD attachment, comments, and selected repository snippets through backend connectors. The LLM never accesses GitLab directly; it receives sanitized ticket/BRD context plus backend-selected code snippets.

## QA Generation

The agent produces:

- BRD summary.
- Current behavior flow from repository context.
- Expected behavior flow from BRD/ticket context.
- Existing-system sanity and regression cases.
- New-requirement functional, negative, edge, and integration cases.
- Requirement evidence and code evidence for each test case.

## RCA Generation

RCA hypotheses are generated as read-only, evidence-backed findings. Each hypothesis includes confidence, evidence, likely files, suggested checks, and suggested fix area. These are requirement/code-supported hypotheses, not production-validated root causes unless logs and runtime validation are supplied.

## Validation Levels

- L1 Requirement-derived: generated from BRD/OpenProject only.
- L2 Code-supported: mapped to selected repository context.
- L3 Build-validated: generated artifact builds successfully.
- L4 Test-validated: generated tests pass.
- L5 Environment-validated: verified in a dev/test environment.

## Guardrails

- Read-only by default.
- No direct push to main/master.
- No production DB writes.
- Human approval required before any branch/MR creation.
- Findings must cite requirement or code evidence.
- Missing environments are shown as validation gaps instead of hidden.

## Demo Walkthrough

1. Select an OpenProject ticket.
2. Select a GitLab repository and branch.
3. Run TraceFix Analysis.
4. Review BRD summary, current flow, expected flow, affected files, test cases, missing dependencies, RCA hypotheses, and validation levels.
5. Show impact metrics and traceability report.

## Impact Metrics

Target demo metrics:

- Manual QA drafting baseline: 25 minutes.
- TraceFix analysis: measured per run.
- Generated cases: counted per run.
- Requirement-linked cases: counted per run.
- Code-supported cases: counted per run.
- Runtime/build-validated cases: counted per run.
