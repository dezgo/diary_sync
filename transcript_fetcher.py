"""Fetch and format YouTube auto-generated transcripts."""

import json
import os
import re
import time
import logging
from datetime import datetime, timedelta

from youtube_transcript_api import YouTubeTranscriptApi

log = logging.getLogger(__name__)

# Shared API instance
_api = YouTubeTranscriptApi()

# Cooldown: skip all transcript fetches for this long after an IP block
BLOCK_COOLDOWN_HOURS = 24

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_STATE_PATH = os.path.join(_SCRIPT_DIR, "state.json")


def _is_ip_block(error: Exception) -> bool:
    """Check if an exception indicates YouTube IP blocking."""
    msg = str(error).lower()
    return "blocked" in msg or "blocking requests from your ip" in msg


def is_in_cooldown() -> bool:
    """Check if we're still in a cooldown period after a previous IP block."""
    try:
        with open(_STATE_PATH, "r") as f:
            state = json.load(f)
        blocked_until = state.get("blocked_until")
        if blocked_until:
            until = datetime.fromisoformat(blocked_until)
            if datetime.now() < until:
                remaining = until - datetime.now()
                hours = remaining.total_seconds() / 3600
                log.warning(
                    f"Transcript cooldown active — blocked until {blocked_until} "
                    f"({hours:.1f}h remaining). Skipping all transcript fetches."
                )
                return True
            # Cooldown has expired, clear it
            clear_cooldown()
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass
    return False


def _set_cooldown():
    """Record an IP block cooldown in state.json."""
    until = datetime.now() + timedelta(hours=BLOCK_COOLDOWN_HOURS)
    try:
        with open(_STATE_PATH, "r") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {"processed_videos": {}}
    state["blocked_until"] = until.isoformat()
    with open(_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)
    log.warning(f"IP block cooldown set until {until.isoformat()} ({BLOCK_COOLDOWN_HOURS}h)")


def clear_cooldown():
    """Remove the cooldown marker from state.json."""
    try:
        with open(_STATE_PATH, "r") as f:
            state = json.load(f)
        if "blocked_until" in state:
            del state["blocked_until"]
            with open(_STATE_PATH, "w") as f:
                json.dump(state, f, indent=2, default=str)
            log.info("IP block cooldown expired, resuming transcript fetches")
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def fetch_transcript(video_id: str, lang: str = "en",
                     max_retries: int = 2) -> list | None | str:
    """Fetch auto-generated transcript segments for a video.

    Returns a list of FetchedTranscriptSnippet objects (with .text, .start,
    .duration attributes), None if captions aren't available yet, or the
    string "BLOCKED" if YouTube is blocking requests from this IP.
    """
    for attempt in range(max_retries + 1):
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
            if _is_ip_block(e):
                if attempt < max_retries:
                    wait = (2 ** attempt) * 30  # 30s, 60s
                    log.warning(
                        f"IP blocked fetching {video_id}, "
                        f"backing off {wait}s (attempt {attempt + 1}/{max_retries + 1})"
                    )
                    time.sleep(wait)
                else:
                    log.error(f"IP still blocked after {max_retries + 1} attempts for {video_id}")
                    _set_cooldown()
                    return "BLOCKED"
            else:
                log.warning(f"Could not fetch transcript for {video_id}: {e}")
                return None

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
