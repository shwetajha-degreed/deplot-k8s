"""Repo slug + hostname helpers."""

from __future__ import annotations

import re
from pathlib import Path


def repo_slug_from_url(repo_url: str | None) -> str:
    """Derive a K8s-safe slug from a repo URL, scoped by owner.

    Previously just the repo name — meant two deploys of different
    owners' repos with the same name (dfranklin07/showcase vs
    somebody/showcase) collided on namespace + hostname. Now the slug
    is `<owner>-<repo>` so redeploys of the *same* owner/repo update
    in place (desired) but different owners get isolated namespaces.

    Max 50 chars: DNS labels cap at 63, and hostnames_for_slug()
    appends `-postgres` / `-api` / `-web` (up to 9 chars) so 50 leaves
    headroom without truncating the service suffix.
    """
    if not repo_url:
        return "app"
    trimmed = repo_url.rstrip("/").replace(".git", "")
    # Drop scheme (https://) and any user@host prefix, then split.
    # Both https://github.com/owner/repo and git@github.com:owner/repo yield
    # the same [owner, repo] tail.
    trimmed = re.sub(r"^[a-z]+://", "", trimmed, flags=re.IGNORECASE)
    trimmed = re.sub(r"^[^/]*@", "", trimmed)  # strip git@github.com or user@
    segments = [s for s in re.split(r"[/:]", trimmed) if s and "." not in s]
    if len(segments) >= 2:
        raw = f"{segments[-2]}-{segments[-1]}"
    elif segments:
        raw = segments[-1]
    else:
        return "app"
    normalized = raw.lower().replace("_", "-")
    normalized = re.sub(r"[^a-z0-9-]", "", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return (normalized[:50] if normalized else "app")


def hostnames_for_slug(slug: str) -> dict[str, str]:
    return {
        "database": f"{slug}-postgres",
        "cache": f"{slug}-cache",
        "search": f"{slug}-search",
        "api": f"{slug}-api",
        "frontend": f"{slug}-web",
    }
