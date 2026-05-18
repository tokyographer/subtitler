from __future__ import annotations

from collections import Counter

from app.transcribe.base import Segment


def detect_and_truncate_loop(
    segments: list[Segment], max_run: int = 5
) -> tuple[list[Segment], int]:
    """
    Scan for the first run of >= max_run consecutive segments whose text is
    identical (case-insensitive, stripped). Truncates the list at the start of
    that run and returns (clean_segments, n_dropped).

    A run of fewer than max_run identical segments is considered legitimate
    repetition (e.g. a repeated phrase for emphasis) and is left untouched.
    """
    if len(segments) < max_run:
        return segments, 0

    i = 0
    while i < len(segments):
        text = segments[i].text.strip().lower()
        j = i + 1
        while j < len(segments) and segments[j].text.strip().lower() == text:
            j += 1
        run_len = j - i
        if run_len >= max_run:
            n_dropped = len(segments) - i
            return segments[:i], n_dropped
        i = j

    return segments, 0


def strip_translation_segments(
    segments: list[Segment],
    primary_language: str | None = None,
    min_segment_chars: int = 12,
) -> tuple[list[Segment], int]:
    """
    Remove interpreter/translation segments from a multilingual transcription.

    Typical scenario: a main speaker (English or Spanish) followed by a live
    interpreter repeating the same content in a local language. This function
    detects the language of each segment and discards those that do not match
    the primary language.

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
        DetectorFactory.seed = 42  # reproducible results
    except ImportError:
        return segments, 0

    if not segments:
        return segments, 0

    # ── Detect per-segment language ───────────────────────────────────────
    detected: list[str | None] = []
    for seg in segments:
        text = seg.text.strip()
        if len(text) < min_segment_chars:
            detected.append(None)
            continue
        try:
            detected.append(detect(text).split("-")[0])  # "zh-cn" → "zh"
        except LangDetectException:
            detected.append(None)

    # ── Fill gaps: short/undetected segments inherit nearest neighbour ────
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

    # ── Determine primary language ────────────────────────────────────────
    if primary_language is None:
        counts = Counter(d for d in detected if d is not None)
        if not counts:
            return segments, 0
        primary_language = counts.most_common(1)[0][0]
    else:
        primary_language = primary_language.split("-")[0]

    # Single language present — nothing to filter
    unique_langs = {d for d in detected if d is not None}
    if len(unique_langs) <= 1:
        return segments, 0

    # ── Filter to primary language ────────────────────────────────────────
    kept = [
        seg for seg, lang in zip(segments, detected)
        if lang is None or lang == primary_language
    ]
    n_dropped = len(segments) - len(kept)
    return kept, n_dropped
