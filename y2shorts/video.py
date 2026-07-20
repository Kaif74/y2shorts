"""yt-dlp download and FFmpeg video transformations."""

from __future__ import annotations

import json
from pathlib import Path

from .config import MAX_VIDEO_HEIGHT
from .utils import PipelineError, run_command


def get_video_duration(url: str) -> float | None:
    """Read source metadata without downloading video."""
    completed = run_command(["yt-dlp", "--no-download", "--print", "%(duration)s", url], description="Video metadata lookup")
    try:
        return float(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def download_audio(url: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    template = str(destination / "audio.%(ext)s")
    run_command(["yt-dlp", "-f", "bestaudio/best", "-x", "--audio-format", "m4a", "-o", template, url], description="Audio download")
    matches = sorted(destination.glob("audio.*"))
    if not matches:
        raise PipelineError("yt-dlp reported success but audio file was not created.")
    return matches[0]


def download_video(url: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    template = str(destination / "source.%(ext)s")
    format_spec = f"bestvideo[height<={MAX_VIDEO_HEIGHT}]+bestaudio/best[height<={MAX_VIDEO_HEIGHT}]"
    run_command(["yt-dlp", "-f", format_spec, "--merge-output-format", "mp4", "-o", template, url], description="Video download")
    matches = sorted(destination.glob("source.*"))
    if not matches:
        raise PipelineError("yt-dlp reported success but source video was not created.")
    return matches[0]


def cut_clip(input_path: Path, output_path: Path, *, start: float, end: float) -> None:
    """Frame-accurate cut; re-encoding avoids keyframe-boundary surprises."""
    run_command([
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(input_path),
        "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-movflags", "+faststart", str(output_path),
    ], description=f"Clip extraction ({output_path.name})")


def reframe_to_vertical(input_path: Path, output_path: Path, mode: str = "center") -> None:
    """Crop to vertical 1080x1920; `tracked` is a seam reserved for v2."""
    if mode not in {"center", "tracked"}:
        raise PipelineError("crop mode must be 'center' or 'tracked'.")
    if mode == "tracked":
        # The call shape stays stable until a MediaPipe crop calculator is added.
        print("Tracked crop is not implemented yet; using center crop.")
    filter_graph = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    run_command([
        "ffmpeg", "-y", "-i", str(input_path), "-vf", filter_graph,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy",
        "-movflags", "+faststart", str(output_path),
    ], description=f"Vertical reframe ({output_path.name})")
