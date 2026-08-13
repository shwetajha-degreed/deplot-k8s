from pathlib import Path

import httpx

from app.config import Settings
from app.services.base import BaseService


class GitHubService(BaseService):
    name = "github"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        headers = {}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        self._client = httpx.AsyncClient(timeout=30.0, headers=headers)

    async def fetch_repo_tree(self, repo_url: str) -> dict[str, str]:
        """Return path -> content snippet map for key files (MVP: demo + API tree)."""
        owner, repo = self._parse_github_url(repo_url)
        api_base = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {"Accept": "application/vnd.github+json"}

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            if self._settings.github_token:
                client.headers["Authorization"] = f"Bearer {self._settings.github_token}"
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
            "zerops.yaml",
            "prisma/schema.prisma",
            "next.config",
        )
        for entry in tree:
            path = entry.get("path", "")
            if entry.get("type") != "blob":
                continue
            if any(k in path for k in key_patterns):
                files[path] = await self._fetch_raw(owner, repo, path)
        return files

    async def _fetch_raw(self, owner: str, repo: str, path: str) -> str:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{path}"
        async with httpx.AsyncClient(timeout=15.0) as client:
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
