"""argparse interface for the local clipper."""

from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

from .pipeline import run_pipeline
from .utils import PipelineError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate vertical, captioned clips from a YouTube URL.")
    parser.add_argument("youtube_url", help="YouTube watch, short, youtu.be, embed, or live URL")
    parser.add_argument("--max-clips", type=int, default=5, help="Maximum candidates to render (default: 5)")
    parser.add_argument("--min-duration", type=float, default=15, help="Shortest allowed clip in seconds (default: 15)")
    parser.add_argument("--max-duration", type=float, default=60, help="Longest allowed clip in seconds (default: 60)")
    parser.add_argument("--crop-mode", choices=("center", "tracked"), default="center")
    parser.add_argument("--whisper-model", choices=("small", "base"), default="small")
    parser.add_argument("--force-whisper", action="store_true", help="Skip YouTube captions and always use Whisper")
    return parser


def main() -> None:
    # Load a local .env file before pipeline configuration is read. Environment
    # variables already set in PowerShell remain unchanged.
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args()
    try:
        run_pipeline(
            args.youtube_url, max_clips=args.max_clips, min_duration=args.min_duration,
            max_duration=args.max_duration, crop_mode=args.crop_mode,
            whisper_model=args.whisper_model, force_whisper=args.force_whisper,
        )
    except PipelineError as exc:
        logging.error("Pipeline stopped: %s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        logging.error("Cancelled.")
        sys.exit(130)
