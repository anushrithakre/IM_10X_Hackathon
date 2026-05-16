from __future__ import annotations

import base64
import html
import io
import json
import re
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree
from zipfile import ZipFile

import httpx

from .mock_data import MOCK_BRD_TEXT, MOCK_BRANCHES, MOCK_BUCKETS, MOCK_REPOS, MOCK_TICKETS
from .schemas import AppSettings, Branch, Bucket, Repository, Ticket

BRD_LINK_RE = re.compile(
    r"https?://(?:docs\.google\.com/document/d/[^\s)>\"]+|[^\s)>\"]*(?:brd|requirement)[^\s)>\"]*)",
    re.IGNORECASE,
)
BRD_ATTACHMENT_RE = re.compile(r"(brd|requirement|frd|prd|spec)", re.IGNORECASE)
TEXT_ATTACHMENT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".html",
    ".htm",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
}
DOCUMENT_ATTACHMENT_EXTENSIONS = {
    *TEXT_ATTACHMENT_EXTENSIONS,
    ".docx",
    ".pdf",
}


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
            try:
                attachments = await self._fetch_work_package_attachments(client, payload, numeric_id)
            except Exception:
                attachments = []
        ticket = self._parse_work_package(payload)
        comment_links = extract_brd_links(comment_payload)
        for link in comment_links:
            if link not in ticket.brd_links:
                ticket.brd_links.append(link)
        comments = []
        for item in comment_payload:
            text = self._comment_text(item)
            if text:
                comments.append(text)
        ticket.comments = comments
        ticket.brd_attachments = self._brd_attachments(attachments)
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

    async def _fetch_work_package_attachments(
        self,
        client: httpx.AsyncClient,
        work_package: dict[str, Any],
        numeric_id: str,
    ) -> list[dict[str, Any]]:
        attachments_href = (
            work_package.get("_links", {}).get("attachments", {}).get("href")
            or f"/api/v3/work_packages/{quote(numeric_id)}/attachments"
        )
        response = await client.get(self._api_href(attachments_href), headers=self._headers())
        response.raise_for_status()
        return response.json().get("_embedded", {}).get("elements", [])

    async def fetch_brd_attachment_text(self, ticket_id: str) -> tuple[str, str, str]:
        if not (self.settings.project_base_url and self.settings.project_token):
            raise ValueError("Project token is not configured, so ticket files cannot be fetched.")
        numeric_id = ticket_id.split("-")[-1]
        url = self._url(f"/api/v3/work_packages/{quote(numeric_id)}")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            work_package = response.json()
            attachments = await self._fetch_work_package_attachments(client, work_package, numeric_id)
            candidates = self._brd_attachments(attachments)
            if not candidates:
                raise ValueError("No BRD-like text attachment found on ticket.")
            attachment = candidates[0]
            download_url = attachment.get("download_url") or attachment.get("href") or ""
            if not download_url:
                raise ValueError("BRD attachment did not include a download URL.")
            file_response = await client.get(self._api_href(download_url), headers=self._headers())
            file_response.raise_for_status()
        text = self._attachment_text(attachment.get("filename", ""), file_response.content).strip()
        if not text:
            raise ValueError("BRD attachment had no extractable text. It may be a scanned/image-only PDF.")
        return text, f"Fetched BRD from ticket attachment: {attachment.get('filename')}", "live"

    async def fetch_ticket_comments_text(self, ticket_id: str) -> str:
        if not (self.settings.project_base_url and self.settings.project_token):
            return ""
        numeric_id = ticket_id.split("-")[-1]
        url = self._url(f"/api/v3/work_packages/{quote(numeric_id)}")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            work_package = response.json()
            comments = await self._fetch_work_package_comments(client, work_package, numeric_id)
        lines = []
        for item in comments:
            text = self._comment_text(item)
            if text:
                lines.append(text)
        return "\n\n".join(lines)

    def _parse_work_package(self, item: dict[str, Any]) -> Ticket:
        raw_id = str(item.get("id", ""))
        title = item.get("subject") or f"Ticket {raw_id}"
        description = item.get("description", {})
        description_text = (
            description.get("raw")
            or description.get("html")
            or ""
            if isinstance(description, dict)
            else str(description)
        )
        description_text = self._clean_markup_text(description_text)
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

    def _brd_attachments(self, attachments: list[dict[str, Any]]) -> list[dict[str, str]]:
        candidates = []
        for item in attachments:
            filename = (
                item.get("fileName")
                or item.get("filename")
                or item.get("name")
                or item.get("title")
                or item.get("_links", {}).get("self", {}).get("title")
                or ""
            )
            href = (
                item.get("_links", {}).get("downloadLocation", {}).get("href")
                or item.get("_links", {}).get("download", {}).get("href")
                or item.get("_links", {}).get("self", {}).get("href")
                or ""
            )
            extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if not href:
                continue
            is_supported = not extension or extension in DOCUMENT_ATTACHMENT_EXTENSIONS
            if not is_supported and not BRD_ATTACHMENT_RE.search(filename):
                continue
            score = 4 if BRD_ATTACHMENT_RE.search(filename) else 1
            if extension in DOCUMENT_ATTACHMENT_EXTENSIONS:
                score += 2
            candidates.append(
                {
                    "filename": filename or "attachment",
                    "href": href,
                    "download_url": href,
                    "score": str(score),
                }
            )
        return sorted(candidates, key=lambda item: item["score"], reverse=True)

    def _attachment_text(self, filename: str, content: bytes) -> str:
        extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if extension == ".docx":
            return self._docx_text(content)
        if extension == ".pdf":
            return self._pdf_text(content)
        if extension in {".html", ".htm"}:
            return re.sub(r"<[^>]+>", " ", content.decode("utf-8", errors="replace"))
        return content.decode("utf-8", errors="replace")

    def _docx_text(self, content: bytes) -> str:
        with ZipFile(io.BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = []
        for paragraph in root.findall(".//w:p", namespace):
            text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
            if text.strip():
                paragraphs.append(text)
        return "\n".join(paragraphs)

    def _pdf_text(self, content: bytes) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF BRD files require the pypdf package. Run pip install -r requirements.txt.") from exc
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def _comment_text(self, item: dict[str, Any]) -> str:
        comment = item.get("comment") or item.get("description") or item.get("details") or ""
        if isinstance(comment, dict):
            text = comment.get("raw") or comment.get("html") or ""
        else:
            text = str(comment)
        return self._clean_markup_text(text)

    def _clean_markup_text(self, text: str) -> str:
        text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
        return " ".join(text.split())

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

    async def fetch_repository_context(self, repo_id: str | None, branch: str | None) -> str:
        if not repo_id or not branch or not (self.settings.scm_base_url and self.settings.scm_token):
            return ""
        try:
            return await self._fetch_live_repository_context(repo_id, branch)
        except Exception:
            if not self.allow_mock:
                raise
        return ""

    async def fetch_agent_project_manifest(self, repo_id: str | None, branch: str | None) -> str:
        if not repo_id or not branch or not (self.settings.scm_base_url and self.settings.scm_token):
            return ""
        raw_url = self._url(
            f"/api/v4/projects/{quote(repo_id, safe='')}/repository/files/{quote('agent.project.yml', safe='')}/raw"
        )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(raw_url, headers=self._headers(), params={"ref": branch})
                if response.status_code >= 400:
                    return ""
                return response.text.strip()
        except Exception:
            if not self.allow_mock:
                raise
        return ""

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

    async def _fetch_live_repository_context(self, repo_id: str, branch: str) -> str:
        tree_url = self._url(f"/api/v4/projects/{quote(repo_id, safe='')}/repository/tree")
        params = {"recursive": "true", "per_page": "100", "ref": branch}
        async with httpx.AsyncClient(timeout=20) as client:
            files: list[str] = []
            page = 1
            while page <= 50:
                response = await client.get(
                    tree_url,
                    headers=self._headers(),
                    params={**params, "page": str(page)},
                )
                response.raise_for_status()
                files.extend(
                    item.get("path", "")
                    for item in response.json()
                    if item.get("type") == "blob" and item.get("path")
                )
                next_page = response.headers.get("X-Next-Page")
                if not next_page:
                    break
                page = int(next_page)
            selected = self._select_context_files(files)
            search_hits = await self._search_repository_blobs(client, repo_id, branch)
            for path in search_hits:
                if path not in selected:
                    selected.insert(0, path)
            snippets = []
            for path in selected[:12]:
                raw_url = self._url(
                    f"/api/v4/projects/{quote(repo_id, safe='')}/repository/files/{quote(path, safe='')}/raw"
                )
                file_response = await client.get(
                    raw_url,
                    headers=self._headers(),
                    params={"ref": branch},
                )
                if file_response.status_code >= 400:
                    continue
                text = file_response.text.strip()
                if text:
                    snippets.append(f"FILE: {path}\n{text[:2500]}")
        file_summary = "\n".join(f"- {path}" for path in selected[:25])
        return (
            f"Repository files scanned: {len(files)}\n"
            f"Repository files considered:\n{file_summary}\n\n"
            "Relevant snippets:\n"
            + "\n\n".join(snippets)
        )

    async def _search_repository_blobs(
        self,
        client: httpx.AsyncClient,
        repo_id: str,
        branch: str,
    ) -> list[str]:
        paths: list[str] = []
        for query in ("whatsapp", "template", "message", "notification", "sms", "media", "image"):
            url = self._url(f"/api/v4/projects/{quote(repo_id, safe='')}/search")
            response = await client.get(
                url,
                headers=self._headers(),
                params={"scope": "blobs", "search": query, "ref": branch, "per_page": "20"},
            )
            if response.status_code >= 400:
                continue
            for item in response.json():
                path = item.get("path") or item.get("filename") or ""
                if path and path not in paths:
                    paths.append(path)
        return paths

    def _select_context_files(self, files: list[str]) -> list[str]:
        allowed = (".py", ".js", ".ts", ".tsx", ".java", ".go", ".php", ".rb", ".cs", ".yml", ".yaml", ".json")
        ignored = ("/node_modules/", "/vendor/", "/dist/", "/build/", "/.next/", "/target/")
        keywords = (
            "whatsapp",
            "template",
            "notification",
            "message",
            "buyer",
            "image",
            "media",
            "api",
            "controller",
            "service",
            "route",
        )
        candidates = []
        for path in files:
            lowered = f"/{path.lower()}"
            if not lowered.endswith(allowed) or any(part in lowered for part in ignored):
                continue
            score = sum(1 for keyword in keywords if keyword in lowered)
            if score:
                candidates.append((score, path))
        return [path for _, path in sorted(candidates, key=lambda item: (-item[0], len(item[1])))]

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
        access_token = await self._access_token()
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
        text = response.text.strip()
        if not text:
            raise ValueError("BRD document was empty")
        return text, "Fetched BRD from configured Google/public document access.", "live"

    async def _access_token(self) -> str:
        if self.settings.google_token:
            return self.settings.google_token
        if not (
            self.settings.google_client_id
            and self.settings.google_client_secret
            and self.settings.google_refresh_token
        ):
            return ""
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.settings.google_client_id,
                    "client_secret": self.settings.google_client_secret,
                    "refresh_token": self.settings.google_refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
        return response.json().get("access_token", "")
