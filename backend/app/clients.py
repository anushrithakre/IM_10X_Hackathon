from __future__ import annotations

import base64
import html
import json
import re
from typing import Any
from urllib.parse import quote

import httpx

from .mock_data import MOCK_BRD_TEXT, MOCK_BRANCHES, MOCK_BUCKETS, MOCK_REPOS, MOCK_TICKETS
from .schemas import AppSettings, Branch, Bucket, Repository, Ticket

BRD_LINK_RE = re.compile(
    r"https?://(?:docs\.google\.com/document/d/[^\s)>\"]+|[^\s)>\"]*(?:brd|requirement)[^\s)>\"]*)",
    re.IGNORECASE,
)


def extract_brd_links(*values: Any) -> list[str]:
    text = html.unescape("\n".join(_flatten_strings(values)))
    links = []
    for match in BRD_LINK_RE.findall(text):
        clean = match.rstrip(".,;]'\"")
        if clean not in links:
            links.append(clean)
    return links


def _flatten_strings(values: Any) -> list[str]:
    out: list[str] = []
    if isinstance(values, str):
        out.append(values)
    elif isinstance(values, dict):
        for value in values.values():
            out.extend(_flatten_strings(value))
    elif isinstance(values, list | tuple):
        for value in values:
            out.extend(_flatten_strings(value))
    return out


class ProjectClient:
    def __init__(self, settings: AppSettings, allow_mock: bool) -> None:
        self.settings = settings
        self.allow_mock = allow_mock

    async def list_buckets(self, query: str = "") -> list[Bucket]:
        if self.settings.project_base_url and self.settings.project_token:
            try:
                return await self._list_live_buckets(query)
            except Exception:
                if not self.allow_mock:
                    raise
        return self._mock_buckets(query)

    async def list_open_tickets(self, query: str = "") -> list[Ticket]:
        if self.settings.project_base_url and self.settings.project_token:
            try:
                return await self._list_live_tickets(query)
            except Exception:
                if not self.allow_mock:
                    raise
        return self._mock_tickets(query)

    async def get_ticket(self, ticket_id: str) -> Ticket:
        if self.settings.project_base_url and self.settings.project_token:
            try:
                return await self._get_live_ticket(ticket_id)
            except Exception:
                if not self.allow_mock:
                    raise
        for ticket in MOCK_TICKETS:
            if ticket.id == ticket_id or ticket.id.split("-")[-1] == ticket_id:
                return ticket
        return MOCK_TICKETS[0]

    async def _list_live_buckets(self, query: str) -> list[Bucket]:
        url = self._url("/api/v3/projects")
        params = {"pageSize": "100", "sortBy": '[["name","asc"]]'}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
        elements = response.json().get("_embedded", {}).get("elements", [])
        buckets = [
            Bucket(
                id=str(item.get("id") or item.get("identifier")),
                name=item.get("name") or item.get("identifier") or "Bucket",
                identifier=item.get("identifier", ""),
                status=item.get("status", "active"),
                source="live",
            )
            for item in elements
        ]
        return self._filter_buckets(buckets, query)

    async def _list_live_tickets(self, query: str) -> list[Ticket]:
        url = self._url("/api/v3/work_packages")
        filters: list[dict[str, Any]] = [
            {"status": {"operator": "o", "values": []}},
            {"assignee": {"operator": "=", "values": [await self._current_user_filter_value()]}},
        ]
        params = {
            "pageSize": "100",
            "sortBy": '[["updatedAt","desc"]]',
            "filters": json.dumps(filters),
        }
        elements: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=15) as client:
            for page in range(1, 21):
                response = await client.get(url, headers=self._headers(), params={**params, "offset": page})
                response.raise_for_status()
                payload = response.json()
                elements.extend(payload.get("_embedded", {}).get("elements", []))
                next_href = payload.get("_links", {}).get("nextByOffset", {}).get("href")
                if not next_href:
                    next_href = payload.get("_links", {}).get("next", {}).get("href")
                if not next_href:
                    break
        tickets = [self._parse_work_package(item) for item in elements]
        return self._filter_tickets(tickets, query)

    async def _current_user_filter_value(self) -> str:
        url = self._url("/api/v3/users/me")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, headers=self._headers())
                response.raise_for_status()
            user_id = response.json().get("id")
            return str(user_id) if user_id else "me"
        except Exception:
            return "me"

    async def _get_live_ticket(self, ticket_id: str) -> Ticket:
        numeric_id = ticket_id.split("-")[-1]
        url = self._url(f"/api/v3/work_packages/{quote(numeric_id)}")
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            payload = response.json()
            try:
                comment_payload = await self._fetch_work_package_comments(client, payload, numeric_id)
            except Exception:
                comment_payload = []
        ticket = self._parse_work_package(payload)
        comment_links = extract_brd_links(comment_payload)
        for link in comment_links:
            if link not in ticket.brd_links:
                ticket.brd_links.append(link)
        return ticket

    async def _fetch_work_package_comments(
        self,
        client: httpx.AsyncClient,
        work_package: dict[str, Any],
        numeric_id: str,
    ) -> list[dict[str, Any]]:
        activities_href = (
            work_package.get("_links", {}).get("activities", {}).get("href")
            or f"/api/v3/work_packages/{quote(numeric_id)}/activities"
        )
        url = self._api_href(activities_href)
        comments: list[dict[str, Any]] = []
        for page in range(1, 6):
            response = await client.get(
                url,
                headers=self._headers(),
                params={"pageSize": "100", "offset": page},
            )
            response.raise_for_status()
            payload = response.json()
            comments.extend(payload.get("_embedded", {}).get("elements", []))
            if not (
                payload.get("_links", {}).get("nextByOffset", {}).get("href")
                or payload.get("_links", {}).get("next", {}).get("href")
            ):
                break
        return comments

    def _parse_work_package(self, item: dict[str, Any]) -> Ticket:
        raw_id = str(item.get("id", ""))
        title = item.get("subject") or f"Ticket {raw_id}"
        description = item.get("description", {})
        description_text = (
            description.get("raw")
            or description.get("html")
            or description.get("format")
            or ""
            if isinstance(description, dict)
            else str(description)
        )
        links = extract_brd_links(item, description_text)
        status = item.get("_links", {}).get("status", {}).get("title", "Open")
        assignee = item.get("_links", {}).get("assignee", {}).get("title", "Unassigned")
        project_href = item.get("_links", {}).get("project", {}).get("href", "")
        bucket_id = project_href.rstrip("/").split("/")[-1] if project_href else ""
        return Ticket(
            id=f"OP-{raw_id}" if raw_id and not raw_id.startswith("OP-") else raw_id,
            title=title,
            status=status,
            assignee=assignee,
            bucket_id=bucket_id,
            updated_at=item.get("updatedAt", ""),
            description=description_text,
            brd_links=links,
            source="live",
        )

    def _mock_tickets(self, query: str) -> list[Ticket]:
        assigned_to_user = [
            ticket
            for ticket in MOCK_TICKETS
            if ticket.assignee == "Jatin"
        ]
        return self._filter_tickets(assigned_to_user, query)

    def _mock_buckets(self, query: str) -> list[Bucket]:
        return self._filter_buckets(MOCK_BUCKETS, query)

    def _filter_buckets(self, buckets: list[Bucket], query: str) -> list[Bucket]:
        if not query:
            return buckets
        needle = query.lower()
        return [
            bucket
            for bucket in buckets
            if needle in bucket.id.lower()
            or needle in bucket.name.lower()
            or needle in bucket.identifier.lower()
        ]

    def _filter_tickets(self, tickets: list[Ticket], query: str) -> list[Ticket]:
        if not query:
            return tickets
        needle = query.lower()
        return [
            ticket
            for ticket in tickets
            if needle in ticket.id.lower() or needle in ticket.title.lower()
        ]

    def _headers(self) -> dict[str, str]:
        basic = base64.b64encode(f"apikey:{self.settings.project_token}".encode()).decode()
        return {
            "Authorization": f"Basic {basic}",
            "X-API-Key": self.settings.project_token,
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return self.settings.project_base_url.rstrip("/") + path

    def _api_href(self, href: str) -> str:
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return self._url(href)


class ScmClient:
    def __init__(self, settings: AppSettings, allow_mock: bool) -> None:
        self.settings = settings
        self.allow_mock = allow_mock

    async def list_repos(self, query: str = "") -> list[Repository]:
        if self.settings.scm_base_url and self.settings.scm_token:
            try:
                return await self._list_live_repos(query)
            except Exception:
                if not self.allow_mock:
                    raise
        return self._mock_repos(query)

    async def list_branches(self, repo_id: str, query: str = "") -> list[Branch]:
        if self.settings.scm_base_url and self.settings.scm_token:
            try:
                return await self._list_live_branches(repo_id, query)
            except Exception:
                if not self.allow_mock:
                    raise
        branches = MOCK_BRANCHES
        if query:
            branches = [branch for branch in branches if query.lower() in branch.name.lower()]
        return branches

    async def _list_live_repos(self, query: str) -> list[Repository]:
        url = self._url("/api/v4/projects")
        params = {"membership": "true", "simple": "true", "per_page": "50"}
        if query:
            params["search"] = query
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
        repos = []
        for item in response.json():
            repos.append(
                Repository(
                    id=str(item.get("id") or item.get("path_with_namespace")),
                    name=item.get("name") or item.get("path") or "Repository",
                    path=item.get("path_with_namespace") or item.get("path", ""),
                    default_branch=item.get("default_branch") or "main",
                    web_url=item.get("web_url", ""),
                    source="live",
                )
            )
        return repos

    async def _list_live_branches(self, repo_id: str, query: str) -> list[Branch]:
        url = self._url(f"/api/v4/projects/{quote(repo_id, safe='')}/repository/branches")
        params = {"per_page": "100"}
        if query:
            params["search"] = query
        items: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=15) as client:
            page = 1
            while page <= 20:
                response = await client.get(
                    url,
                    headers=self._headers(),
                    params={**params, "page": str(page)},
                )
                response.raise_for_status()
                items.extend(response.json())
                next_page = response.headers.get("X-Next-Page")
                if not next_page:
                    break
                page = int(next_page)
        return [
            Branch(
                name=item.get("name", ""),
                protected=bool(item.get("protected")),
                default=bool(item.get("default")),
                source="live",
            )
            for item in items
            if item.get("name")
        ]

    def _mock_repos(self, query: str) -> list[Repository]:
        if not query:
            return MOCK_REPOS
        needle = query.lower()
        return [
            repo
            for repo in MOCK_REPOS
            if needle in repo.name.lower() or needle in repo.path.lower() or needle in repo.id.lower()
        ]

    def _headers(self) -> dict[str, str]:
        return {
            "PRIVATE-TOKEN": self.settings.scm_token,
            "Authorization": f"Bearer {self.settings.scm_token}",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return self.settings.scm_base_url.rstrip("/") + path


class GoogleDocClient:
    def __init__(self, settings: AppSettings, allow_mock: bool) -> None:
        self.settings = settings
        self.allow_mock = allow_mock

    async def fetch_text(self, brd_url: str) -> tuple[str, str, str]:
        if self.allow_mock and "demo-tracefix-brd" in brd_url:
            return MOCK_BRD_TEXT, "Fetched mock BRD for the built-in demo ticket.", "mock"
        if brd_url:
            try:
                return await self._fetch_live_text(brd_url)
            except Exception:
                if not self.allow_mock:
                    raise
        return MOCK_BRD_TEXT, "Fetched mock BRD because live Google Doc access was unavailable.", "mock"

    async def _fetch_live_text(self, brd_url: str) -> tuple[str, str, str]:
        doc_match = re.search(r"docs\.google\.com/document/d/([^/]+)", brd_url)
        url = brd_url
        if doc_match:
            doc_id = doc_match.group(1)
            url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
        headers = {}
        if self.settings.google_auth_mode == "token" and self.settings.google_token:
            headers["Authorization"] = f"Bearer {self.settings.google_token}"
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
        text = response.text.strip()
        if not text:
            raise ValueError("BRD document was empty")
        return text, "Fetched BRD from configured Google/public document access.", "live"
