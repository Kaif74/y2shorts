"""Mistral-based clip selection, chunking, and strict response validation."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable

from .config import (
    CLIP_SELECTOR_SYSTEM_PROMPT,
    CLIP_SELECTOR_USER_PROMPT,
    MISTRAL_MODEL,
    TRANSCRIPT_CHUNK_CHARS,
    TRANSCRIPT_CHUNK_OVERLAP_CHARS,
)
from .models import ClipCandidate, TranscriptSegment
from .utils import PipelineError

LOGGER = logging.getLogger(__name__)


def render_transcript(segments: Iterable[TranscriptSegment]) -> str:
    return "\n".join(f"[{s.start:.2f} - {s.end:.2f}] {s.text}" for s in segments)


def chunk_transcript(segments: list[TranscriptSegment]) -> list[list[TranscriptSegment]]:
    """Chunk at segment boundaries and overlap context so hooks are not lost."""
    chunks: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []
    chars = 0
    for segment in segments:
        size = len(segment.text) + 30
        if current and chars + size > TRANSCRIPT_CHUNK_CHARS:
            chunks.append(current)
            overlap: list[TranscriptSegment] = []
            overlap_chars = 0
            for old in reversed(current):
                overlap.insert(0, old)
                overlap_chars += len(old.text) + 30
                if overlap_chars >= TRANSCRIPT_CHUNK_OVERLAP_CHARS:
                    break
            current, chars = overlap, overlap_chars
        current.append(segment)
        chars += size
    if current:
        chunks.append(current)
    return chunks


def _extract_json(text: str) -> dict[str, object]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PipelineError(f"Mistral model returned malformed JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PipelineError("Mistral model response JSON must be an object.")
    return parsed


def validate_candidates(
    payload: dict[str, object], *, min_duration: float, max_duration: float
) -> list[ClipCandidate]:
    """Validate strict candidate objects while retaining valid peers.

    Models occasionally round a computed duration or slightly overrun a title.
    Duration is derived from the authoritative start/end timestamps and titles
    are safely shortened; malformed or unusable candidates are discarded
    without throwing away the rest of a successful model response.
    """
    raw = payload.get("candidates")
    if not isinstance(raw, list) or not raw:
        raise PipelineError("Mistral model response must include a non-empty candidates array.")
    candidates: list[ClipCandidate] = []
    rejected: list[str] = []
    fields = {"start", "end", "duration", "rank", "score", "reason", "viral_title", "alt_titles"}
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or set(item) != fields:
            rejected.append(f"#{index}: schema")
            continue
        if not isinstance(item["alt_titles"], list) or len(item["alt_titles"]) != 2:
            rejected.append(f"#{index}: alt_titles")
            continue
        try:
            start, end = float(item["start"]), float(item["end"])
            supplied_duration = float(item["duration"])
            rank, score = int(item["rank"]), float(item["score"])
        except (TypeError, ValueError) as exc:
            rejected.append(f"#{index}: types ({exc})")
            continue
        duration = end - start
        if abs(duration - supplied_duration) > 1.0:
            rejected.append(f"#{index}: duration disagrees with timestamps")
            continue
        title = str(item["viral_title"]).strip()
        if len(title) > 60:
            title = title[:60].rsplit(" ", 1)[0].rstrip(" ,.!?-") or title[:60]
        candidate = ClipCandidate(
            start=start, end=end, duration=duration, rank=rank, score=score,
            reason=str(item["reason"]).strip(), viral_title=title,
            alt_titles=[str(value).strip() for value in item["alt_titles"]],
        )
        if (
            candidate.start < 0 or candidate.end <= candidate.start
            or not min_duration - 0.25 <= candidate.duration <= max_duration + 0.25
            or not 0 <= candidate.score <= 100 or candidate.rank < 1
            or not candidate.reason or not candidate.viral_title or len(candidate.viral_title) > 60
            or len(candidate.alt_titles) != 2
        ):
            rejected.append(f"#{index}: duration, score, or text constraints")
            continue
        candidates.append(candidate)
    if rejected:
        LOGGER.warning("Discarded %d invalid candidate(s): %s", len(rejected), "; ".join(rejected))
    if not candidates:
        raise PipelineError("No valid candidates remained after validation: " + "; ".join(rejected))
    return candidates


def select_clips(
    transcript: list[TranscriptSegment], *, min_duration: float, max_duration: float
) -> list[ClipCandidate]:
    """Call Mistral once per transcript chunk, retrying malformed output once."""
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise PipelineError("MISTRAL_API_KEY is not set. Create one before clip selection.")
    try:
        from mistralai.client import Mistral
    except ImportError as exc:
        raise PipelineError("Install requirements.txt to enable Mistral clip selection.") from exc

    client = Mistral(api_key=api_key)
    all_candidates: list[ClipCandidate] = []
    system = CLIP_SELECTOR_SYSTEM_PROMPT.format(min_duration=min_duration, max_duration=max_duration)
    for chunk in chunk_transcript(transcript):
        user = CLIP_SELECTOR_USER_PROMPT.format(transcript=render_transcript(chunk))
        last_error: PipelineError | None = None
        for attempt in range(2):
            try:
                completion = client.chat.complete(
                    model=MISTRAL_MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user + (
                            "\nReturn JSON only. Calculate duration exactly as end minus start, "
                            "and keep viral_title under 60 characters."
                            if attempt else ""
                        )},
                    ],
                    temperature=0.3,
                    top_p=0.95,
                    max_tokens=4000,
                )
                response = completion.choices[0].message.content
                if not isinstance(response, str):
                    raise PipelineError("Mistral returned a non-text completion.")
            except Exception as exc:
                if isinstance(exc, PipelineError):
                    raise
                raise PipelineError(f"Mistral clip selection request failed: {exc}") from exc
            try:
                all_candidates.extend(validate_candidates(_extract_json(response), min_duration=min_duration, max_duration=max_duration))
                break
            except PipelineError as exc:
                last_error = exc
        else:
            raise PipelineError(f"Mistral model failed validation after one retry: {last_error}")

    # De-duplicate overlap candidates and retain only non-overlapping highest-scoring clips.
    accepted: list[ClipCandidate] = []
    for candidate in sorted(all_candidates, key=lambda c: (-c.score, c.start)):
        if not any(candidate.start < kept.end and candidate.end > kept.start for kept in accepted):
            accepted.append(candidate)
    accepted.sort(key=lambda c: -c.score)
    return [
        ClipCandidate(**{**candidate.to_dict(), "rank": index})
        for index, candidate in enumerate(accepted, start=1)
    ]
