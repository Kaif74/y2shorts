"""Sequential end-to-end orchestration with optional progress reporting."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from .captions import burn_captions, make_ass_subtitles
from .config import DOWNLOAD_DIR, OUTPUT_DIR
from .llm import select_clips
from .models import ClipCandidate, TranscriptSegment
from .transcript import fetch_youtube_transcript, transcript_is_low_quality, transcribe_with_whisper
from .utils import PipelineError, extract_video_id
from .video import cut_clip, download_audio, download_video, get_video_duration, reframe_to_vertical

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[str, str, str], None]


def _emit(callback: ProgressCallback | None, stage: str, status: str, detail: str) -> None:
    """Report pipeline progress without allowing UI/reporting failures to stop clipping."""
    if callback:
        try:
            callback(stage, status, detail)
        except Exception:
            LOGGER.debug("Progress callback failed", exc_info=True)


def _write_rankings(output_dir: Path, candidates: list[ClipCandidate]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "rankings.json").write_text(
        json.dumps({"clips": [c.to_dict() for c in candidates]}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def acquire_transcript(
    url: str, video_id: str, *, force_whisper: bool, whisper_model: str,
    on_progress: ProgressCallback | None = None,
) -> list[TranscriptSegment]:
    _emit(on_progress, "fetch_transcript", "in_progress", "Looking for YouTube captions")
    duration = get_video_duration(url)
    if duration and duration > 7200:
        LOGGER.warning("Source is %.1f hours long; transcript will be chunked for Mistral.", duration / 3600)
    if not force_whisper:
        try:
            transcript = fetch_youtube_transcript(video_id)
            if not transcript_is_low_quality(transcript, duration):
                LOGGER.info("Transcript fetched from YouTube captions (%d segments).", len(transcript))
                _emit(on_progress, "fetch_transcript", "done", f"YouTube captions found ({len(transcript)} segments)")
                return transcript
            LOGGER.warning("YouTube captions look sparse; falling back to Whisper.")
        except PipelineError as exc:
            LOGGER.warning("Caption API unavailable: %s", exc)
    LOGGER.info("Downloading audio for Whisper fallback (model=%s, GPU preferred).", whisper_model)
    _emit(on_progress, "fetch_transcript", "in_progress", f"No usable captions; transcribing with Whisper {whisper_model}")
    audio = download_audio(url, DOWNLOAD_DIR / video_id)
    transcript = transcribe_with_whisper(audio, model_size=whisper_model)
    LOGGER.info("Whisper transcript complete (%d timestamped segments).", len(transcript))
    _emit(on_progress, "fetch_transcript", "done", f"Whisper transcript ready ({len(transcript)} segments)")
    return transcript


def run_pipeline(
    url: str, *, max_clips: int = 5, min_duration: float = 15, max_duration: float = 60,
    crop_mode: str = "center", whisper_model: str = "small", force_whisper: bool = False,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Run every stage in sequence and return the source video's output directory."""
    if max_clips < 1 or min_duration <= 0 or max_duration < min_duration:
        raise PipelineError("Check --max-clips and duration limits.")
    video_id = extract_video_id(url)
    output_dir = OUTPUT_DIR / video_id
    output_dir.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Video ID: %s", video_id)
    transcript = acquire_transcript(
        url, video_id, force_whisper=force_whisper, whisper_model=whisper_model,
        on_progress=on_progress,
    )

    LOGGER.info("Sending timestamped transcript to Mistral for clip selection.")
    _emit(on_progress, "llm_ranking", "in_progress", "Finding the strongest short-form moments")
    candidates = select_clips(transcript, min_duration=min_duration, max_duration=max_duration)[:max_clips]
    if not candidates:
        raise PipelineError("Mistral model produced no non-overlapping clip candidates.")
    _write_rankings(output_dir, candidates)
    _emit(on_progress, "llm_ranking", "done", f"{len(candidates)} ranked candidates found")

    LOGGER.info("Mistral returned %d candidates; downloading source video once.", len(candidates))
    _emit(on_progress, "download_video", "in_progress", "Downloading source video once")
    source = download_video(url, DOWNLOAD_DIR / video_id)
    _emit(on_progress, "download_video", "done", "Source video ready")

    for index, candidate in enumerate(candidates, start=1):
        filename = f"clip_{index:02d}_rank{candidate.rank}_score{round(candidate.score):02d}.mp4"
        final_path = output_dir / filename
        work_dir = output_dir / ".work"
        work_dir.mkdir(exist_ok=True)
        raw = work_dir / f"{index:02d}_raw.mp4"
        vertical = work_dir / f"{index:02d}_vertical.mp4"
        subtitles = work_dir / f"{index:02d}.ass"
        LOGGER.info("Clipping %d/%d: %.1fs-%.1fs (%s)", index, len(candidates), candidate.start, candidate.end, candidate.viral_title)
        _emit(on_progress, "clipping", "in_progress", f"Clip {index} of {len(candidates)}: extracting moment")
        try:
            cut_clip(source, raw, start=candidate.start, end=candidate.end)
            _emit(on_progress, "reframing", "in_progress", f"Clip {index} of {len(candidates)}: framing for vertical")
            reframe_to_vertical(raw, vertical, mode=crop_mode)
            _emit(on_progress, "captioning", "in_progress", f"Clip {index} of {len(candidates)}: burning captions")
            make_ass_subtitles(transcript, clip_start=candidate.start, clip_end=candidate.end, output_path=subtitles)
            burn_captions(vertical, subtitles, final_path)
            _emit(on_progress, "captioning", "done", f"Clip {index} of {len(candidates)} complete")
        except PipelineError as exc:
            LOGGER.error("Clip %d failed; continuing: %s", index, exc)
            _emit(on_progress, "clipping", "error", f"Clip {index} skipped: {exc}")
        finally:
            for temporary in (raw, vertical, subtitles):
                temporary.unlink(missing_ok=True)
    work_dir = output_dir / ".work"
    if work_dir.exists() and not any(work_dir.iterdir()):
        work_dir.rmdir()
    LOGGER.info("Finished. Review clips and rankings at %s", output_dir.resolve())
    _emit(on_progress, "done", "done", "Processing complete")
    return output_dir
