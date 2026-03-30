"""Deterministic persona composition from member profiles."""

from __future__ import annotations

import re

from ..roster.models import MemberProfile, PresentationStyle
from .models import Persona, WritingStyle


# ── style templates keyed by PresentationStyle ───────────────────────

_STYLE_MAP: dict[PresentationStyle, WritingStyle] = {
    PresentationStyle.ENERGETIC: WritingStyle(
        readme_voice="punchy, high-energy, emoji-friendly, short paragraphs",
        commit_style="conventional-commits, action verbs, exclamation marks",
        communication_tone="enthusiastic, encouraging, uses exclamation marks",
        vocabulary_notes="says 'ship it!' not 'deploy', 'let's go!' not 'proceed'",
    ),
    PresentationStyle.METHODICAL: WritingStyle(
        readme_voice="structured, numbered steps, thorough, covers edge cases",
        commit_style="conventional-commits, precise scope, references issue IDs",
        communication_tone="calm, organized, bullet-point heavy",
        vocabulary_notes="says 'verified' not 'looks good', 'documented' not 'noted'",
    ),
    PresentationStyle.NARRATIVE: WritingStyle(
        readme_voice="storytelling, problem-solution arcs, relatable examples",
        commit_style="descriptive subjects, explains the why in body",
        communication_tone="warm, conversational, uses analogies",
        vocabulary_notes="says 'here's the story' not 'summary', 'journey' not 'process'",
    ),
    PresentationStyle.TECHNICAL: WritingStyle(
        readme_voice="concise, technical, lots of code blocks, spec-like",
        commit_style="conventional-commits, short subjects, references modules",
        communication_tone="precise, direct, minimal filler",
        vocabulary_notes="says 'implements' not 'adds', 'refactors' not 'cleans up'",
    ),
}


def _slugify(text: str) -> str:
    """Convert arbitrary text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "event"


def compose_persona(
    member: MemberProfile,
    account_ids: list[str],
    event_name: str,
    event_context: str = "",
) -> Persona:
    """Build an event-scoped Persona from a MemberProfile.

    Writing style is derived deterministically from the member's
    presentation_style enum. Bios are templated from the member's
    skills and interests.
    """
    slug = _slugify(event_name)
    persona_id = f"{member.member_id}-{slug}"

    style = _STYLE_MAP[member.presentation_style]

    top_skills = ", ".join(s.name for s in member.skills[:3]) or "various technologies"
    interests_str = ", ".join(member.interests[:3]) or "building cool things"

    bio_short = (
        f"{member.display_name} — skilled in {top_skills}, "
        f"passionate about {interests_str}."
    )
    bio_long = (
        f"{member.display_name} brings expertise in {top_skills} to {event_name}. "
        f"With a focus on {interests_str}, they're ready to build something impactful. "
        f"{member.notes}".rstrip()
    )

    return Persona(
        persona_id=persona_id,
        member_id=member.member_id,
        account_ids=account_ids,
        writing_style=style,
        bio_short=bio_short,
        bio_long=bio_long,
        event_context=event_context,
    )
