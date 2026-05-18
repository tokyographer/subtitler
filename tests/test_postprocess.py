import pytest

from app.transcribe.base import Segment
from app.transcribe.postprocess import detect_and_truncate_loop


def _segs(*texts: str) -> list[Segment]:
    """Build a Segment list with dummy timestamps for testing."""
    return [Segment(start=float(i), end=float(i + 1), text=t) for i, t in enumerate(texts)]


class TestDetectAndTruncateLoop:
    def test_no_repetition_unchanged(self):
        segs = _segs("Hello", "World", "How are you", "I am fine", "Thank you")
        result, n = detect_and_truncate_loop(segs)
        assert n == 0
        assert result == segs

    def test_empty_list(self):
        result, n = detect_and_truncate_loop([])
        assert result == []
        assert n == 0

    def test_fewer_segments_than_threshold_unchanged(self):
        # 4 identical segments but max_run=5 → no truncation
        segs = _segs("Gold.", "Gold.", "Gold.", "Gold.")
        result, n = detect_and_truncate_loop(segs, max_run=5)
        assert n == 0
        assert len(result) == 4

    def test_run_exactly_at_threshold_triggers(self):
        segs = _segs("Gold.", "Gold.", "Gold.", "Gold.", "Gold.")
        result, n = detect_and_truncate_loop(segs, max_run=5)
        assert n == 5
        assert result == []

    def test_long_run_triggers_truncation(self):
        valid = _segs("Hello", "World", "This is fine")
        loop = _segs(*["Gold."] * 100)
        # Give loop segments non-overlapping timestamps
        for i, s in enumerate(loop):
            s.start = float(len(valid) + i)
            s.end = float(len(valid) + i + 1)
        segs = valid + loop
        result, n = detect_and_truncate_loop(segs, max_run=5)
        assert n == 100
        assert len(result) == 3
        assert result[0].text == "Hello"
        assert result[-1].text == "This is fine"

    def test_run_in_middle_truncates_from_that_point(self):
        before = _segs("A", "B", "C")
        loop = _segs(*["Repeat"] * 10)
        after = _segs("D", "E")
        # Adjust timestamps
        for i, s in enumerate(loop):
            s.start = float(3 + i); s.end = float(4 + i)
        for i, s in enumerate(after):
            s.start = float(13 + i); s.end = float(14 + i)
        segs = before + loop + after
        result, n = detect_and_truncate_loop(segs, max_run=5)
        assert len(result) == 3
        assert n == 12  # 10 loop + 2 after

    def test_case_insensitive_comparison(self):
        segs = _segs("gold.", "Gold.", "GOLD.", "gold.", "Gold.")
        result, n = detect_and_truncate_loop(segs, max_run=5)
        assert n == 5
        assert result == []

    def test_short_run_below_threshold_not_truncated(self):
        # 4 identical then different — below max_run=5 → untouched
        segs = _segs("Repeat", "Repeat", "Repeat", "Repeat", "Something else", "More content")
        result, n = detect_and_truncate_loop(segs, max_run=5)
        assert n == 0
        assert len(result) == 6

    def test_custom_max_run(self):
        # max_run=3: 3 identical segments should trigger
        segs = _segs("X", "X", "X", "Y", "Z")
        result, n = detect_and_truncate_loop(segs, max_run=3)
        assert n == 5
        assert result == []

    def test_run_at_very_start(self):
        segs = _segs("Loop", "Loop", "Loop", "Loop", "Loop", "Valid")
        result, n = detect_and_truncate_loop(segs, max_run=5)
        assert n == 6
        assert result == []

    def test_whitespace_stripped_for_comparison(self):
        segs = _segs("  Gold.  ", "Gold.", " Gold. ", "Gold.", "Gold.")
        result, n = detect_and_truncate_loop(segs, max_run=5)
        assert n == 5
        assert result == []

    def test_normal_repeated_phrase_below_threshold(self):
        # A real speaker saying the same word 3 times in a row is fine at max_run=5
        segs = _segs("Yes.", "Yes.", "Yes.", "Exactly.", "That's right.")
        result, n = detect_and_truncate_loop(segs, max_run=5)
        assert n == 0
        assert len(result) == 5
