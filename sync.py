#!/usr/bin/env python
"""Diary YouTube Sync — syncs YouTube video links and auto-generated
transcripts into Obsidian diary notes."""

import os
import re
import sys
import json
import time
import logging
from datetime import date, timedelta
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

import yaml

from youtube_client import get_authenticated_service, get_recent_uploads
from transcript_fetcher import fetch_transcript, format_transcript
from diary_finder import find_diary_note, find_all_diary_notes, parse_date_from_filename, is_diary_filename
from note_updater import analyze_note, update_note, fix_tag_if_needed

# Full month names for generating filenames
_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_TITLE_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_TITLE_DATE_RE = re.compile(r"(\d{1,2})\s+(\w+)\s+(\d{4})")


def parse_date_from_title(title: str) -> date | None:
    """Extract a date from a YouTube video title like '27 August 2025'."""
    m = _TITLE_DATE_RE.search(title)
    if not m:
        return None
    month = _TITLE_MONTHS.get(m.group(2).lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")
STATE_PATH = os.path.join(SCRIPT_DIR, "state.json")
CREDENTIALS_PATH = os.path.join(SCRIPT_DIR, "credentials.json")
TOKEN_PATH = os.path.join(SCRIPT_DIR, "token.json")
BACKUP_DIR = os.path.join(SCRIPT_DIR, "backups")

log = logging.getLogger("diary_sync")


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return {"processed_videos": {}}


def save_state(state: dict):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)


def setup_logging(config: dict):
    level = getattr(logging, config.get("log_level", "INFO"))
    log_path = os.path.join(SCRIPT_DIR, "sync.log")

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


def sync_videos(config: dict, state: dict) -> tuple[dict, set[date]]:
    """Main video sync: match YouTube uploads to diary notes.

    Returns (stats dict, set of upload dates).
    """
    processed = state["processed_videos"]

    # Authenticate
    if not os.path.exists(CREDENTIALS_PATH):
        log.error(
            f"OAuth credentials not found at {CREDENTIALS_PATH}. "
            "Download from Google Cloud Console (APIs > Credentials > OAuth 2.0 Client ID > Desktop app)."
        )
        sys.exit(1)

    youtube = get_authenticated_service(CREDENTIALS_PATH, TOKEN_PATH)
    log.info("YouTube API authenticated")

    # Fetch recent uploads — use a wide lookback for missing upload detection
    tz = ZoneInfo(config.get("timezone", "Australia/Sydney"))
    lookback = config.get("lookback_days", 30)
    since = date.today() - timedelta(days=lookback)

    # For missing upload detection, fetch ALL uploads since July 2025
    fetch_since = min(since, date(2025, 7, 1))
    videos = get_recent_uploads(youtube, config["channel_id"], fetch_since, tz)
    log.info(f"Found {len(videos)} uploads since {fetch_since}")

    # Collect all upload dates for missing upload check
    # Include both publish dates and title dates (they can differ for late-night uploads)
    upload_dates = set()
    for v in videos:
        upload_dates.add(v["published_date"])
        td = parse_date_from_title(v["title"])
        if td:
            upload_dates.add(td)

    # Only process videos within the normal lookback window for sync
    sync_videos_list = [v for v in videos if v["published_date"] >= since]
    log.info(f"Processing {len(sync_videos_list)} uploads within lookback window")

    stats = {
        "updated": 0,
        "skipped": 0,
        "no_note": 0,
        "no_transcript": 0,
        "errors": 0,
    }

    for video in sync_videos_list:
        vid = video["video_id"]
        vdate = video["published_date"]
        log.info(f"Processing: {video['title']} ({vid}) from {vdate}")

        # Skip if already fully processed
        if vid in processed and processed[vid].get("status") == "complete":
            log.debug("  Already processed, skipping")
            stats["skipped"] += 1
            continue

        # Find matching diary note by publish date, then fall back to title date
        # (late-night uploads can cross midnight, making the publish date +1 day)
        note_path = find_diary_note(
            config["vault_path"], config.get("diary_subdir", "Diary"), vdate
        )
        if not note_path:
            title_date = parse_date_from_title(video["title"])
            if title_date and title_date != vdate:
                log.info(f"  Publish date {vdate} missed, trying title date {title_date}")
                note_path = find_diary_note(
                    config["vault_path"], config.get("diary_subdir", "Diary"), title_date
                )
                if note_path:
                    vdate = title_date
        if not note_path:
            log.warning(f"  No diary note found for {vdate}")
            stats["no_note"] += 1
            continue

        log.info(f"  Matched: {os.path.basename(note_path)}")

        # Analyze note
        analysis = analyze_note(note_path)

        # If it already has a real video link + transcript, mark complete and skip
        if (
            analysis["has_video_link"]
            and not analysis["has_placeholder"]
            and analysis["has_blockquote_transcript"]
        ):
            log.info("  Note already has video link + transcript, marking complete")
            processed[vid] = {
                "status": "complete",
                "note": os.path.basename(note_path),
                "date": str(vdate),
            }
            stats["skipped"] += 1
            continue

        # Fetch transcript (with rate limit delay to avoid YouTube IP bans)
        transcript_lang = config.get("transcript_lang", "en")
        time.sleep(2)
        segments = fetch_transcript(vid, transcript_lang)

        if segments is None:
            log.warning(f"  Transcript not available yet for {vid}")
            processed[vid] = {
                "status": "no_transcript",
                "note": os.path.basename(note_path),
                "date": str(vdate),
            }
            stats["no_transcript"] += 1
            # Even without transcript, if it's a placeholder, we can still fix the URL
            if analysis["has_placeholder"]:
                try:
                    from note_updater import update_note as _update

                    # Update with empty transcript — will just fix the URL
                    _update(note_path, video["url"], "", analysis, BACKUP_DIR)
                    log.info("  Fixed placeholder URL (transcript pending)")
                except Exception as e:
                    log.error(f"  Failed to fix placeholder: {e}", exc_info=True)
            continue

        transcript_text = format_transcript(segments)
        if not transcript_text.strip():
            log.warning(f"  Transcript was empty after formatting for {vid}")
            stats["no_transcript"] += 1
            continue

        # Update the note
        try:
            modified = update_note(
                note_path, video["url"], transcript_text, analysis, BACKUP_DIR
            )
            if modified:
                log.info("  Updated note successfully")
                stats["updated"] += 1
            else:
                log.info("  No changes needed")
                stats["skipped"] += 1

            processed[vid] = {
                "status": "complete",
                "note": os.path.basename(note_path),
                "date": str(vdate),
            }
        except Exception as e:
            log.error(f"  Failed to update note: {e}", exc_info=True)
            stats["errors"] += 1

    return stats, upload_dates


def audit_tags(config: dict):
    """Walk all diary notes and fix any tag/date mismatches."""
    log.info("Running tag audit...")
    notes = find_all_diary_notes(
        config["vault_path"], config.get("diary_subdir", "Diary")
    )

    fixed = 0
    ok = 0
    errors = 0

    for filepath, note_date in notes:
        try:
            was_fixed = fix_tag_if_needed(filepath, note_date.year, BACKUP_DIR)
            if was_fixed:
                fixed += 1
            else:
                ok += 1
        except Exception as e:
            log.error(
                f"  Error fixing tag in {os.path.basename(filepath)}: {e}",
                exc_info=True,
            )
            errors += 1

    log.info(f"Tag audit: {fixed} fixed, {ok} OK, {errors} errors")


def check_missing_uploads(config: dict, upload_dates: set[date]):
    """Find diary notes from July 2025 onward that have no matching YouTube upload.

    This helps detect videos that were recorded but never uploaded.
    """
    log.info("Checking for diary notes with no matching YouTube upload...")
    # Only check from July 2025 onward (when video diary started)
    video_start = date(2025, 7, 1)

    notes = find_all_diary_notes(
        config["vault_path"], config.get("diary_subdir", "Diary")
    )

    missing = []
    for filepath, note_date in notes:
        if note_date < video_start:
            continue
        if note_date > date.today():
            continue
        if note_date not in upload_dates:
            missing.append((note_date, os.path.basename(filepath)))

    missing.sort(key=lambda x: x[0])

    if missing:
        log.warning(f"Found {len(missing)} diary notes with no YouTube upload:")
        for note_date, filename in missing:
            log.warning(f"  {note_date} — {filename}")
    else:
        log.info("All diary notes (since July 2025) have matching YouTube uploads")


def create_today_note(config: dict):
    """Create today's diary note if it doesn't already exist."""
    vault_path = config["vault_path"]
    diary_subdir = config.get("diary_subdir", "Diary")
    today = date.today()

    # Check if a note already exists for today
    existing = find_diary_note(vault_path, diary_subdir, today)
    if existing:
        log.debug(f"Today's note already exists: {os.path.basename(existing)}")
        return

    # Build filename: "Dear Diary, it's Monday 16 February 2026.md"
    day_name = today.strftime("%A")
    month_name = _MONTH_NAMES[today.month]
    filename = f"Dear Diary, it's {day_name} {today.day} {month_name} {today.year}.md"

    # Put it in Diary/YYYY/
    year_dir = os.path.join(vault_path, diary_subdir, str(today.year))
    os.makedirs(year_dir, exist_ok=True)

    filepath = os.path.join(year_dir, filename)
    tag = f"Diary-{today.year}"

    content = f"""---

tags:
  - {tag}

---
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    log.info(f"Created today's diary note: {filename}")


def main():
    config = load_config()
    setup_logging(config)

    log.info("=== Diary YouTube Sync starting ===")

    # Validate vault path
    vault_path = config.get("vault_path", "")
    if not os.path.isdir(vault_path):
        log.error(f"Vault path not found: {vault_path}")
        sys.exit(2)

    # Create today's note if it doesn't exist yet
    try:
        create_today_note(config)
    except Exception as e:
        log.error(f"Failed to create today's note: {e}", exc_info=True)

    state = load_state()
    upload_dates = set()

    try:
        stats, upload_dates = sync_videos(config, state)
        log.info(
            f"Video sync: {stats['updated']} updated, {stats['skipped']} skipped, "
            f"{stats['no_note']} no note, {stats['no_transcript']} no transcript, "
            f"{stats['errors']} errors"
        )
    except Exception as e:
        log.error(f"Video sync failed: {e}", exc_info=True)
    finally:
        save_state(state)

    # Tag audit pass
    try:
        audit_tags(config)
    except Exception as e:
        log.error(f"Tag audit failed: {e}", exc_info=True)

    # Missing upload check
    if upload_dates:
        try:
            check_missing_uploads(config, upload_dates)
        except Exception as e:
            log.error(f"Missing upload check failed: {e}", exc_info=True)

    log.info("=== Diary YouTube Sync complete ===")


if __name__ == "__main__":
    main()
