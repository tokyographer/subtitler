import pytest

from app.subtitles.srt import format_timestamp, segments_to_srt, wrap_subtitle_text


class TestFormatTimestamp:
    def test_zero(self):
        assert format_timestamp(0.0) == "00:00:00,000"

    def test_one_second(self):
        assert format_timestamp(1.0) == "00:00:01,000"

    def test_fractional(self):
        assert format_timestamp(4.5) == "00:00:04,500"

    def test_minutes(self):
        assert format_timestamp(90.0) == "00:01:30,000"

    def test_hours(self):
        assert format_timestamp(3661.0) == "01:01:01,000"

    def test_milliseconds(self):
        assert format_timestamp(1.123) == "00:00:01,123"

    def test_large(self):
        assert format_timestamp(7384.567) == "02:03:04,567"

    def test_negative_clamped(self):
        assert format_timestamp(-1.0) == "00:00:00,000"

    def test_rounding(self):
        # 1.0005 rounds to 1001 ms
        result = format_timestamp(1.0005)
        assert result.endswith(",001") or result.endswith(",000")


class TestWrapSubtitleText:
    def test_short_unchanged(self):
        text = "Hello world"
        assert wrap_subtitle_text(text) == "Hello world"

    def test_exactly_max_unchanged(self):
        text = "x" * 42
        assert wrap_subtitle_text(text) == text

    def test_long_splits_into_two_lines(self):
        text = "This is a fairly long subtitle that needs to be wrapped."
        result = wrap_subtitle_text(text)
        lines = result.split("\n")
        assert len(lines) == 2

    def test_no_leading_trailing_whitespace(self):
        result = wrap_subtitle_text("  Hello world  ")
        assert result == "Hello world"

    def test_no_space_no_crash(self):
        long_word = "a" * 100
        result = wrap_subtitle_text(long_word)
        assert result == long_word  # can't split without a space

    def test_split_is_near_middle(self):
        text = "The quick brown fox jumps over the lazy dog and runs away fast."
        result = wrap_subtitle_text(text)
        lines = result.split("\n")
        # Neither line should be very short
        assert len(lines[0]) > 5
        assert len(lines[1]) > 5

    def test_custom_max_chars(self):
        text = "Hello world test"
        result = wrap_subtitle_text(text, max_chars=10)
        assert "\n" in result


class TestSegmentsToSrt:
    def test_empty_returns_empty_string(self):
        assert segments_to_srt([]) == ""

    def test_single_segment(self):
        segments = [{"start": 0.0, "end": 4.5, "text": "Hello world"}]
        srt = segments_to_srt(segments)
        assert "1\n00:00:00,000 --> 00:00:04,500\nHello world" in srt

    def test_multiple_segments(self):
        segments = [
            {"start": 0.0, "end": 4.0, "text": "First subtitle"},
            {"start": 4.0, "end": 8.0, "text": "Second subtitle"},
        ]
        srt = segments_to_srt(segments)
        assert "1\n00:00:00,000 --> 00:00:04,000\nFirst subtitle" in srt
        assert "2\n00:00:04,000 --> 00:00:08,000\nSecond subtitle" in srt

    def test_blocks_separated_by_blank_line(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "A"},
            {"start": 2.0, "end": 4.0, "text": "B"},
        ]
        srt = segments_to_srt(segments)
        assert "\n\n" in srt

    def test_skips_empty_text_segments(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": ""},
            {"start": 2.0, "end": 4.0, "text": "  "},
            {"start": 4.0, "end": 6.0, "text": "Real text"},
        ]
        srt = segments_to_srt(segments)
        assert "1\n" in srt
        assert "2\n" not in srt  # only one non-empty segment

    def test_unicode_content(self):
        segments = [{"start": 0.0, "end": 2.0, "text": "日本語テスト 🎬"}]
        srt = segments_to_srt(segments)
        assert "日本語テスト 🎬" in srt

    def test_youtube_compatible_comma_separator(self):
        segments = [{"start": 1.0, "end": 3.5, "text": "Test"}]
        srt = segments_to_srt(segments)
        assert "00:00:01,000 --> 00:00:03,500" in srt

    def test_ends_with_newline(self):
        segments = [{"start": 0.0, "end": 1.0, "text": "Hi"}]
        srt = segments_to_srt(segments)
        assert srt.endswith("\n")

    def test_long_text_wrapped(self):
        text = "This is a very long subtitle text that definitely needs to be wrapped for the screen."
        segments = [{"start": 0.0, "end": 5.0, "text": text}]
        srt = segments_to_srt(segments)
        # The text block should have a line break
        block_text = srt.split("\n", 2)[2]  # skip index + timestamp lines
        assert "\n" in block_text

    def test_sequence_numbers_are_sequential(self):
        segments = [
            {"start": float(i), "end": float(i + 1), "text": f"Segment {i}"}
            for i in range(5)
        ]
        srt = segments_to_srt(segments)
        for n in range(1, 6):
            assert f"{n}\n" in srt
