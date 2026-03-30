"""Tests for persona models and deterministic persona composition."""

import yaml

from bob.personas.models import (
    Persona,
    WritingStyle,
    persona_from_dict,
    persona_to_dict,
)
from bob.personas.generator import (
    _slugify,
    compose_persona,
)
from bob.roster.models import (
    Availability,
    MemberProfile,
    PresentationStyle,
    Skill,
)


# ── WritingStyle tests ───────────────────────────────────────────────


class TestWritingStyle:
    def test_creation(self):
        ws = WritingStyle(
            readme_voice="concise",
            commit_style="conventional",
            communication_tone="direct",
            vocabulary_notes="says 'ship it'",
        )
        assert ws.readme_voice == "concise"
        assert ws.commit_style == "conventional"
        assert ws.communication_tone == "direct"
        assert ws.vocabulary_notes == "says 'ship it'"


# ── Persona tests ────────────────────────────────────────────────────


class TestPersona:
    def test_creation_with_defaults(self):
        ws = WritingStyle("a", "b", "c", "d")
        p = Persona(
            persona_id="alice-eth",
            member_id="alice",
            account_ids=["devpost:alice"],
            writing_style=ws,
            bio_short="Short bio.",
            bio_long="Long bio paragraph.",
        )
        assert p.persona_id == "alice-eth"
        assert p.avatar_url == ""
        assert p.event_context == ""

    def test_creation_with_all_fields(self):
        ws = WritingStyle("a", "b", "c", "d")
        p = Persona(
            persona_id="bob-hack",
            member_id="bob",
            account_ids=["github:bob", "devpost:bob"],
            writing_style=ws,
            bio_short="Short.",
            bio_long="Long.",
            avatar_url="https://example.com/avatar.png",
            event_context="DeFi track, 48h sprint",
        )
        assert p.avatar_url == "https://example.com/avatar.png"
        assert p.event_context == "DeFi track, 48h sprint"
        assert len(p.account_ids) == 2


# ── Slugify tests ────────────────────────────────────────────────────


class TestSlugify:
    def test_basic(self):
        assert _slugify("ETHGlobal 2026") == "ethglobal-2026"

    def test_special_chars(self):
        assert _slugify("Hack the Planet!!!") == "hack-the-planet"

    def test_leading_trailing_whitespace(self):
        assert _slugify("  My Hackathon  ") == "my-hackathon"

    def test_consecutive_special_chars(self):
        assert _slugify("AI & ML -- Workshop") == "ai-ml-workshop"

    def test_already_slugified(self):
        assert _slugify("already-a-slug") == "already-a-slug"

    def test_empty_string_returns_fallback(self):
        assert _slugify("") == "event"

    def test_all_special_chars_returns_fallback(self):
        assert _slugify("---!!!???") == "event"

    def test_unicode_stripped_to_ascii(self):
        result = _slugify("Über Häck")
        assert result == "ber-h-ck"


# ── compose_persona tests ────────────────────────────────────────────


def _make_member(
    style: PresentationStyle = PresentationStyle.TECHNICAL,
    **kwargs,
) -> MemberProfile:
    defaults = dict(
        member_id="alice",
        display_name="Alice Chen",
        skills=[Skill("Solidity", "blockchain", 5), Skill("React", "frontend", 4)],
        interests=["DeFi", "ZK proofs"],
        presentation_style=style,
        availability=Availability(timezone="America/New_York"),
        notes="Won 3 hackathons.",
    )
    defaults.update(kwargs)
    return MemberProfile(**defaults)


class TestComposePersona:
    def test_persona_id_format(self):
        member = _make_member()
        persona = compose_persona(member, ["acc1"], "ETHGlobal 2026")
        assert persona.persona_id == "alice-ethglobal-2026"

    def test_persona_id_special_chars_in_event(self):
        member = _make_member()
        persona = compose_persona(member, [], "Hack & Build!! 2026")
        assert persona.persona_id == "alice-hack-build-2026"

    def test_member_id_propagated(self):
        member = _make_member()
        persona = compose_persona(member, ["a1", "a2"], "Test")
        assert persona.member_id == "alice"
        assert persona.account_ids == ["a1", "a2"]

    def test_event_context_propagated(self):
        member = _make_member()
        persona = compose_persona(member, [], "Test", event_context="DeFi track")
        assert persona.event_context == "DeFi track"

    def test_bio_includes_skills(self):
        member = _make_member()
        persona = compose_persona(member, [], "Test Hack")
        assert "Solidity" in persona.bio_short
        assert "React" in persona.bio_short
        assert "Solidity" in persona.bio_long

    def test_bio_includes_interests(self):
        member = _make_member()
        persona = compose_persona(member, [], "Test")
        assert "DeFi" in persona.bio_short
        assert "ZK proofs" in persona.bio_short

    def test_bio_fallback_no_skills(self):
        member = _make_member(skills=[])
        persona = compose_persona(member, [], "Test")
        assert "various technologies" in persona.bio_short

    def test_bio_fallback_no_interests(self):
        member = _make_member(interests=[])
        persona = compose_persona(member, [], "Test")
        assert "building cool things" in persona.bio_short

    def test_each_style_produces_different_writing(self):
        styles_seen = set()
        for style in PresentationStyle:
            member = _make_member(style=style)
            persona = compose_persona(member, [], "Test")
            styles_seen.add(persona.writing_style.readme_voice)
        # All four styles should produce distinct readme_voice
        assert len(styles_seen) == 4

    def test_energetic_style(self):
        persona = compose_persona(_make_member(style=PresentationStyle.ENERGETIC), [], "Test")
        assert "energy" in persona.writing_style.readme_voice.lower() or \
               "punchy" in persona.writing_style.readme_voice.lower()

    def test_technical_style(self):
        persona = compose_persona(_make_member(style=PresentationStyle.TECHNICAL), [], "Test")
        assert "technical" in persona.writing_style.readme_voice.lower() or \
               "concise" in persona.writing_style.readme_voice.lower()

    def test_methodical_style(self):
        persona = compose_persona(_make_member(style=PresentationStyle.METHODICAL), [], "Test")
        assert "structured" in persona.writing_style.readme_voice.lower()

    def test_narrative_style(self):
        persona = compose_persona(_make_member(style=PresentationStyle.NARRATIVE), [], "Test")
        assert "story" in persona.writing_style.readme_voice.lower()


# ── Serialization round-trip ─────────────────────────────────────────


class TestPersonaSerialization:
    def test_to_dict_from_dict_roundtrip(self):
        member = _make_member()
        original = compose_persona(member, ["devpost:alice"], "ETHGlobal 2026")

        d = persona_to_dict(original)
        raw = yaml.safe_dump(d, sort_keys=False)
        loaded = yaml.safe_load(raw)
        restored = persona_from_dict(loaded)

        assert restored.persona_id == original.persona_id
        assert restored.member_id == original.member_id
        assert restored.account_ids == original.account_ids
        assert restored.writing_style.readme_voice == original.writing_style.readme_voice
        assert restored.writing_style.commit_style == original.writing_style.commit_style
        assert restored.bio_short == original.bio_short
        assert restored.bio_long == original.bio_long
        assert restored.avatar_url == original.avatar_url
        assert restored.event_context == original.event_context

    def test_to_dict_produces_yaml_safe_types(self):
        member = _make_member()
        persona = compose_persona(member, ["a1"], "Test")
        d = persona_to_dict(persona)
        # Should not raise — all types are YAML-safe
        raw = yaml.safe_dump(d)
        assert isinstance(raw, str)
