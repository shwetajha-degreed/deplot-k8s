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
from app.models.deployment import DeploymentPlan, DeploymentPlanService, K8sConfig
from app.services.base import BaseService
from app.services.gemini import GeminiClient
from app.services.k8s import hostnames_for_slug, repo_slug_from_url


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

        # Python DB drivers imply a database — without this
        # dev-velocity's backend/requirements.txt (sqlalchemy + asyncpg)
        # sat unread and Deplot skipped provisioning; the app fell back
        # to localhost:5433 and got connection-refused.
        #
        # Priority matters: aiosqlite is a strong SQLite signal that
        # trumps SQLAlchemy (which is generic and often shipped alongside
        # aiosqlite for embedded/dev DBs). asyncpg/psycopg are
        # Postgres-specific and win when present.
        if not stack.database:
            if re.search(
                r"\b(asyncpg|psycopg2?(?:-binary)?|pg8000)\b", combined, re.I
            ):
                stack.database = "postgresql"
                signals["database"] = "python-driver"
            elif re.search(r"\b(aiosqlite)\b", combined, re.I):
                stack.database = "sqlite"
                signals["database"] = "sqlite"
            elif re.search(r"\b(sqlalchemy)\b", combined, re.I):
                # SQLAlchemy without an explicit driver signal — default
                # to Postgres. Cheaper to over-provision than to leave
                # the app connection-refused.
                stack.database = "postgresql"
                signals["database"] = "sqlalchemy-default"
            elif re.search(r"\b(pymongo|motor)\b", combined, re.I):
                stack.database = "mongodb"
                signals["database"] = "python-driver"

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

    def __init__(self) -> None:
        pass

    def build_plan(self, stack: StackDetection, graph: ArchitectureGraph) -> DeploymentPlan:
        # TODO(k8s-port): replace with real AKS pricing tier logic.
        services = [
            DeploymentPlanService(name=n.id, type=n.type) for n in graph.nodes
        ]
        return DeploymentPlan(services=services, estimated_build_minutes=5)


class YamlGeneratorService(BaseService):
    name = "yaml_generator"

    def __init__(
        self,
        prompts_dir: Path,
        gemini: GeminiClient | None = None,
        registry_prefix: str = "dgscucorecr01.azurecr.io",
        gateway_ns: str = "internal-gateway",
        gateway_name: str = "internal-gateway",
        base_domain: str = "internal.sbx.degreed.com",
    ) -> None:
        self._prompts_dir = prompts_dir
        self._gemini = gemini
        self._registry = registry_prefix
        self._gateway_ns = gateway_ns
        self._gateway_name = gateway_name
        self._base_domain = base_domain

    async def generate(self, stack: StackDetection, repo_url: str | None) -> K8sConfig:
        slug = stack.repo_slug or repo_slug_from_url(repo_url)
        stack.repo_slug = slug
        services = [
            n for n in ["frontend", "api", "database", "cache", "search"]
            if self._service_needed(n, stack)
        ]
        namespace = f"deploy-{slug}"

        manifests: list[dict] = []
        if self._gemini and self._gemini.enabled:
            prompt = self._load_prompt("yaml_generator.md")
            data = await self._gemini.generate_manifests(
                slug=slug,
                stack_summary=self._stack_summary(stack),
                graph_summary=", ".join(services),
                prompt_template=prompt,
            )
            if data and isinstance(data.get("manifests"), list):
                manifests = data["manifests"]

        if not manifests:
            manifests = self._fallback_manifests(stack, slug, namespace, services)

        return K8sConfig(manifests=manifests, namespace=namespace, services=services)

    def _load_prompt(self, name: str) -> str:
        path = self._prompts_dir / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _stack_summary(self, stack: StackDetection) -> str:
        parts = [
            f"framework={stack.framework}",
            f"runtime={stack.runtime}",
            f"has_backend={stack.has_backend}",
            f"has_frontend={stack.has_frontend}",
            f"database={stack.database}",
            f"cache={stack.cache}",
        ]
        return ", ".join(p for p in parts if p.split("=")[1] not in ("None", "False", ""))

    def _fallback_manifests(
        self,
        stack: StackDetection,
        slug: str,
        namespace: str,
        services: list[str],
    ) -> list[dict]:
        deployable = [s for s in services if s in ("api", "frontend")]
        if not deployable and stack.has_backend:
            deployable = ["api"]
        if not deployable:
            deployable = ["web"]

        manifests: list[dict] = []
        for svc in deployable:
            port = 8000 if svc == "api" else 3000
            image = f"{self._registry}/{slug}-{svc}:latest"
            # api and frontend both get HTTPRoutes: frontend so browsers can
            # reach the UI, api so the frontend's baked-in NEXT_PUBLIC_API_URL
            # resolves from the client's browser (not just cluster-internal).
            external = svc in ("frontend", "web", "api")

            manifests.append(_deployment(namespace, svc, slug, image, port))
            manifests.append(_service(namespace, svc, port))
            if external:
                manifests.append(
                    _http_route(
                        namespace,
                        svc,
                        slug,
                        port,
                        self._gateway_ns,
                        self._gateway_name,
                        self._base_domain,
                    )
                )
        return manifests

    def validate(self, stack: StackDetection, config: K8sConfig) -> ValidationReport:
        # Deplot injects DATABASE_URL, REDIS_URL, TYPESENSE_* etc. into the
        # app container's env when the corresponding dep is detected — so
        # they're never "missing" from the runtime standpoint even if a
        # regex over source didn't find them. The old warning fired on
        # every deploy of a repo whose DATABASE_URL usage lives in a file
        # we didn't scan, which was noise.
        issues: list[ValidationIssue] = []
        if not config.manifests:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="NO_MANIFESTS",
                    message="No K8s manifests generated yet — port yaml_generator to K8s",
                )
            )
        errors = [i for i in issues if i.severity == "error"]
        return ValidationReport(passed=len(errors) == 0, issues=issues)

    def _load_fullstack(self, stack: StackDetection, repo_url: str | None, slug: str) -> str:
        path = self._templates_dir / "k8s" / "import_fullstack.yaml.j2"
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
        return f"# Template not found: {path.name}\nmanifests: []\n"

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


def _deployment(namespace: str, name: str, slug: str, image: str, port: int) -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/name": name,
                "app.kubernetes.io/part-of": slug,
            },
        },
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app.kubernetes.io/name": name}},
            "template": {
                "metadata": {"labels": {"app.kubernetes.io/name": name}},
                "spec": {
                    "containers": [
                        {
                            "name": name,
                            "image": image,
                            "ports": [{"containerPort": port}],
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "500m", "memory": "512Mi"},
                            },
                            "readinessProbe": {
                                # TCP probe works for any app that opens the
                                # port; HTTP GET /health assumes the app
                                # implements it and 404s on frameworks like
                                # Next.js by default.
                                "tcpSocket": {"port": port},
                                "initialDelaySeconds": 5,
                                "periodSeconds": 10,
                            },
                            "env": [{"name": "PORT", "value": str(port)}],
                        }
                    ]
                },
            },
        },
    }


def _service(namespace: str, name: str, port: int) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "type": "ClusterIP",
            "selector": {"app.kubernetes.io/name": name},
            "ports": [{"port": port, "targetPort": port, "protocol": "TCP"}],
        },
    }


def _http_route(
    namespace: str,
    name: str,
    slug: str,
    port: int,
    gateway_ns: str,
    gateway_name: str,
    base_domain: str,
) -> dict:
    return {
        "apiVersion": "gateway.networking.k8s.io/v1",
        "kind": "HTTPRoute",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "parentRefs": [
                {"name": gateway_name, "namespace": gateway_ns, "sectionName": "https-degreed-com"}
            ],
            "hostnames": [f"{slug}-{name}.{base_domain}"],
            "rules": [
                {
                    "matches": [{"path": {"type": "PathPrefix", "value": "/"}}],
                    "backendRefs": [{"name": name, "port": port}],
                }
            ],
        },
    }
