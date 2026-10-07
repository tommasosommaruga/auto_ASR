"""Match transcript lines to speaker time spans."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimedText:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SpeakerSpan:
    start: float
    end: float
    speaker: int


def assign_speakers(segments: list[TimedText], spans: list[SpeakerSpan]) -> list[dict]:
    """Give each text segment the speaker who occupies the most of its time.

    When a segment does not overlap a speaker span, the nearest span is used
    so a short gap still stays with the person who was just talking.
    """
    turns = []
    for segment in segments:
        text = " ".join(segment.text.split())
        if not text:
            continue
        turns.append(
            {
                "speaker": _speaker_for(segment, spans),
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "text": text,
            }
        )
    return _merge_turns(turns)


def _speaker_for(segment: TimedText, spans: list[SpeakerSpan]) -> int:
    if not spans:
        return 0
    best_speaker = None
    best_overlap = 0.0
    for span in spans:
        amount = _overlap(segment.start, segment.end, span.start, span.end)
        if amount > best_overlap:
            best_overlap = amount
            best_speaker = span.speaker
    if best_speaker is not None:
        return best_speaker
    midpoint = (segment.start + segment.end) / 2
    nearest = min(
        spans,
        key=lambda span: min(abs(midpoint - span.start), abs(midpoint - span.end)),
    )
    return nearest.speaker


def _overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def _merge_turns(turns: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for turn in turns:
        previous = merged[-1] if merged else None
        if previous is not None and previous["speaker"] == turn["speaker"]:
            previous["end"] = turn["end"]
            previous["text"] = f"{previous['text']} {turn['text']}".strip()
            continue
        merged.append(dict(turn))
    return merged
