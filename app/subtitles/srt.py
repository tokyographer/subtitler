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
    Wrap subtitle text to at most two lines of max_chars each.
    Splits near the midpoint at a word boundary.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text

    mid = len(text) // 2
    # Prefer splitting before the midpoint
    split_at = text.rfind(" ", 0, mid + 1)
    if split_at == -1:
        split_at = text.find(" ", mid)
    if split_at == -1:
        return text  # single long word — leave as-is

    line1 = text[:split_at].strip()
    line2 = text[split_at:].strip()
    return f"{line1}\n{line2}"


def segments_to_srt(
    segments: list[dict],
    max_chars: int = 42,
) -> str:
    """
    Convert a list of transcription segments to a YouTube-compatible SRT string.

    Each segment must have: start (float), end (float), text (str).
    Returns an empty string if segments is empty.
    """
    if not segments:
        return ""

    MIN_DURATION = 0.5  # seconds — YouTube requires end > start

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

        out_idx += 1
        wrapped = wrap_subtitle_text(raw_text, max_chars)
        ts_start = format_timestamp(start)
        ts_end = format_timestamp(end)

        blocks.append(f"{out_idx}\n{ts_start} --> {ts_end}\n{wrapped}")

    return "\n\n".join(blocks) + "\n"
