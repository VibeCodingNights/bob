"""Agentic validation layer — triage → investigate → apply.

Triage: Source confidence (curated platforms auto-pass) + structural scoring (auto-reject)
Investigate: Per-event agent with tools to fetch pages, check links, submit grounded verdicts
Apply: Provenance-checked corrections from agent investigations
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import httpx

from bob.agent import InvestigationResult, TokenUsage, investigate
from bob.models import Hackathon

logger = logging.getLogger(__name__)

# Sources that are hackathon-curated (high base confidence)
_CURATED_SOURCES = frozenset({"devpost", "mlh", "devfolio"})

# --- Structural Scoring ---

_STRONG_KEYWORDS = (
    "hackathon", "hack night", "hack day", "hack week", "hackfest",
    "buildathon", "codeathon", "code jam", "devjam",
)
_SOFT_KEYWORDS = (
    "build weekend", "build day", "build night", "code fest",
    "sprint", "ship day", "hacking", "hackers",
    "challenge", "jam session",
)
_ANTI_KEYWORDS = (
    "happy hour", "after hours", "afterparty", "party", "social",
    "meetup", "talk", "lecture", "conference", "summit", "showcase",
    "exhibit", "comedy", "lounge", "pre-pour", "pitch", "demo day",
    "networking", "mixer", "brunch", "dinner", "lunch",
)


def structural_score(h: Hackathon) -> int:
    """Generalized hackathon scoring across all sources."""
    text = f"{h.name} {h.description}".lower()
    score = 0

    if h.source in _CURATED_SOURCES:
        score += 3

    if any(kw in text for kw in _STRONG_KEYWORDS):
        score += 3
    if any(kw in text for kw in _SOFT_KEYWORDS):
        score += 1
    if any(kw in text for kw in _ANTI_KEYWORDS):
        score -= 2

    if h.start_date and h.end_date:
        hours = (h.end_date - h.start_date).total_seconds() / 3600
        if hours > 6:
            score += 2
        if hours > 12:
            score += 1

    if h.start_date and h.start_date.weekday() >= 4:
        score += 1

    return score


# --- Orchestrator ---

ProgressCallback = Callable[[str, str], None]


@dataclass
class EvidenceItem:
    """A single piece of evidence backing a correction."""
    field: str
    value: str
    source_url: str
    extracted_text: str


@dataclass
class ValidationResult:
    """Full validation result for a hackathon."""
    hackathon: Hackathon
    valid: bool = True
    confidence: float = 1.0
    tier: str = "source"  # source, structural, investigated, unverified, error
    corrections: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    evidence_chain: list[EvidenceItem] = field(default_factory=list)
    reasoning: str = ""


def _investigation_to_result(
    hackathon: Hackathon,
    inv: InvestigationResult,
) -> ValidationResult:
    """Map an InvestigationResult to a ValidationResult."""
    corrections = {}
    evidence_chain = []
    for c in inv.corrections:
        corrections[c["field"]] = c["value"]
        evidence_chain.append(EvidenceItem(
            field=c["field"],
            value=c["value"],
            source_url=c.get("source_url", ""),
            extracted_text=c.get("extracted_text", ""),
        ))

    return ValidationResult(
        hackathon=hackathon,
        valid=inv.valid,
        confidence=inv.confidence,
        tier="investigated",
        corrections=corrections,
        flags=[inv.reasoning] if inv.reasoning else [],
        evidence_chain=evidence_chain,
        reasoning=inv.reasoning,
    )


async def validate_batch(
    hackathons: list[Hackathon],
    *,
    skip_curated: bool = True,
    use_llm: bool = True,
    model: str = "claude-haiku-4-5-20251001",
    concurrency: int = 5,
    on_progress: ProgressCallback | None = None,
) -> list[ValidationResult]:
    """Triage → investigate → return results."""
    results = [ValidationResult(hackathon=h) for h in hackathons]
    needs_investigation: list[int] = []
    _emit = on_progress or (lambda tier, msg: None)

    # --- Triage: curated auto-pass, structural auto-reject ---
    passed_source = 0
    rejected = 0

    for i, h in enumerate(hackathons):
        score = structural_score(h)

        if skip_curated and h.source in _CURATED_SOURCES:
            results[i].tier = "source"
            results[i].confidence = 0.95
            passed_source += 1
            continue

        if score <= -1:
            results[i].valid = False
            results[i].tier = "structural"
            results[i].confidence = 0.85
            results[i].flags.append(f"low_score={score}")
            rejected += 1
            continue

        needs_investigation.append(i)

    _emit("triage", (
        f"{passed_source} curated pass, {rejected} rejected, "
        f"{len(needs_investigation)} need investigation"
    ))

    if not needs_investigation:
        return results

    if not use_llm:
        # Mark ambiguous events as unverified (no agent call)
        for i in needs_investigation:
            results[i].tier = "unverified"
            results[i].confidence = 0.5
        return results

    # --- Investigate: concurrent per-event agents ---
    _emit("investigation", f"Investigating {len(needs_investigation)} events...")
    sem = asyncio.Semaphore(concurrency)
    token_usage = TokenUsage()

    http = httpx.AsyncClient(
        timeout=10.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; hackathon-finder/0.1)"},
    )

    async def _investigate_one(idx: int) -> tuple[int, InvestigationResult | Exception]:
        async with sem:
            try:
                _emit("investigation", f"  → {hackathons[idx].name}")
                inv = await investigate(
                    hackathon=hackathons[idx], model=model, http_client=http,
                )
                return idx, inv
            except Exception as e:
                logger.warning("Investigation failed for %s: %s", hackathons[idx].name, e)
                return idx, e

    try:
        tasks = [_investigate_one(i) for i in needs_investigation]
        inv_results = await asyncio.gather(*tasks)
    finally:
        await http.aclose()

    investigated = 0
    inv_rejected = 0
    corrected = 0
    errors = 0

    for idx, result in inv_results:
        if isinstance(result, Exception):
            results[idx].tier = "error"
            results[idx].valid = True
            results[idx].confidence = 0.3
            results[idx].flags.append(f"investigation_error: {result}")
            errors += 1
            continue

        token_usage.add(result)
        results[idx] = _investigation_to_result(hackathons[idx], result)

        if result.valid:
            investigated += 1
        else:
            inv_rejected += 1
        if result.corrections:
            corrected += 1

    parts = [f"{investigated} verified", f"{inv_rejected} rejected"]
    if corrected:
        parts.append(f"{corrected} corrected")
    if errors:
        parts.append(f"{errors} errors")
    _emit("investigation", ", ".join(parts))
    _emit("tokens", token_usage.summary())

    return results


def apply_corrections(
    hackathons: list[Hackathon],
    results: list[ValidationResult],
) -> list[Hackathon]:
    """Apply validated corrections and filter invalid events."""
    validated = []
    for h, r in zip(hackathons, results):
        if not r.valid:
            continue
        if "location" in r.corrections:
            h.location = r.corrections["location"]
        if "start_date" in r.corrections:
            try:
                h.start_date = datetime.fromisoformat(
                    r.corrections["start_date"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass
        if "end_date" in r.corrections:
            try:
                h.end_date = datetime.fromisoformat(
                    r.corrections["end_date"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass
        if "format" in r.corrections:
            from bob.models import Format
            try:
                h.format = Format(r.corrections["format"])
            except ValueError:
                pass
        if "registration_status" in r.corrections:
            from bob.models import RegistrationStatus
            try:
                h.registration_status = RegistrationStatus(r.corrections["registration_status"])
            except ValueError:
                pass
        validated.append(h)
    return validated
