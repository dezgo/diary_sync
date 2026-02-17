"""Fetch and format YouTube auto-generated transcripts."""

import json
import os
import re
import logging
import urllib.request
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


def _get_external_ip() -> str | None:
    """Get our current external IP address."""
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=5) as resp:
            return resp.read().decode().strip()
    except Exception:
        return None


def is_in_cooldown() -> bool:
    """Check if we're in cooldown for our current IP.

    Only blocks transcript fetches if the current external IP matches
    the one that was blocked. Different IP (e.g. VPN) is fine.
    """
    try:
        with open(_STATE_PATH, "r") as f:
            state = json.load(f)
        blocked = state.get("ip_block")
        if not blocked:
            return False

        until = datetime.fromisoformat(blocked["until"])
        if datetime.now() >= until:
            # Cooldown expired
            clear_cooldown()
            return False

        # Check if we're on a different IP now
        current_ip = _get_external_ip()
        blocked_ip = blocked.get("ip")
        if current_ip and blocked_ip and current_ip != blocked_ip:
            log.info(
                f"Current IP ({current_ip}) differs from blocked IP "
                f"({blocked_ip}) — transcript fetches OK"
            )
            return False

        remaining = until - datetime.now()
        hours = remaining.total_seconds() / 3600
        log.warning(
            f"IP {blocked_ip} blocked by YouTube — cooldown until "
            f"{blocked['until'][:16]} ({hours:.1f}h remaining)"
        )
        return True

    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return False


def _set_cooldown():
    """Record an IP block cooldown in state.json, tagged with the blocked IP."""
    until = datetime.now() + timedelta(hours=BLOCK_COOLDOWN_HOURS)
    current_ip = _get_external_ip()
    try:
        with open(_STATE_PATH, "r") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {"processed_videos": {}}
    state["ip_block"] = {
        "ip": current_ip,
        "until": until.isoformat(),
        "since": datetime.now().isoformat(),
    }
    with open(_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)
    log.warning(
        f"IP {current_ip} blocked — cooldown set for {BLOCK_COOLDOWN_HOURS}h "
        f"(until {until.isoformat()[:16]})"
    )


def clear_cooldown():
    """Remove the cooldown marker from state.json."""
    try:
        with open(_STATE_PATH, "r") as f:
            state = json.load(f)
        changed = False
        # Clean up old format
        if "blocked_until" in state:
            del state["blocked_until"]
            changed = True
        if "ip_block" in state:
            del state["ip_block"]
            changed = True
        if changed:
            with open(_STATE_PATH, "w") as f:
                json.dump(state, f, indent=2, default=str)
            log.info("IP block cooldown cleared")
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def fetch_transcript(video_id: str, lang: str = "en") -> list | None | str:
    """Fetch auto-generated transcript segments for a video.

    Returns a list of FetchedTranscriptSnippet objects (with .text, .start,
    .duration attributes), None if captions aren't available yet, or the
    string "BLOCKED" if YouTube is blocking requests from this IP.
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
        if _is_ip_block(e):
            log.error(f"IP blocked fetching {video_id}")
            _set_cooldown()
            return "BLOCKED"
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
