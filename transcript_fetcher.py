"""Fetch and format YouTube auto-generated transcripts."""

import re
import logging

from youtube_transcript_api import YouTubeTranscriptApi

log = logging.getLogger(__name__)

# Shared API instance
_api = YouTubeTranscriptApi()


def fetch_transcript(video_id: str, lang: str = "en") -> list | None:
    """Fetch auto-generated transcript segments for a video.

    Returns a list of FetchedTranscriptSnippet objects (with .text, .start,
    .duration attributes), or None if captions aren't available yet.
    """
    try:
        transcript_list = _api.list(video_id)

        # Prefer auto-generated in the requested language
        try:
            transcript = transcript_list.find_generated_transcript([lang])
        except Exception:
            try:
                transcript = transcript_list.find_generated_transcript(["en"])
            except Exception:
                try:
                    transcript = transcript_list.find_manually_created_transcript(
                        [lang, "en"]
                    )
                except Exception:
                    log.warning(f"No transcript found for {video_id}")
                    return None

        fetched = transcript.fetch()
        log.info(f"Fetched {len(fetched)} transcript segments for {video_id}")
        return list(fetched)

    except Exception as e:
        log.warning(f"Could not fetch transcript for {video_id}: {e}")
        return None


def format_transcript(segments: list, pause_threshold: float = 3.0) -> str:
    """Format raw transcript segments into clean prose paragraphs.

    Breaks into new paragraphs when there's a pause longer than
    pause_threshold seconds between segments.
    """
    if not segments:
        return ""

    paragraphs = []
    current_paragraph = []

    for i, seg in enumerate(segments):
        text = seg.text.strip()
        if not text:
            continue

        # Skip noise markers like [Music], [Applause], etc.
        if re.fullmatch(r"\[.*\]", text):
            continue

        # Remove inline noise markers
        text = re.sub(r"\[.*?\]", "", text).strip()
        if not text:
            continue

        current_paragraph.append(text)

        # Check for pause-based paragraph break
        if i < len(segments) - 1:
            seg_end = seg.start + seg.duration
            next_start = segments[i + 1].start
            gap = next_start - seg_end
            if gap > pause_threshold:
                paragraphs.append(_join_paragraph(current_paragraph))
                current_paragraph = []

    # Don't forget the last paragraph
    if current_paragraph:
        paragraphs.append(_join_paragraph(current_paragraph))

    return "\n\n".join(paragraphs)


def _join_paragraph(parts: list[str]) -> str:
    """Join segment texts into a single clean paragraph."""
    text = " ".join(parts)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    # Capitalize first letter
    if text:
        text = text[0].upper() + text[1:]
    return text
