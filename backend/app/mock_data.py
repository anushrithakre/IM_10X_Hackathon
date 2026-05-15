from __future__ import annotations

from .schemas import Branch, Bucket, Repository, Ticket


MOCK_BRD_URL = "https://docs.google.com/document/d/demo-tracefix-brd/edit"

MOCK_BUCKETS = [
    Bucket(
        id="qa-platform",
        name="QA Platform",
        identifier="qa-platform",
    ),
    Bucket(
        id="buyer-experience",
        name="Buyer Experience",
        identifier="buyer-experience",
    ),
]

MOCK_TICKETS = [
    Ticket(
        id="OP-1842",
        title="Add intelligent QA generation for BRD-driven changes",
        status="Open",
        assignee="Jatin",
        bucket_id="qa-platform",
        updated_at="2026-05-15T09:10:00Z",
        description=(
            "Build a dashboard that reads the BRD, identifies requirements, "
            "generates test coverage, and prepares RCA-ready analysis. "
            f"BRD: {MOCK_BRD_URL}"
        ),
        brd_links=[MOCK_BRD_URL],
    ),
    Ticket(
        id="OP-1843",
        title="Optimize ticket-to-repository analysis workflow",
        status="Open",
        assignee="QA Platform",
        bucket_id="qa-platform",
        updated_at="2026-05-14T15:22:00Z",
        description=(
            "The current workflow asks users to paste BRD and repository links. "
            "Expected behavior is to select an open ticket and auto-detect links."
        ),
        brd_links=[],
    ),
]

MOCK_REPOS = [
    Repository(
        id="tracefix-ai",
        name="TraceFix AI",
        path="platform/tracefix-ai",
        default_branch="main",
        web_url="https://scm.intermesh.net/platform/tracefix-ai",
    ),
    Repository(
        id="qa-orchestrator",
        name="QA Orchestrator",
        path="qa/qa-orchestrator",
        default_branch="release",
        web_url="https://scm.intermesh.net/qa/qa-orchestrator",
    ),
]

MOCK_BRANCHES = [
    Branch(name="main", default=True),
    Branch(name="release"),
    Branch(name="feature/brd-analysis"),
]

MOCK_BRD_TEXT = """
Business Requirement Document: TraceFix AI Milestone 1

Background:
Engineers currently paste BRD links and repository links manually into different
tools. This creates repeated work and makes it difficult to trace a requirement
from an OpenProject ticket to code and tests.

Current Behavior:
Users manually collect the BRD Google Doc link, SCM repository, and target branch.
There is no single dashboard for storing API credentials, selecting open tickets,
or analyzing BRD requirements.

Expected Behavior:
The system should provide a dashboard with Workbench and Settings sections.
Users should save Project, SCM, and Google tokens once through backend settings.
In the Workbench, users should search tickets assigned to the API-token user by
title or ticket id, detect the BRD Google Doc link, select an SCM repository and
branch, and run BRD analysis.

Acceptance Criteria:
1. The dashboard asks only for OpenProject, SCM, and Google tokens.
2. Ticket search supports title and ticket id for open tickets assigned to the user.
3. The workbench does not require bucket selection before showing assigned tickets.
4. The selected ticket displays detected BRD links.
5. If no BRD link is detected, the user can enter one manually.
6. The dashboard lists repositories and branches from the configured SCM account.
7. BRD analysis returns summary bullets, requirement IDs, current behavior,
   expected behavior, acceptance criteria, and open questions.
8. When live integrations fail, demo fallback data keeps the workflow usable.

Open Questions:
- Which exact OpenProject custom field stores BRD links in production?
- Which SCM API version is enabled on scm.intermesh.net?
"""
