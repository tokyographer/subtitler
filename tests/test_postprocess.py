import pytest

from app.transcribe.base import Segment
from app.transcribe.postprocess import (
    LoopInfo,
    detect_and_truncate_loop,
    detect_loop,
    strip_translation_segments,
)


def _segs(*texts: str) -> list[Segment]:
    """Build a Segment list with dummy timestamps for testing."""
    return [Segment(start=float(i), end=float(i + 1), text=t) for i, t in enumerate(texts)]


# ── detect_and_truncate_loop (backward-compat wrapper) ───────────────────────

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
        # 10 identical segments but below max_run=20 → no truncation
        segs = _segs(*["Gold."] * 10)
        result, n = detect_and_truncate_loop(segs, max_run=20)
        assert n == 0
        assert len(result) == 10

    def test_run_exactly_at_threshold_and_fraction_triggers(self):
        # 20 identical segments out of 20 = 100% fraction → triggers
        segs = _segs(*["Gold."] * 20)
        result, n = detect_and_truncate_loop(segs, max_run=20)
        assert n == 20
        assert result == []

    def test_long_run_triggers_truncation(self):
        valid = _segs("Hello", "World", "This is fine")
        loop = _segs(*["Gold."] * 100)
        for i, s in enumerate(loop):
            s.start = float(len(valid) + i)
            s.end = float(len(valid) + i + 1)
        segs = valid + loop
        # 100 loop / 103 total = 97% > 10% → triggers
        result, n = detect_and_truncate_loop(segs, max_run=20)
        assert n == 100
        assert len(result) == 3
        assert result[0].text == "Hello"
        assert result[-1].text == "This is fine"

    def test_short_run_in_long_file_not_flagged(self):
        # 11 "Right." in a 1179-segment file (0.9%) must NOT trigger
        # This mirrors the real-world false positive on Anthony Day 3.
        filler = _segs(*[f"Segment {i}" for i in range(1168)])
        short_loop = _segs(*["Right."] * 11)
        more_content = _segs(*[f"Content {i}" for i in range(100)])
        segs = filler + short_loop + more_content
        result, n = detect_and_truncate_loop(segs, max_run=20)
        assert n == 0
        assert len(result) == len(segs)  # nothing removed

    def test_case_insensitive_comparison(self):
        # 20 case-variant identical segments = 100% → triggers
        segs = _segs(*["gold.", "Gold.", "GOLD.", "gold.", "Gold."] * 4)
        result, n = detect_and_truncate_loop(segs, max_run=20)
        assert n == 20
        assert result == []

    def test_short_run_below_threshold_not_truncated(self):
        segs = _segs("Repeat", "Repeat", "Repeat", "Repeat", "Something else", "More content")
        result, n = detect_and_truncate_loop(segs, max_run=20)
        assert n == 0
        assert len(result) == 6

    def test_custom_max_run(self):
        # 100-segment file: 30 identical = 30% > 10% and >= max_run=25 → triggers
        filler = _segs(*[f"S{i}" for i in range(70)])
        loop = _segs(*["X"] * 30)
        segs = filler + loop
        result, n = detect_and_truncate_loop(segs, max_run=25)
        assert n == 30
        assert len(result) == 70

    def test_run_at_very_start_dominates_file(self):
        # 25 identical at start, then 1 different = loop is 25/26 = 96% → triggers
        segs = _segs(*["Loop"] * 25) + _segs("Valid")
        result, n = detect_and_truncate_loop(segs, max_run=20)
        assert n == 26  # loop + the valid segment after it
        assert result == []

    def test_whitespace_stripped_for_comparison(self):
        # 20 whitespace-variant identical segments in a 20-seg file → triggers
        segs = _segs(*["  Gold.  ", "Gold.", " Gold. ", "Gold.", "Gold."] * 4)
        result, n = detect_and_truncate_loop(segs, max_run=20)
        assert n == 20
        assert result == []

    def test_normal_repeated_phrase_below_threshold(self):
        segs = _segs("Yes.", "Yes.", "Yes.", "Exactly.", "That's right.")
        result, n = detect_and_truncate_loop(segs, max_run=20)
        assert n == 0
        assert len(result) == 5


# ── detect_loop — new interface ───────────────────────────────────────────────

class TestDetectLoop:
    def test_no_loop_returns_all_clean(self):
        segs = _segs("Hello", "World", "Goodbye")
        clean, loop, info = detect_loop(segs)
        assert info is None
        assert clean == segs
        assert loop == []

    def test_loop_returns_split_not_discarded(self):
        """Raw data must never be thrown away — loop segments come back in loop."""
        valid = _segs("Hello", "World")
        loop_segs = [Segment(start=float(2 + i), end=float(3 + i), text="Gold.") for i in range(100)]
        segs = valid + loop_segs
        # 100/102 = 98% > 10% and 100 >= 20 → triggers
        clean, loop, info = detect_loop(segs, max_run=20, min_fraction=0.10)
        assert len(clean) == 2
        assert len(loop) == 100
        assert len(clean) + len(loop) == len(segs)  # nothing discarded

    def test_loop_info_fields_are_accurate(self):
        valid = _segs("Intro", "Main point")
        loop_segs = [Segment(start=5.0 + i, end=6.0 + i, text="Gold.") for i in range(100)]
        segs = valid + loop_segs
        clean, loop, info = detect_loop(segs, max_run=20, min_fraction=0.0, focus_language="en")
        assert info is not None
        assert info.repeated_text == "Gold."
        assert info.loop_start_index == 2
        assert info.loop_start_time == 5.0
        assert info.segment_count == 100
        assert info.focus_language == "en"

    def test_loop_info_records_none_when_auto_detect(self):
        """UI uses focus_language=None to decide whether to say 'set a language'."""
        segs = _segs(*["Repeat."] * 20)
        _, _, info = detect_loop(segs, max_run=20, min_fraction=0.0, focus_language=None)
        assert info is not None
        assert info.focus_language is None

    def test_loop_info_records_language_when_set(self):
        """UI must NOT say 'set a language' when one was already selected."""
        segs = _segs(*["Repeat."] * 20)
        _, _, info = detect_loop(segs, max_run=20, min_fraction=0.0, focus_language="en")
        assert info is not None
        assert info.focus_language == "en"

    def test_loop_info_to_dict_is_serialisable(self):
        segs = _segs(*["Loop"] * 20)
        _, _, info = detect_loop(segs, max_run=20, min_fraction=0.0, focus_language="ro")
        d = info.to_dict()
        assert d["repeated_text"] == "Loop"
        assert d["focus_language"] == "ro"
        assert isinstance(d["loop_start_time"], float)

    # ── Multilingual preservation ─────────────────────────────────────────

    def test_focus_language_does_not_remove_other_language_segments(self):
        """detect_loop is not a content filter — it must never remove segments
        because they are in a different language from focus_language."""
        segs = _segs(
            "Hello world",        # English
            "Hola mundo",         # Spanish
            "Bonjour le monde",   # French
            "Ciao mondo",         # Italian
            "Merhaba dünya",      # Turkish
        )
        clean, loop, info = detect_loop(segs, focus_language="en")
        assert info is None           # no repetition loop
        assert len(clean) == 5        # all five segments preserved
        assert loop == []

    def test_multilingual_segments_preserved_by_default(self):
        """Without calling strip_translation_segments, all languages survive."""
        segs = _segs(
            "This is English",
            "Esto es español",
            "C'est du français",
            "Das ist Deutsch",
        )
        clean, loop, info = detect_loop(segs)
        assert info is None
        assert len(clean) == 4

    def test_detect_loop_never_calls_translation_filter(self):
        """strip_translation_segments is a separate explicit step.
        detect_loop must not invoke it — the segment count must stay the same."""
        segs = _segs(
            "This is a long English sentence for testing purposes here",
            "Aceasta este o propoziție română lungă pentru testare",
            "This is another English sentence with enough characters to detect",
            "Iată o altă propoziție în română suficient de lungă",
        )
        clean, loop, info = detect_loop(segs, focus_language="en")
        # No repetition loop → all segments returned unchanged
        assert info is None
        assert len(clean) == 4

    # ── strip_translation_segments explicit filter ─────────────────────────

    def test_translation_filter_only_runs_when_explicitly_called(self):
        """focus_language alone must never activate the translation filter."""
        segs = _segs("Hello", "Hola", "Bonjour", "Ciao", "Merhaba")
        # detect_loop with focus_language="en" must NOT filter Spanish/French/etc.
        clean, loop, info = detect_loop(segs, focus_language="en")
        assert len(clean) == 5  # no segments removed by detect_loop

        # Only when strip_translation_segments is explicitly called does filtering happen.
        # (We skip calling it here to confirm the above is sufficient.)

    def test_raw_preserved_even_when_loop_detected(self):
        """clean + loop must always reconstruct the full original list."""
        content = _segs("Real content A", "Real content B", "Real content C")
        # 100 repetitions out of 103 total = 97% > 10% and >= 20 → triggers
        loop_part = [Segment(start=float(3 + i), end=float(4 + i), text="Buzz.") for i in range(100)]
        segs = content + loop_part

        clean, loop, info = detect_loop(segs, max_run=20, min_fraction=0.10)

        assert info is not None
        assert len(clean) + len(loop) == len(segs)
        clean_texts = [s.text for s in clean]
        assert "Real content A" in clean_texts
        assert "Real content B" in clean_texts
        assert "Real content C" in clean_texts
        assert len(loop) == 100  # not silently dropped

    def test_short_run_in_long_file_not_flagged(self):
        """11 'Right.' in a 1179-segment file (0.9%) must NOT trigger — this is
        the real-world Anthony Day 3 false positive."""
        filler = _segs(*[f"Segment {i}" for i in range(1168)])
        short_loop = _segs(*["Right."] * 11)
        segs = filler + short_loop
        clean, loop, info = detect_loop(segs, max_run=20, min_fraction=0.10)
        assert info is None
        assert len(clean) == len(segs)  # everything preserved
