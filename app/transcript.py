from __future__ import annotations

import anthropic

from app.config import settings

_SYSTEM_PROMPT = """\
Take the attached SRT subtitle file and reconstruct it into a coherent, readable transcript.

Important instructions:
- Reconstruct a continuous readable text using only the file content.
- Use only the content contained in the SRT file.
- Do not add external sources, explanations, interpretations, or new concepts.
- Preserve the original sequence of ideas.
- Preserve the main speaker's meaning, tone, language and teaching style as much as possible.
- Keep the original language of each fragment. If the file contains mixed languages, preserve them rather than translating.
- Correct formatting problems caused by subtitle segmentation.
- Summarize content when it is clearly corrupted or repetitive.
- If a phrase is unclear, preserve it as closely as possible rather than inventing a correction.

Output format:
1. Title based on the content of the transcript.
2. Clean reconstructed transcript divided into readable sections.
3. A short note at the end listing any transcription problems, repetitions, missing context, or unclear passages.\
"""


def reconstruct_transcript(srt_content: str) -> str:
    if not settings.anthropic_api_key:
        raise ValueError(
            "SUBTITLER_ANTHROPIC_API_KEY is not set. "
            "Add it to your .env file and restart the server."
        )
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.transcript_model,
        max_tokens=8096,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": srt_content}],
    )
    return response.content[0].text
