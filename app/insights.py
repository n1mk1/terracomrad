"""Optional AI Insights layer — one multimodal Gemini call per report.

Packages the analysis screen's compact AOI profile (built client-side) together
with the flattened scan + overlay PNG into a single Google Gemini Flash request,
and returns a fixed-schema narrative report. This is the only place in TerraComrad
that makes an external network call, and it is inert unless a provider key is
configured (see ``app/config.py``). Every report is framed as educational
decision-support over a rule-based demo classifier — never a diagnosis.
"""

from __future__ import annotations

import asyncio
import json
import random
import re

from pydantic import BaseModel

from app.config import settings


class InsightsUnavailable(RuntimeError):
    """Feature is disabled or no API key is configured (maps to HTTP 503)."""


class InsightsError(RuntimeError):
    """The provider call failed or returned something unusable (maps to HTTP 502)."""


class InsightReport(BaseModel):
    """Fixed output schema, so the frontend can render clean, predictable sections."""

    headline: str
    detection_summary: str
    shape_assessment: str
    margin_assessment: str
    risk_discussion: str
    birads_suggestion: str
    recommended_followup: str
    limitations: str
    disclaimer: str


SYSTEM_INSTRUCTION = (
    "You are a radiology decision-support assistant helping a patient read a single "
    "mammographic Area-of-Interest (AOI). You receive (1) a rendered image crop showing the "
    "system's generated mass mask, outline/bounding-box overlays, and any doctor-drawn ROIs, "
    "and (2) a compact JSON profile of rule-based measurements. All inputs come from an "
    "explainable RULE-BASED DEMO, not a trained model. Interpret and synthesize the evidence, "
    "tying your reasoning to the provided shape, margin, geometry, and Crown Shyness boundary "
    "metrics. Never assert a definitive diagnosis; this is educational decision-support only. "
    "Return ONLY valid JSON matching the requested schema."
)


def build_prompt(profile: dict) -> str:
    """Build the text part of the request: the compact AOI package + output framing."""
    package = json.dumps(profile, ensure_ascii=False, separators=(",", ":"))
    return (
        "AOI profile (rule-based demo measurements):\n"
        f"{package}\n\n"
        "Using the attached rendered image together with this profile, write a concise report. "
        "Keep each field to 1-3 sentences. You may use light Markdown inside the text fields "
        "(short **bold** emphasis or '-' bullet lists) for readability. For birads_suggestion, "
        "give a BI-RADS category with a one-line rationale, or 'N/A' when there is no AOI. "
        "Always include a non-diagnostic disclaimer. Return only JSON for the schema."
    )


# Matches a complete "key": "value" pair in (possibly truncated) JSON. The string
# body is captured with its escapes intact so json.loads can unescape it cleanly.
_FIELD_RE = re.compile(r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _strip_fences(text: str) -> str:
    """Drop a ```json … ``` code fence if the model wrapped its JSON in one."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _salvage_fields(text: str) -> dict:
    """Recover whatever schema fields completed from a partial/truncated JSON object."""
    report: dict = {}
    for key, raw in _FIELD_RE.findall(text):
        if key in InsightReport.model_fields and key not in report:
            try:
                report[key] = json.loads(f'"{raw}"')   # unescape \n, \" etc.
            except json.JSONDecodeError:
                report[key] = raw
    return report


def _extract_report(response) -> dict:
    """Parse the model response into a plain dict, tolerating non-strict/partial JSON."""
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, InsightReport):
        return parsed.model_dump()
    text = _strip_fences((getattr(response, "text", None) or "").strip())
    if not text:
        raise InsightsError("Empty response from model.")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # Truncated or lightly malformed JSON: recover the fields that did complete
    # instead of dumping a raw JSON blob into the report panel.
    salvaged = _salvage_fields(text)
    if salvaged:
        return salvaged
    raise InsightsError("Model returned an unreadable response; try regenerating.")


def _usage(response) -> dict:
    """Surface provider token usage for the UI (best-effort)."""
    meta = getattr(response, "usage_metadata", None)
    if not meta:
        return {}
    return {
        "prompt_token_count": getattr(meta, "prompt_token_count", None),
        "candidates_token_count": getattr(meta, "candidates_token_count", None),
        "total_token_count": getattr(meta, "total_token_count", None),
    }


# Provider HTTP status codes worth retrying: the model is momentarily overloaded
# (503), rate-limited (429), or hit a transient server fault (500/504). Google's
# own guidance for these is "try again later", so we back off and do exactly that.
_RETRYABLE_CODES = frozenset({429, 500, 503, 504})
_MAX_ATTEMPTS = 4           # one initial call + up to three retries
_BACKOFF_BASE = 1.0         # seconds; doubles each retry (1s, 2s, 4s) plus jitter


def _retryable_code(exc: Exception) -> int | None:
    """The HTTP status of a google-genai error if it's transient, else None."""
    code = getattr(exc, "code", None)
    return code if isinstance(code, int) and code in _RETRYABLE_CODES else None


def _generate_sync(image_bytes: bytes, prompt: str):
    """One blocking Gemini call; run in a worker thread by ``generate_insights``.

    Raises the raw SDK exception so the caller can read its status code and decide
    whether to retry; ``generate_insights`` wraps the final failure for the UI.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.api_key)
    return client.models.generate_content(
        model=settings.model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            prompt,
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=InsightReport,
            # gemini-2.5-* spend output tokens on internal "thinking"; with a low
            # cap that left the JSON truncated (→ unparseable → raw dump in the UI).
            # Disable thinking and give the answer room so the schema always closes.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=2048,
            temperature=0.4,
        ),
    )


async def generate_insights(image_bytes: bytes, profile: dict) -> dict:
    """Run one multimodal request and return ``{report, model, provider, usage}``.

    Transient provider errors (overload/rate-limit/5xx) are retried with
    exponential backoff so a momentary Gemini spike doesn't fail the report; if
    every attempt still fails we surface a plain "try again" message for the UI.
    """
    if not settings.configured:
        raise InsightsUnavailable(
            "AI insights are not configured. Set INSIGHTS_API_KEY (or GEMINI_API_KEY)."
        )
    prompt = build_prompt(profile)

    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = await asyncio.to_thread(_generate_sync, image_bytes, prompt)
            return {
                "report": _extract_report(response),
                "model": settings.model,
                "provider": settings.provider,
                "usage": _usage(response),
            }
        except Exception as exc:  # SDK / network / provider-side failure
            if _retryable_code(exc) is None:
                raise InsightsError(f"{settings.provider} request failed: {exc}") from exc
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(_BACKOFF_BASE * 2 ** attempt + random.uniform(0, 0.4))

    # Every attempt hit a transient error — tell the doctor to simply retry.
    raise InsightsError(
        f"{settings.provider.capitalize()} is busy right now. Please click "
        "“Try again” to regenerate the insights in a moment."
    ) from last_exc
