#!/usr/bin/env python
"""Diary YouTube Sync — syncs YouTube video links and auto-generated
transcripts into Obsidian diary notes."""

import argparse
import os
import re
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
from diary_finder import find_diary_note, find_all_diary_notes, parse_date_from_filename, is_diary_filename
from note_updater import analyze_note, update_note, fix_tag_if_needed, embed_photos
from summariser import generate_summary
from photo_finder import (
    find_selfie,
    find_photo_of_day,
    find_potd_in_drop_dir,
    prepare_for_embed,
    classify_embedded_photos,
    selfie_diary_date,
    _read_capture_time,
    _date_from_filename,
    _is_image,
)

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


def _gather_photos_for_note(
    config: dict,
    video: dict,
    vdate: date,
    analysis: dict,
) -> list[str]:
    """Locate selfie + photo-of-day for this note and copy them into the vault.

    Returns the list of attachment filenames to embed, fetching only the photos
    the note is missing (so a note that already has the POTD still gets a selfie
    backfilled, and vice versa). Returns an empty list when both are already
    present or iCloud isn't configured.
    """
    coverage = classify_embedded_photos(analysis.get("embedded_filenames", set()))
    if coverage["has_selfie"] and coverage["has_potd"]:
        log.debug("  Note already has selfie + photo-of-day; skipping auto-embed")
        return []

    icloud_photos = config.get("icloud_photos_dir")
    shared_root = config.get("photo_of_day_shared_dir")
    if not icloud_photos and not shared_root:
        log.debug("  iCloud paths not configured; skipping photo lookup")
        return []

    from pathlib import Path
    vault_root = Path(config["vault_path"])
    attachments_subdir = config.get("attachments_subdir", "attachments/Diary")
    photos_dir = Path(icloud_photos) if icloud_photos else None
    shared_dir = Path(shared_root) if shared_root else None
    album_fmt = config.get("photo_of_day_album_format", "Photo of the day {year}")
    window = int(config.get("selfie_window_minutes", 60))
    cutoff = int(config.get("selfie_day_cutoff_hour", 5))

    filenames: list[str] = []

    # Selfie: closest EXIF capture to YouTube upload time (only if missing)
    upload_time = video.get("published_at")
    delete_after = bool(config.get("delete_selfie_after_embed", False))
    if not coverage["has_selfie"] and photos_dir and upload_time:
        try:
            selfie = find_selfie(upload_time, photos_dir, window_minutes=window,
                                 diary_date=vdate, day_cutoff_hour=cutoff)
            if selfie:
                # Stamp by the photo's capture time, not the upload time: two
                # entries uploaded in the same second (e.g. a catch-up upload)
                # would otherwise collide on one filename and share a photo.
                selfie_when = _read_capture_time(selfie) or upload_time
                fname = prepare_for_embed(selfie, vault_root, attachments_subdir, selfie_when)
                if fname:
                    filenames.append(fname)
                    if delete_after:
                        dest = vault_root / attachments_subdir / str(selfie_when.year) / fname
                        if dest.is_file() and dest.stat().st_size > 0:
                            try:
                                selfie.unlink()
                                log.info(f"  Deleted selfie source from iCloud: {selfie.name}")
                            except OSError as e:
                                log.warning(f"  Could not delete selfie source: {e}")
                        else:
                            log.warning(f"  Skipping selfie delete; embed validation failed for {dest}")
        except Exception as e:
            log.error(f"  Selfie lookup failed: {e}", exc_info=True)

    # Photo of the day (only if missing): prefer the phone "drop folder" (a
    # reliably-synced Google Drive folder you share the photo into); fall back
    # to the iCloud shared album.
    if not coverage["has_potd"]:
        from datetime import datetime, time
        drop_root = config.get("photo_of_day_drop_dir")
        drop_dir = Path(drop_root) if drop_root else None
        drop_delete = bool(config.get("photo_of_day_drop_delete_after", True))

        pod = None
        pod_from_drop = False
        if drop_dir:
            try:
                pod = find_potd_in_drop_dir(vdate, drop_dir, day_cutoff_hour=cutoff)
                pod_from_drop = pod is not None
            except Exception as e:
                log.error(f"  Drop-folder POTD lookup failed: {e}", exc_info=True)
        if pod is None and shared_dir:
            try:
                pod = find_photo_of_day(vdate, shared_dir, album_fmt, photos_dir or shared_dir)
            except Exception as e:
                log.error(f"  Photo-of-day lookup failed: {e}", exc_info=True)

        if pod:
            # Stamp at noon of the diary date to keep ordering predictable and to
            # mark it as the script POTD (see classify_embedded_photos).
            when = datetime.combine(vdate, time(12, 0))
            fname = prepare_for_embed(pod, vault_root, attachments_subdir, when)
            if fname:
                filenames.append(fname)
                if pod_from_drop and drop_delete:
                    dest = vault_root / attachments_subdir / str(vdate.year) / fname
                    if dest.is_file() and dest.stat().st_size > 0:
                        try:
                            pod.unlink()
                            log.info(f"  Removed POTD from drop folder: {pod.name}")
                        except OSError as e:
                            log.warning(f"  Could not delete drop POTD: {e}")

    return filenames

log = logging.getLogger("diary_sync")


def drain_potd_drop_folder(config: dict) -> int:
    """Ingest *every* photo sitting in the POTD drop folder into its diary note.

    Independent of the video sync, the lookback window, and whether a day was
    already marked complete: each file is matched to a diary day (filename
    yyyy-MM-dd, else EXIF capture date), embedded as that day's photo-of-day if
    the note doesn't already have one, then deleted. This is what makes "share a
    POTD for any day, any age — even 12 months back — and it just gets picked up"
    actually true. Returns the number embedded.
    """
    drop_root = config.get("photo_of_day_drop_dir")
    if not drop_root:
        return 0

    from pathlib import Path
    from datetime import datetime, time

    drop_dir = Path(drop_root)
    if not drop_dir.is_dir():
        return 0

    vault_root = Path(config["vault_path"])
    diary_subdir = config.get("diary_subdir", "Diary")
    attachments_subdir = config.get("attachments_subdir", "attachments/Diary")
    cutoff = int(config.get("selfie_day_cutoff_hour", 5))
    delete_after = bool(config.get("photo_of_day_drop_delete_after", True))

    embedded = 0
    already: list[date] = []
    for entry in sorted(drop_dir.iterdir()):
        if not entry.is_file() or not _is_image(entry):
            continue

        d = _date_from_filename(entry.stem)
        if d is None:
            cap = _read_capture_time(entry)
            d = selfie_diary_date(cap, cutoff) if cap else None
        if d is None:
            log.warning(f"  Drop POTD {entry.name}: can't determine its date; leaving it")
            continue

        note_path = find_diary_note(config["vault_path"], diary_subdir, d)
        if not note_path:
            try:
                note_path = create_diary_note(config, d)
            except Exception as e:
                log.error(f"  Drop POTD {entry.name}: couldn't find/create note for {d}: {e}")
                continue

        analysis = analyze_note(note_path)
        if classify_embedded_photos(analysis.get("embedded_filenames", set()))["has_potd"]:
            already.append(d)
            continue

        when = datetime.combine(d, time(12, 0))
        fname = prepare_for_embed(entry, vault_root, attachments_subdir, when)
        if not fname:
            log.error(f"  Drop POTD {entry.name}: failed to prepare for embed")
            continue
        try:
            if embed_photos(note_path, [fname], str(BACKUP_DIR)):
                embedded += 1
                log.info(f"  Drop POTD embedded for {d}: {fname} -> {os.path.basename(note_path)}")
            if delete_after:
                dest = vault_root / attachments_subdir / str(d.year) / fname
                if dest.is_file() and dest.stat().st_size > 0:
                    entry.unlink(missing_ok=True)
        except Exception as e:
            log.error(f"  Drop POTD {entry.name}: embed failed: {e}", exc_info=True)

    if already:
        log.info(f"  Drop folder: {len(already)} file(s) for days that already have a "
                 f"POTD; left untouched ({', '.join(str(d) for d in already)})")
    return embedded


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return {"processed_videos": {}}


def save_state(state: dict):
    # Preserve ip_block if it was written to disk during this run
    try:
        with open(STATE_PATH, "r") as f:
            on_disk = json.load(f)
        if "ip_block" in on_disk:
            state["ip_block"] = on_disk["ip_block"]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
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

    # Force UTF-8 on the console so non-ASCII log text (e.g. "→") doesn't crash
    # the handler on Windows, where stdout defaults to cp1252.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


def sync_videos(config: dict, state: dict, target_date: date | None = None) -> tuple[dict, set[date]]:
    """Main video sync: match YouTube uploads to diary notes.

    If target_date is set, only process videos matching that date.
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

    # Filter videos to process
    if target_date:
        # Single-date mode: match by title date or publish date
        sync_videos_list = []
        for v in videos:
            td = parse_date_from_title(v["title"])
            if td == target_date or v["published_date"] == target_date:
                sync_videos_list.append(v)
        log.info(f"Single-date mode: found {len(sync_videos_list)} video(s) for {target_date}")
    else:
        # Normal mode: process videos within the lookback window
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

        # Skip if already fully processed (unless single-date mode)
        if not target_date and vid in processed and processed[vid].get("status") == "complete":
            log.debug("  Already processed, skipping")
            stats["skipped"] += 1
            continue

        # Find matching diary note — prefer title date over publish date
        # (late-night uploads cross midnight, making publish date +1 day)
        title_date = parse_date_from_title(video["title"])
        if title_date and title_date != vdate:
            log.info(f"  Title date {title_date} differs from publish date {vdate}, using title date")
            vdate = title_date

        # Always create the note if missing (no conflict risk — only done on home PC)
        note_path = find_diary_note(
            config["vault_path"], config.get("diary_subdir", "Diary"), vdate
        )
        if not note_path:
            log.info(f"  No diary note for {vdate}, creating one")
            try:
                note_path = create_diary_note(config, vdate)
            except Exception as e:
                log.error(f"  Failed to create diary note for {vdate}: {e}", exc_info=True)
                stats["no_note"] += 1
                continue

        # Wait at least 2 days before modifying a note, to give Syncthing
        # time to sync phone edits back to this machine (skip in --date mode)
        sync_delay = config.get("sync_delay_days", 2)
        if not target_date and (date.today() - vdate).days < sync_delay:
            log.info(f"  Skipping {vdate} (less than {sync_delay} days old, waiting for sync)")
            stats["skipped"] += 1
            continue

        log.info(f"  Matched: {os.path.basename(note_path)}")

        # Analyze note
        analysis = analyze_note(note_path)

        video_done = (
            analysis["has_video_link"]
            and not analysis["has_placeholder"]
            and analysis["has_blockquote_transcript"]
        )
        coverage = classify_embedded_photos(analysis.get("embedded_filenames", set()))
        photos_complete = coverage["has_selfie"] and coverage["has_potd"]

        # Both video and photos present (selfie + POTD) — fully complete
        if video_done and photos_complete:
            log.info("  Note already has video link + transcript + photos, marking complete")
            processed[vid] = {
                "status": "complete",
                "note": os.path.basename(note_path),
                "date": str(vdate),
            }
            stats["skipped"] += 1
            continue

        # Gather photos up-front (cheap when nothing to do)
        photo_filenames = _gather_photos_for_note(config, video, vdate, analysis)

        # Video already done, just adding photos — bypass transcript fetch entirely
        if video_done:
            if not photo_filenames:
                log.info("  Video complete; no new photos found this run (will retry)")
                stats["skipped"] += 1
                continue
            try:
                modified = update_note(
                    note_path, video["url"], "", analysis, BACKUP_DIR,
                    photo_filenames=photo_filenames,
                )
                if modified:
                    log.info(f"  Embedded {len(photo_filenames)} photo(s) on existing note")
                    stats["updated"] += 1
                processed[vid] = {
                    "status": "complete",
                    "note": os.path.basename(note_path),
                    "date": str(vdate),
                }
            except Exception as e:
                log.error(f"  Failed to add photos: {e}", exc_info=True)
                stats["errors"] += 1
            continue

        # Fetch transcript (with randomised delay to avoid YouTube IP bans)
        if is_in_cooldown():
            log.info("  Skipping transcript fetch (IP cooldown active)")
            stats["no_transcript"] += 1
            continue

        transcript_lang = config.get("transcript_lang", "en")
        time.sleep(5 + random.uniform(0, 5))
        segments = fetch_transcript(vid, transcript_lang)

        if segments == "BLOCKED":
            log.error("IP blocked by YouTube, skipping remaining transcript fetches")
            stats["no_transcript"] += 1
            break

        if segments is None:
            log.warning(f"  Transcript not available yet for {vid}")
            processed[vid] = {
                "status": "no_transcript",
                "note": os.path.basename(note_path),
                "date": str(vdate),
            }
            stats["no_transcript"] += 1
            # Even without transcript, fix the placeholder URL and add any photos we found
            if analysis["has_placeholder"] or photo_filenames:
                try:
                    from note_updater import update_note as _update

                    _update(note_path, video["url"], "", analysis, BACKUP_DIR,
                            photo_filenames=photo_filenames)
                    log.info("  Updated placeholder URL / photos (transcript pending)")
                except Exception as e:
                    log.error(f"  Failed partial update: {e}", exc_info=True)
            continue

        transcript_text = format_transcript(segments)
        if not transcript_text.strip():
            log.warning(f"  Transcript was empty after formatting for {vid}")
            stats["no_transcript"] += 1
            continue

        # Generate summary from transcript
        summary_text = None
        if not analysis["has_summary"]:
            summary_text = generate_summary(
                transcript_text,
                api_key=config.get("anthropic_api_key"),
                model=config.get("summary_model"),
            )

        # Update the note
        try:
            modified = update_note(
                note_path, video["url"], transcript_text, analysis, BACKUP_DIR,
                summary_text=summary_text,
                photo_filenames=photo_filenames,
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
        if note_date >= date.today():
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


def create_diary_note(config: dict, note_date: date) -> str:
    """Create a diary note for the given date if it doesn't already exist.

    Returns the filepath of the note (existing or newly created).
    """
    vault_path = config["vault_path"]
    diary_subdir = config.get("diary_subdir", "Diary")

    # Check if a note already exists
    existing = find_diary_note(vault_path, diary_subdir, note_date)
    if existing:
        log.debug(f"Note already exists: {os.path.basename(existing)}")
        return existing

    # Build filename: "Dear Diary, it's Monday 16 February 2026.md"
    day_name = note_date.strftime("%A")
    month_name = _MONTH_NAMES[note_date.month]
    filename = f"Dear Diary, it's {day_name} {note_date.day} {month_name} {note_date.year}.md"

    # Put it in Diary/YYYY/
    year_dir = os.path.join(vault_path, diary_subdir, str(note_date.year))
    os.makedirs(year_dir, exist_ok=True)

    filepath = os.path.join(year_dir, filename)
    tag = f"Diary-{note_date.year}"

    content = f"""---
date: {note_date.isoformat()}
tags:
  - {tag}
---
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    log.info(f"Created diary note: {filename}")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Diary YouTube Sync")
    parser.add_argument("--date", type=str, default=None,
                        help="Sync a single date only (YYYY-MM-DD)")
    args = parser.parse_args()

    config = load_config()
    setup_logging(config)

    target_date = None
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            log.error(f"Invalid date format: {args.date} (expected YYYY-MM-DD)")
            sys.exit(1)

    # Validate vault path
    vault_path = config.get("vault_path", "")
    if not os.path.isdir(vault_path):
        log.error(f"Vault path not found: {vault_path}")
        sys.exit(2)

    if target_date:
        log.info(f"=== Diary YouTube Sync starting (single date: {target_date}) ===")
    else:
        log.info("=== Diary YouTube Sync starting ===")

    # Create any missing diary notes up to tomorrow (skip in single-date mode)
    if not target_date:
        lookback = config.get("lookback_days", 30)
        tomorrow = date.today() + timedelta(days=1)
        d = date.today() - timedelta(days=lookback)
        while d <= tomorrow:
            try:
                create_diary_note(config, d)
            except Exception as e:
                log.error(f"Failed to create note for {d}: {e}", exc_info=True)
            d += timedelta(days=1)

    state = load_state()
    upload_dates = set()

    try:
        stats, upload_dates = sync_videos(config, state, target_date)
        log.info(
            f"Video sync: {stats['updated']} updated, {stats['skipped']} skipped, "
            f"{stats['no_note']} no note, {stats['no_transcript']} no transcript, "
            f"{stats['errors']} errors"
        )
    except Exception as e:
        log.error(f"Video sync failed: {e}", exc_info=True)
    finally:
        save_state(state)

    # Drain the POTD drop folder — ingest every dropped photo regardless of date,
    # lookback, or complete-state (skip in single-date mode; that path handles its
    # own date via _gather_photos_for_note).
    if not target_date:
        try:
            n = drain_potd_drop_folder(config)
            if n:
                log.info(f"Drop folder: embedded {n} photo-of-day file(s)")
        except Exception as e:
            log.error(f"Drop-folder drain failed: {e}", exc_info=True)

    # Tag audit and missing upload check (skip in single-date mode)
    if not target_date:
        try:
            audit_tags(config)
        except Exception as e:
            log.error(f"Tag audit failed: {e}", exc_info=True)

        if upload_dates:
            try:
                check_missing_uploads(config, upload_dates)
            except Exception as e:
                log.error(f"Missing upload check failed: {e}", exc_info=True)

    # Write status report (skip in single-date mode)
    if not target_date:
        try:
            from status_report import write_report
            out = write_report(config)
            log.info(f"Wrote status report: {out.name}")
        except Exception as e:
            log.error(f"Status report failed: {e}", exc_info=True)

    log.info("=== Diary YouTube Sync complete ===")


if __name__ == "__main__":
    main()
