"""Gemini client for structured AIOps output."""

from __future__ import annotations

import json
import re

from app.config import Settings


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._enabled = bool(settings.gemini_api_key)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def analyze_logs(
        self,
        *,
        logs: list[str],
        stack_summary: str,
        yaml_excerpt: str,
    ) -> dict | None:
        if not self._enabled:
            return None

        import google.generativeai as genai

        genai.configure(api_key=self._settings.gemini_api_key)
        model = genai.GenerativeModel(self._settings.gemini_model)

        log_text = "\n".join(logs[-80:]) if logs else "No logs available."
        prompt = f"""You are Deplot AIOps Analyst. Analyze deployment failure logs and respond with JSON only.

Stack: {stack_summary}

Config excerpt:
{yaml_excerpt[:2000]}

Logs:
{log_text}

Return JSON with keys:
- root_cause (string)
- reason (string)
- impact (string)
- confidence (float 0-1)
- suggested_fix (string)
- log_summary (string, one line)
- runbook (array of 3-5 strings)
- env_changes (object, key-value env vars to fix)
- yaml_diff (string, optional diff snippet)
"""
        try:
            response = await model.generate_content_async(prompt)
            text = response.text or ""
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                return json.loads(match.group())
        except Exception:
            return None
        return None

    async def enhance_score_recommendations(
        self,
        *,
        security: float,
        performance: float,
        scalability: float,
        reliability: float,
        observability: float,
        gaps: list[str],
        stack_summary: str,
    ) -> list[str] | None:
        if not self._enabled or not gaps:
            return None

        import google.generativeai as genai

        genai.configure(api_key=self._settings.gemini_api_key)
        model = genai.GenerativeModel(self._settings.gemini_model)

        prompt = f"""You are Deplot Optimization Advisor. Given computed readiness scores and gaps, return JSON only.

Stack: {stack_summary}
Scores (0-10): security={security}, performance={performance}, scalability={scalability}, reliability={reliability}, observability={observability}

Known gaps:
{chr(10).join(f"- {g}" for g in gaps[:8])}

Return JSON: {{ "recommendations": ["...", "..."] }} with 2-4 short, actionable Zerops-specific items. Do not repeat gaps verbatim."""

        try:
            response = await model.generate_content_async(prompt)
            text = response.text or ""
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                data = json.loads(match.group())
                recs = data.get("recommendations")
                if isinstance(recs, list):
                    return [str(r) for r in recs if r][:4]
        except Exception:
            return None
        return None

    async def analyze_stack(self, files: dict[str, str]) -> dict | None:
        if not self._enabled or not files:
            return None

        import google.generativeai as genai

        genai.configure(api_key=self._settings.gemini_api_key)
        model = genai.GenerativeModel(self._settings.gemini_model)

        file_list = sorted(files.keys())[:40]
        snippets = [f"--- {path} ---\n{files[path][:800]}" for path in file_list[:12]]

        prompt = f"""You are Deplot Repository Analyzer. Infer stack from file tree and snippets. Return JSON only.

File tree ({len(file_list)} files): {", ".join(file_list)}

Snippets:
{chr(10).join(snippets)}

Return JSON keys:
- framework, backend_framework, runtime, backend_runtime, database, cache, search
- has_frontend, has_backend (boolean)
- confidence (float 0-1)
- analysis_summary (string)
- detected_env_vars (array of strings)
"""

        try:
            response = await model.generate_content_async(prompt)
            text = response.text or ""
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                return json.loads(match.group())
        except Exception:
            return None
        return None
