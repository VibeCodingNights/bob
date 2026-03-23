"""Tests for the CLI module — pure functions and argument parsing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta

import pytest

from hackathon_finder.cli import (
    _filter_by_date,
    _format_date,
    _normalize_utc,
    _to_json_obj,
    _add_discover_args,
)
from hackathon_finder.models import Format, Hackathon, RegistrationStatus


def _make(name="Test", **kwargs):
    """Create a minimal Hackathon for testing."""
    return Hackathon(name=name, url="https://example.com", source="test", **kwargs)


# ---------------------------------------------------------------------------
# _normalize_utc
# ---------------------------------------------------------------------------

class TestNormalizeUtc:
    def test_naive_gets_utc(self):
        dt = datetime(2026, 6, 1, 12, 0)
        result = _normalize_utc(dt)
        assert result.tzinfo == timezone.utc
        assert result == datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    def test_utc_passes_through(self):
        dt = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        result = _normalize_utc(dt)
        assert result is not dt or result == dt  # value equality
        assert result.tzinfo == timezone.utc
        assert result == dt

    def test_non_utc_converted(self):
        eastern = timezone(timedelta(hours=-5))
        dt = datetime(2026, 6, 1, 12, 0, tzinfo=eastern)
        result = _normalize_utc(dt)
        assert result.tzinfo == timezone.utc
        assert result == datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# _filter_by_date
# ---------------------------------------------------------------------------

class TestFilterByDate:
    def test_no_start_date_always_kept(self):
        h = _make(start_date=None)
        after = datetime(2026, 1, 1, tzinfo=timezone.utc)
        before = datetime(2026, 12, 31, tzinfo=timezone.utc)
        assert _filter_by_date([h], after, before) == [h]

    def test_before_after_excluded(self):
        h = _make(start_date=datetime(2026, 1, 15, tzinfo=timezone.utc))
        after = datetime(2026, 3, 1, tzinfo=timezone.utc)
        assert _filter_by_date([h], after, None) == []

    def test_after_before_excluded(self):
        h = _make(start_date=datetime(2026, 9, 1, tzinfo=timezone.utc))
        before = datetime(2026, 6, 1, tzinfo=timezone.utc)
        assert _filter_by_date([h], None, before) == []

    def test_within_range_kept(self):
        h = _make(start_date=datetime(2026, 6, 15, tzinfo=timezone.utc))
        after = datetime(2026, 6, 1, tzinfo=timezone.utc)
        before = datetime(2026, 7, 1, tzinfo=timezone.utc)
        assert _filter_by_date([h], after, before) == [h]

    def test_both_bounds_none(self):
        h1 = _make(name="A", start_date=datetime(2026, 1, 1, tzinfo=timezone.utc))
        h2 = _make(name="B", start_date=None)
        result = _filter_by_date([h1, h2], None, None)
        assert result == [h1, h2]

    def test_mixed_list(self):
        h_early = _make(name="Early", start_date=datetime(2026, 1, 1, tzinfo=timezone.utc))
        h_mid = _make(name="Mid", start_date=datetime(2026, 6, 15, tzinfo=timezone.utc))
        h_late = _make(name="Late", start_date=datetime(2026, 12, 1, tzinfo=timezone.utc))
        h_none = _make(name="NoDate", start_date=None)

        after = datetime(2026, 3, 1, tzinfo=timezone.utc)
        before = datetime(2026, 9, 1, tzinfo=timezone.utc)
        result = _filter_by_date([h_early, h_mid, h_late, h_none], after, before)
        assert [h.name for h in result] == ["Mid", "NoDate"]


# ---------------------------------------------------------------------------
# _to_json_obj
# ---------------------------------------------------------------------------

class TestToJsonObj:
    def test_all_keys_present(self):
        h = _make()
        obj = _to_json_obj(h)
        expected_keys = {
            "event_id", "name", "url", "source", "format", "location",
            "start_date", "end_date", "organizer", "registration_status",
            "themes", "prize_amount", "participants",
        }
        assert set(obj.keys()) == expected_keys

    def test_dates_iso_when_present(self):
        dt = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        h = _make(start_date=dt, end_date=dt)
        obj = _to_json_obj(h)
        assert obj["start_date"] == dt.isoformat()
        assert obj["end_date"] == dt.isoformat()

    def test_dates_none_when_absent(self):
        h = _make()
        obj = _to_json_obj(h)
        assert obj["start_date"] is None
        assert obj["end_date"] is None

    def test_format_is_enum_value(self):
        h = _make(format=Format.IN_PERSON)
        obj = _to_json_obj(h)
        assert obj["format"] == "in-person"

    def test_empty_organizer_becomes_none(self):
        h = _make(organizer="")
        obj = _to_json_obj(h)
        assert obj["organizer"] is None

    def test_nonempty_organizer_preserved(self):
        h = _make(organizer="MLH")
        obj = _to_json_obj(h)
        assert obj["organizer"] == "MLH"

    def test_empty_prize_becomes_none(self):
        h = _make(prize_amount="")
        obj = _to_json_obj(h)
        assert obj["prize_amount"] is None

    def test_nonempty_prize_preserved(self):
        h = _make(prize_amount="$10k")
        obj = _to_json_obj(h)
        assert obj["prize_amount"] == "$10k"

    def test_registration_status_is_value(self):
        h = _make(registration_status=RegistrationStatus.OPEN)
        obj = _to_json_obj(h)
        assert obj["registration_status"] == "open"


# ---------------------------------------------------------------------------
# _format_date
# ---------------------------------------------------------------------------

class TestFormatDate:
    def test_tbd_when_no_start(self):
        h = _make(start_date=None)
        assert _format_date(h) == "TBD"

    def test_single_day(self):
        dt = datetime(2026, 3, 15)
        h = _make(start_date=dt, end_date=dt)
        assert _format_date(h) == "Mar 15"

    def test_single_day_no_end(self):
        h = _make(start_date=datetime(2026, 3, 15))
        assert _format_date(h) == "Mar 15"

    def test_multi_day(self):
        h = _make(
            start_date=datetime(2026, 3, 15),
            end_date=datetime(2026, 3, 17),
        )
        assert _format_date(h) == "Mar 15 - Mar 17"

    def test_multi_day_cross_month(self):
        h = _make(
            start_date=datetime(2026, 1, 30),
            end_date=datetime(2026, 2, 1),
        )
        assert _format_date(h) == "Jan 30 - Feb 01"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser():
    """Reconstruct the CLI parser for testing (mirrors cli.main())."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")

    subparsers = parser.add_subparsers(dest="command")

    discover_parser = subparsers.add_parser("discover")
    _add_discover_args(discover_parser)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("url")
    analyze_parser.add_argument("--model", default="claude-sonnet-4-5-20250929")
    analyze_parser.add_argument("--budget", type=int, default=30)
    analyze_parser.add_argument("--map-root", default=None)
    analyze_parser.add_argument("--json", action="store_true")

    _add_discover_args(parser)  # backward compat
    return parser


class TestArgParsing:
    def test_discover_json(self):
        parser = _build_parser()
        args = parser.parse_args(["discover", "--json"])
        assert args.command == "discover"
        assert args.json is True

    def test_analyze_url(self):
        parser = _build_parser()
        args = parser.parse_args(["analyze", "https://example.com"])
        assert args.command == "analyze"
        assert args.url == "https://example.com"

    def test_backward_compat_no_subcommand(self):
        parser = _build_parser()
        args = parser.parse_args(["--json"])
        assert args.command is None
        assert args.json is True

    def test_analyze_budget(self):
        parser = _build_parser()
        args = parser.parse_args(["analyze", "--budget", "50", "https://example.com"])
        assert args.command == "analyze"
        assert args.budget == 50
        assert args.url == "https://example.com"

    def test_discover_date_filters(self):
        parser = _build_parser()
        args = parser.parse_args(["discover", "--after", "2026-06-01", "--before", "2026-12-31"])
        assert args.after == "2026-06-01"
        assert args.before == "2026-12-31"

    def test_analyze_defaults(self):
        parser = _build_parser()
        args = parser.parse_args(["analyze", "https://example.com"])
        assert args.model == "claude-sonnet-4-5-20250929"
        assert args.budget == 30
        assert args.map_root is None
        assert args.json is False
