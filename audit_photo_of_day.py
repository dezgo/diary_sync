#!/usr/bin/env python
"""Audit photo-of-the-day coverage for a year.

Walks each day from Jan 1 to today (or year end) and classifies it:
  - Missing from shared album (you need to add it on the iPhone)
  - Album has photo, note doesn't embed it (auto-fixable with --commit)
  - No diary note exists yet (skipped)
  - Fully done

Default is dry-run. --commit will backfill any auto-fixable notes.
"""

import argparse
import logging
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import yaml

from diary_finder import find_diary_note
from note_updater import analyze_note, embed_photos
from photo_finder import find_photo_of_day, prepare_for_embed

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
BACKUP_DIR = SCRIPT_DIR / "backups"

log = logging.getLogger("photo_audit")


def main():
    parser = argparse.ArgumentParser(description="Audit photo-of-day coverage")
    parser.add_argument("--year", type=int, default=date.today().year,
                        help="Year to audit (default: current year)")
    parser.add_argument("--commit", action="store_true",
                        help="Actually backfill missing embeds (default: dry-run)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show INFO-level photo_finder logs")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    vault_root = Path(config["vault_path"])
    diary_subdir = config.get("diary_subdir", "Diary")
    shared_root = Path(config["photo_of_day_shared_dir"])
    icloud_photos_dir = Path(config.get("icloud_photos_dir") or shared_root)
    album_fmt = config["photo_of_day_album_format"]
    attachments_subdir = config.get("attachments_subdir", "attachments/Diary")

    today = date.today()
    end_day = min(today, date(args.year, 12, 31))
    d = date(args.year, 1, 1)

    missing_from_album: list[date] = []
    backfill_candidates: list[tuple[date, Path, str]] = []  # (date, photo_path, note_path)
    no_note: list[date] = []
    fully_done = 0

    while d <= end_day:
        photo = find_photo_of_day(d, shared_root, album_fmt, icloud_photos_dir)
        note_path = find_diary_note(str(vault_root), diary_subdir, d)

        if not photo:
            missing_from_album.append(d)
        elif not note_path:
            no_note.append(d)
        else:
            analysis = analyze_note(note_path)
            has_photos = any(
                f.startswith("Pasted image ")
                for f in analysis.get("embedded_filenames", set())
            )
            if has_photos:
                fully_done += 1
            else:
                backfill_candidates.append((d, photo, note_path))
        d += timedelta(days=1)

    total = (end_day - date(args.year, 1, 1)).days + 1
    print(f"=== Photo-of-day audit for {args.year} ({total} days checked) ===")
    print(f"  Fully done (album + note):    {fully_done}")
    print(f"  Missing from shared album:    {len(missing_from_album)}")
    print(f"  Note backfill needed:         {len(backfill_candidates)}")
    print(f"  No diary note yet:            {len(no_note)}")
    print()

    if missing_from_album:
        print("Missing from shared album (add manually on iPhone):")
        for md in missing_from_album:
            print(f"  {md} -- {md.strftime('%A')}")
        print()

    if backfill_candidates:
        print("Notes needing photo-of-day backfill:")
        for bd, photo, note in backfill_candidates:
            print(f"  {bd} -- {photo.name} -> {Path(note).name}")
        print()

    if not args.commit:
        if backfill_candidates:
            print(f"Re-run with --commit to backfill {len(backfill_candidates)} note(s).")
        return

    # --commit: actually backfill
    embedded = 0
    errors = 0
    for bd, photo, note in backfill_candidates:
        when = datetime.combine(bd, time(12, 0))
        fname = prepare_for_embed(photo, vault_root, attachments_subdir, when)
        if not fname:
            print(f"  ERROR preparing {photo.name} for {bd}")
            errors += 1
            continue
        try:
            if embed_photos(note, [fname], str(BACKUP_DIR)):
                embedded += 1
                print(f"  EMBEDDED: {bd} -> {fname}")
        except Exception as e:
            print(f"  ERROR embedding {bd}: {e}")
            errors += 1

    print()
    print(f"=== Backfill complete: {embedded} embedded, {errors} errors ===")


if __name__ == "__main__":
    main()
