"""Set creation timestamp on diary notes to match their date.

Usage:
    python fix_dates.py          # dry-run: show what would change
    python fix_dates.py --apply  # actually update timestamps
"""

import os
import sys
from datetime import datetime, time

import pywintypes
import win32file
import win32con
import yaml

from diary_finder import find_all_diary_notes_everywhere

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")


def set_creation_date(filepath, target_dt):
    """Set creation time on a Windows file, leaving modified time alone."""
    wintime = pywintypes.Time(target_dt)
    handle = win32file.CreateFile(
        filepath,
        win32con.GENERIC_WRITE,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
        None,
        win32con.OPEN_EXISTING,
        win32con.FILE_ATTRIBUTE_NORMAL,
        None,
    )
    try:
        # SetFileTime(handle, CreationTime, AccessTime, ModifiedTime)
        # Pass None for access/modified to leave them unchanged
        win32file.SetFileTime(handle, wintime, None, None)
    finally:
        handle.Close()


def main():
    dry_run = "--apply" not in sys.argv

    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    vault_path = config["vault_path"]
    all_notes, _ = find_all_diary_notes_everywhere(vault_path)

    would_fix = 0
    already_ok = 0
    errors = 0

    for filepath, note_date in all_notes:
        target_dt = datetime.combine(note_date, time(12, 0))  # noon on that day

        # Check current timestamps
        stat = os.stat(filepath)
        current_mtime = datetime.fromtimestamp(stat.st_mtime)
        current_ctime = datetime.fromtimestamp(stat.st_ctime)

        # Skip if creation date already matches
        if current_ctime.date() == note_date:
            already_ok += 1
            continue

        rel = os.path.relpath(filepath, vault_path)
        if dry_run:
            print(f"  {rel}")
            print(f"    created: {current_ctime:%Y-%m-%d %H:%M} -> {note_date} 12:00")
            would_fix += 1
        else:
            try:
                set_creation_date(filepath, target_dt)
                would_fix += 1
            except Exception as e:
                print(f"  ERROR: {rel}: {e}")
                errors += 1

    print()
    if dry_run:
        print(f"DRY RUN: {would_fix} files to fix, {already_ok} already correct.")
        print(f"Run with --apply to update timestamps.")
    else:
        print(f"Done: {would_fix} fixed, {already_ok} already correct, {errors} errors.")


if __name__ == "__main__":
    main()
