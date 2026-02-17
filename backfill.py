#!/usr/bin/env python
"""Backfill transcripts in small batches to avoid YouTube rate limiting.

Designed to run every 6 hours via Task Scheduler. Processes up to
BATCH_SIZE videos per run with delays between each fetch.
"""

import os
import sys
import json
import time
import random
import logging
from datetime import date, timedelta
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

import yaml

from youtube_client import get_authenticated_service, get_recent_uploads
from transcript_fetcher import fetch_transcript, format_transcript, is_in_cooldown
from diary_finder import find_diary_note
from note_updater import analyze_note, update_note
from sync import parse_date_from_title

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")
STATE_PATH = os.path.join(SCRIPT_DIR, "state.json")
CREDENTIALS_PATH = os.path.join(SCRIPT_DIR, "credentials.json")
TOKEN_PATH = os.path.join(SCRIPT_DIR, "token.json")
BACKUP_DIR = os.path.join(SCRIPT_DIR, "backups")

BATCH_SIZE = 5
BASE_DELAY = 10   # seconds between transcript fetches
DELAY_JITTER = 5  # randomised +/- seconds to avoid bot patterns

log = logging.getLogger("diary_sync")


def setup_logging():
    log_path = os.path.join(SCRIPT_DIR, "sync.log")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return {"processed_videos": {}}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)


def main():
    setup_logging()
    config = load_config()
    state = load_state()
    processed = state["processed_videos"]

    log.info(f"=== Backfill starting (batch of {BATCH_SIZE}) ===")

    if is_in_cooldown():
        log.info("=== Backfill skipped (IP cooldown) ===")
        return

    # Authenticate
    youtube = get_authenticated_service(CREDENTIALS_PATH, TOKEN_PATH)

    # Fetch all uploads since July 2025
    tz = ZoneInfo(config.get("timezone", "Australia/Sydney"))
    since = date(2025, 7, 1)
    videos = get_recent_uploads(youtube, config["channel_id"], since, tz)
    log.info(f"Found {len(videos)} total uploads since {since}")

    # Filter to videos not yet fully processed
    todo = []
    for video in videos:
        vid = video["video_id"]
        if vid in processed and processed[vid].get("status") == "complete":
            continue
        todo.append(video)

    log.info(f"{len(todo)} videos still need processing")

    if not todo:
        log.info("Nothing to backfill — all videos processed!")
        log.info("=== Backfill complete ===")
        return

    # Process up to BATCH_SIZE (only counting ones that actually hit YouTube)
    updated = 0
    skipped = 0
    failed = 0
    no_note = 0
    fetched = 0

    for video in todo:
        vid = video["video_id"]
        vdate = video["published_date"]
        log.info(f"Backfill: {video['title']} ({vid}) from {vdate}")

        # Find matching diary note — prefer title date over publish date
        title_date = parse_date_from_title(video["title"])
        if title_date and title_date != vdate:
            note_path = find_diary_note(
                config["vault_path"], config.get("diary_subdir", "Diary"), title_date
            )
            if note_path:
                vdate = title_date
            else:
                note_path = find_diary_note(
                    config["vault_path"], config.get("diary_subdir", "Diary"), vdate
                )
        else:
            note_path = find_diary_note(
                config["vault_path"], config.get("diary_subdir", "Diary"), vdate
            )
        if not note_path:
            log.warning(f"  No diary note found for {vdate}")
            no_note += 1
            continue

        log.info(f"  Matched: {os.path.basename(note_path)}")

        # Check if note already has transcript
        analysis = analyze_note(note_path)
        if (
            analysis["has_video_link"]
            and not analysis["has_placeholder"]
            and analysis["has_blockquote_transcript"]
        ):
            log.info("  Already has transcript, marking complete")
            processed[vid] = {
                "status": "complete",
                "note": os.path.basename(note_path),
                "date": str(vdate),
            }
            skipped += 1
            continue

        # Check batch limit (only count actual YouTube fetches)
        if fetched >= BATCH_SIZE:
            log.info(f"  Batch limit reached ({BATCH_SIZE} fetches), stopping")
            break

        # Rate limit delay with jitter to avoid bot detection
        delay = BASE_DELAY + random.uniform(-DELAY_JITTER, DELAY_JITTER)
        log.debug(f"  Rate limit delay: {delay:.1f}s")
        time.sleep(delay)
        fetched += 1

        # Fetch transcript (returns "BLOCKED" if IP is banned)
        segments = fetch_transcript(vid, config.get("transcript_lang", "en"))
        if segments == "BLOCKED":
            log.error("IP blocked by YouTube, aborting remaining batch")
            failed += 1
            break
        if segments is None:
            log.warning(f"  Transcript not available for {vid}")
            failed += 1
            # Don't save as no_transcript — leave it unprocessed for next batch
            continue

        transcript_text = format_transcript(segments)
        if not transcript_text.strip():
            log.warning(f"  Empty transcript for {vid}")
            failed += 1
            continue

        # Update the note
        try:
            modified = update_note(
                note_path, video["url"], transcript_text, analysis, BACKUP_DIR
            )
            if modified:
                log.info("  Updated note successfully")
                updated += 1
            else:
                log.info("  No changes needed")
                skipped += 1

            processed[vid] = {
                "status": "complete",
                "note": os.path.basename(note_path),
                "date": str(vdate),
            }
        except Exception as e:
            log.error(f"  Failed to update note: {e}", exc_info=True)
            failed += 1

    save_state(state)
    remaining = len(todo) - (updated + skipped + failed + no_note)
    log.info(
        f"Backfill batch: {updated} updated, {skipped} skipped, "
        f"{failed} failed, {no_note} no note, ~{remaining} remaining"
    )
    log.info("=== Backfill complete ===")


if __name__ == "__main__":
    main()
