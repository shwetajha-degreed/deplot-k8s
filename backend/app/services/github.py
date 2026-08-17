import asyncio
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

        Same behavior as before, plus the raw tree is now cached on the
        instance so callers can pull the full path list via
        get_last_tree_paths(). This lets analyze feed the paths + key file
        contents into generate_dockerfile so Gemini can locate the actual
        entrypoint (e.g. `dev_velocity.main:app` vs `app.main:app`) rather
        than guessing from a hardcoded stack summary.

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
            # Repos default to whatever their owner chose — main, master,
            # develop, trunk, ... Fetch /repos/{owner}/{repo} first so we
            # get the authoritative default_branch instead of guessing.
            # This also gives us a proper 404 with token context if the
            # repo doesn't exist or the token can't see it, instead of
            # bubbling up a misleading "master 404".
            meta = await client.get(api_base)
            meta.raise_for_status()
            self._last_default_branch = (
                meta.json().get("default_branch") or "main"
            )
            # Resolve branch → tree SHA via /commits before hitting
            # /git/trees. Passing a branch name directly to /git/trees
            # works for most repos but 404s on some (GitHub's tree
            # endpoint documents `tree_sha` in the path, and the
            # branch-name shortcut is not universally supported — same
            # token that succeeds on /commits/main can 404 on
            # /git/trees/main for the same repo). Handing it a real
            # tree SHA sidesteps that.
            commit_resp = await client.get(f"{api_base}/commits/{self._last_default_branch}")
            commit_resp.raise_for_status()
            tree_sha = (
                (commit_resp.json().get("commit") or {}).get("tree") or {}
            ).get("sha") or self._last_default_branch

            # Retry the tree endpoint on transient GitHub failures.
            # `/repos` and `/commits` already succeeded, so a 404 here
            # is not "repo not visible" — it's transient. Retry 3×
            # with exponential backoff.
            tree_url = f"{api_base}/git/trees/{tree_sha}?recursive=1"
            resp = None
            for attempt in range(3):
                candidate = await client.get(tree_url)
                if candidate.status_code < 400:
                    resp = candidate
                    break
                # 5xx / transient 404 → retry. 401/403 → real, bail.
                if candidate.status_code in (401, 403):
                    resp = candidate
                    break
                if attempt == 2:
                    resp = candidate
                    break
                await asyncio.sleep(0.5 * (2 ** attempt))
            resp.raise_for_status()
            tree = resp.json().get("tree", [])

        # Cache all blob paths for callers that want the full skeleton
        # (analyze -> generate_dockerfile).
        self._last_tree_paths = [
            entry.get("path", "") for entry in tree if entry.get("type") == "blob"
        ]

        files: dict[str, str] = {}
        key_patterns = (
            "package.json",
            "requirements.txt",
            "pyproject.toml",
            "Dockerfile",
            "prisma/schema.prisma",
            "next.config",
            "main.py",
            "server.js",
            "go.mod",
            "Cargo.toml",
            "Gemfile",
            "pom.xml",
            "build.gradle",
            # For required-env detection:
            ".env.example",
            ".env.sample",
            ".env.template",
            "settings.py",
            "config.py",
            "config.js",
            "config.ts",
            "App.js",
            "App.jsx",
            "App.tsx",
            "index.js",
            "index.ts",
        )
        for path in self._last_tree_paths:
            if any(k in path for k in key_patterns):
                files[path] = await self._fetch_raw(owner, repo, path, token)
        return files

    def get_last_tree_paths(self) -> list[str]:
        return list(getattr(self, "_last_tree_paths", []) or [])

    def get_last_default_branch(self) -> str:
        return getattr(self, "_last_default_branch", "main") or "main"

    async def fetch_dockerfile(
        self,
        repo_url: str,
        service_name: str,
        monorepo_path: str | None = None,
        github_token: str | None = None,
    ) -> str | None:
        """Find a Dockerfile in the repo for this service, in priority order.

        1. {monorepo_path}/Dockerfile  (e.g. backend/Dockerfile)
        2. Dockerfile.{service_name}   (e.g. Dockerfile.api at repo root)
        3. Dockerfile                  (repo root)

        Returns the raw content, or None if no match. The team's own
        Dockerfile is preferred over Gemini-generated or fallback ones —
        it's authoritative, was actually tested, and covers stacks our
        fallback doesn't know (Go, .NET, Ruby, Java, etc.).
        """
        owner, repo = self._parse_github_url(repo_url)
        token = self._token(github_token)

        candidates: list[str] = []
        if monorepo_path and monorepo_path not in (".", ""):
            candidates.append(f"{monorepo_path.strip('/')}/Dockerfile")
        # Fallback monorepo layouts our stack detector doesn't always populate:
        if service_name in ("api", "backend"):
            candidates.extend(["backend/Dockerfile", "api/Dockerfile"])
        elif service_name in ("frontend", "web"):
            candidates.extend(["frontend/Dockerfile", "web/Dockerfile"])
        if service_name:
            candidates.append(f"Dockerfile.{service_name}")
        candidates.append("Dockerfile")
        # De-dup while preserving order.
        seen: set[str] = set()
        candidates = [c for c in candidates if not (c in seen or seen.add(c))]

        for path in candidates:
            content = await self._fetch_raw(owner, repo, path, token)
            if content and "FROM " in content:
                return content
        return None

    async def _fetch_raw(
        self, owner: str, repo: str, path: str, token: str | None = None
    ) -> str:
        # Prefer the GitHub API /contents endpoint over raw.githubusercontent.com:
        # raw.* is inconsistent for private repos (Bearer tokens sometimes
        # trigger a 302 to a signed URL that drops the auth header; fine-grained
        # tokens often 404 outright). The API path returns base64-encoded
        # content and works uniformly with `Authorization: Bearer <PAT>` for
        # both public and private repos.
        import base64

        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                # Try master branch fallback for older repos.
                resp = await client.get(url, params={"ref": "master"})
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("encoding") == "base64":
                        raw = base64.b64decode(data.get("content", "") or "")
                        return raw.decode("utf-8", errors="replace")[:8000]
                except Exception:
                    pass
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
