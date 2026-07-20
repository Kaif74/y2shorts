"""Small dependency-free utilities."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class PipelineError(RuntimeError):
    """An expected pipeline failure with a useful message for the CLI."""


def extract_video_id(url: str) -> str:
    """Extract an 11-character video id from ordinary YouTube URL forms."""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            video_id = parsed.path.strip("/").split("/")[1]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise PipelineError("Could not extract a valid YouTube video ID from the URL.")
    return video_id


def run_command(command: list[str], *, description: str) -> subprocess.CompletedProcess[str]:
    """Run a media command and expose useful stderr if it fails."""
    try:
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise PipelineError(
            f"{command[0]!r} was not found. Install it and add it to PATH."
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-2_000:]
        raise PipelineError(f"{description} failed (exit {completed.returncode}):\n{detail}")
    return completed


def ffmpeg_filter_path(path: Path) -> str:
    """Escape a Windows path for FFmpeg's subtitles=filename filter."""
    return str(path.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
