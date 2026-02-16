#!/usr/bin/env python
"""One-off script to fix placeholder [Video](https://a) links in diary notes.

Finds all diary notes since July 2025 with placeholder video links, matches
them to YouTube uploads by date, and replaces the placeholder URL with the
real YouTube link (plus transcript if the note doesn't already have one).
"""

import os
import re
import sys
import json
import time
import logging
from datetime import date
from zoneinfo import ZoneInfo

import yaml

from youtube_client import get_authenticated_service, get_recent_uploads
from transcript_fetcher import fetch_transcript, format_transcript
from diary_finder import find_all_diary_notes
from note_updater import analyze_note, update_note

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")
STATE_PATH = os.path.join(SCRIPT_DIR, "state.json")
CREDENTIALS_PATH = os.path.join(SCRIPT_DIR, "credentials.json")
TOKEN_PATH = os.path.join(SCRIPT_DIR, "token.json")
BACKUP_DIR = os.path.join(SCRIPT_DIR, "backups")

VIDEO_START = date(2025, 7, 1)

log = logging.getLogger("fix_placeholders")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    # --- Find placeholder notes ---
    log.info("Scanning for diary notes with placeholder video links...")
    notes = find_all_diary_notes(config["vault_path"], config.get("diary_subdir", "Diary"))

    placeholders = []  # (filepath, note_date)
    for filepath, note_date in notes:
        if note_date < VIDEO_START or note_date > date.today():
            continue
        analysis = analyze_note(filepath)
        if analysis["has_placeholder"]:
            placeholders.append((filepath, note_date))
            log.info(f"  Placeholder: {note_date}  {os.path.basename(filepath)}")

    if not placeholders:
        log.info("No placeholder notes found. Nothing to do.")
        return

    log.info(f"Found {len(placeholders)} placeholder notes")

    # --- Fetch YouTube uploads ---
    log.info("Authenticating with YouTube...")
    youtube = get_authenticated_service(CREDENTIALS_PATH, TOKEN_PATH)

    tz = ZoneInfo(config.get("timezone", "Australia/Sydney"))
    videos = get_recent_uploads(youtube, config["channel_id"], VIDEO_START, tz)
    log.info(f"Fetched {len(videos)} uploads since {VIDEO_START}")

    # Build date -> video lookup using the date from the video TITLE
    # (not publish date, which can be +1 day due to late-night uploads
    # crossing midnight in Sydney time)
    _MONTH_NAMES = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    _TITLE_DATE_RE = re.compile(r"(\d{1,2})\s+(\w+)\s+(\d{4})")

    title_date_to_video = {}
    for v in videos:
        m = _TITLE_DATE_RE.search(v["title"])
        if m:
            month = _MONTH_NAMES.get(m.group(2).lower())
            if month:
                try:
                    title_date = date(int(m.group(3)), month, int(m.group(1)))
                    if title_date not in title_date_to_video:
                        title_date_to_video[title_date] = v
                except ValueError:
                    pass

    # --- Load state ---
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            state = json.load(f)
    else:
        state = {"processed_videos": {}}
    processed = state["processed_videos"]

    # --- Fix each placeholder ---
    stats = {"fixed": 0, "no_video": 0, "no_transcript": 0, "errors": 0}

    for filepath, note_date in placeholders:
        basename = os.path.basename(filepath)
        video = title_date_to_video.get(note_date)

        if not video:
            log.warning(f"  No YouTube upload for {note_date} — skipping {basename}")
            stats["no_video"] += 1
            continue

        vid = video["video_id"]
        url = video["url"]
        log.info(f"  Fixing {note_date}: {basename} -> {url}")

        # Re-analyze (fresh read)
        analysis = analyze_note(filepath)

        # Fetch transcript
        time.sleep(2)  # rate limit
        segments = fetch_transcript(vid, config.get("transcript_lang", "en"))

        transcript_text = ""
        if segments:
            transcript_text = format_transcript(segments)

        if not transcript_text.strip():
            log.warning(f"  No transcript available for {vid}")
            stats["no_transcript"] += 1
            # Still fix the placeholder URL even without transcript

        try:
            modified = update_note(filepath, url, transcript_text, analysis, BACKUP_DIR)
            if modified:
                log.info(f"  Updated {basename}")
                stats["fixed"] += 1
            else:
                log.info(f"  No changes needed for {basename}")
        except Exception as e:
            log.error(f"  Failed to update {basename}: {e}", exc_info=True)
            stats["errors"] += 1
            continue

        # Update state
        processed[vid] = {
            "status": "complete" if transcript_text.strip() else "no_transcript",
            "note": basename,
            "date": str(note_date),
        }

    # --- Save state ---
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)

    log.info(
        f"Done! Fixed: {stats['fixed']}, No video: {stats['no_video']}, "
        f"No transcript: {stats['no_transcript']}, Errors: {stats['errors']}"
    )


if __name__ == "__main__":
    main()
