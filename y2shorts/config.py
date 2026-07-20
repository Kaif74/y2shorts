"""Central configuration and prompt text; edit this file to tune output."""

from __future__ import annotations

from pathlib import Path

DOWNLOAD_DIR = Path("downloads")
OUTPUT_DIR = Path("output")
MAX_VIDEO_HEIGHT = 1080
MAX_LLM_TRANSCRIPT_CHARS = 48_000
# Conservative request sizing avoids provider token-per-minute limits on long
# caption tracks. The overlap preserves context at chunk boundaries.
TRANSCRIPT_CHUNK_CHARS = 16_000
TRANSCRIPT_CHUNK_OVERLAP_CHARS = 2_000
MIN_CAPTION_COVERAGE = 0.15
MISTRAL_MODEL = "mistral-small-2603"

# Values are supplied to FFmpeg's ASS force_style option.  Font selection is
# intentionally configurable because installed fonts differ between machines.
CAPTION_STYLE = {
    "font_name": "Arial",
    "font_size": 22,
    "alignment": 2,  # bottom-centre
    "margin_v": 240,
    "primary_colour": "&H00FFFFFF",  # AABBGGRR (white)
    "outline_colour": "&H00101010",
    "back_colour": "&H80000000",
    "outline": 3,
    "shadow": 1,
    "bold": -1,
    # Reserved for word highlighting when a word-level renderer is added.
    "highlight_colour": "&H0000D7FF",
}

CLIP_SELECTOR_SYSTEM_PROMPT = """You are an expert short-form video editor.
Choose the most compelling, self-contained portions of the supplied timestamped
transcript for YouTube Shorts/Reels/TikTok. A clip must have a strong hook in
its first 3 seconds and a complete thought or payoff, not a dangling fragment.
Prioritize surprising insight, story turns, emotional stakes, useful advice,
conflict, or a memorable payoff. Do not invent events or timestamps.

Return ONLY valid JSON: an object with a `candidates` array. Each candidate
must contain exactly these fields:
start (number, seconds), end (number, seconds), duration (number), rank
(integer, 1 is best), score (number 0-100), reason (string), viral_title
(string under 60 characters), alt_titles (array of exactly two strings).
Return 5-8 non-overlapping candidates, ranked best to worst. Every duration
must be between {min_duration} and {max_duration} seconds, and duration must
equal end minus start (within 0.5 seconds)."""

CLIP_SELECTOR_USER_PROMPT = """Select clips from this transcript. Times are
absolute seconds from the source video. Respect the clip constraints exactly.

TRANSCRIPT:
{transcript}
"""
