import re
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


# Env vars Deplot injects itself — hide from the "required env" list so the
# wizard's textarea doesn't ask users to supply them again.
_DEPLOT_MANAGED_ENV: frozenset[str] = frozenset(
    {
        "DATABASE_URL",
        "DATABASE_URL_SYNC",
        "REDIS_URL",
        "TYPESENSE_URL",
        "TYPESENSE_HOST",
        "TYPESENSE_PORT",
        "TYPESENSE_PROTOCOL",
        "TYPESENSE_API_KEY",
        "PORT",
        "HOST",
        "HOSTNAME",
        "NODE_ENV",
        "PYTHONUNBUFFERED",
        "PYTHONDONTWRITEBYTECODE",
        "NEXT_PUBLIC_API_URL",
        "REACT_APP_API_URL",
        "VITE_API_URL",
        "BACKEND_URL",
        "PATH",
        "HOME",
        "USER",
    }
)


# Match the local-dev fallback string an app assigns when the runtime env
# is unset:
#     process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"
#     process.env.REACT_APP_API_URL || 'http://localhost:5000'
#     import.meta.env.VITE_API_URL ?? `http://127.0.0.1:8000/api`
# Captures the URL literal (quotes stripped). We read the PATH from it
# so we can mirror the app's own convention when baking the build arg.
_API_URL_FALLBACK_RE = re.compile(
    r"""(?:NEXT_PUBLIC_API_URL|REACT_APP_API_URL|VITE_API_URL|API_URL|API_BASE)"""
    r"""\s*(?:\?\?|\|\||:)\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)


def _detect_api_url_path(files: dict[str, str]) -> str:
    """Return the path portion (e.g. "/api/v1") the frontend expects
    NEXT_PUBLIC_API_URL / REACT_APP_API_URL / VITE_API_URL to resolve to.

    Scans the app's OWN fallback string — we mirror whatever convention
    its author chose. Empty string means bake the bare origin.
    """
    for path, content in (files or {}).items():
        if not content:
            continue
        low = path.lower()
        if not low.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs")):
            continue
        for match in _API_URL_FALLBACK_RE.finditer(content):
            url = match.group(1).strip()
            # Skip prod-looking URLs and empty strings; the LOCAL fallback
            # is the signal we want. Prod URLs are baked at deploy time
            # anyway and would be misleading.
            if not url or not url.startswith(("http://localhost", "http://127.")):
                continue
            # Extract path after the host:port portion.
            m = re.match(r"https?://[^/]+(/[^?#]*)?", url)
            if not m:
                continue
            return (m.group(1) or "").rstrip("/")
    return ""


def _scan_required_env(files: dict[str, str]) -> list[str]:
    """Return env var names referenced by the app's source or documented
    in a .env.example / .env.sample / .env.template file.

    Detects:
      - Python:  os.getenv("FOO") | os.environ["FOO"] | os.environ.get("FOO")
      - Node/Vue/Next: process.env.FOO | process.env["FOO"]
      - Vite:  import.meta.env.VITE_FOO
      - .env.example style KEY=... lines

    Filters out Deplot-managed env vars (DATABASE_URL, REDIS_URL, ...)
    and standard container env (PATH, HOME, ...) so the wizard only
    prompts for values the user actually needs to provide.
    """
    found: set[str] = set()

    py_patterns = (
        re.compile(r"os\.getenv\(\s*['\"]([A-Z_][A-Z0-9_]*)['\"]"),
        re.compile(r"os\.environ\[\s*['\"]([A-Z_][A-Z0-9_]*)['\"]\s*\]"),
        re.compile(r"os\.environ\.get\(\s*['\"]([A-Z_][A-Z0-9_]*)['\"]"),
    )
    js_patterns = (
        re.compile(r"process\.env\.([A-Z_][A-Z0-9_]*)"),
        re.compile(r"process\.env\[\s*['\"]([A-Z_][A-Z0-9_]*)['\"]\s*\]"),
        re.compile(r"import\.meta\.env\.([A-Z_][A-Z0-9_]*)"),
    )

    for path, content in (files or {}).items():
        text = content or ""
        if not text:
            continue
        low = path.lower()
        if low.endswith((".py", ".pyi")) or low.endswith(("config.py", "settings.py")):
            patterns = py_patterns
        elif low.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
            patterns = js_patterns
        else:
            patterns = py_patterns + js_patterns
        for pat in patterns:
            found.update(pat.findall(text))

        # .env.example (or .sample / .template) is the canonical source
        # of truth when the repo ships one.
        if any(marker in low for marker in (".env.example", ".env.sample", ".env.template")):
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip()
                if re.match(r"^[A-Z_][A-Z0-9_]*$", key):
                    found.add(key)

    filtered = [k for k in found if k not in _DEPLOT_MANAGED_ENV]
    return sorted(filtered)

from app.agents.orchestrator import AgentContext
from app.api.deps import get_orchestrator
from app.bootstrap import get_service
from app.models.analysis import (
    AnalysisSession,
    AnalyzeRequest,
    AnalyzeResponse,
    ArchitectureGraph,
    SessionStatus,
    ValidationReport,
)
from app.models.deployment import DeploymentPlan, K8sConfig
from app.services.k8s import repo_slug_from_url
from app.services.store import session_store

router = APIRouter()


class SessionIdBody(BaseModel):
    session_id: UUID


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_repo(body: AnalyzeRequest):
    session = AnalysisSession(
        repo_url=str(body.repo_url) if body.repo_url else None,
        github_token=body.github_token,
        status=SessionStatus.ANALYZING,
    )
    session_store.save(session)

    github = get_service("github")
    orchestrator = get_orchestrator()

    files: dict[str, str] = {}
    if body.demo_mode:
        files = _demo_files()
    elif body.repo_url:
        try:
            files = await github.fetch_repo_tree(
                str(body.repo_url), github_token=body.github_token
            )
        except Exception as exc:
            # Distinguish a real perm error from a transient GitHub-side
            # blip so the wizard's error banner points users at the right
            # thing to check.
            msg = str(exc)
            code = "REPO_FETCH_FAILED"
            hint = ""
            if "404" in msg:
                hint = (
                    " GitHub returned 404 — this usually means either the "
                    "token can't see this repo/branch (Contents: Read "
                    "permission on fine-grained tokens, or `repo` scope on "
                    "classic tokens), or GitHub is degraded — check "
                    "https://www.githubstatus.com/ and retry."
                )
            elif "401" in msg or "403" in msg:
                hint = " Token appears invalid or lacks required scopes."
            elif "5" in msg[:5] or "timeout" in msg.lower():
                hint = (
                    " GitHub appears to be degraded — check "
                    "https://www.githubstatus.com/ and retry in a moment."
                )
                code = "GITHUB_DEGRADED"
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"Could not fetch repository: {exc}.{hint}",
                    "code": code,
                },
            ) from exc
    else:
        raise HTTPException(
            status_code=400,
            detail="repo_url is required when demo_mode is false",
        )

    stack = await orchestrator.run("repository_analyzer", AgentContext(payload={"files": files}))
    if session.repo_url:
        stack.repo_slug = repo_slug_from_url(session.repo_url)
    elif body.demo_mode:
        stack.repo_slug = "demo"
    session.stack = stack
    # Persist analyze context so deploy can enrich Gemini's Dockerfile prompt.
    session.files_seen = {p: (c or "")[:4000] for p, c in files.items() if c}
    if hasattr(github, "get_last_tree_paths"):
        try:
            session.tree_paths = github.get_last_tree_paths()[:2000]
        except Exception:
            session.tree_paths = []
    if hasattr(github, "get_last_default_branch"):
        try:
            session.default_branch = github.get_last_default_branch()
        except Exception:
            session.default_branch = "main"
    # Broaden the env-var scan beyond the key_patterns bucket. That bucket
    # is optimized for stack detection (pyproject, package.json, ...) but
    # env vars live in ANY source file — dev-velocity's OPENAI_API_KEY sits
    # in ai_insights.py which isn't in key_patterns. Do a second pass: fetch
    # up to N Python/JS/TS files from the tree and scan them for env refs
    # only (content isn't stored on the session).
    scan_files: dict[str, str] = dict(files)
    if hasattr(github, "get_last_tree_paths"):
        paths = github.get_last_tree_paths()
        # Bounded to avoid fanning out on huge repos. 40 files ≈ one round
        # of parallel-ish GitHub API calls; every hit is a small text file.
        _MAX_SCAN_FILES = 40
        source_paths = [
            p for p in paths
            if p.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".mjs"))
            and p not in scan_files
            and "node_modules/" not in p
            and "/dist/" not in p
            and "/build/" not in p
            and "/.next/" not in p
            and "/tests/" not in p
            and "test_" not in p.rsplit("/", 1)[-1]
        ][:_MAX_SCAN_FILES]
        try:
            owner, repo = github._parse_github_url(str(body.repo_url))
            # Parallel with concurrency cap: 40 sequential httpx calls to
            # api.github.com (~500ms each) put analyze over Envoy's 15s
            # upstream timeout for repos with many matched source files
            # (e.g. maestro_forge). asyncio.gather with a small semaphore
            # cuts wall-clock to seconds while staying under GitHub's
            # primary rate-limit (5000/hr for authenticated).
            import asyncio as _asyncio
            sem = _asyncio.Semaphore(8)

            async def _fetch_bounded(path: str):
                async with sem:
                    try:
                        return path, await github._fetch_raw(
                            owner, repo, path, body.github_token
                        )
                    except Exception:
                        return path, None

            results = await _asyncio.gather(
                *[_fetch_bounded(p) for p in source_paths]
            )
            for p, content in results:
                if content:
                    scan_files[p] = content
        except Exception:
            pass
    session.required_env = _scan_required_env(scan_files)
    # Mirror the frontend's own local-dev NEXT_PUBLIC_API_URL fallback
    # path (e.g. /api/v1 or "") into the stack. Deploy will bake the
    # baked API URL as `<origin><path>` so ${API_BASE}/health lands on
    # whatever route the app author expected without Deplot needing to
    # know FastAPI/Django/Express route conventions.
    if session.stack:
        session.stack.api_url_path = _detect_api_url_path(scan_files)
    session.status = SessionStatus.READY
    session_store.save(session)

    return AnalyzeResponse(
        session_id=session.id,
        status=session.status,
        stack=stack,
        required_env=session.required_env,
    )


@router.post("/architecture", response_model=ArchitectureGraph)
async def generate_architecture(body: SessionIdBody):
    session = session_store.get(body.session_id)
    if not session or not session.stack:
        raise HTTPException(status_code=404, detail="Session not found or not analyzed")

    orchestrator = get_orchestrator()
    graph = await orchestrator.run(
        "infrastructure_planner",
        AgentContext(payload={"stack": session.stack}),
    )
    session.architecture = graph
    session_store.save(session)
    return graph


@router.post("/generate-yaml", response_model=K8sConfig)
async def generate_yaml(body: SessionIdBody):
    session = session_store.get(body.session_id)
    if not session or not session.stack:
        raise HTTPException(status_code=404, detail="Session not found or not analyzed")

    orchestrator = get_orchestrator()
    config = await orchestrator.run(
        "yaml_generator",
        AgentContext(payload={"stack": session.stack, "repo_url": session.repo_url}),
    )
    return config


class ValidateRequest(BaseModel):
    session_id: UUID


@router.post("/validate", response_model=ValidationReport)
async def validate_config(body: ValidateRequest):
    session = session_store.get(body.session_id)
    if not session or not session.stack:
        raise HTTPException(status_code=404, detail="Session not found")

    yaml_svc = get_service("yaml_generator")
    config = await yaml_svc.generate(session.stack, session.repo_url)

    orchestrator = get_orchestrator()
    return await orchestrator.run(
        "deployment_validator",
        AgentContext(payload={"stack": session.stack, "config": config}),
    )


@router.get("/sessions/{session_id}", response_model=AnalysisSession)
async def get_session(session_id: UUID):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions/{session_id}/plan", response_model=DeploymentPlan)
async def get_plan(session_id: UUID):
    session = session_store.get(session_id)
    if not session or not session.stack:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.architecture:
        orchestrator = get_orchestrator()
        session.architecture = await orchestrator.run(
            "infrastructure_planner",
            AgentContext(payload={"stack": session.stack}),
        )
        session_store.save(session)

    planner = get_service("planner")
    return planner.build_plan(session.stack, session.architecture)


def _demo_files() -> dict[str, str]:
    return {
        "package.json": '{"dependencies":{"next":"15.0.0","@prisma/client":"5.0.0","typesense":"2.0.0","ioredis":"5.0.0"},"engines":{"node":">=22"}}',
        "requirements.txt": "fastapi\nuvicorn\n",
        "prisma/schema.prisma": 'datasource db { provider = "postgresql" url = env("DATABASE_URL") }',
    }
