"""Caption API and local Whisper transcript acquisition."""

from __future__ import annotations

import logging
from pathlib import Path

from .config import MIN_CAPTION_COVERAGE
from .models import TranscriptSegment
from .utils import PipelineError

LOGGER = logging.getLogger(__name__)


def fetch_youtube_transcript(video_id: str) -> list[TranscriptSegment]:
    """Fetch manually created or auto-generated YouTube captions."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id)
        raw_items = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else fetched
    except Exception as exc:
        raise PipelineError(f"YouTube captions unavailable: {exc}") from exc
    segments = [
        TranscriptSegment(
            start=float(item["start"]),
            end=float(item["start"]) + float(item.get("duration", 0.0)),
            text=str(item.get("text", "")).replace("\n", " ").strip(),
        )
        for item in raw_items
        if str(item.get("text", "")).strip()
    ]
    if not segments:
        raise PipelineError("YouTube returned an empty caption transcript.")
    return segments


def transcript_is_low_quality(segments: list[TranscriptSegment], duration: float | None) -> bool:
    """Reject very sparse captions while retaining normal short-form videos."""
    if len(segments) < 2 or sum(len(s.text) for s in segments) < 40:
        return True
    if duration and duration > 120:
        covered = sum(max(0.0, s.end - s.start) for s in segments)
        return covered / duration < MIN_CAPTION_COVERAGE
    return False


def transcribe_with_whisper(
    audio_path: Path, *, model_size: str = "small", device: str = "cuda"
) -> list[TranscriptSegment]:
    """Transcribe audio sequentially using GPU int8-float16 where possible."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise PipelineError("Install requirements.txt to enable Whisper fallback.") from exc

    compute_type = "int8_float16" if device == "cuda" else "int8"
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        segments, _info = model.transcribe(
            str(audio_path), word_timestamps=True, vad_filter=True, beam_size=5
        )
        result: list[TranscriptSegment] = []
        for segment in segments:
            # Word timestamps are used as granular caption segments when present.
            words = getattr(segment, "words", None) or []
            if words:
                result.extend(
                    TranscriptSegment(float(word.start), float(word.end), word.word.strip())
                    for word in words
                    if word.start is not None and word.end is not None and word.word.strip()
                )
            elif segment.text.strip():
                result.append(TranscriptSegment(float(segment.start), float(segment.end), segment.text.strip()))
        if not result:
            raise PipelineError("Whisper completed but returned no speech segments.")
        return result
    except Exception as exc:
        if device == "cuda":
            LOGGER.warning("GPU Whisper failed (%s); retrying sequentially on CPU.", exc)
            return transcribe_with_whisper(audio_path, model_size=model_size, device="cpu")
        if isinstance(exc, PipelineError):
            raise
        raise PipelineError(f"Whisper transcription failed: {exc}") from exc
