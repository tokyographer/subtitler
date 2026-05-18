from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.transcribe.base import Segment


@dataclass
class LoopInfo:
    """Details about a detected hallucination/repetition loop."""
    repeated_text: str
    loop_start_index: int
    loop_start_time: float    # seconds
    segment_count: int        # segments from the loop start to end of list
    focus_language: str | None = None  # None = auto-detect was selected

    def to_dict(self) -> dict:
        return {
            "repeated_text": self.repeated_text,
            "loop_start_index": self.loop_start_index,
            "loop_start_time": self.loop_start_time,
            "segment_count": self.segment_count,
            "focus_language": self.focus_language,
        }


def detect_loop(
    segments: list[Segment],
    max_run: int = 20,
    min_fraction: float = 0.10,
    focus_language: str | None = None,
) -> tuple[list[Segment], list[Segment], LoopInfo | None]:
    """
    Detect a Whisper hallucination/repetition loop.

    Returns (clean_segments, loop_segments, loop_info).

    - clean_segments: content before the loop (may be empty)
    - loop_segments: the loop and everything after it — preserved, never discarded
    - loop_info: None if no loop was detected

    A run is only treated as a hallucination loop when BOTH conditions hold:
      1. run_length >= max_run  (default 20) — rules out conversational
         repetition ("Right.", "Yes.", "Okay." said 5–15 times in a row).
      2. loop_segment_count >= min_fraction * total_segments  (default 10%) —
         rules out a short run in a long file where the rest is real content.

    Real Whisper hallucinations typically produce hundreds of identical segments
    that represent the majority of the file. A run of 11 "Right." in a 1 000-
    segment file (< 2%) is almost certainly real speech, not a hallucination.

    focus_language is stored in loop_info so the UI can give accurate advice:
    if it is not None, a language was already selected and the advice should
    NOT tell the user to "select a language".
    """
    total = len(segments)
    if total < max_run:
        return segments, [], None

    i = 0
    while i < total:
        text = segments[i].text.strip().lower()
        j = i + 1
        while j < total and segments[j].text.strip().lower() == text:
            j += 1
        run_len = j - i
        if run_len >= max_run:
            loop_segs = segments[i:]
            fraction = len(loop_segs) / total
            if fraction >= min_fraction:
                info = LoopInfo(
                    repeated_text=segments[i].text.strip(),
                    loop_start_index=i,
                    loop_start_time=segments[i].start,
                    segment_count=len(loop_segs),
                    focus_language=focus_language,
                )
                return segments[:i], loop_segs, info
            # Run meets length threshold but not fraction — skip over it
            # (treat as legitimate repeated speech) and keep scanning.
        i = j

    return segments, [], None


def detect_and_truncate_loop(
    segments: list[Segment], max_run: int = 5
) -> tuple[list[Segment], int]:
    """Backward-compatible wrapper around detect_loop. Returns (clean, n_dropped)."""
    clean, loop, _ = detect_loop(segments, max_run=max_run)
    return clean, len(loop)


def strip_translation_segments(
    segments: list[Segment],
    primary_language: str | None = None,
    min_segment_chars: int = 12,
) -> tuple[list[Segment], int]:
    """
    Remove interpreter/translation segments from a multilingual transcription.

    This is an EXPLICIT optional filter — it must never be called automatically
    because focus_language is a Whisper decoding hint, not a content filter.

    Typical use case: a main speaker followed by a live interpreter repeating
    the same content in a different language. This function detects the language
    of each segment and discards those not matching the primary language.

    Parameters
    ----------
    segments:
        Full segment list after transcription.
    primary_language:
        ISO 639-1 code of the main speaker ("en", "es", …).
        Pass None to auto-detect from the most frequent language in the list.
    min_segment_chars:
        Segments shorter than this are skipped for detection (unreliable on
        very short text) and inherit the language of the nearest neighbour.

    Returns
    -------
    (kept_segments, n_dropped)
        n_dropped == 0 means either nothing was filtered or langdetect is not
        installed — in both cases the original list is returned unchanged.
    """
    try:
        from langdetect import DetectorFactory, LangDetectException, detect
        DetectorFactory.seed = 42
    except ImportError:
        return segments, 0

    if not segments:
        return segments, 0

    detected: list[str | None] = []
    for seg in segments:
        text = seg.text.strip()
        if len(text) < min_segment_chars:
            detected.append(None)
            continue
        try:
            detected.append(detect(text).split("-")[0])
        except LangDetectException:
            detected.append(None)

    # Fill gaps: short/undetected segments inherit nearest neighbour
    last: str | None = None
    for i in range(len(detected)):
        if detected[i] is not None:
            last = detected[i]
        elif last is not None:
            detected[i] = last
    last = None
    for i in range(len(detected) - 1, -1, -1):
        if detected[i] is not None:
            last = detected[i]
        elif last is not None:
            detected[i] = last

    if primary_language is None:
        counts = Counter(d for d in detected if d is not None)
        if not counts:
            return segments, 0
        primary_language = counts.most_common(1)[0][0]
    else:
        primary_language = primary_language.split("-")[0]

    unique_langs = {d for d in detected if d is not None}
    if len(unique_langs) <= 1:
        return segments, 0

    kept = [
        seg for seg, lang in zip(segments, detected)
        if lang is None or lang == primary_language
    ]
    return kept, len(segments) - len(kept)
