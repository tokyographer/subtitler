from __future__ import annotations


def format_timestamp(seconds: float) -> str:
    """Convert float seconds to SRT timestamp: HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0.0
    millis = round(seconds * 1000)
    h = millis // 3_600_000
    millis %= 3_600_000
    m = millis // 60_000
    millis %= 60_000
    s = millis // 1_000
    ms = millis % 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def wrap_subtitle_text(text: str, max_chars: int = 42) -> str:
    """
    Wrap subtitle text to at most two lines of *max_chars* each.
    Splits near the midpoint at a word boundary.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text

    mid = len(text) // 2
    split_at = text.rfind(" ", 0, mid + 1)
    if split_at == -1:
        split_at = text.find(" ", mid)
    if split_at == -1:
        return text  # single long token — leave as-is

    return f"{text[:split_at].strip()}\n{text[split_at:].strip()}"


def merge_segments(segments: list[dict], gap_ms: int = 0) -> list[dict]:
    """
    Merge consecutive segments whose inter-segment gap is smaller than
    *gap_ms* milliseconds.  Pass ``gap_ms=0`` (default) to skip merging.

    Useful for cleaning up Whisper output where a single thought is split
    across many tiny segments with very short pauses between them.
    """
    if gap_ms <= 0 or len(segments) <= 1:
        return segments

    result: list[dict] = []
    for seg in segments:
        if not result:
            result.append(dict(seg))
            continue
        gap = (float(seg["start"]) - float(result[-1]["end"])) * 1000
        if 0 <= gap < gap_ms:
            prev = result[-1]
            prev["end"] = seg["end"]
            prev["text"] = prev["text"].rstrip() + " " + str(seg["text"]).lstrip()
        else:
            result.append(dict(seg))
    return result


def segments_to_srt(
    segments: list[dict],
    max_chars: int = 42,
    max_duration: float = 0.0,
    merge_gap_ms: int = 0,
) -> str:
    """
    Convert transcription segments to a YouTube-compatible SRT string.

    Parameters
    ----------
    segments:
        List of dicts with ``start`` (float), ``end`` (float), ``text`` (str).
    max_chars:
        Maximum characters per subtitle line before wrapping.
    max_duration:
        Cap the display duration of each block (seconds).  ``0`` = no cap.
        The audio segment timing is unchanged; only the SRT end timestamp is
        shortened so the subtitle disappears earlier.
    merge_gap_ms:
        Merge consecutive segments separated by less than this many milliseconds.
        ``0`` = disabled.
    """
    if not segments:
        return ""

    if merge_gap_ms > 0:
        segments = merge_segments(segments, merge_gap_ms)

    MIN_DURATION = 0.5  # YouTube requires end > start

    blocks: list[str] = []
    out_idx = 0
    for seg in segments:
        start = float(seg.get("start", 0))
        end = float(seg.get("end", 0))
        raw_text = str(seg.get("text", "")).strip()

        if not raw_text:
            continue

        if end <= start:
            end = start + MIN_DURATION

        if max_duration > 0:
            end = min(end, start + max_duration)
            if end <= start:
                end = start + MIN_DURATION

        out_idx += 1
        wrapped = wrap_subtitle_text(raw_text, max_chars)
        blocks.append(
            f"{out_idx}\n{format_timestamp(start)} --> {format_timestamp(end)}\n{wrapped}"
        )

    return "\n\n".join(blocks) + "\n"
