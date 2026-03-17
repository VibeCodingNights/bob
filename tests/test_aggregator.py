"""Tests for the aggregator (dedup, sort)."""

from datetime import datetime, timezone


from hackathon_finder.aggregator import deduplicate, sort_hackathons
from hackathon_finder.models import Hackathon


def _h(name: str, source: str = "devpost", start: datetime | None = None, **kw) -> Hackathon:
    return Hackathon(name=name, url=f"https://{source}.com/{name}", source=source, start_date=start, **kw)


class TestDeduplicate:
    def test_no_duplicates(self):
        items = [_h("Alpha"), _h("Beta")]
        assert len(deduplicate(items)) == 2

    def test_exact_name_dedup(self):
        items = [_h("Cool", source="devpost"), _h("Cool", source="mlh")]
        result = deduplicate(items)
        assert len(result) == 1
        assert result[0].source == "devpost"  # higher priority

    def test_priority_ordering(self):
        """Lower priority number wins."""
        items = [
            _h("Hack", source="meetup"),
            _h("Hack", source="mlh"),
            _h("Hack", source="devpost"),
        ]
        result = deduplicate(items)
        assert len(result) == 1
        assert result[0].source == "devpost"

    def test_dedup_strips_noise_words(self):
        """'Cool Hackathon 2026' and 'Cool Hack' should dedup."""
        items = [
            _h("Cool Hackathon 2026", source="devpost"),
            _h("Cool Hack", source="mlh"),
        ]
        result = deduplicate(items)
        assert len(result) == 1

    def test_empty_input(self):
        assert deduplicate([]) == []

    def test_single_item(self):
        items = [_h("Solo")]
        result = deduplicate(items)
        assert len(result) == 1

    def test_different_names_not_deduped(self):
        items = [_h("Alpha Hackathon"), _h("Beta Hackathon")]
        result = deduplicate(items)
        assert len(result) == 2


class TestSortHackathons:
    def test_sorts_by_date_ascending(self):
        items = [
            _h("Late", start=datetime(2026, 12, 1)),
            _h("Early", start=datetime(2026, 1, 1)),
            _h("Mid", start=datetime(2026, 6, 1)),
        ]
        result = sort_hackathons(items)
        assert [h.name for h in result] == ["Early", "Mid", "Late"]

    def test_none_dates_sort_last(self):
        items = [
            _h("NoDate"),
            _h("HasDate", start=datetime(2026, 3, 1)),
        ]
        result = sort_hackathons(items)
        assert result[0].name == "HasDate"
        assert result[1].name == "NoDate"

    def test_same_date_sorted_by_name(self):
        dt = datetime(2026, 6, 1)
        items = [_h("Zebra", start=dt), _h("Alpha", start=dt)]
        result = sort_hackathons(items)
        assert [h.name for h in result] == ["Alpha", "Zebra"]

    def test_empty_input(self):
        assert sort_hackathons([]) == []

    def test_timezone_aware_dates(self):
        items = [
            _h("UTC", start=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)),
            _h("Naive", start=datetime(2026, 6, 1, 10, 0)),
        ]
        # Should not raise — handles mixed tz-aware and naive
        result = sort_hackathons(items)
        assert len(result) == 2

    def test_all_none_dates(self):
        items = [_h("B"), _h("A")]
        result = sort_hackathons(items)
        assert [h.name for h in result] == ["A", "B"]
