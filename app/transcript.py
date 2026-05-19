from __future__ import annotations

import json

import anthropic
import httpx

from app.config import settings

_SYSTEM_PROMPT = """\
You receive the raw content of an SRT subtitle file. Reconstruct it into a clean, readable transcript.

Processing steps:
1. Strip all SRT sequence numbers and timestamps — the output must contain only spoken text.
2. Merge subtitle fragments into complete sentences and natural paragraphs. Subtitles are split mid-sentence; reconstruct the intended sentences.
3. Restore missing punctuation (periods, commas, question marks) only where it is clearly implied by the sentence structure. Do not guess punctuation when the sentence meaning is ambiguous.
4. Group related sentences into logical sections with a short descriptive heading.
5. Preserve all languages exactly as spoken. Do not translate any language into another. If the speaker switches between English, Spanish, Romanian, Italian, German, French, Turkish, or any other language, reproduce it faithfully in that language.
6. Mark unclear, incomplete, or unintelligible passages with [?] instead of inventing plausible content.
7. If a passage is clearly a transcription artifact (a repeated word or phrase that appears mechanical rather than intentional), mark it as [transcription artifact] and move on — do not reproduce the repetition.

Rules — these are absolute:
- Use only the content present in the SRT file. Do not add information, explanations, summaries, or interpretations from outside the file.
- Do not translate or paraphrase. Preserve the speaker's original words, style, and tone.
- Do not invent or guess missing content. When text is missing or unclear, use [?] or [unclear] explicitly.
- Preserve multilingual content: a speaker switching between languages is intentional and must be reproduced as-is, not normalized to a single language.
- The transcript must be reconstructible back to the original segments — do not add new ideas, context, or conclusions.

Output format:
# [Title — inferred from the content, not invented. If no clear title can be inferred, write "Transcript".]

[Reconstructed transcript divided into sections with short headings]

---
## Transcription notes
[List any: unclear passages marked with [?], suspected missing audio, language switches observed, transcription artifacts removed. Write "None" if the transcript is clean.]\
"""


def reconstruct_transcript(srt_content: str, provider: str | None = None, ollama_model: str | None = None) -> str:
    effective = provider or settings.transcript_provider
    if effective == "ollama":
        return _reconstruct_with_ollama(srt_content, ollama_model or settings.ollama_model)
    return _reconstruct_with_claude(srt_content)


def _reconstruct_with_claude(srt_content: str) -> str:
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


def _reconstruct_with_ollama(srt_content: str, model: str) -> str:
    url = f"{settings.ollama_base_url}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": srt_content},
        ],
        "options": {"num_ctx": settings.ollama_num_ctx},
        "stream": True,
    }
    # Stream the response so the per-chunk read timeout resets with every token —
    # the overall generation time is unbounded as long as tokens keep arriving.
    chunks: list[str] = []
    timeout = httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0)
    with httpx.Client(timeout=timeout) as client:
        with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if not data.get("done"):
                    chunks.append(data["message"]["content"])
    return "".join(chunks)
