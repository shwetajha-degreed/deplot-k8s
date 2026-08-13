import json
import re
from pathlib import Path

from app.models.analysis import (
    ArchitectureEdge,
    ArchitectureGraph,
    ArchitectureNode,
    StackDetection,
    ValidationIssue,
    ValidationReport,
)
from app.models.deployment import DeploymentPlan, ZeropsConfig
from app.services.base import BaseService
from app.services.gemini import GeminiClient
from app.services.zerops import repo_slug_from_url, hostnames_for_slug


class AnalysisService(BaseService):
    name = "analysis"

    def detect_stack(self, files: dict[str, str]) -> StackDetection:
        signals: dict = {}
        stack = StackDetection(raw_signals=signals)

        pkg_paths = [k for k in files if k.endswith("package.json")]
        root_pkg = files.get("package.json") or (files.get(pkg_paths[0]) if pkg_paths else "")
        frontend_path = "."
        for path in pkg_paths:
            if path.startswith("frontend/") or path == "frontend/package.json":
                frontend_path = "frontend"
                root_pkg = files[path]
                break

        if root_pkg:
            stack.has_frontend = True
            stack.language = "javascript"
            stack.package_manager = "npm"
            stack.monorepo_frontend_path = frontend_path if frontend_path != "." else None
            if "@next/" in root_pkg or '"next"' in root_pkg:
                stack.framework = "nextjs"
                stack.runtime = "nodejs@22"
                signals["framework"] = "nextjs"
            if "typesense" in root_pkg.lower() or "@typesense/typesense" in root_pkg:
                stack.search = "typesense"
                signals["search"] = "typesense"
            if "prisma" in root_pkg.lower():
                stack.database = "postgresql"
                signals["database"] = "prisma/postgresql"

        req_paths = [k for k in files if k.endswith("requirements.txt")]
        backend_path = "."
        req = files.get("requirements.txt") or ""
        for path in req_paths:
            if path.startswith("backend/") or path == "backend/requirements.txt":
                backend_path = "backend"
                req = files[path]
                break
        if not req and req_paths:
            req = files[req_paths[0]]

        if req:
            stack.has_backend = True
            stack.monorepo_backend_path = backend_path if backend_path != "." else None
            if "fastapi" in req.lower():
                stack.backend_framework = "fastapi"
                stack.backend_runtime = "python@3.12"
                signals["backend"] = "fastapi"
                if not stack.framework:
                    stack.framework = "fastapi"
                    stack.runtime = "python@3.12"
            stack.language = stack.language or "python"

        if stack.has_frontend and stack.has_backend:
            signals["layout"] = "fullstack"

        combined = " ".join(files.values())
        if re.search(r"redis|valkey|ioredis", combined, re.I):
            stack.cache = "valkey"
            signals["cache"] = "valkey"

        env_from_code = set(
            re.findall(
                r"process\.env\.(\w+)|os\.environ\[['\"](\w+)['\"]\]",
                combined,
            )
        )
        env_from_prisma = set(re.findall(r'env\(["\'](\w+)["\']\)', combined))
        stack.detected_env_vars = sorted(
            {a or b for a, b in env_from_code if a or b} | env_from_prisma
        )
        stack.confidence = 0.9 if stack.framework or stack.has_backend else 0.4
        return stack

    async def enrich_with_llm(self, stack: StackDetection, files: dict[str, str], gemini: GeminiClient) -> StackDetection:
        report = await gemini.analyze_stack(files)
        if not report:
            return stack

        if report.get("framework") and (not stack.framework or stack.confidence < 0.75):
            stack.framework = str(report["framework"])
        if report.get("backend_framework"):
            stack.backend_framework = str(report["backend_framework"])
        if report.get("runtime"):
            stack.runtime = str(report["runtime"])
        if report.get("backend_runtime"):
            stack.backend_runtime = str(report["backend_runtime"])
        if report.get("database"):
            stack.database = str(report["database"])
        if report.get("cache"):
            stack.cache = str(report["cache"])
        if report.get("search"):
            stack.search = str(report["search"])
        if report.get("has_frontend") is not None:
            stack.has_frontend = bool(report["has_frontend"])
        if report.get("has_backend") is not None:
            stack.has_backend = bool(report["has_backend"])

        llm_conf = float(report.get("confidence", 0))
        stack.confidence = max(stack.confidence, llm_conf)
        stack.analysis_summary = report.get("analysis_summary")
        env_vars = report.get("detected_env_vars")
        if isinstance(env_vars, list):
            merged = set(stack.detected_env_vars) | {str(v) for v in env_vars if v}
            stack.detected_env_vars = sorted(merged)
        stack.raw_signals["llm"] = report
        return stack

    def build_architecture(self, stack: StackDetection) -> ArchitectureGraph:
        nodes: list[ArchitectureNode] = []
        edges: list[ArchitectureEdge] = []
        slug = stack.repo_slug or "app"
        hostnames = hostnames_for_slug(slug)

        if stack.has_frontend:
            nodes.append(
                ArchitectureNode(
                    id="frontend",
                    label="Frontend",
                    type="frontend",
                    technology="Next.js" if stack.framework == "nextjs" else stack.framework or "web",
                    hostname=hostnames["frontend"],
                )
            )
        if stack.has_backend or stack.search or stack.cache or stack.database:
            api_tech = stack.backend_framework or stack.framework or "API"
            nodes.append(
                ArchitectureNode(
                    id="api",
                    label="API",
                    type="api",
                    technology=api_tech,
                    hostname=hostnames["api"],
                )
            )
            if stack.has_frontend:
                edges.append(ArchitectureEdge(source="frontend", target="api", label="HTTP"))
        if stack.database:
            nodes.append(
                ArchitectureNode(
                    id="database",
                    label="Database",
                    type="database",
                    technology=stack.database,
                    hostname=hostnames["database"],
                )
            )
            edges.append(ArchitectureEdge(source="api", target="database"))
        if stack.cache:
            nodes.append(
                ArchitectureNode(
                    id="cache",
                    label="Cache",
                    type="cache",
                    technology="Valkey",
                    hostname=hostnames["cache"],
                )
            )
            edges.append(ArchitectureEdge(source="api", target="cache"))
        if stack.search:
            nodes.append(
                ArchitectureNode(
                    id="search",
                    label="Search",
                    type="search",
                    technology=stack.search,
                    hostname=hostnames["search"],
                )
            )
            edges.append(ArchitectureEdge(source="api", target="search", label="index"))

        return ArchitectureGraph(nodes=nodes, edges=edges)


class PlannerService(BaseService):
    name = "planner"

    def __init__(self, project_core: str = "lightweight") -> None:
        self._project_core = project_core

    def build_plan(self, stack: StackDetection, graph: ArchitectureGraph) -> DeploymentPlan:
        from app.services.zerops_pricing import build_deployment_plan

        return build_deployment_plan(graph.nodes, project_core=self._project_core)


class YamlGeneratorService(BaseService):
    name = "yaml_generator"

    def __init__(self, templates_dir: Path, search_heavy: bool = True) -> None:
        self._templates_dir = templates_dir
        self._search_heavy = search_heavy

    def generate(self, stack: StackDetection, repo_url: str | None) -> ZeropsConfig:
        slug = stack.repo_slug or repo_slug_from_url(repo_url)
        stack.repo_slug = slug

        if self._search_heavy:
            import_yaml = self._load_fullstack(stack, repo_url, slug)
            zerops_yaml = f"# Target stack for {slug}\n# See import_yaml for embedded web + api zeropsYaml"
            services = ["frontend", "api", "database", "cache", "search"]
        else:
            template_name = "nextjs" if stack.framework == "nextjs" else "fastapi"
            template_path = self._templates_dir / "zerops" / f"{template_name}.yaml.j2"
            import_path = self._templates_dir / "zerops" / f"import_{template_name}.yaml.j2"
            zerops_yaml = self._load_template(template_path, stack, repo_url, slug)
            import_yaml = self._load_template(import_path, stack, repo_url, slug)
            services = [
                n for n in ["frontend", "api", "database", "cache", "search"] if self._service_needed(n, stack)
            ]

        return ZeropsConfig(
            zerops_yaml=zerops_yaml,
            import_yaml=import_yaml,
            services=services,
        )

    def validate(self, stack: StackDetection, config: ZeropsConfig) -> ValidationReport:
        issues: list[ValidationIssue] = []
        required = {"DATABASE_URL"} if stack.database else set()
        missing = required - set(stack.detected_env_vars)
        for var in missing:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="MISSING_ENV",
                    message=f"Environment variable {var} not detected in source — Zerops import will wire it automatically",
                    field=var,
                )
            )
        for svc in ("postgres", "cache", "search"):
            if self._search_heavy and f"-{svc}" not in config.import_yaml:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="MISSING_SERVICE",
                        message=f"Import YAML missing managed service: {svc}",
                    )
                )
        if "readinessCheck" not in config.import_yaml and "readiness" not in config.zerops_yaml:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="NO_READINESS",
                    message="Verify readiness checks on runtime services",
                )
            )
        errors = [i for i in issues if i.severity == "error"]
        return ValidationReport(passed=len(errors) == 0, issues=issues)

    def _load_fullstack(self, stack: StackDetection, repo_url: str | None, slug: str) -> str:
        path = self._templates_dir / "zerops" / "import_fullstack.yaml.j2"
        fe = stack.monorepo_frontend_path or "."
        be = stack.monorepo_backend_path or "."
        fe_prefix = f"{fe}/" if fe != "." else ""
        be_prefix = f"{be}/" if be != "." else ""

        api_runtime = stack.backend_runtime or "python@3.12"
        web_runtime = stack.runtime or "nodejs@22"

        if stack.backend_framework == "fastapi" or "python" in (api_runtime or ""):
            api_build = f"cd {be_prefix.rstrip('/') or '.'} && pip install . --target dependencies" if be_prefix else "pip install -r requirements.txt"
            api_deploy = f"{be_prefix}~" if be_prefix else "./"
            api_cache = f"{be_prefix}dependencies" if be_prefix else "dependencies"
            api_start = "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
            api_health = "/api/v1/health"
        else:
            api_build = f"cd {be_prefix.rstrip('/') or '.'} && npm ci && npm run build"
            api_deploy = f"{be_prefix}~" if be_prefix else "./"
            api_cache = f"{be_prefix}node_modules" if be_prefix else "node_modules"
            api_start = "npm start"
            api_health = "/api/health"

        web_build = f"cd {fe_prefix.rstrip('/') or '.'} && npm ci && npm run build"
        web_deploy = f"{fe_prefix}~" if fe_prefix else "./"
        web_cache = f"{fe_prefix}node_modules" if fe_prefix else "node_modules"

        if not stack.has_backend:
            stack.has_backend = True
        if not stack.has_frontend:
            stack.has_frontend = True

        content = path.read_text(encoding="utf-8")
        replacements = {
            "{{SLUG}}": slug,
            "{{REPO_URL}}": repo_url or "https://github.com/example/app",
            "{{API_RUNTIME}}": api_runtime,
            "{{WEB_RUNTIME}}": web_runtime,
            "{{API_BUILD_CMD}}": api_build,
            "{{API_DEPLOY_PATH}}": api_deploy,
            "{{API_CACHE_PATH}}": api_cache,
            "{{API_START_CMD}}": api_start,
            "{{API_HEALTH_PATH}}": api_health,
            "{{WEB_BUILD_CMD}}": web_build,
            "{{WEB_DEPLOY_PATH}}": web_deploy,
            "{{WEB_CACHE_PATH}}": web_cache,
        }
        for key, val in replacements.items():
            content = content.replace(key, val)
        return content

    def _load_template(
        self, path: Path, stack: StackDetection, repo_url: str | None, slug: str
    ) -> str:
        if path.exists():
            content = path.read_text(encoding="utf-8")
            return (
                content.replace("{{RUNTIME}}", stack.runtime or "nodejs@22")
                .replace("{{REPO_URL}}", repo_url or "https://github.com/example/app")
                .replace("{{FRAMEWORK}}", stack.framework or "app")
                .replace("{{SLUG}}", slug)
            )
        return f"# Template not found: {path.name}\nzerops: []\n"

    @staticmethod
    def _service_needed(name: str, stack: StackDetection) -> bool:
        mapping = {
            "frontend": stack.has_frontend,
            "api": stack.has_backend,
            "database": bool(stack.database),
            "cache": bool(stack.cache),
            "search": bool(stack.search),
        }
        return mapping.get(name, False)
