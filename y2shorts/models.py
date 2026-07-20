"""Data objects shared between independent pipeline stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ClipCandidate:
    start: float
    end: float
    duration: float
    rank: int
    score: float
    reason: str
    viral_title: str
    alt_titles: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
