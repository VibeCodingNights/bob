"""Tests for the validation orchestrator (triage + apply_corrections)."""

from datetime import datetime, timezone
import os
from unittest.mock import AsyncMock, patch

import pytest

from bob.agent import InvestigationResult
from bob.models import Format, Hackathon, RegistrationStatus
from bob.validate import (
    ValidationResult,
    apply_corrections,
    structural_score,
    validate_batch,
)


def _h(**kw) -> Hackathon:
    defaults = {"name": "Test Hackathon", "url": "https://example.com", "source": "eventbrite"}
    defaults.update(kw)
    return Hackathon(**defaults)


# --- Structural Scoring ---


class TestStructuralScore:
    def test_curated_source_bonus(self):
        h = _h(source="devpost")
        assert structural_score(h) >= 3

    def test_curated_plus_keyword(self):
        h = _h(source="mlh", name="Campus Hackathon")
        assert structural_score(h) >= 6

    def test_strong_keyword(self):
        h = _h(name="SF Hackathon 2026")
        assert structural_score(h) >= 3

    def test_anti_keyword_reduces(self):
        h = _h(name="Hackathon Happy Hour")
        score = structural_score(h)
        assert score == 1  # +3 strong, -2 anti

    def test_meetup_anti_keyword(self):
        h = _h(name="Python Meetup", source="meetup", description="Weekly meetup")
        assert structural_score(h) <= 0

    def test_duration_signal(self):
        h = _h(
            name="Tech Event",
            start_date=datetime(2026, 3, 21, 9, 0, tzinfo=timezone.utc),
            end_date=datetime(2026, 3, 22, 18, 0, tzinfo=timezone.utc),  # 33h
        )
        score = structural_score(h)
        assert score >= 3  # +2 (>6h) +1 (>12h) +1 (Saturday)

    def test_weekend_bonus(self):
        h = _h(
            name="Code Event",
            start_date=datetime(2026, 3, 21, 9, 0, tzinfo=timezone.utc),  # Saturday
        )
        score_weekend = structural_score(h)
        h2 = _h(
            name="Code Event",
            start_date=datetime(2026, 3, 18, 9, 0, tzinfo=timezone.utc),  # Wednesday
        )
        score_weekday = structural_score(h2)
        assert score_weekend > score_weekday

    def test_no_signals(self):
        h = _h(name="AI Discussion", description="A casual chat")
        assert structural_score(h) == 0

    def test_luma_soft_keyword_with_duration(self):
        h = _h(
            name="Build Sprint",
            source="luma",
            start_date=datetime(2026, 3, 21, 9, 0, tzinfo=timezone.utc),
            end_date=datetime(2026, 3, 21, 20, 0, tzinfo=timezone.utc),
        )
        assert structural_score(h) >= 4  # +1 soft +2 duration +1 weekend


# --- Validate Batch (triage only, no network) ---


@pytest.mark.asyncio
async def test_curated_sources_auto_pass():
    hackathons = [
        _h(source="devpost", name="DevHack"),
        _h(source="mlh", name="MLH Event"),
        _h(source="devfolio", name="Devfolio Hack"),
    ]
    results = await validate_batch(hackathons, use_llm=False)
    assert all(r.valid for r in results)
    assert all(r.tier == "source" for r in results)


@pytest.mark.asyncio
async def test_structural_rejection():
    hackathons = [
        _h(name="Happy Hour Mixer", source="meetup", description="Networking party"),
    ]
    results = await validate_batch(hackathons, use_llm=False)
    assert not results[0].valid
    assert results[0].tier == "structural"


@pytest.mark.asyncio
async def test_ambiguous_without_llm_is_unverified():
    """Events that aren't curated or rejected become 'unverified' when LLM is off."""
    hackathons = [
        _h(name="Weekend Hackathon", source="eventbrite"),
    ]
    results = await validate_batch(hackathons, use_llm=False)
    assert results[0].valid
    assert results[0].tier == "unverified"


_MOCK_ENV = {"ANTHROPIC_API_KEY": "sk-test-fake-key"}


@pytest.mark.asyncio
async def test_validate_batch_with_mock_agent():
    """Full pipeline: triage + mock agent investigation."""
    hackathons = [
        _h(name="Ambiguous Event", source="luma"),
    ]
    mock_result = InvestigationResult(
        valid=True,
        confidence=0.9,
        reasoning="Event page confirms hackathon with prizes",
        corrections=[],
        input_tokens=500,
        output_tokens=200,
        tool_rounds=1,
    )

    with (
        patch.dict(os.environ, _MOCK_ENV),
        patch("bob.validate.investigate", new_callable=AsyncMock) as mock_inv,
    ):
        mock_inv.return_value = mock_result
        results = await validate_batch(hackathons, use_llm=True)

    assert results[0].tier == "investigated"
    assert results[0].valid is True
    assert results[0].confidence == 0.9
    assert results[0].reasoning == "Event page confirms hackathon with prizes"
    mock_inv.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_batch_agent_error_fallback():
    """Agent exception should not crash the pipeline."""
    hackathons = [
        _h(name="Error Event", source="luma"),
    ]

    with (
        patch.dict(os.environ, _MOCK_ENV),
        patch("bob.validate.investigate", new_callable=AsyncMock) as mock_inv,
    ):
        mock_inv.side_effect = RuntimeError("API key missing")
        results = await validate_batch(hackathons, use_llm=True)

    assert results[0].tier == "error"
    assert results[0].valid is True
    assert results[0].confidence == 0.3


@pytest.mark.asyncio
async def test_validate_batch_corrections_mapped():
    """Agent corrections should populate both corrections dict and evidence_chain."""
    hackathons = [
        _h(name="Mislocated Hack", source="eventbrite", location="Wrong City"),
    ]
    mock_result = InvestigationResult(
        valid=True,
        confidence=0.85,
        reasoning="Location corrected per event page",
        corrections=[{
            "field": "location",
            "value": "San Francisco, CA",
            "source_url": "https://example.com",
            "extracted_text": "Venue: San Francisco Convention Center",
        }],
        input_tokens=600,
        output_tokens=250,
        tool_rounds=1,
    )

    with (
        patch.dict(os.environ, _MOCK_ENV),
        patch("bob.validate.investigate", new_callable=AsyncMock) as mock_inv,
    ):
        mock_inv.return_value = mock_result
        results = await validate_batch(hackathons, use_llm=True)

    assert results[0].corrections == {"location": "San Francisco, CA"}
    assert len(results[0].evidence_chain) == 1
    assert results[0].evidence_chain[0].source_url == "https://example.com"
    assert results[0].evidence_chain[0].extracted_text == "Venue: San Francisco Convention Center"


# --- Apply Corrections ---


def test_apply_corrections():
    h = _h(location="Wrong City")
    results = [ValidationResult(hackathon=h, valid=True, corrections={"location": "Right City"})]
    validated = apply_corrections([h], results)
    assert len(validated) == 1
    assert validated[0].location == "Right City"


def test_apply_corrections_filters_invalid():
    h1 = _h(name="Valid")
    h2 = _h(name="Invalid")
    results = [
        ValidationResult(hackathon=h1, valid=True),
        ValidationResult(hackathon=h2, valid=False),
    ]
    validated = apply_corrections([h1, h2], results)
    assert len(validated) == 1
    assert validated[0].name == "Valid"


def test_apply_corrections_format():
    h = _h(format=Format.VIRTUAL)
    results = [ValidationResult(hackathon=h, valid=True, corrections={"format": "in-person"})]
    validated = apply_corrections([h], results)
    assert validated[0].format == Format.IN_PERSON


def test_apply_corrections_registration_status():
    h = _h(registration_status=RegistrationStatus.UNKNOWN)
    results = [
        ValidationResult(hackathon=h, valid=True, corrections={"registration_status": "open"})
    ]
    validated = apply_corrections([h], results)
    assert validated[0].registration_status == RegistrationStatus.OPEN
