"""Repo slug + hostname helpers."""

from __future__ import annotations

import re
from pathlib import Path


def repo_slug_from_url(repo_url: str | None) -> str:
    if not repo_url:
        return "app"
    path = repo_url.rstrip("/").replace(".git", "")
    name = Path(path).name.lower()
    slug = re.sub(r"[^a-z0-9-]", "", name.replace("_", "-"))
    return (slug[:20] if slug else "app")


def hostnames_for_slug(slug: str) -> dict[str, str]:
    return {
        "database": f"{slug}-postgres",
        "cache": f"{slug}-cache",
        "search": f"{slug}-search",
        "api": f"{slug}-api",
        "frontend": f"{slug}-web",
    }
