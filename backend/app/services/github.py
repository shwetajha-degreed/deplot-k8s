from pathlib import Path

import httpx

from app.config import Settings
from app.services.base import BaseService


class GitHubService(BaseService):
    name = "github"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _token(self, override: str | None) -> str | None:
        # Per-request token wins over the platform-wide default.
        return override or (self._settings.github_token or None)

    async def fetch_repo_tree(
        self, repo_url: str, github_token: str | None = None
    ) -> dict[str, str]:
        """Return path -> content snippet map for key files.

        github_token: optional GitHub PAT for private repos; takes precedence
        over settings.github_token.
        """
        owner, repo = self._parse_github_url(repo_url)
        api_base = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {"Accept": "application/vnd.github+json"}
        token = self._token(github_token)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            resp = await client.get(f"{api_base}/git/trees/main?recursive=1")
            if resp.status_code == 404:
                resp = await client.get(f"{api_base}/git/trees/master?recursive=1")
            resp.raise_for_status()
            tree = resp.json().get("tree", [])

        files: dict[str, str] = {}
        key_patterns = (
            "package.json",
            "requirements.txt",
            "pyproject.toml",
            "Dockerfile",
            "prisma/schema.prisma",
            "next.config",
        )
        for entry in tree:
            path = entry.get("path", "")
            if entry.get("type") != "blob":
                continue
            if any(k in path for k in key_patterns):
                files[path] = await self._fetch_raw(owner, repo, path, token)
        return files

    async def _fetch_raw(
        self, owner: str, repo: str, path: str, token: str | None = None
    ) -> str:
        # raw.githubusercontent.com returns 404 for private repos when
        # unauthenticated; the token unlocks them.
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{path}"
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                url = url.replace("/main/", "/master/")
                resp = await client.get(url)
            if resp.status_code == 200:
                return resp.text[:8000]
        return ""

    @staticmethod
    def _parse_github_url(repo_url: str) -> tuple[str, str]:
        path = repo_url.strip().rstrip(".,;/").replace(".git", "")
        # Prefer URL path segments over pathlib (which mishandles scheme:// hosts).
        if "github.com/" in path:
            tail = path.split("github.com/", 1)[1]
            parts = [p for p in tail.split("/") if p]
            if len(parts) >= 2:
                return parts[0], parts[1]
        parts = [p for p in Path(path).parts if p not in (".", "/")]
        if len(parts) < 2:
            raise ValueError(f"Invalid GitHub URL: {repo_url}")
        return parts[-2], parts[-1]
