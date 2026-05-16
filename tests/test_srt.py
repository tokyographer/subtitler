import json
import tempfile
from pathlib import Path

import pytest

from app.subtitles.srt import format_timestamp, merge_segments, segments_to_srt, wrap_subtitle_text
from app.transcribe.whisper_cpp_engine import _parse_json, _parse_srt_ts, _flag_rejected, _write_wav


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

    def test_max_duration_caps_end_time(self):
        segments = [{"start": 0.0, "end": 10.0, "text": "Long segment"}]
        srt = segments_to_srt(segments, max_duration=3.0)
        assert "00:00:03,000" in srt
        assert "00:00:10,000" not in srt

    def test_max_duration_zero_means_no_cap(self):
        segments = [{"start": 0.0, "end": 10.0, "text": "Long segment"}]
        srt = segments_to_srt(segments, max_duration=0.0)
        assert "00:00:10,000" in srt

    def test_merge_gap_joins_close_segments(self):
        segments = [
            {"start": 0.0, "end": 1.0, "text": "Hello"},
            {"start": 1.1, "end": 2.0, "text": "world"},
        ]
        # 100 ms gap → merge at 150 ms threshold
        merged = merge_segments(segments, gap_ms=150)
        assert len(merged) == 1
        assert "Hello" in merged[0]["text"]
        assert "world" in merged[0]["text"]

    def test_merge_gap_keeps_large_gap(self):
        segments = [
            {"start": 0.0, "end": 1.0, "text": "Hello"},
            {"start": 2.0, "end": 3.0, "text": "world"},
        ]
        merged = merge_segments(segments, gap_ms=500)
        assert len(merged) == 2  # 1000 ms gap > 500 ms threshold

    def test_merge_gap_zero_is_noop(self):
        segments = [
            {"start": 0.0, "end": 1.0, "text": "A"},
            {"start": 1.05, "end": 2.0, "text": "B"},
        ]
        assert merge_segments(segments, gap_ms=0) == segments

    def test_merge_gap_preserves_endpoint(self):
        segments = [
            {"start": 0.0, "end": 1.0, "text": "A"},
            {"start": 1.05, "end": 3.0, "text": "B"},
        ]
        merged = merge_segments(segments, gap_ms=200)
        assert merged[0]["end"] == 3.0

    def test_segments_to_srt_merge_gap_param(self):

        segments = [
            {"start": 0.0, "end": 1.0, "text": "Hello"},
            {"start": 1.05, "end": 2.0, "text": "world"},
        ]
        srt = segments_to_srt(segments, merge_gap_ms=200)
        # Only one block
        assert "2\n" not in srt
        assert "Hello" in srt
        assert "world" in srt


class TestWhisperCppHelpers:
    def test_parse_srt_ts_zero(self):
        assert _parse_srt_ts("00:00:00,000") == 0.0

    def test_parse_srt_ts_seconds(self):
        assert abs(_parse_srt_ts("00:00:04,500") - 4.5) < 0.001

    def test_parse_srt_ts_hours(self):
        assert abs(_parse_srt_ts("01:01:01,000") - 3661.0) < 0.001

    def test_parse_srt_ts_bad_input(self):
        assert _parse_srt_ts("garbage") == 0.0

    def test_flag_rejected_unknown(self):
        assert _flag_rejected("error: unknown argument --print-progress", "print-progress")

    def test_flag_rejected_unrecognized(self):
        assert _flag_rejected("unrecognized option: --print-progress", "print-progress")

    def test_flag_rejected_false_when_other_error(self):
        assert not _flag_rejected("model not found", "print-progress")

    def test_parse_json_offsets(self, tmp_path):
        payload = {
            "transcription": [
                {"offsets": {"from": 0, "to": 4500}, "text": " Hello world"},
                {"offsets": {"from": 4500, "to": 8000}, "text": " Second line"},
            ]
        }
        p = tmp_path / "out.json"
        p.write_text(json.dumps(payload))
        segs = _parse_json(p)
        assert len(segs) == 2
        assert segs[0].start == 0.0
        assert abs(segs[0].end - 4.5) < 0.001
        assert segs[0].text == "Hello world"
        assert abs(segs[1].start - 4.5) < 0.001

    def test_parse_json_timestamp_fallback(self, tmp_path):
        """Segments without offsets fall back to timestamp strings."""
        payload = {
            "transcription": [
                {
                    "timestamps": {"from": "00:00:01,000", "to": "00:00:03,500"},
                    "text": " Fallback test",
                }
            ]
        }
        p = tmp_path / "out.json"
        p.write_text(json.dumps(payload))
        segs = _parse_json(p)
        assert len(segs) == 1
        assert abs(segs[0].start - 1.0) < 0.001
        assert abs(segs[0].end - 3.5) < 0.001

    def test_parse_json_skips_empty_text(self, tmp_path):
        payload = {
            "transcription": [
                {"offsets": {"from": 0, "to": 1000}, "text": ""},
                {"offsets": {"from": 1000, "to": 2000}, "text": "  "},
                {"offsets": {"from": 2000, "to": 3000}, "text": "Real text"},
            ]
        }
        p = tmp_path / "out.json"
        p.write_text(json.dumps(payload))
        segs = _parse_json(p)
        assert len(segs) == 1
        assert segs[0].text == "Real text"

    def test_parse_json_empty_transcription(self, tmp_path):
        p = tmp_path / "out.json"
        p.write_text(json.dumps({"transcription": []}))
        assert _parse_json(p) == []

    def test_write_wav_produces_valid_file(self, tmp_path):
        import numpy as np
        import wave

        audio = np.zeros(16_000, dtype=np.float32)  # 1 second of silence
        out = tmp_path / "test.wav"
        _write_wav(audio, out)

        assert out.exists()
        with wave.open(str(out)) as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16_000
            assert wf.getnframes() == 16_000

    def test_write_wav_clips_values(self, tmp_path):
        import numpy as np
        import wave

        audio = np.array([2.0, -2.0, 0.5], dtype=np.float32)
        out = tmp_path / "clip.wav"
        _write_wav(audio, out)

        with wave.open(str(out)) as wf:
            raw = wf.readframes(3)
        import struct
        samples = struct.unpack("<3h", raw)
        assert samples[0] == 32767   # clipped +1
        assert samples[1] == -32767  # clipped -1
        assert abs(samples[2] - 16383) <= 1  # 0.5 * 32767
