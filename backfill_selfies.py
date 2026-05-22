#!/usr/bin/env python
"""Backfill missing selfies into recent diary notes.

Why this exists: the selfie auto-embed was silently broken for a stretch — the
iPhone front-camera EXIF lens model is "front TrueDepth camera", but the matcher
looked for the literal "front camera", so every selfie was rejected. Notes
processed in that window got a photo-of-day but no selfie, and were marked
"complete" in state.json. A normal `sync.py` run skips complete videos at its
early guard, so it never re-evaluates their photos — the backlog can't self-heal.

This script re-scans recent notes directly, ignores that guard, and embeds the
missing selfie (and any missing photo-of-day) by reusing the same matching the
sync uses. Dry-run by default; pass --commit to actually embed.
"""

import argparse
import logging
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from youtube_client import get_authenticated_service, get_recent_uploads
from diary_finder import find_all_diary_notes
from note_updater import analyze_note, update_note
from photo_finder import classify_embedded_photos, find_selfie
from sync import (
    parse_date_from_title,
    _gather_photos_for_note,
    CONFIG_PATH,
    BACKUP_DIR,
    CREDENTIALS_PATH,
    TOKEN_PATH,
)

log = logging.getLogger("backfill_selfies")


def main():
    parser = argparse.ArgumentParser(description="Backfill missing selfies into diary notes")
    parser.add_argument("--days", type=int, default=120,
                        help="How many days back to scan (default: 120)")
    parser.add_argument("--commit", action="store_true",
                        help="Actually embed selfies (default: dry-run)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show INFO-level photo_finder/selfie logs")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    vault_root = config["vault_path"]
    diary_subdir = config.get("diary_subdir", "Diary")
    photos_dir = Path(config["icloud_photos_dir"]) if config.get("icloud_photos_dir") else None
    window = int(config.get("selfie_window_minutes", 60))
    cutoff = int(config.get("selfie_day_cutoff_hour", 5))

    today = date.today()
    window_start = today - timedelta(days=args.days)

    # Fetch uploads and index them by diary date (title date preferred, like sync).
    youtube = get_authenticated_service(CREDENTIALS_PATH, TOKEN_PATH)
    tz = ZoneInfo(config.get("timezone", "Australia/Sydney"))
    videos = get_recent_uploads(youtube, config["channel_id"], window_start, tz)

    by_date: dict[date, dict] = {}
    for v in videos:  # reverse-chronological; setdefault keeps the latest upload
        by_date.setdefault(v["published_date"], v)
        td = parse_date_from_title(v["title"])
        if td:
            by_date.setdefault(td, v)

    # Find notes in the window that are missing a selfie.
    notes = find_all_diary_notes(vault_root, diary_subdir)
    will_embed: list[tuple] = []   # (date, note_path, video, analysis)
    no_selfie_found: list[date] = []
    no_video: list[date] = []

    for note_path, ndate in notes:
        if ndate < window_start or ndate > today or "sync-conflict" in note_path:
            continue
        analysis = analyze_note(note_path)
        if classify_embedded_photos(analysis.get("embedded_filenames", set()))["has_selfie"]:
            continue  # already has a selfie

        video = by_date.get(ndate)
        if not video:
            no_video.append(ndate)
            continue

        # Read-only check: is there actually a front-camera photo to embed?
        selfie = None
        if photos_dir:
            selfie = find_selfie(video["published_at"], photos_dir, window_minutes=window,
                                 diary_date=ndate, day_cutoff_hour=cutoff)
        if selfie:
            will_embed.append((ndate, note_path, video, analysis))
        else:
            no_selfie_found.append(ndate)

    will_embed.sort(key=lambda x: x[0], reverse=True)
    no_selfie_found.sort(reverse=True)
    no_video.sort(reverse=True)

    print(f"=== Selfie backfill ({args.days}-day window, since {window_start}) ===")
    print(f"  Will embed a selfie:          {len(will_embed)}")
    print(f"  Missing selfie, none in iCloud window: {len(no_selfie_found)}")
    print(f"  Missing selfie, no video to anchor:    {len(no_video)}")
    print()

    if will_embed:
        print("Selfie will be embedded for:")
        for d, _, _, _ in will_embed:
            print(f"  {d} -- {d.strftime('%A')}")
        print()
    if no_selfie_found:
        print("No front-camera photo found within window (check iCloud Photos):")
        for d in no_selfie_found:
            print(f"  {d} -- {d.strftime('%A')}")
        print()

    if not args.commit:
        if will_embed:
            print(f"Re-run with --commit to embed {len(will_embed)} selfie(s).")
        return

    # --commit: embed. _gather_photos_for_note fetches only what's missing.
    embedded = 0
    errors = 0
    for d, note_path, video, analysis in will_embed:
        try:
            photo_filenames = _gather_photos_for_note(config, video, d, analysis)
            if not photo_filenames:
                print(f"  SKIP {d}: nothing to embed (selfie vanished between scan and commit)")
                continue
            update_note(note_path, video["url"], "", analysis, BACKUP_DIR,
                        photo_filenames=photo_filenames)
            embedded += 1
            print(f"  EMBEDDED {d}: {', '.join(photo_filenames)}")
        except Exception as e:
            print(f"  ERROR {d}: {e}")
            errors += 1

    print()
    print(f"=== Backfill complete: {embedded} embedded, {errors} errors ===")
    print("Tip: open Diary Dashboard and re-run status_report.py to confirm.")


if __name__ == "__main__":
    main()
