"""ASS subtitle generation and caption burn-in."""

from __future__ import annotations

from pathlib import Path

from .config import CAPTION_STYLE
from .models import TranscriptSegment
from .utils import ffmpeg_filter_path, run_command


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, rest = divmod(centiseconds, 360_000)
    minutes, rest = divmod(rest, 6_000)
    secs, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_escape(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def make_ass_subtitles(segments: list[TranscriptSegment], *, clip_start: float, clip_end: float, output_path: Path) -> None:
    """Write clip-relative subtitles, grouping short words into readable phrases."""
    relevant = [s for s in segments if s.end > clip_start and s.start < clip_end and s.text.strip()]
    grouped: list[tuple[float, float, str]] = []
    words: list[str] = []
    group_start: float | None = None
    group_end = 0.0
    for segment in relevant:
        start, end = max(segment.start, clip_start), min(segment.end, clip_end)
        if group_start is None:
            group_start = start
        words.append(segment.text)
        group_end = end
        if len(" ".join(words)) >= 38 or len(words) >= 7 or segment.text.rstrip().endswith((".", "!", "?")):
            grouped.append((group_start - clip_start, group_end - clip_start, " ".join(words)))
            words, group_start = [], None
    if words and group_start is not None:
        grouped.append((group_start - clip_start, group_end - clip_start, " ".join(words)))

    style = CAPTION_STYLE
    header = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        f"Style: Default,{style['font_name']},{style['font_size']},{style['primary_colour']},{style['highlight_colour']},{style['outline_colour']},{style['back_colour']},{style['bold']},0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},{style['alignment']},80,80,{style['margin_v']},1",
        "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ])
    lines = [header]
    for start, end, text in grouped:
        if end > start:
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{_ass_escape(text)}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def burn_captions(input_path: Path, ass_path: Path, output_path: Path) -> None:
    subtitle_filter = f"subtitles=filename='{ffmpeg_filter_path(ass_path)}'"
    run_command([
        "ffmpeg", "-y", "-i", str(input_path), "-vf", subtitle_filter,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy",
        "-movflags", "+faststart", str(output_path),
    ], description=f"Caption burn-in ({output_path.name})")
